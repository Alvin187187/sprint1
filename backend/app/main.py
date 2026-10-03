"""Application entrypoint."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.db import close_pool, fetch_one, open_pool
from app.deps import get_document_store, get_llm_client
from app.docsource import DocumentUnavailable
from app.routers import admin, auth, chat, conversations

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(name)s %(message)s",
)
logger = logging.getLogger("advisor")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await open_pool()
    logger.info(
        "advisor console up | advisor=%s provider=%s model=%s tz=%s",
        settings.advisor_id,
        settings.doc_provider,
        settings.model,
        settings.app_timezone,
    )
    try:
        yield
    finally:
        await get_llm_client().aclose()
        await close_pool()


settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    lifespan=lifespan,
    # The schema would otherwise advertise internals to anyone who finds the URL.
    docs_url="/api/docs" if settings.environment == "development" else None,
    redoc_url=None,
    openapi_url="/api/openapi.json" if settings.environment == "development" else None,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "PATCH"],
    allow_headers=["Content-Type", "Authorization"],
)

app.include_router(auth.router)
app.include_router(conversations.router)
app.include_router(conversations.usage_router)
app.include_router(chat.router)
app.include_router(admin.router)


@app.exception_handler(DocumentUnavailable)
async def document_unavailable_handler(request: Request, exc: DocumentUnavailable) -> JSONResponse:
    return JSONResponse(
        {
            "error": "doc_error",
            "message": (
                "The advisor's configuration can't be loaded right now. "
                "This has been logged — please try again shortly."
            ),
        },
        status_code=503,
    )


@app.get("/api/health", tags=["ops"])
async def health() -> dict:
    """Readiness, not just liveness: reports the dependencies that can break.

    Deliberately does not fetch the Docs — a health check that burns Docs API
    quota on every probe causes the outage it is meant to detect.
    """
    checks: dict[str, str] = {}
    try:
        await fetch_one("select 1 as ok")
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        checks["database"] = f"error: {type(exc).__name__}"

    checks["provider_key"] = "configured" if settings.openrouter_api_key else "missing"
    checks["doc_provider"] = get_document_store().source_name
    healthy = checks["database"] == "ok" and checks["provider_key"] == "configured"

    return {"status": "ok" if healthy else "degraded", "checks": checks}
