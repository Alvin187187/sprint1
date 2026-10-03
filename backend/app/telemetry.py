"""Append-only event log (PRD §8).

Writing telemetry must never be able to fail a user request, so every call is
wrapped: a broken log line degrades observability, not availability.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from uuid import UUID

from app.db import execute

logger = logging.getLogger("advisor.telemetry")

# PRD §8 plus the events the hardened design adds.
MESSAGE_SENT = "message_sent"
LLM_CALL_COMPLETED = "llm_call_completed"
REQUEST_BLOCKED = "request_blocked"
PROMPT_CACHE_HIT = "prompt_cache_hit"
PROMPT_CACHE_MISS = "prompt_cache_miss"
DOC_FETCH_ERROR = "doc_fetch_error"
DOC_REVISION_CHANGED = "doc_revision_changed"
PROVIDER_ERROR = "provider_error"
PROMPT_LEAK_BLOCKED = "prompt_leak_blocked"
PROMPT_PROBE_SUSPECTED = "prompt_probe_suspected"
PROMPT_PROBE_SUSPECTED = "prompt_probe_suspected"
LOGIN_SUCCEEDED = "login_succeeded"
LOGIN_FAILED = "login_failed"
IDEMPOTENT_REPLAY = "idempotent_replay"


async def log_event(
    event_type: str,
    *,
    severity: str = "info",
    user_id: UUID | str | None = None,
    conversation_id: UUID | str | None = None,
    message_id: UUID | str | None = None,
    advisor_id: str | None = None,
    **payload: Any,
) -> None:
    try:
        await execute(
            """
            insert into advisor.events
                (event_type, severity, user_id, conversation_id, message_id, advisor_id, payload)
            values (%s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (
                event_type,
                severity,
                str(user_id) if user_id else None,
                str(conversation_id) if conversation_id else None,
                str(message_id) if message_id else None,
                advisor_id,
                json.dumps(payload, default=str),
            ),
        )
    except Exception:  # noqa: BLE001 - telemetry is best-effort by design
        logger.warning("failed to persist event %s", event_type, exc_info=True)
