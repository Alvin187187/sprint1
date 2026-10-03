"""Local-file document source.

Used for development and for the eval harness, so the whole pipeline is
testable without Google credentials. Behaviour is identical to the Docs
provider from the cache layer's point of view.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.docsource.base import DocumentFetchError


class LocalFileSource:
    name = "local"

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()

    async def fetch(self, ref: str) -> str:
        return await asyncio.to_thread(self._read, ref)

    def _read(self, ref: str) -> str:
        # `ref` comes from the advisors table, not from a request, but resolving
        # it against the root anyway keeps a bad config row from reading /etc.
        candidate = (self._root / Path(ref).name).resolve()
        if self._root not in candidate.parents and candidate.parent != self._root:
            raise DocumentFetchError(f"{ref} resolves outside the document root")
        if not candidate.is_file():
            raise DocumentFetchError(f"{candidate} does not exist")
        text = candidate.read_text(encoding="utf-8").strip()
        if not text:
            raise DocumentFetchError(f"{candidate} is empty")
        return text
