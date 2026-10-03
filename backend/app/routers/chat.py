"""The chat turn (FR-01).

Two entry points over identical orchestration:

  POST /messages         blocking JSON — used by the eval harness and tests
  POST /messages/stream  SSE — used by the UI

Guardrails and document loading happen *before* the streaming response starts,
so a blocked or misconfigured request still gets a real HTTP status code instead
of an error buried inside a 200 stream.
"""

from __future__ import annotations

import asyncio
import json
import logging
from uuid import UUID

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import JSONResponse, StreamingResponse

from app import guardrails, pricing, prompting, repository, telemetry
from app.deps import AdvisorDep, CurrentUser, DocumentStoreDep, LLMClientDep, SettingsDep
from app.llm import Completion, ProviderError
from app.schemas import MessageOut, SendMessageRequest, UsageOut
from app.turn import TurnBlocked, TurnContext, TurnService, TurnUnavailable

logger = logging.getLogger("advisor.chat")

router = APIRouter(prefix="/api/conversations", tags=["chat"])


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


async def _load_conversation(conversation_id: UUID, user: dict) -> dict:
    row = await repository.get_conversation(conversation_id, user["id"])
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    return row


def _blocked_response(exc: TurnBlocked, usage: dict) -> JSONResponse:
    code = (
        status.HTTP_429_TOO_MANY_REQUESTS
        if exc.reservation.reason == "rate_limited"
        else status.HTTP_403_FORBIDDEN
    )
    body = {
        "blocked": True,
        "reason": exc.reservation.reason,
        "message": exc.message,
        "retry_after_seconds": exc.reservation.retry_after_seconds or None,
        "usage": UsageOut(**usage).model_dump(mode="json"),
    }
    headers = {}
    if exc.reservation.retry_after_seconds:
        headers["Retry-After"] = str(exc.reservation.retry_after_seconds)
    return JSONResponse(body, status_code=code, headers=headers)


