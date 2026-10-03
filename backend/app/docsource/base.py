"""Document source contract.

The prompt and grounding text are *configuration delivered at runtime*, so they
get the same treatment as any other remote dependency: one interface, several
interchangeable implementations, and an explicit failure mode.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

PROMPT = "prompt"
GROUNDING = "grounding"


class DocumentUnavailable(RuntimeError):
    """Raised when a document could not be fetched and no last-good copy exists.

    The caller must surface a user-facing error and must NOT call the LLM.
    Calling a model with a missing system prompt produces an unaligned,
    ungrounded advisor — strictly worse than an error message.
    """

    def __init__(self, kind: str, detail: str) -> None:
        super().__init__(f"{kind} document unavailable: {detail}")
        self.kind = kind
        self.detail = detail


class DocumentFetchError(RuntimeError):
    """A transient failure from the underlying source."""


@dataclass(frozen=True)
class DocumentRevision:
    kind: str
    source: str
    body: str
    revision_hash: str
    snapshot_id: int | None
    fetched_at: datetime
    from_cache: bool = False
    # True when the live fetch failed and this is a last-good copy. Surfaced to
    # the admin view so a silently-stale prompt is visible rather than mystifying.
    stale: bool = False

    @property
    def short_hash(self) -> str:
        return self.revision_hash[:12]


@runtime_checkable
class DocumentSource(Protocol):
    """Fetches raw document text by reference."""

    name: str

    async def fetch(self, ref: str) -> str: ...
