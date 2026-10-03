"""Score every chunk for a query, with per-term idf, to debug ranking."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.grounding import GroundingIndex, chunk_document, tokenize  # noqa: E402

BODY = (Path(__file__).resolve().parents[2] / "content" / "grounding.md").read_text(encoding="utf-8")


def main() -> None:
    queries = sys.argv[1:] or ["What should go in my portfolio to get an analyst interview?"]
    index = GroundingIndex(chunk_document(BODY))

    for query in queries:
        terms = sorted(set(tokenize(query)))
        print(f"\nquery: {query}")
        print("  term idf:")
        for term in terms:
            print(f"    {term:<14} df={index._doc_freq.get(term, 0):<3} idf={index._idf(term):.3f}")
        print("  ranking:")
        for hit in index.search(query, limit=12, min_score=0.0):
            print(f"    {hit.score:.4f}  {hit.chunk.chunk_id}")


if __name__ == "__main__":
    main()