@router.post("/{conversation_id}/messages")
async def send_message(
    conversation_id: UUID,
    payload: SendMessageRequest,
    user: CurrentUser,
    advisor: AdvisorDep,
    settings: SettingsDep,
    store: DocumentStoreDep,
    llm: LLMClientDep,
) -> Response:
    await _load_conversation(conversation_id, user)
    service = TurnService(settings, store, llm)

    replay = await service.replay_if_duplicate(
        conversation_id, payload.client_request_id, user["id"]
    )
    if replay is not None:
        return JSONResponse(
            {
                "replayed": True,
                "messages": [MessageOut(**m).model_dump(mode="json") for m in replay],
                "usage": UsageOut(**await guardrails.current_usage(settings, user)).model_dump(
                    mode="json"
                ),
            }
        )

    try:
        outcome = await service.run(
            user=user,
            advisor=advisor,
            conversation_id=conversation_id,
            content=payload.content.strip(),
            client_request_id=payload.client_request_id,
        )
    except TurnBlocked as exc:
        return _blocked_response(exc, await guardrails.current_usage(settings, user))
    except TurnUnavailable as exc:
        return JSONResponse(
            {"error": exc.status, "message": exc.message},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    return JSONResponse(
        {
            "user_message": MessageOut(**outcome.user_message).model_dump(mode="json"),
            "assistant_message": MessageOut(**outcome.assistant_message).model_dump(mode="json"),
            "usage": UsageOut(**outcome.usage).model_dump(mode="json"),
            "redacted": outcome.redacted,
        }
    )


@router.post("/{conversation_id}/messages/stream")
async def stream_message(
    conversation_id: UUID,
    payload: SendMessageRequest,
    user: CurrentUser,
    advisor: AdvisorDep,
    settings: SettingsDep,
    store: DocumentStoreDep,
    llm: LLMClientDep,
) -> Response:
    await _load_conversation(conversation_id, user)
    service = TurnService(settings, store, llm)
    content = payload.content.strip()

    replay = await service.replay_if_duplicate(
        conversation_id, payload.client_request_id, user["id"]
    )
    if replay is not None:
        return JSONResponse(
            {
                "replayed": True,
                "messages": [MessageOut(**m).model_dump(mode="json") for m in replay],
                "usage": UsageOut(**await guardrails.current_usage(settings, user)).model_dump(
                    mode="json"
                ),
            }
        )

    turn_id = repository.new_turn_id()

    # --- everything that can legitimately fail with a status code ---
    try:
        reservation = await service.reserve(
            user, conversation_id, content, turn_id, payload.client_request_id
        )
    except TurnBlocked as exc:
        return _blocked_response(exc, await guardrails.current_usage(settings, user))

    try:
        context = await service.build_context(advisor, conversation_id, content)
    except TurnUnavailable as exc:
        await guardrails.release(user["id"], reservation, refund_message=True)
        await repository.insert_message(
            conversation_id=conversation_id,
            user_id=user["id"],
            turn_id=turn_id,
            role="user",
            content=content,
            status="doc_error",
            client_request_id=payload.client_request_id,
        )
        await repository.insert_message(
            conversation_id=conversation_id,
            user_id=user["id"],
            turn_id=turn_id,
            role="assistant",
            content=exc.message,
            status="doc_error",
        )
        return JSONResponse(
            {"error": exc.status, "message": exc.message},
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    async def event_stream():
        result, deltas = await service.stream_result(context)
        settled = False
        emitted = 0
        try:
            yield _sse("meta", {"turn_id": str(turn_id), "conversation_id": str(conversation_id)})
            async for piece in deltas:
                emitted += len(piece)
                yield _sse("delta", {"text": piece})

            completion = result.to_completion(context.model)
            outcome = await service.finalize(
                user=user,
                advisor=advisor,
                conversation_id=conversation_id,
                content=content,
                turn_id=turn_id,
                reservation=reservation,
                context=context,
                completion=completion,
                client_request_id=payload.client_request_id,
            )
            settled = True
            yield _sse(
                "done",
                {
                    "user_message": MessageOut(**outcome.user_message).model_dump(mode="json"),
                    "assistant_message": MessageOut(**outcome.assistant_message).model_dump(
                        mode="json"
                    ),
                    "usage": UsageOut(**outcome.usage).model_dump(mode="json"),
                    "redacted": outcome.redacted,
                    # If the reply was redacted the streamed text is wrong; tell
                    # the client to replace what it rendered.
                    "replace_text": outcome.assistant_message["content"]
                    if outcome.redacted
                    else None,
                },
            )
        except ProviderError as exc:
            await guardrails.release(user["id"], reservation, refund_message=True)
            await telemetry.log_event(
                telemetry.PROVIDER_ERROR,
                severity="error",
                user_id=user["id"],
                conversation_id=conversation_id,
                advisor_id=advisor["id"],
                detail=str(exc)[:500],
                status_code=exc.status,
                partial_chars=emitted,
            )
            await _persist_failed_turn(
                user, conversation_id, turn_id, content, result.text, payload.client_request_id
            )
            settled = True
            yield _sse("error", {"error": "provider_error", "message": _PROVIDER_MESSAGE})
        except asyncio.CancelledError:
            # Client navigated away. Keep what the model already produced so the
            # conversation is not silently missing a turn on resume (FR-04).
            if not settled and result.text.strip():
                await _persist_partial_turn(
                    service, user, advisor, conversation_id, turn_id, content,
                    reservation, context, result, payload.client_request_id,
                )
                settled = True
            raise
        finally:
            if not settled:
                await guardrails.release(user["id"], reservation, refund_message=True)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


_PROVIDER_MESSAGE = (
    "I couldn't reach the model just now. This attempt wasn't counted against your "
    "daily limit — please try again."
)


async def _persist_failed_turn(
    user: dict,
    conversation_id: UUID,
    turn_id: UUID,
    content: str,
    partial: str,
    client_request_id: str | None,
) -> None:
    await repository.insert_message(
        conversation_id=conversation_id,
        user_id=user["id"],
        turn_id=turn_id,
        role="user",
        content=content,
        status="provider_error",
        client_request_id=client_request_id,
    )
    await repository.insert_message(
        conversation_id=conversation_id,
        user_id=user["id"],
        turn_id=turn_id,
        role="assistant",
        content=prompting.scrub(partial.strip()) or _PROVIDER_MESSAGE,
        status="provider_error",
    )


async def _persist_partial_turn(
    service: TurnService,
    user: dict,
    advisor: dict,
    conversation_id: UUID,
    turn_id: UUID,
    content: str,
    reservation: guardrails.Reservation,
    context: TurnContext,
    result,
    client_request_id: str | None,
) -> None:
    completion = Completion(
        text=result.text,
        model=result.model or context.model,
        prompt_tokens=result.prompt_tokens or context.estimated_prompt_tokens,
        completion_tokens=result.completion_tokens or pricing.estimate_tokens(result.text),
        finish_reason="client_disconnect",
        latency_ms=result.latency_ms,
        usage_reported=result.usage_reported,
    )
    try:
        await service.finalize(
            user=user,
            advisor=advisor,
            conversation_id=conversation_id,
            content=content,
            turn_id=turn_id,
            reservation=reservation,
            context=context,
            completion=completion,
            client_request_id=client_request_id,
        )
    except Exception:  # noqa: BLE001 - disconnect cleanup must not raise
        logger.warning("failed to persist partial turn %s", turn_id, exc_info=True)
