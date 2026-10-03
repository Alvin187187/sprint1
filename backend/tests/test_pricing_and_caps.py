"""Cost math and cap-resolution tests (FR-05, FR-07)."""

from __future__ import annotations

import pytest

from app import guardrails, pricing
from app.config import Settings


def settings(**overrides) -> Settings:
    base = {
        "default_daily_message_cap": 40,
        "default_daily_token_cap": 60_000,
        "default_daily_spend_cap_usd": 0.50,
        "app_timezone": "Asia/Manila",
    }
    base.update(overrides)
    return Settings(**base)


def test_cost_uses_separate_prompt_and_completion_prices():
    cost = pricing.cost_of("openai/gpt-4o-mini", 1_000_000, 1_000_000)
    assert cost == pytest.approx(0.15 + 0.60)


def test_unknown_model_falls_back_without_raising():
    assert pricing.cost_of("some/unreleased-model", 1000, 1000) > 0


def test_token_estimate_is_conservative_for_reservations():
    """Overestimating is the safe direction — it makes the cap stricter."""
    text = "a" * 370
    assert pricing.estimate_tokens(text) >= 100


def test_per_user_cap_overrides_the_global_default():
    caps = guardrails.resolve_caps(settings(), {"daily_message_cap": 5})
    assert caps.messages == 5
    assert caps.tokens == 60_000


def test_zero_cap_means_unlimited():
    caps = guardrails.resolve_caps(settings(), {"daily_message_cap": 0})
    assert caps.messages == 0


def test_usage_date_follows_app_timezone_not_utc():
    """A Manila cohort's caps must roll over at Manila midnight.

    23:30 UTC is already the next calendar day in Manila (UTC+8).
    """
    from datetime import datetime, timezone

    late_utc = datetime(2026, 3, 10, 23, 30, tzinfo=timezone.utc)
    manila_day = guardrails.today_in_app_tz(settings(), late_utc)
    utc_day = late_utc.date()
    assert manila_day.day == utc_day.day + 1


def test_block_messages_are_actionable():
    reservation = guardrails.Reservation(
        allowed=False,
        reason="rate_limited",
        usage_date=guardrails.today_in_app_tz(settings()),
        reserved_tokens=0,
        messages_used=3,
        tokens_used=100,
        est_spend_usd=0.0,
        retry_after_seconds=12,
        caps=guardrails.resolve_caps(settings(), {}),
    )
    message = reservation.user_message("Asia/Manila")
    assert "12 seconds" in message
    assert reservation.status == "blocked_rate"


def test_cap_block_maps_to_blocked_cap_status():
    reservation = guardrails.Reservation(
        allowed=False,
        reason="token_cap",
        usage_date=guardrails.today_in_app_tz(settings()),
        reserved_tokens=0,
        messages_used=40,
        tokens_used=60_000,
        est_spend_usd=0.4,
        retry_after_seconds=0,
        caps=guardrails.resolve_caps(settings(), {}),
    )
    assert reservation.status == "blocked_cap"
    assert "Asia/Manila" in reservation.user_message("Asia/Manila")
    assert reservation.remaining_tokens() == 0
