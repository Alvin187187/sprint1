"""Cap and rate-limit enforcement (FR-05, FR-06).

All the interesting logic lives in `advisor.reserve_turn` in Postgres. This
module is the thin typed wrapper plus cap resolution, and it exists mainly to
make the reserve → settle / release lifecycle hard to get wrong at the call site.

Why reserve-then-settle instead of a plain post-hoc increment: token usage is
only known *after* the provider replies, so a check-then-call design lets any
number of concurrent requests pass the same cap check. The reservation takes the
estimated cost of the turn out of the budget up front and reconciles to the real
number afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from uuid import UUID

from app.config import Settings
from app.db import fetch_one, execute

BLOCK_REASONS = {
    "rate_limited": (
        "You're sending messages a bit fast. Give it {retry} seconds and try again."
    ),
    "message_cap": (
        "You've reached your daily message limit for the advisor. It resets at "
        "midnight {tz}."
    ),
    "token_cap": (
        "You've reached your daily usage limit for the advisor. It resets at "
        "midnight {tz}."
    ),
    "spend_cap": (
        "You've reached your daily usage limit for the advisor. It resets at "
        "midnight {tz}."
    ),
}

# Maps a block reason to the message.status value persisted for the turn.
STATUS_FOR_REASON = {
    "rate_limited": "blocked_rate",
    "message_cap": "blocked_cap",
    "token_cap": "blocked_cap",
    "spend_cap": "blocked_cap",
}


@dataclass(frozen=True)
class Caps:
    messages: int
    tokens: int
    spend_usd: float


@dataclass(frozen=True)
class Reservation:
    allowed: bool
    reason: str | None
    usage_date: date
    reserved_tokens: int
    messages_used: int
    tokens_used: int
    est_spend_usd: float
    retry_after_seconds: int
    caps: Caps

    @property
    def status(self) -> str:
        return STATUS_FOR_REASON.get(self.reason or "", "ok")

    def user_message(self, timezone_label: str) -> str:
        template = BLOCK_REASONS.get(self.reason or "", "This request was blocked.")
        return template.format(retry=self.retry_after_seconds, tz=timezone_label)

    def remaining_messages(self) -> int | None:
        if self.caps.messages <= 0:
            return None
        return max(0, self.caps.messages - self.messages_used)

    def remaining_tokens(self) -> int | None:
        if self.caps.tokens <= 0:
            return None
        return max(0, self.caps.tokens - self.tokens_used)


def today_in_app_tz(settings: Settings, now: datetime | None = None) -> date:
    moment = now or datetime.now(settings.tz)
    return moment.astimezone(settings.tz).date()


def resolve_caps(settings: Settings, user: dict) -> Caps:
    """Per-user override wins; 0 or negative means unlimited."""
    return Caps(
        messages=_pick(user.get("daily_message_cap"), settings.default_daily_message_cap),
        tokens=_pick(user.get("daily_token_cap"), settings.default_daily_token_cap),
        spend_usd=float(
            _pick(user.get("daily_spend_cap_usd"), settings.default_daily_spend_cap_usd)
        ),
    )


def _pick(override, default):
    return default if override is None else override


async def reserve(
    settings: Settings,
    user: dict,
    estimated_tokens: int,
) -> Reservation:
    caps = resolve_caps(settings, user)
    usage_date = today_in_app_tz(settings)

    row = await fetch_one(
        """
        select * from advisor.reserve_turn(
            %s::uuid, %s::date, %s::int, %s::int, %s::int, %s::numeric, %s::int, %s::int
        )
        """,
        (
            str(user["id"]),
            usage_date,
            estimated_tokens,
            caps.messages,
            caps.tokens,
            caps.spend_usd,
            settings.rate_limit_per_window,
            settings.rate_limit_window_seconds,
        ),
    )
    assert row is not None

    return Reservation(
        allowed=bool(row["allowed"]),
        reason=row["reason"],
        usage_date=usage_date,
        reserved_tokens=estimated_tokens if row["allowed"] else 0,
        messages_used=row["messages_used"],
        tokens_used=row["tokens_used"],
        est_spend_usd=float(row["est_spend_usd"] or 0),
        retry_after_seconds=int(row["retry_after_seconds"] or 0),
        caps=caps,
    )


async def settle(
    user_id: UUID | str,
    reservation: Reservation,
    actual_tokens: int,
    cost_usd: float,
) -> None:
    await execute(
        "select advisor.settle_turn(%s::uuid, %s::date, %s::int, %s::int, %s::numeric)",
        (str(user_id), reservation.usage_date, reservation.reserved_tokens, actual_tokens, cost_usd),
    )


async def release(
    user_id: UUID | str,
    reservation: Reservation,
    *,
    refund_message: bool,
) -> None:
    """Undo a reservation after a failure that wasn't the user's fault."""
    await execute(
        "select advisor.release_turn(%s::uuid, %s::date, %s::int, %s::boolean)",
        (str(user_id), reservation.usage_date, reservation.reserved_tokens, refund_message),
    )


async def current_usage(settings: Settings, user: dict) -> dict:
    caps = resolve_caps(settings, user)
    usage_date = today_in_app_tz(settings)
    row = await fetch_one(
        """
        select messages_used, tokens_used, est_spend_usd
          from advisor.usage_counters
         where user_id = %s::uuid and usage_date = %s::date
        """,
        (str(user["id"]), usage_date),
    )
    messages_used = row["messages_used"] if row else 0
    tokens_used = row["tokens_used"] if row else 0
    return {
        "usage_date": usage_date,
        "timezone": settings.app_timezone,
        "messages_used": messages_used,
        "tokens_used": tokens_used,
        "message_cap": caps.messages or None,
        "token_cap": caps.tokens or None,
        "messages_remaining": max(0, caps.messages - messages_used) if caps.messages > 0 else None,
        "tokens_remaining": max(0, caps.tokens - tokens_used) if caps.tokens > 0 else None,
        "rate_limit_per_minute": settings.rate_limit_per_window,
    }
