"""Conversation list, resume, rename, archive (FR-04)."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, HTTPException, status

from app import guardrails, repository
from app.deps import AdvisorDep, CurrentUser, SettingsDep
from app.schemas import (
    ConversationDetail,
    ConversationSummary,
    CreateConversationRequest,
    MessageOut,
    UsageOut,
)

router = APIRouter(prefix="/api/conversations", tags=["conversations"])


@router.get("", response_model=list[ConversationSummary])
async def list_conversations(user: CurrentUser) -> list[ConversationSummary]:
    rows = await repository.list_conversations(user["id"])
    return [ConversationSummary(**row) for row in rows]


@router.post("", response_model=ConversationDetail, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    payload: CreateConversationRequest, user: CurrentUser, advisor: AdvisorDep
) -> ConversationDetail:
    row = await repository.create_conversation(
        user["id"], advisor["id"], (payload.title or "New conversation")[:160]
    )
    return ConversationDetail(
        id=row["id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        messages=[],
    )


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: UUID, user: CurrentUser) -> ConversationDetail:
    row = await repository.get_conversation(conversation_id, user["id"])
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    messages = await repository.list_messages(conversation_id)
    return ConversationDetail(
        id=row["id"],
        title=row["title"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        messages=[MessageOut(**m) for m in messages],
    )


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_conversation(conversation_id: UUID, user: CurrentUser) -> None:
    row = await repository.get_conversation(conversation_id, user["id"])
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    await repository.archive_conversation(conversation_id, user["id"])


usage_router = APIRouter(prefix="/api/usage", tags=["usage"])


@usage_router.get("", response_model=UsageOut)
async def my_usage(user: CurrentUser, settings: SettingsDep) -> UsageOut:
    """The learner sees their own remaining allowance — never cost (PRD §2.1)."""
    return UsageOut(**await guardrails.current_usage(settings, user))
