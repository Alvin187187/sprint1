"""Structural prompt-secrecy check (NFR Security: 0 exposures).

Instead of manually inspecting network traffic once during a demo, walk the
generated OpenAPI schema and assert that no response model anywhere in the API
has a field that could carry prompt or grounding text. If someone later adds
`system_prompt` to a response for debugging, this fails in CI.
"""

from __future__ import annotations

import json

import pytest

from app.main import app

# Field names that must never appear in any schema the client can receive.
FORBIDDEN_FIELDS = {
    "system_message",
    "system_prompt",
    "prompt_body",
    "persona_prompt",
    "persona_body",
    "grounding_body",
    "grounding_text",
    "grounding_excerpt",
    "doc_body",
    "body",
    "canary",
    "api_key",
    "openrouter_api_key",
    "password_hash",
    "service_account",
    "database_url",
    "token_hash",
}


@pytest.fixture(scope="module")
def spec() -> dict:
    return app.openapi()


def test_every_route_is_namespaced_under_api(spec):
    for path in spec["paths"]:
        assert path.startswith("/api"), path


def test_no_schema_exposes_prompt_bearing_fields(spec):
    offenders: list[str] = []
    for name, schema in (spec.get("components", {}).get("schemas", {})).items():
        for field in (schema.get("properties") or {}):
            if field.lower() in FORBIDDEN_FIELDS:
                offenders.append(f"{name}.{field}")
    assert not offenders, f"client-visible schema exposes {offenders}"


def test_no_prompt_text_leaked_into_the_schema_itself(spec):
    """Descriptions and examples are client-visible too."""
    blob = json.dumps(spec).lower()
    for phrase in (
        "non-negotiable system rules",
        "you are the **career transition advisor**",
        "bridge over leap",
    ):
        assert phrase not in blob, phrase


def test_admin_turn_rows_expose_revisions_not_documents(spec):
    props = spec["components"]["schemas"]["AdminTurnRow"]["properties"]
    assert "prompt_revision" in props
    assert "grounding_revision" in props
    assert not any(p in props for p in ("prompt_body", "grounding_body", "system_message"))


def test_user_facing_message_model_has_no_cost_field(spec):
    """PRD §2.1: the end user never sees cost data."""
    props = spec["components"]["schemas"]["MessageOut"]["properties"]
    assert "est_cost_usd" not in props
