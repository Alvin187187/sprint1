"""Admin observability (FR-07, FR-08).

Exposes revision hashes, chunk ids, token counts, and cost. Never exposes a
document body — knowing *which* prompt revision ran is the operationally useful
fact, and it carries no secrecy risk.
"""

from __future__ import annotations

import time
from typing import Annotated

from fastapi import APIRouter, Query

from app import repository
from app.deps import AdvisorDep, CurrentAdmin, DocumentStoreDep, SettingsDep
from app.docsource import GROUNDING, PROMPT
from app.schemas import (
    AdminConversationRow,
    AdminEventRow,
    AdminOverviewOut,
    AdminTurnRow,
    AdminUsageRow,
    DocStatusOut,
)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.get("/overview", response_model=AdminOverviewOut)
async def overview(
    admin: CurrentAdmin,
    advisor: AdvisorDep,
    settings: SettingsDep,
    store: DocumentStoreDep,
) -> AdminOverviewOut:
    totals = await repository.admin_totals()
    snapshots = await repository.latest_doc_snapshots(advisor["id"])
    cache = {c["kind"]: c for c in store.cache_state(advisor["id"])}

    docs = [
        DocStatusOut(
            kind=row["doc_kind"],
            source=row["source"],
            revision=row["revision_hash"][:12],
            char_count=row["char_count"],
            stale=bool(cache.get(row["doc_kind"], {}).get("stale")),
            cache_expires_in_seconds=cache.get(row["doc_kind"], {}).get("expires_in_seconds"),
            fetched_at=row["fetched_at"],
        )
        for row in snapshots
    ]

    return AdminOverviewOut(
        totals={
            "users": totals.get("users", 0),
            "conversations": totals.get("conversations", 0),
            "messages": totals.get("messages", 0),
            "tokens": int(totals.get("tokens", 0) or 0),
            "est_cost_usd": round(float(totals.get("est_cost_usd", 0) or 0), 6),
            "blocked": totals.get("blocked", 0),
            "errored": totals.get("errored", 0),
            "avg_latency_ms": int(float(totals.get("avg_latency_ms", 0) or 0)),
            "model": advisor.get("model") or settings.model,
            "doc_provider": store.source_name,
            "doc_cache_ttl_seconds": settings.doc_cache_ttl_seconds,
            "timezone": settings.app_timezone,
            "default_message_cap": settings.default_daily_message_cap,
            "default_token_cap": settings.default_daily_token_cap,
            "rate_limit_per_minute": settings.rate_limit_per_window,
        },
        docs=docs,
        by_status=await repository.admin_status_breakdown(),
        by_event=await repository.admin_event_breakdown(),
    )


@router.get("/turns", response_model=list[AdminTurnRow])
async def turns(
    admin: CurrentAdmin,
    limit: Annotated[int, Query(ge=1, le=300)] = 80,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
    user_email: Annotated[str | None, Query()] = None,
) -> list[AdminTurnRow]:
    rows = await repository.admin_recent_turns(limit, status_filter, user_email)
    return [AdminTurnRow(**row) for row in rows]


@router.get("/usage", response_model=list[AdminUsageRow])
async def usage(
    admin: CurrentAdmin,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
) -> list[AdminUsageRow]:
    rows = await repository.admin_usage(days)
    return [AdminUsageRow(**row) for row in rows]


@router.get("/conversations", response_model=list[AdminConversationRow])
async def conversations(
    admin: CurrentAdmin,
    limit: Annotated[int, Query(ge=1, le=300)] = 60,
) -> list[AdminConversationRow]:
    rows = await repository.admin_conversations(limit)
    return [AdminConversationRow(**row) for row in rows]


@router.get("/events", response_model=list[AdminEventRow])
async def events(
    admin: CurrentAdmin,
    limit: Annotated[int, Query(ge=1, le=300)] = 100,
    event_type: Annotated[str | None, Query()] = None,
) -> list[AdminEventRow]:
    rows = await repository.admin_events(limit, event_type)
    return [AdminEventRow(**row) for row in rows]


@router.post("/docs/refresh")
async def refresh_docs(
    admin: CurrentAdmin,
    advisor: AdvisorDep,
    store: DocumentStoreDep,
) -> dict:
    """Drop the in-process cache so the next turn re-reads the Docs.

    The PRD only requires the TTL path, but during a live demo waiting out a
    5-minute TTL is a bad look. This proves the no-redeploy property on demand
    without changing how the TTL behaves.
    """
    store.invalidate(advisor["id"])
    started = time.perf_counter()
    prompt = await store.get(advisor["id"], PROMPT, advisor, required=True)
    grounding = await store.get(advisor["id"], GROUNDING, advisor, required=False)
    return {
        "refreshed": True,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "prompt_revision": prompt.short_hash if prompt else None,
        "grounding_revision": grounding.short_hash if grounding else None,
        "stale": [d.kind for d in (prompt, grounding) if d is not None and d.stale],
    }
