"""Runtime configuration.

Every secret and every tunable lives here and is read from the environment.
Nothing in this module may be serialized to a client response.
"""

from __future__ import annotations

from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- app ---
    app_name: str = "Advisor Console"
    environment: str = "development"
    advisor_id: str = "career-transition"
    # Caps reset on the calendar day in this timezone, not UTC. A Manila cohort
    # whose caps rolled over at 08:00 local would be a support nightmare.
    app_timezone: str = "Asia/Manila"
    cors_origins: str = "http://localhost:5173"

    # --- database ---
    database_url: str = Field(default="", description="Postgres DSN (Supabase pooler)")
    db_pool_min: int = 1
    db_pool_max: int = 8

    # --- auth ---
    session_ttl_hours: int = 720
    session_cookie_secure: bool = False
    # Set in production so the admin console is not world-open.
    admin_emails: str = ""

    # --- document control plane ---
    doc_provider: str = "local"  # "local" | "google_docs"
    doc_cache_ttl_seconds: int = 300
    doc_root: str = "../content"
    google_service_account_json: str = ""  # raw JSON or a path to the key file
    prompt_doc_id: str = ""
    grounding_doc_id: str = ""

    # --- grounding retrieval ---
    grounding_max_chunks: int = 3
    grounding_max_chars: int = 2600
    # Tuned with scripts/tune_threshold.py against questions that should and
    # should not retrieve. See docs/ARCHITECTURE.md §Retrieval for why this is a
    # quality threshold and not a security boundary.
    grounding_min_score: float = 0.08

    # --- model / provider ---
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    model: str = "openai/gpt-4o-mini"
    model_temperature: float = 0.4
    max_output_tokens: int = 900
    request_timeout_seconds: float = 60.0
    max_history_turns: int = 12
    max_user_message_chars: int = 4000

    # --- guardrails ---
    default_daily_message_cap: int = 40
    default_daily_token_cap: int = 60_000
    default_daily_spend_cap_usd: float = 0.50
    rate_limit_per_window: int = 6
    rate_limit_window_seconds: int = 60

    # --- pricing (USD per 1M tokens); override per model via MODEL_PRICE_* ---
    price_prompt_per_mtok: float = 0.15
    price_completion_per_mtok: float = 0.60

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.app_timezone)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def admin_email_set(self) -> set[str]:
        return {e.strip().lower() for e in self.admin_emails.split(",") if e.strip()}


@lru_cache
def get_settings() -> Settings:
    return Settings()
