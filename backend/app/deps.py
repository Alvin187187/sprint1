"""Shared request dependencies: settings, singletons, and the current user."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request, status

from app import repository, telemetry
from app.config import Settings, get_settings
from app.docsource import DocumentStore
from app.llm import LLMClient

SettingsDep = Annotated[Settings, Depends(get_settings)]


@lru_cache
def get_document_store() -> DocumentStore:
    return DocumentStore(get_settings())


@lru_cache
def get_llm_client() -> LLMClient:
    return LLMClient(get_settings())


DocumentStoreDep = Annotated[DocumentStore, Depends(get_document_store)]
LLMClientDep = Annotated[LLMClient, Depends(get_llm_client)]


async def current_user(
    request: Request,
    advisor_session: Annotated[str | None, Cookie(alias="advisor_session")] = None,
) -> dict:
    from app.security import hash_session_token  # local import avoids a cycle

    # Cookie for the browser; bearer token for the eval harness and curl.
    token = advisor_session
    if not token:
        header = request.headers.get("authorization", "")
        if header.lower().startswith("bearer "):
            token = header[7:].strip()
    if not token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not signed in")

    user = await repository.get_user_by_session(hash_session_token(token))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Session expired or invalid")
    return user


CurrentUser = Annotated[dict, Depends(current_user)]


async def current_admin(user: CurrentUser, settings: SettingsDep) -> dict:
    allowed = user["role"] == "admin" or user["email"].lower() in settings.admin_email_set
    if not allowed:
        await telemetry.log_event(
            "admin_access_denied", severity="warn", user_id=user["id"], email=user["email"]
        )
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Admin access required")
    return user


CurrentAdmin = Annotated[dict, Depends(current_admin)]


async def require_advisor(settings: SettingsDep) -> dict:
    advisor = await repository.get_advisor(settings.advisor_id)
    if advisor is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"Advisor '{settings.advisor_id}' is not configured",
        )
    return advisor


AdvisorDep = Annotated[dict, Depends(require_advisor)]
