"""Turn orchestration — the one place where a user message becomes an advisor reply.

Ordering matters and is deliberate:

    1. idempotency replay check     cheapest, and prevents double-charging
    2. reserve (caps + rate limit)  before any paid or external work
    3. load prompt + grounding      a doc failure must not consume budget
    4. provider call
    5. egress leak scan
    6. persist turn + settle usage

Steps 3-6 each have a failure path that releases the reservation, so a user is
never charged for our infrastructure failing. Every exit writes both a message
row (FR-07) and an event (PRD §8).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app import guardrails, pricing, prompting, repository, telemetry
from app.config import Settings
from app.docsource import GROUNDING, PROMPT, DocumentStore, DocumentUnavailable
from app.grounding import select_grounding
from app.llm import Completion, LLMClient, ProviderError, StreamResult

logger = logging.getLogger("advisor.turn")

DOC_ERROR_MESSAGE = (
    "The advisor's configuration can't be loaded right now, so I'm not able to reply. "
    "This has been logged — please try again in a few minutes."
)
PROVIDER_ERROR_MESSAGE = (
    "I couldn't reach the model just now. Your message was saved and this attempt "
    "wasn't counted against your daily limit — please try again."
)
EMPTY_REPLY_MESSAGE = (
    "I didn't manage to produce a reply to that. Could you rephrase or add a bit "
    "more detail?"
)


class TurnBlocked(Exception):
    """Guardrails rejected the turn before any external call."""

    def __init__(self, reservation: guardrails.Reservation, message: str) -> None:
        super().__init__(message)
        self.reservation = reservation
        self.message = message


class TurnUnavailable(Exception):
    """A dependency failed; the user gets an error state, not a model reply."""

    def __init__(self, message: str, *, status: str) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


@dataclass
class TurnContext:
    """Everything resolved before the provider call."""

    messages: list[dict[str, str]]
    model: str
    temperature: float
    max_tokens: int
    prompt_snapshot_id: int | None
    grounding_snapshot_id: int | None
    grounding_chunk_ids: list[str]
    grounding_scores: list[float]
    prompt_revision: str
    grounding_revision: str | None
    stale_docs: list[str]
    system_message: str = field(repr=False, default="")
    persona_body: str = field(repr=False, default="")
    grounding_body: str = field(repr=False, default="")
    estimated_prompt_tokens: int = 0


@dataclass
class TurnOutcome:
    user_message: dict[str, Any]
    assistant_message: dict[str, Any]
    turn_id: UUID
    usage: dict[str, Any]
    redacted: bool = False


class TurnService:
    def __init__(
        self,
        settings: Settings,
        store: DocumentStore,
        llm: LLMClient,
    ) -> None:
        self._settings = settings
        self._store = store
        self._llm = llm

    # --- step 1 ---------------------------------------------------------------

    async def replay_if_duplicate(
        self, conversation_id: UUID | str, client_request_id: str | None, user_id: UUID | str
    ) -> list[dict] | None:
        if not client_request_id:
            return None
        existing = await repository.find_by_request_id(conversation_id, client_request_id)
        if existing is None:
            return None
        await telemetry.log_event(
            telemetry.IDEMPOTENT_REPLAY,
            user_id=user_id,
            conversation_id=conversation_id,
            client_request_id=client_request_id,
        )
        return await repository.messages_for_turn(existing["turn_id"])

    # --- step 2 ---------------------------------------------------------------

    async def reserve(
        self,
        user: dict,
        conversation_id: UUID | str,
        content: str,
        turn_id: UUID,
        client_request_id: str | None,
    ) -> guardrails.Reservation:
        # Reserve against an estimate that includes the system prompt and history,
        # not just the user's text, or the token cap under-counts by ~10x.
        estimate = pricing.estimate_tokens(content) + self._settings.max_output_tokens
        reservation = await guardrails.reserve(self._settings, user, estimate)

        if not reservation.allowed:
            message = reservation.user_message(self._settings.app_timezone)
            # Persist both sides of the blocked turn so the admin log shows what
            # the learner actually tried to ask (FR-05 "and logged").
            await repository.insert_message(
                conversation_id=conversation_id,
                user_id=user["id"],
                turn_id=turn_id,
                role="user",
                content=content,
                status=reservation.status,
                client_request_id=client_request_id,
            )
            await repository.insert_message(
                conversation_id=conversation_id,
                user_id=user["id"],
                turn_id=turn_id,
                role="assistant",
                content=message,
                status=reservation.status,
            )
            await telemetry.log_event(
                telemetry.REQUEST_BLOCKED,
                severity="warn",
                user_id=user["id"],
                conversation_id=conversation_id,
                advisor_id=self._settings.advisor_id,
                reason=reservation.reason,
                messages_used=reservation.messages_used,
                tokens_used=reservation.tokens_used,
                message_cap=reservation.caps.messages,
                token_cap=reservation.caps.tokens,
            )
            raise TurnBlocked(reservation, message)

        return reservation

    # --- step 3 ---------------------------------------------------------------

    async def build_context(
        self, advisor: dict, conversation_id: UUID | str, content: str
    ) -> TurnContext:
        try:
            prompt_doc = await self._store.get(advisor["id"], PROMPT, advisor, required=True)
            grounding_doc = await self._store.get(advisor["id"], GROUNDING, advisor, required=False)
        except DocumentUnavailable as exc:
            raise TurnUnavailable(DOC_ERROR_MESSAGE, status="doc_error") from exc

        assert prompt_doc is not None

        excerpt, chunk_ids, scores = "", [], []
        if grounding_doc is not None:
            excerpt, chunk_ids, scores = select_grounding(
                grounding_doc.body,
                content,
                max_chunks=self._settings.grounding_max_chunks,
                max_chars=self._settings.grounding_max_chars,
                min_score=self._settings.grounding_min_score,
            )

        probes = prompting.looks_like_prompt_probe(content)
        if probes:
            # Logged, not blocked — see prompting._PROBE_PATTERNS for why.
            await telemetry.log_event(
                telemetry.PROMPT_PROBE_SUSPECTED,
                severity="warn",
                conversation_id=conversation_id,
                advisor_id=advisor["id"],
                patterns=probes,
                excerpt=content[:200],
            )

        assembled = prompting.assemble_system_message(prompt_doc.body, excerpt, chunk_ids)

        history = await repository.history_for_prompt(
            conversation_id, self._settings.max_history_turns
        )
        messages: list[dict[str, str]] = [{"role": "system", "content": assembled.system_message}]
        messages.extend({"role": r["role"], "content": r["content"]} for r in history)
        messages.append({"role": "user", "content": content})

        stale = [d.kind for d in (prompt_doc, grounding_doc) if d is not None and d.stale]

        return TurnContext(
            messages=messages,
            model=advisor.get("model") or self._settings.model,
            temperature=float(advisor.get("temperature") or self._settings.model_temperature),
            max_tokens=int(advisor.get("max_output_tokens") or self._settings.max_output_tokens),
            prompt_snapshot_id=prompt_doc.snapshot_id,
            grounding_snapshot_id=grounding_doc.snapshot_id if grounding_doc else None,
            grounding_chunk_ids=chunk_ids,
            grounding_scores=scores,
            prompt_revision=prompt_doc.short_hash,
            grounding_revision=grounding_doc.short_hash if grounding_doc else None,
            stale_docs=stale,
            system_message=assembled.system_message,
            persona_body=prompt_doc.body,
            grounding_body=excerpt,
            estimated_prompt_tokens=pricing.estimate_tokens(
                "".join(m["content"] for m in messages)
            ),
        )

    # --- steps 4-6 ------------------------------------------------------------

    async def run(
        self,
        *,
        user: dict,
        advisor: dict,
        conversation_id: UUID | str,
        content: str,
        client_request_id: str | None = None,
    ) -> TurnOutcome:
        turn_id = repository.new_turn_id()
        reservation = await self.reserve(
            user, conversation_id, content, turn_id, client_request_id
        )

        try:
            context = await self.build_context(advisor, conversation_id, content)
        except TurnUnavailable:
            await guardrails.release(user["id"], reservation, refund_message=True)
            raise

        try:
            completion = await self._llm.complete(
                context.messages,
                model=context.model,
                temperature=context.temperature,
                max_tokens=context.max_tokens,
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
            )
            raise TurnUnavailable(PROVIDER_ERROR_MESSAGE, status="provider_error") from exc

        return await self.finalize(
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

    async def finalize(
        self,
        *,
        user: dict,
        advisor: dict,
        conversation_id: UUID | str,
        content: str,
        turn_id: UUID,
        reservation: guardrails.Reservation,
        context: TurnContext,
        completion: Completion,
        client_request_id: str | None,
    ) -> TurnOutcome:
        """Scan, cost, persist, settle. Shared by the streaming and blocking paths."""
        status = "ok"
        redacted = False
        reply = completion.text.strip()

        verdict = prompting.detect_leak(reply, context.persona_body, context.grounding_body)
        if verdict.leaked:
            status = "redacted"
            redacted = True
            await telemetry.log_event(
                telemetry.PROMPT_LEAK_BLOCKED,
                severity="error",
                user_id=user["id"],
                conversation_id=conversation_id,
                advisor_id=advisor["id"],
                kind=verdict.kind,
                detail=verdict.detail,
                prompt_revision=context.prompt_revision,
            )
            reply = prompting.REDACTION_MESSAGE
        elif not reply:
            status = "truncated"
            reply = EMPTY_REPLY_MESSAGE
        elif completion.finish_reason in {"length", "client_disconnect"}:
            status = "truncated"

        reply = prompting.scrub(reply)

        prompt_tokens = completion.prompt_tokens or context.estimated_prompt_tokens
        completion_tokens = completion.completion_tokens or pricing.estimate_tokens(reply)
        cost = pricing.estimate_turn_cost(completion.model, prompt_tokens, completion_tokens)

        user_row = await repository.insert_message(
            conversation_id=conversation_id,
            user_id=user["id"],
            turn_id=turn_id,
            role="user",
            content=content,
            status="ok",
            prompt_tokens=prompt_tokens,
            model=completion.model,
            prompt_snapshot_id=context.prompt_snapshot_id,
            grounding_snapshot_id=context.grounding_snapshot_id,
            grounding_chunk_ids=context.grounding_chunk_ids,
            client_request_id=client_request_id,
        )
        assistant_row = await repository.insert_message(
            conversation_id=conversation_id,
            user_id=user["id"],
            turn_id=turn_id,
            role="assistant",
            content=reply,
            status=status,
            completion_tokens=completion_tokens,
            est_cost_usd=cost.est_cost_usd,
            model=completion.model,
            latency_ms=completion.latency_ms,
            prompt_snapshot_id=context.prompt_snapshot_id,
            grounding_snapshot_id=context.grounding_snapshot_id,
            grounding_chunk_ids=context.grounding_chunk_ids,
        )

        await guardrails.settle(
            user["id"], reservation, prompt_tokens + completion_tokens, cost.est_cost_usd
        )

        await telemetry.log_event(
            telemetry.LLM_CALL_COMPLETED,
            user_id=user["id"],
            conversation_id=conversation_id,
            message_id=assistant_row["id"],
            advisor_id=advisor["id"],
            model=completion.model,
            status=status,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            est_cost_usd=cost.est_cost_usd,
            latency_ms=completion.latency_ms,
            usage_reported=completion.usage_reported,
            grounding_chunks=context.grounding_chunk_ids,
            grounding_scores=context.grounding_scores,
            prompt_revision=context.prompt_revision,
            grounding_revision=context.grounding_revision,
            stale_docs=context.stale_docs,
            finish_reason=completion.finish_reason,
        )

        await self._maybe_title(conversation_id, content)

        usage = await guardrails.current_usage(self._settings, user)
        return TurnOutcome(
            user_message=user_row,
            assistant_message=assistant_row,
            turn_id=turn_id,
            usage=usage,
            redacted=redacted,
        )

    async def stream_result(self, context: TurnContext) -> tuple[StreamResult, Any]:
        """Return (mutable result, async generator of deltas)."""
        result = StreamResult()
        generator = self._llm.stream(
            context.messages,
            model=context.model,
            temperature=context.temperature,
            max_tokens=context.max_tokens,
            result=result,
        )
        return result, generator

    async def _maybe_title(self, conversation_id: UUID | str, first_user_message: str) -> None:
        """Derive a title from the opening message — no extra model call needed."""
        row = await repository.get_conversation_row_for_title(conversation_id)
        if row is None or row["message_count"] > 2 or row["title"] != "New conversation":
            return
        words = first_user_message.strip().split()
        title = " ".join(words[:9])
        if len(words) > 9:
            title += "…"
        await repository.rename_conversation(conversation_id, title[:160] or "New conversation")
