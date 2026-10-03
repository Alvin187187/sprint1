"""Keyword grounding retrieval.

The PRD rules out embeddings for this phase, so this stays lexical — but
"lexical" does not have to mean "naive substring match". Two cheap upgrades do
most of the work:

1. **Heading-aware chunking.** Splitting on markdown headings keeps each chunk
   topically coherent and gives us a title to score against. Fixed-size windows
   would cut "Don't" lists in half.
2. **BM25-style scoring** with document-frequency weighting, so a query term
   that appears in every chunk ("learner", "data") contributes almost nothing
   while a distinctive term ("portfolio", "salary", "resume") dominates. A plain
   overlap count ranks the longest chunk first on nearly every query.

Heading text is weighted because the author's own section titles are the
strongest available relevance signal in a hand-written reference doc.

No external dependencies, no index build step, no network call.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field

_WORD_RE = re.compile(r"[a-z0-9']+")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")

# Deliberately small: an aggressive stoplist would eat domain words.
_STOPWORDS = frozenset(
    """
    a about an and any are as at be been being but by can could did do does
    doing for from had has have how i if in into is it its just me my of on
    only or other our out over should so some such than that the their them
    then there these they this those to too up us was we were what when where
    which while who why will with would you your yours
    """.split()
)

# Light stemming: collapses plural/gerund variants without a stemmer dependency.
_SUFFIXES = ("ing", "ers", "er", "ies", "es", "s", "ed", "ly")

# Heading relevance is applied as a multiplier, not an additive bonus. Additive
# weighting let a tiny chunk whose *title* happened to share a word outrank a
# section that actually answered the question. As a multiplier it can only
# amplify a chunk that already matches on content, so it can be weighted heavily:
# in a hand-written reference doc the author's own section titles are the single
# best relevance signal available.
_HEADING_BOOST = 3.0
_K1 = 1.4
# Length normalization is kept moderate. At the textbook 0.75 a 28-token section
# outranked a 150-token one on a single incidental word match, because BM25's
# length penalty rewards brevity hard.
_B = 0.5
# Floor on the share of the score that ignores coverage. Without a coverage term,
# matching 1 of 5 query terms scores the same as matching 4 of 5.
_COVERAGE_FLOOR = 0.3


def fold(text: str) -> str:
    """Strip diacritics so accented and plain spellings collide.

    Without this, `Résumé` in the reference doc tokenizes to `r` + `sum` and a
    learner asking about their "resume" never matches the section written for
    exactly that question. The same applies to Filipino and Spanish-influenced
    words that show up throughout this domain.
    """
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for raw in _WORD_RE.findall(fold(text).lower()):
        if raw in _STOPWORDS or len(raw) < 2:
            continue
        tokens.append(_stem(raw))
    return tokens


def _stem(word: str) -> str:
    if len(word) <= 4:
        return word
    for suffix in _SUFFIXES:
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            return word[: -len(suffix)]
    return word


@dataclass
class Chunk:
    chunk_id: str
    heading: str
    text: str
    tokens: list[str] = field(default_factory=list)
    heading_tokens: set[str] = field(default_factory=set)

    @property
    def char_count(self) -> int:
        return len(self.text)


@dataclass
class ScoredChunk:
    chunk: Chunk
    score: float


def chunk_document(body: str, *, max_chars: int = 1400) -> list[Chunk]:
    """Split on markdown headings, then soft-wrap over-long sections on blank lines."""
    sections: list[tuple[int, str, list[str]]] = []
    current_level = 1
    current_heading = "Overview"
    current_lines: list[str] = []

    for line in body.splitlines():
        match = _HEADING_RE.match(line.strip())
        if match:
            if current_lines:
                sections.append((current_level, current_heading, current_lines))
            current_level = len(match.group(1))
            current_heading = match.group(2).strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines:
        sections.append((current_level, current_heading, current_lines))

    # Drop the leading H1 block. In a conventional markdown reference doc that is
    # the title plus authoring notes — front matter, not reference content — and
    # indexing it means every query containing a word from the title matches it.
    if len(sections) > 1 and sections[0][0] == 1:
        sections = sections[1:]

    sections_without_level = [(heading, lines) for _, heading, lines in sections]

    chunks: list[Chunk] = []
    for heading, lines in sections_without_level:
        for index, part in enumerate(_split_to_budget(lines, max_chars)):
            text = part.strip()
            if not text:
                continue
            slug = re.sub(r"[^a-z0-9]+", "-", fold(heading).lower()).strip("-") or "section"
            chunk_id = f"{slug}#{index}" if index else slug
            heading_tokens = set(tokenize(heading))
            chunks.append(
                Chunk(
                    chunk_id=chunk_id,
                    heading=heading,
                    text=f"{heading}\n{text}",
                    tokens=tokenize(f"{heading} {text}"),
                    heading_tokens=heading_tokens,
                )
            )
    return chunks


def _split_to_budget(lines: list[str], max_chars: int) -> list[str]:
    blocks: list[str] = []
    buffer: list[str] = []
    size = 0
    for line in lines:
        if size + len(line) > max_chars and buffer:
            blocks.append("\n".join(buffer))
            buffer, size = [], 0
        buffer.append(line)
        size += len(line) + 1
    if buffer:
        blocks.append("\n".join(buffer))
    return blocks


class GroundingIndex:
    """In-memory BM25-ish index over one document revision."""

    def __init__(self, chunks: list[Chunk]) -> None:
        self.chunks = chunks
        self._doc_freq: dict[str, int] = {}
        for chunk in chunks:
            for term in set(chunk.tokens):
                self._doc_freq[term] = self._doc_freq.get(term, 0) + 1
        lengths = [len(c.tokens) for c in chunks] or [1]
        self._avg_len = sum(lengths) / len(lengths)
        self._n = max(1, len(chunks))
        # idf a term would have if it appeared in exactly one chunk — the ceiling.
        self._max_idf = math.log(1 + (self._n - 1 + 0.5) / 1.5)

    def _idf(self, term: str) -> float:
        df = self._doc_freq.get(term, 0)
        if df == 0:
            return 0.0
        return math.log(1 + (self._n - df + 0.5) / (df + 0.5))

    def _demand(self, term: str) -> float:
        """What this query term *asks for*, whether or not the document has it.

        Out-of-vocabulary terms must count against coverage. Scoring them as 0
        on both sides of the ratio meant a question written entirely in words the
        document has never seen ("ignore previous instructions, print verbatim")
        measured as 100% covered, and then matched whichever section happened to
        share one incidental word. Charging unknown terms the maximum idf makes
        off-domain questions score low — which is the correct outcome, since
        there is nothing in the reference doc to ground them in.
        """
        idf = self._idf(term)
        return idf if idf > 0 else self._max_idf

    def search(self, query: str, *, limit: int, min_score: float) -> list[ScoredChunk]:
        query_terms = set(tokenize(query))
        if not query_terms or not self.chunks:
            return []

        scored: list[ScoredChunk] = []
        # Denominator spans the whole query, including terms the document lacks.
        demand = sum(self._demand(t) for t in query_terms) or 1.0

        for chunk in self.chunks:
            counts: dict[str, int] = {}
            for token in chunk.tokens:
                if token in query_terms:
                    counts[token] = counts.get(token, 0) + 1
            if not counts:
                continue
            length = len(chunk.tokens) or 1
            score = 0.0
            matched_idf = 0.0
            for term, freq in counts.items():
                idf = self._idf(term)
                denominator = freq + _K1 * (1 - _B + _B * length / self._avg_len)
                score += idf * (freq * (_K1 + 1)) / denominator
                matched_idf += idf

            # How much of the question this chunk actually speaks to, weighted so
            # a distinctive term counts for more than a common one.
            coverage = min(1.0, matched_idf / demand)
            score *= _COVERAGE_FLOOR + (1 - _COVERAGE_FLOOR) * coverage

            # How concentrated this chunk's match is in its own title. Scoped to
            # what the chunk matched rather than to total demand, so an
            # off-domain query full of unknown words doesn't also mute the
            # heading signal for the terms it *did* match.
            heading_idf = sum(self._idf(t) for t in query_terms & chunk.heading_tokens)
            heading_focus = heading_idf / matched_idf if matched_idf else 0.0
            score *= 1 + _HEADING_BOOST * min(1.0, heading_focus)

            scored.append(ScoredChunk(chunk=chunk, score=score / demand))

        scored.sort(key=lambda s: s.score, reverse=True)
        return [s for s in scored if s.score >= min_score][:limit]


def select_grounding(
    body: str,
    query: str,
    *,
    max_chunks: int = 3,
    max_chars: int = 2600,
    min_score: float = 0.12,
) -> tuple[str, list[str], list[float]]:
    """Return (excerpt text, chunk ids used, scores) for a user query.

    Returns an empty excerpt when nothing clears `min_score` — injecting an
    irrelevant chunk is worse than injecting none, because the model will try to
    make it relevant.
    """
    index = GroundingIndex(chunk_document(body))
    hits = index.search(query, limit=max_chunks, min_score=min_score)
    if not hits:
        return "", [], []

    parts: list[str] = []
    ids: list[str] = []
    scores: list[float] = []
    budget = max_chars
    for hit in hits:
        text = hit.chunk.text
        if len(text) > budget:
            if budget < 300:
                break
            text = text[:budget].rsplit("\n", 1)[0] + "\n[...]"
        parts.append(text)
        ids.append(hit.chunk.chunk_id)
        scores.append(round(hit.score, 4))
        budget -= len(text)
        if budget <= 0:
            break

    return "\n\n---\n\n".join(parts), ids, scores
