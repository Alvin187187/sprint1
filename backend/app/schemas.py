"""Request/response models.

Note what is absent: no model here has a field for the system prompt, the
grounding excerpt, or the assembled context. That is the structural half of the
prompt-secrecy guarantee (NFR Security) — there is no shape in which a route
*could* return them, so secrecy does not rely on remembering to exclude them.

Admin models expose revision hashes and chunk ids, never document bodies.
"""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field


# --- auth ---------------------------------------------------------------------


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    id: UUID
    email: str
    display_name: str
    role: str


class AdvisorOut(BaseModel):
    id: str
    name: str


class SessionOut(BaseModel):
    user: UserOut
    advisor: AdvisorOut


# --- usage --------------------------------------------------------------------


class UsageOut(BaseModel):
    usage_date: date
    timezone: str
    messages_used: int
    tokens_used: int
    message_cap: int | None
    token_cap: int | None
    messages_remaining: int | None
    tokens_remaining: int | None
    rate_limit_per_minute: int


# --- conversations ------------------------------------------------------------


class ConversationSummary(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    last_message_at: datetime | None
    message_count: int
    preview: str | None = None


class MessageOut(BaseModel):
    id: UUID
    role: str
    content: str
    status: str
    created_at: datetime
    # Token counts are shown to the user's own session only as a usage signal;
    # cost is admin-only per PRD §2.1.
    tokens: int | None = None


class ConversationDetail(BaseModel):
    id: UUID
    title: str
    created_at: datetime
    updated_at: datetime
    messages: list[MessageOut]


class CreateConversationRequest(BaseModel):
    title: str | None = Field(default=None, max_length=160)


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    # Client-generated idempotency key. A retried or double-clicked send with the
    # same key replays the stored turn instead of charging the user twice.
    client_request_id: str | None = Field(default=None, max_length=64)


class BlockedOut(BaseModel):
    blocked: bool = True
    reason: str
    message: str
    retry_after_seconds: int | None = None
    usage: UsageOut


# --- admin --------------------------------------------------------------------


class AdminTurnRow(BaseModel):
    message_id: UUID
    conversation_id: UUID
    user_email: str
    role: str
    status: str
    model: str | None
    prompt_tokens: int
    completion_tokens: int
    tokens: int
    est_cost_usd: float
    latency_ms: int | None
    prompt_revision: str | None
    grounding_revision: str | None
    grounding_chunk_ids: list[str]
    content_excerpt: str
    created_at: datetime


class AdminUsageRow(BaseModel):
    user_id: UUID
    email: str
    display_name: str
    usage_date: date | None
    messages_used: int
    tokens_used: int
    est_spend_usd: float
    daily_message_cap: int
    daily_token_cap: int


class AdminConversationRow(BaseModel):
    id: UUID
    user_email: str
    title: str
    message_count: int
    total_tokens: int
    total_est_cost_usd: float
    last_message_at: datetime | None
    created_at: datetime


class AdminEventRow(BaseModel):
    id: int
    event_type: str
    severity: str
    user_email: str | None
    payload: dict
    created_at: datetime


class DocStatusOut(BaseModel):
    kind: str
    source: str
    revision: str
    char_count: int
    stale: bool
    cache_expires_in_seconds: int | None
    fetched_at: datetime


class AdminOverviewOut(BaseModel):
    totals: dict
    docs: list[DocStatusOut]
    by_status: dict[str, int]
    by_event: dict[str, int]
