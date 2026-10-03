"""Token estimation and cost attribution.

Prices are USD per million tokens and are intentionally data, not logic, so the
pair can correct them without touching the request path. When OpenRouter returns
real usage we use it; the estimate only covers the pre-flight reservation and
provider failures where no usage is reported.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

# USD per 1M tokens. Verify against openrouter.ai/models before the demo —
# these are the figures the cost column in the admin view is built on.
PRICES: dict[str, tuple[float, float]] = {
    "openai/gpt-4o-mini": (0.15, 0.60),
    "openai/gpt-4o": (2.50, 10.00),
    "openai/gpt-4.1-mini": (0.40, 1.60),
    "anthropic/claude-3.5-haiku": (0.80, 4.00),
    "anthropic/claude-sonnet-4": (3.00, 15.00),
    "google/gemini-2.0-flash-001": (0.10, 0.40),
    "meta-llama/llama-3.3-70b-instruct": (0.12, 0.30),
}

_DEFAULT_PRICE = (0.15, 0.60)

# Rough bytes-per-token for English prose. Only used for reservations, so a
# small overestimate is the safe direction — it makes the cap conservative.
_CHARS_PER_TOKEN = 3.7


@dataclass(frozen=True)
class Cost:
    prompt_tokens: int
    completion_tokens: int
    est_cost_usd: float

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, math.ceil(len(text) / _CHARS_PER_TOKEN))


def price_for(model: str) -> tuple[float, float]:
    return PRICES.get(model, _DEFAULT_PRICE)


def cost_of(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    prompt_price, completion_price = price_for(model)
    return round(
        (prompt_tokens / 1_000_000) * prompt_price
        + (completion_tokens / 1_000_000) * completion_price,
        6,
    )


def estimate_turn_cost(model: str, prompt_tokens: int, completion_tokens: int) -> Cost:
    return Cost(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        est_cost_usd=cost_of(model, prompt_tokens, completion_tokens),
    )
