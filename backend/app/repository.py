"""Data access. Plain SQL, no ORM — the schema is small and the queries are the
interesting part, so hiding them behind a mapper would cost more than it saves.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID, uuid4

from app.db import connection, fetch_all, fetch_one


# --- users & sessions ---------------------------------------------------------


async def get_user_by_email(email: str) -> dict | None:
    return await fetch_one(
        "select * from advisor.users where lower(email) = lower(%s) and disabled_at is null",
        (email,),
    )


async def get_user(user_id: UUID | str) -> dict | None:
    return await fetch_one("select * from advisor.users where id = %s::uuid", (str(user_id),))


async def create_session(user_id: UUID | str, token_hash: str, ttl_hours: int, user_agent: str | None) -> dict:
    row = await fetch_one(
        """
        insert into advisor.sessions (user_id, token_hash, expires_at, user_agent)
        values (%s::uuid, %s, now() + make_interval(hours => %s), %s)
        returning id, expires_at
        """,
        (str(user_id), token_hash, ttl_hours, user_agent),
    )
    assert row is not None
    return row


async def get_user_by_session(token_hash: str) -> dict | None:
    return await fetch_one(
        """
        select u.*
          from advisor.sessions s
          join advisor.users u on u.id = s.user_id
         where s.token_hash = %s
           and s.revoked_at is null
           and s.expires_at > now()
           and u.disabled_at is null
        """,
        (token_hash,),
    )


async def revoke_session(token_hash: str) -> None:
    async with connection() as conn:
        await conn.execute(
            "update advisor.sessions set revoked_at = now() where token_hash = %s",
            (token_hash,),
        )


# --- advisor ------------------------------------------------------------------


async def get_advisor(advisor_id: str) -> dict | None:
    return await fetch_one("select * from advisor.advisors where id = %s", (advisor_id,))


# --- conversations ------------------------------------------------------------


async def list_conversations(user_id: UUID | str, limit: int = 50) -> list[dict]:
    return await fetch_all(
        """
        select c.id, c.title, c.created_at, c.updated_at, c.last_message_at, c.message_count,
               (
                 select left(m.content, 120) from advisor.messages m
                  where m.conversation_id = c.id and m.role = 'user'
                  order by m.created_at desc limit 1
               ) as preview
          from advisor.conversations c
         where c.user_id = %s::uuid and c.archived_at is null
         order by coalesce(c.last_message_at, c.created_at) desc
         limit %s
        """,
        (str(user_id), limit),
    )


async def create_conversation(user_id: UUID | str, advisor_id: str, title: str) -> dict:
    row = await fetch_one(
        """
        insert into advisor.conversations (user_id, advisor_id, title)
        values (%s::uuid, %s, %s)
        returning id, title, created_at, updated_at, last_message_at, message_count
        """,
        (str(user_id), advisor_id, title),
    )
    assert row is not None
    return row


async def get_conversation(conversation_id: UUID | str, user_id: UUID | str) -> dict | None:
    return await fetch_one(
        """
        select * from advisor.conversations
         where id = %s::uuid and user_id = %s::uuid and archived_at is null
        """,
        (str(conversation_id), str(user_id)),
    )


async def get_conversation_row_for_title(conversation_id: UUID | str) -> dict | None:
    return await fetch_one(
        "select title, message_count from advisor.conversations where id = %s::uuid",
        (str(conversation_id),),
    )


async def rename_conversation(conversation_id: UUID | str, title: str) -> None:
    async with connection() as conn:
        await conn.execute(
            "update advisor.conversations set title = %s, updated_at = now() where id = %s::uuid",
            (title, str(conversation_id)),
        )


async def archive_conversation(conversation_id: UUID | str, user_id: UUID | str) -> None:
    async with connection() as conn:
        await conn.execute(
            """
            update advisor.conversations set archived_at = now(), updated_at = now()
             where id = %s::uuid and user_id = %s::uuid
            """,
            (str(conversation_id), str(user_id)),
        )


# --- messages -----------------------------------------------------------------


async def list_messages(conversation_id: UUID | str) -> list[dict]:
    return await fetch_all(
        """
        select id, role, content, status, tokens, created_at
          from advisor.messages
         where conversation_id = %s::uuid
         order by created_at, id
        """,
        (str(conversation_id),),
    )


async def history_for_prompt(conversation_id: UUID | str, max_turns: int) -> list[dict]:
    """Most recent N successful messages, oldest-first.

    Blocked and errored rows are excluded: a 'you hit your cap' notice is a
    product artifact, not conversational context, and feeding it back would
    teach the advisor to talk about limits.
    """
    rows = await fetch_all(
        """
        select role, content from (
            select role, content, created_at, id
              from advisor.messages
             where conversation_id = %s::uuid and status in ('ok', 'truncated')
             order by created_at desc, id desc
             limit %s
        ) recent
        order by created_at, id
        """,
        (str(conversation_id), max_turns * 2),
    )
    return rows


async def find_by_request_id(conversation_id: UUID | str, client_request_id: str) -> dict | None:
    return await fetch_one(
        """
        select turn_id from advisor.messages
         where conversation_id = %s::uuid and client_request_id = %s
         limit 1
        """,
        (str(conversation_id), client_request_id),
    )


async def messages_for_turn(turn_id: UUID | str) -> list[dict]:
    return await fetch_all(
        """
        select id, role, content, status, tokens, created_at
          from advisor.messages where turn_id = %s::uuid
         order by created_at, id
        """,
        (str(turn_id),),
    )


async def insert_message(
    *,
    conversation_id: UUID | str,
    user_id: UUID | str,
    turn_id: UUID,
    role: str,
    content: str,
    status: str = "ok",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    est_cost_usd: float = 0.0,
    model: str | None = None,
    latency_ms: int | None = None,
    prompt_snapshot_id: int | None = None,
    grounding_snapshot_id: int | None = None,
    grounding_chunk_ids: list[str] | None = None,
    client_request_id: str | None = None,
) -> dict:
    row = await fetch_one(
        """
        insert into advisor.messages (
            conversation_id, user_id, turn_id, role, content, status,
            prompt_tokens, completion_tokens, est_cost_usd, model, latency_ms,
            prompt_snapshot_id, grounding_snapshot_id, grounding_chunk_ids, client_request_id
        )
        values (%s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        returning id, role, content, status, tokens, created_at
        """,
        (
            str(conversation_id),
            str(user_id),
            str(turn_id),
            role,
            content,
            status,
            prompt_tokens,
            completion_tokens,
            est_cost_usd,
            model,
            latency_ms,
            prompt_snapshot_id,
            grounding_snapshot_id,
            grounding_chunk_ids or [],
            client_request_id,
        ),
    )
    assert row is not None
    return row


def new_turn_id() -> UUID:
    return uuid4()


# --- admin read models --------------------------------------------------------


async def admin_recent_turns(limit: int, status: str | None, user_email: str | None) -> list[dict]:
    return await fetch_all(
        """
        select m.id as message_id, m.conversation_id, u.email as user_email, m.role, m.status,
               m.model, m.prompt_tokens, m.completion_tokens, m.tokens, m.est_cost_usd,
               m.latency_ms, m.grounding_chunk_ids,
               left(ps.revision_hash, 12) as prompt_revision,
               left(gs.revision_hash, 12) as grounding_revision,
               left(m.content, 400) as content_excerpt,
               m.created_at
          from advisor.messages m
          join advisor.users u on u.id = m.user_id
          left join advisor.doc_snapshots ps on ps.id = m.prompt_snapshot_id
          left join advisor.doc_snapshots gs on gs.id = m.grounding_snapshot_id
         where (%s::text is null or m.status = %s::text)
           and (%s::text is null or lower(u.email) = lower(%s::text))
         order by m.created_at desc
         limit %s
        """,
        (status, status, user_email, user_email, limit),
    )


async def admin_usage(days: int) -> list[dict]:
    return await fetch_all(
        """
        select u.id as user_id, u.email, u.display_name,
               uc.usage_date,
               coalesce(uc.messages_used, 0) as messages_used,
               coalesce(uc.tokens_used, 0)   as tokens_used,
               coalesce(uc.est_spend_usd, 0) as est_spend_usd,
               coalesce(u.daily_message_cap, 0) as daily_message_cap,
               coalesce(u.daily_token_cap, 0)   as daily_token_cap
          from advisor.users u
          left join advisor.usage_counters uc
                 on uc.user_id = u.id
                and uc.usage_date > (current_date - %s::int)
         order by uc.usage_date desc nulls last, u.email
        """,
        (days,),
    )


async def admin_conversations(limit: int) -> list[dict]:
    return await fetch_all(
        """
        select c.id, u.email as user_email, c.title, c.message_count, c.total_tokens,
               c.total_est_cost_usd, c.last_message_at, c.created_at
          from advisor.conversations c
          join advisor.users u on u.id = c.user_id
         order by coalesce(c.last_message_at, c.created_at) desc
         limit %s
        """,
        (limit,),
    )


async def admin_events(limit: int, event_type: str | None) -> list[dict]:
    return await fetch_all(
        """
        select e.id, e.event_type, e.severity, u.email as user_email, e.payload, e.created_at
          from advisor.events e
          left join advisor.users u on u.id = e.user_id
         where (%s::text is null or e.event_type = %s::text)
         order by e.id desc
         limit %s
        """,
        (event_type, event_type, limit),
    )


async def admin_totals() -> dict[str, Any]:
    row = await fetch_one(
        """
        select
          (select count(*) from advisor.users)                                   as users,
          (select count(*) from advisor.conversations)                           as conversations,
          (select count(*) from advisor.messages)                                as messages,
          (select coalesce(sum(tokens), 0) from advisor.messages)                as tokens,
          (select coalesce(sum(est_cost_usd), 0) from advisor.messages)          as est_cost_usd,
          (select count(*) from advisor.messages where status like 'blocked%%')   as blocked,
          (select count(*) from advisor.messages
            where status in ('provider_error', 'doc_error'))                     as errored,
          (select coalesce(avg(latency_ms), 0) from advisor.messages
            where role = 'assistant' and status = 'ok')                          as avg_latency_ms
        """
    )
    return row or {}


async def admin_status_breakdown() -> dict[str, int]:
    rows = await fetch_all(
        "select status, count(*) as n from advisor.messages group by status order by n desc"
    )
    return {r["status"]: r["n"] for r in rows}


async def admin_event_breakdown(hours: int = 24) -> dict[str, int]:
    rows = await fetch_all(
        """
        select event_type, count(*) as n from advisor.events
         where created_at > now() - make_interval(hours => %s)
         group by event_type order by n desc
        """,
        (hours,),
    )
    return {r["event_type"]: r["n"] for r in rows}


async def latest_doc_snapshots(advisor_id: str) -> list[dict]:
    return await fetch_all(
        """
        select distinct on (doc_kind)
               doc_kind, source, revision_hash, char_count, fetched_at
          from advisor.doc_snapshots
         where advisor_id = %s
         order by doc_kind, fetched_at desc
        """,
        (advisor_id,),
    )
