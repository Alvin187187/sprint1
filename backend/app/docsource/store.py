"""Two-layer document cache.

Layer 1  in-process TTL cache  — satisfies the PRD's "edit goes live within TTL"
Layer 2  `advisor.doc_snapshots` — durable last-good store + revision registry

The PRD specifies only layer 1. Layer 2 exists because an in-process cache is
empty after every restart, cold start, or new worker, so a Docs outage that
coincides with a deploy would leave the console with *no* prompt at all. With
snapshots persisted, the worst case degrades to "serving yesterday's prompt and
saying so" instead of "advisor is down".

A single-flight lock per document keeps a cache expiry from turning N concurrent
sends into N Docs API calls.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from datetime import datetime, timezone

from app.config import Settings
from app.db import fetch_one
from app.docsource.base import (
    GROUNDING,
    PROMPT,
    DocumentFetchError,
    DocumentRevision,
    DocumentSource,
    DocumentUnavailable,
)
from app.docsource.google_docs import GoogleDocsSource
from app.docsource.local import LocalFileSource
from app import telemetry

# After a failed fetch, don't retry on every single request.
_FAILURE_BACKOFF_SECONDS = 20


def revision_hash(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def build_source(settings: Settings) -> DocumentSource:
    if settings.doc_provider == "google_docs":
        return GoogleDocsSource(settings.google_service_account_json)
    return LocalFileSource(settings.doc_root)


class _CacheEntry:
    __slots__ = ("revision", "expires_at")

    def __init__(self, revision: DocumentRevision, expires_at: float) -> None:
        self.revision = revision
        self.expires_at = expires_at


class DocumentStore:
    def __init__(self, settings: Settings, source: DocumentSource | None = None) -> None:
        self._settings = settings
        self._source = source or build_source(settings)
        self._cache: dict[tuple[str, str], _CacheEntry] = {}
        self._locks: dict[tuple[str, str], asyncio.Lock] = {}

    @property
    def source_name(self) -> str:
        return self._source.name

    def _ref_for(self, kind: str, advisor_row: dict) -> str | None:
        if self._settings.doc_provider == "google_docs":
            return (
                self._settings.prompt_doc_id if kind == PROMPT else self._settings.grounding_doc_id
            ) or None
        return advisor_row.get("prompt_doc_ref" if kind == PROMPT else "grounding_doc_ref")

    def invalidate(self, advisor_id: str, kind: str | None = None) -> None:
        for key in list(self._cache):
            if key[0] == advisor_id and (kind is None or key[1] == kind):
                del self._cache[key]

    def cache_state(self, advisor_id: str) -> list[dict]:
        now = time.monotonic()
        out = []
        for (adv, kind), entry in self._cache.items():
            if adv != advisor_id:
                continue
            out.append(
                {
                    "kind": kind,
                    "revision": entry.revision.short_hash,
                    "source": entry.revision.source,
                    "stale": entry.revision.stale,
                    "expires_in_seconds": max(0, int(entry.expires_at - now)),
                    "fetched_at": entry.revision.fetched_at,
                }
            )
        return out

    async def get(
        self, advisor_id: str, kind: str, advisor_row: dict, *, required: bool = True
    ) -> DocumentRevision | None:
        key = (advisor_id, kind)
        entry = self._cache.get(key)
        if entry and entry.expires_at > time.monotonic():
            await telemetry.log_event(
                telemetry.PROMPT_CACHE_HIT,
                advisor_id=advisor_id,
                kind=kind,
                revision=entry.revision.short_hash,
                stale=entry.revision.stale,
            )
            return DocumentRevision(
                kind=entry.revision.kind,
                source=entry.revision.source,
                body=entry.revision.body,
                revision_hash=entry.revision.revision_hash,
                snapshot_id=entry.revision.snapshot_id,
                fetched_at=entry.revision.fetched_at,
                from_cache=True,
                stale=entry.revision.stale,
            )

        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            # Another coroutine may have refreshed while we waited.
            entry = self._cache.get(key)
            if entry and entry.expires_at > time.monotonic():
                return entry.revision
            return await self._refresh(advisor_id, kind, advisor_row, required=required)

    async def _refresh(
        self, advisor_id: str, kind: str, advisor_row: dict, *, required: bool
    ) -> DocumentRevision | None:
        await telemetry.log_event(
            telemetry.PROMPT_CACHE_MISS, advisor_id=advisor_id, kind=kind
        )
        ref = self._ref_for(kind, advisor_row)
        if not ref:
            if required:
                raise DocumentUnavailable(kind, "no document reference configured")
            return None

        try:
            body = await self._source.fetch(ref)
        except DocumentFetchError as exc:
            return await self._fall_back(advisor_id, kind, str(exc), required=required)
        except Exception as exc:  # noqa: BLE001 - any source failure is a doc failure
            return await self._fall_back(advisor_id, kind, repr(exc), required=required)

        digest = revision_hash(body)
        previous = await fetch_one(
            """
            select revision_hash from advisor.doc_snapshots
             where advisor_id = %s and doc_kind = %s
             order by fetched_at desc limit 1
            """,
            (advisor_id, kind),
        )
        row = await fetch_one(
            """
            insert into advisor.doc_snapshots
                (advisor_id, doc_kind, source, revision_hash, body, char_count)
            values (%s, %s, %s, %s, %s, %s)
            on conflict (advisor_id, doc_kind, revision_hash)
                do update set fetched_at = now()
            returning id, fetched_at
            """,
            (advisor_id, kind, self._source.name, digest, body, len(body)),
        )
        assert row is not None

        if previous is None or previous["revision_hash"] != digest:
            await telemetry.log_event(
                telemetry.DOC_REVISION_CHANGED,
                advisor_id=advisor_id,
                kind=kind,
                revision=digest[:12],
                previous=(previous or {}).get("revision_hash", "")[:12] or None,
                char_count=len(body),
            )

        revision = DocumentRevision(
            kind=kind,
            source=self._source.name,
            body=body,
            revision_hash=digest,
            snapshot_id=row["id"],
            fetched_at=row["fetched_at"],
        )
        self._store(advisor_id, kind, revision, self._settings.doc_cache_ttl_seconds)
        return revision

    async def _fall_back(
        self, advisor_id: str, kind: str, detail: str, *, required: bool
    ) -> DocumentRevision | None:
        await telemetry.log_event(
            telemetry.DOC_FETCH_ERROR,
            severity="error",
            advisor_id=advisor_id,
            kind=kind,
            detail=detail[:500],
        )
        row = await fetch_one(
            """
            select id, body, revision_hash, source, fetched_at
              from advisor.doc_snapshots
             where advisor_id = %s and doc_kind = %s
             order by fetched_at desc limit 1
            """,
            (advisor_id, kind),
        )
        if row is None:
            if required:
                # No prompt and no history: fail loudly rather than call the
                # model naked. PRD §6 "doc unreachable, no cache".
                raise DocumentUnavailable(kind, detail)
            return None

        revision = DocumentRevision(
            kind=kind,
            source=row["source"],
            body=row["body"],
            revision_hash=row["revision_hash"],
            snapshot_id=row["id"],
            fetched_at=row["fetched_at"] or datetime.now(timezone.utc),
            stale=True,
        )
        self._store(advisor_id, kind, revision, _FAILURE_BACKOFF_SECONDS)
        return revision

    def _store(self, advisor_id: str, kind: str, revision: DocumentRevision, ttl: int) -> None:
        self._cache[(advisor_id, kind)] = _CacheEntry(revision, time.monotonic() + ttl)


__all__ = [
    "GROUNDING",
    "PROMPT",
    "DocumentRevision",
    "DocumentStore",
    "DocumentUnavailable",
    "build_source",
    "revision_hash",
]
