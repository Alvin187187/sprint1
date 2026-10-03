-- Advisor Console — initial schema
-- Everything lives in the `advisor` schema so it never collides with other apps.

create schema if not exists advisor;

-- ---------------------------------------------------------------------------
-- Identity (FR-04 prerequisite; deliberately minimal per PRD non-goals)
-- ---------------------------------------------------------------------------

create table advisor.users (
    id              uuid primary key default gen_random_uuid(),
    email           text        not null,
    display_name    text        not null,
    password_hash   text        not null,
    role            text        not null default 'user' check (role in ('user', 'admin')),
    -- null = fall back to the global default cap from env
    daily_message_cap   integer,
    daily_token_cap     integer,
    daily_spend_cap_usd numeric(12, 6),
    created_at      timestamptz not null default now(),
    disabled_at     timestamptz
);

create unique index users_email_key on advisor.users (lower(email));

create table advisor.sessions (
    id          uuid primary key default gen_random_uuid(),
    user_id     uuid        not null references advisor.users (id) on delete cascade,
    token_hash  text        not null unique,
    created_at  timestamptz not null default now(),
    expires_at  timestamptz not null,
    revoked_at  timestamptz,
    user_agent  text
);

create index sessions_user_idx on advisor.sessions (user_id, expires_at desc);

-- ---------------------------------------------------------------------------
-- Advisor registry. One row for this phase, but keyed so the cache and the
-- doc control plane never assume a singleton.
-- ---------------------------------------------------------------------------

create table advisor.advisors (
    id                  text primary key,
    name                text        not null,
    prompt_doc_ref      text        not null,
    grounding_doc_ref   text,
    model               text        not null,
    temperature         numeric(3, 2) not null default 0.4,
    max_output_tokens   integer     not null default 900,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- Document control plane.
--
-- The PRD only asks for an in-process TTL cache with a last-good fallback, but
-- an in-process cache dies with the worker. Persisting every revision here
-- gives us (a) a real last-good store that survives restarts and (b) a stable
-- revision id that each turn can point at, so eval results stay attributable
-- to the exact prompt text that produced them.
-- ---------------------------------------------------------------------------

create table advisor.doc_snapshots (
    id              bigserial primary key,
    advisor_id      text        not null references advisor.advisors (id) on delete cascade,
    doc_kind        text        not null check (doc_kind in ('prompt', 'grounding')),
    source          text        not null check (source in ('google_docs', 'local', 'inline')),
    revision_hash   text        not null,
    body            text        not null,
    char_count      integer     not null,
    first_seen_at   timestamptz not null default now(),
    fetched_at      timestamptz not null default now()
);

create unique index doc_snapshots_revision_key
    on advisor.doc_snapshots (advisor_id, doc_kind, revision_hash);

-- "last good" lookup: newest fetched_at per (advisor, kind)
create index doc_snapshots_latest_idx
    on advisor.doc_snapshots (advisor_id, doc_kind, fetched_at desc);

-- ---------------------------------------------------------------------------
-- Conversations & messages (FR-01, FR-04, FR-07)
-- ---------------------------------------------------------------------------

create table advisor.conversations (
    id                  uuid primary key default gen_random_uuid(),
    user_id             uuid        not null references advisor.users (id) on delete cascade,
    advisor_id          text        not null references advisor.advisors (id),
    title               text        not null default 'New conversation',
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    last_message_at     timestamptz,
    archived_at         timestamptz,
    message_count       integer     not null default 0,
    total_tokens        integer     not null default 0,
    total_est_cost_usd  numeric(12, 6) not null default 0
);

create index conversations_user_idx
    on advisor.conversations (user_id, coalesce(last_message_at, created_at) desc);

create table advisor.messages (
    id                      uuid primary key default gen_random_uuid(),
    conversation_id         uuid        not null references advisor.conversations (id) on delete cascade,
    user_id                 uuid        not null references advisor.users (id) on delete cascade,
    turn_id                 uuid        not null,
    role                    text        not null check (role in ('user', 'assistant')),
    content                 text        not null,
    status                  text        not null default 'ok' check (status in (
                                'ok', 'blocked_cap', 'blocked_rate', 'provider_error',
                                'doc_error', 'truncated', 'redacted'
                            )),
    prompt_tokens           integer     not null default 0,
    completion_tokens       integer     not null default 0,
    tokens                  integer     generated always as (prompt_tokens + completion_tokens) stored,
    est_cost_usd            numeric(12, 6) not null default 0,
    model                   text,
    latency_ms              integer,
    -- which exact prompt/grounding revision produced this turn
    prompt_snapshot_id      bigint      references advisor.doc_snapshots (id),
    grounding_snapshot_id   bigint      references advisor.doc_snapshots (id),
    grounding_chunk_ids     text[]      not null default '{}',
    -- idempotency: a retried or double-clicked send must not double-charge
    client_request_id       text,
    created_at              timestamptz not null default now()
);

create index messages_conversation_idx on advisor.messages (conversation_id, created_at);
create index messages_user_day_idx on advisor.messages (user_id, created_at desc);
create unique index messages_idempotency_key
    on advisor.messages (conversation_id, client_request_id)
    where client_request_id is not null;

-- Keep conversation rollups current so the admin view never has to aggregate
-- the whole messages table.
create or replace function advisor.touch_conversation()
returns trigger
language plpgsql
as $$
begin
    update advisor.conversations c
       set message_count      = c.message_count + 1,
           total_tokens       = c.total_tokens + new.tokens,
           total_est_cost_usd = c.total_est_cost_usd + new.est_cost_usd,
           last_message_at    = greatest(coalesce(c.last_message_at, new.created_at), new.created_at),
           updated_at         = now()
     where c.id = new.conversation_id;
    return new;
end;
$$;

create trigger messages_touch_conversation
    after insert on advisor.messages
    for each row execute function advisor.touch_conversation();

-- ---------------------------------------------------------------------------
-- Usage counters (FR-05). `usage_date` is the calendar day in APP_TIMEZONE,
-- computed by the application — not a UTC date — so a Manila-based cohort
-- does not get its caps reset at 8am local time.
--
-- `tokens_reserved` holds in-flight estimates. Without it, two concurrent
-- requests both read the pre-call total, both pass the cap check, and the cap
-- is overshot by a full turn each time.
-- ---------------------------------------------------------------------------

create table advisor.usage_counters (
    user_id         uuid        not null references advisor.users (id) on delete cascade,
    usage_date      date        not null,
    messages_used   integer     not null default 0,
    tokens_used     integer     not null default 0,
    tokens_reserved integer     not null default 0,
    est_spend_usd   numeric(12, 6) not null default 0,
    updated_at      timestamptz not null default now(),
    primary key (user_id, usage_date)
);

-- ---------------------------------------------------------------------------
-- Telemetry (PRD §8). Append-only, one shape for every event type.
-- ---------------------------------------------------------------------------

create table advisor.events (
    id              bigserial primary key,
    event_type      text        not null,
    severity        text        not null default 'info' check (severity in ('info', 'warn', 'error')),
    user_id         uuid        references advisor.users (id) on delete set null,
    conversation_id uuid,
    message_id      uuid,
    advisor_id      text,
    payload         jsonb       not null default '{}'::jsonb,
    created_at      timestamptz not null default now()
);

create index events_type_time_idx on advisor.events (event_type, created_at desc);
create index events_user_time_idx on advisor.events (user_id, created_at desc);
-- supports the sliding-window rate limit lookup
create index events_rate_window_idx
    on advisor.events (user_id, created_at desc)
    where event_type = 'message_sent';

-- ---------------------------------------------------------------------------
-- Guardrail critical section.
--
-- Rate limit + all three caps + the reservation happen inside one transaction
-- behind a per-user advisory lock. This is the difference between "usually
-- enforced" and the PRD's 100% hard-block target under concurrent sends.
-- ---------------------------------------------------------------------------

create or replace function advisor.reserve_turn(
    p_user_id           uuid,
    p_usage_date        date,
    p_est_tokens        integer,
    p_msg_cap           integer,
    p_token_cap         integer,
    p_spend_cap         numeric,
    p_rate_limit        integer,
    p_window_seconds    integer
)
returns table (
    allowed              boolean,
    reason               text,
    messages_used        integer,
    tokens_used          integer,
    est_spend_usd        numeric,
    retry_after_seconds  integer
)
language plpgsql
as $$
declare
    v_messages      integer;
    v_tokens        integer;
    v_reserved      integer;
    v_spend         numeric;
    v_recent        integer;
    v_oldest        timestamptz;
begin
    -- serialize every guardrail decision for this user
    perform pg_advisory_xact_lock(hashtextextended(p_user_id::text, 0));

    insert into advisor.usage_counters (user_id, usage_date)
    values (p_user_id, p_usage_date)
    on conflict (user_id, usage_date) do nothing;

    select uc.messages_used, uc.tokens_used, uc.tokens_reserved, uc.est_spend_usd
      into v_messages, v_tokens, v_reserved, v_spend
      from advisor.usage_counters uc
     where uc.user_id = p_user_id and uc.usage_date = p_usage_date
       for update;

    -- FR-06: per-user sliding window
    if p_rate_limit > 0 then
        select count(*), min(e.created_at)
          into v_recent, v_oldest
          from advisor.events e
         where e.user_id = p_user_id
           and e.event_type = 'message_sent'
           and e.created_at > now() - make_interval(secs => p_window_seconds);

        if v_recent >= p_rate_limit then
            return query select
                false,
                'rate_limited'::text,
                v_messages,
                v_tokens,
                v_spend,
                greatest(1, ceil(extract(epoch from (
                    v_oldest + make_interval(secs => p_window_seconds) - now()
                )))::integer);
            return;
        end if;
    end if;

    -- FR-05: daily caps
    if p_msg_cap > 0 and v_messages >= p_msg_cap then
        return query select false, 'message_cap'::text, v_messages, v_tokens, v_spend, 0;
        return;
    end if;

    if p_token_cap > 0 and (v_tokens + v_reserved + p_est_tokens) > p_token_cap then
        return query select false, 'token_cap'::text, v_messages, v_tokens, v_spend, 0;
        return;
    end if;

    if p_spend_cap > 0 and v_spend >= p_spend_cap then
        return query select false, 'spend_cap'::text, v_messages, v_tokens, v_spend, 0;
        return;
    end if;

    update advisor.usage_counters
       set messages_used   = messages_used + 1,
           tokens_reserved = tokens_reserved + p_est_tokens,
           updated_at      = now()
     where user_id = p_user_id and usage_date = p_usage_date;

    insert into advisor.events (event_type, user_id, payload)
    values ('message_sent', p_user_id,
            jsonb_build_object('est_tokens', p_est_tokens, 'usage_date', p_usage_date));

    return query select true, null::text, v_messages + 1, v_tokens, v_spend, 0;
end;
$$;

-- Convert a reservation into real usage once the provider reports actuals.
create or replace function advisor.settle_turn(
    p_user_id       uuid,
    p_usage_date    date,
    p_reserved      integer,
    p_actual_tokens integer,
    p_cost_usd      numeric
)
returns void
language sql
as $$
    update advisor.usage_counters
       set tokens_reserved = greatest(0, tokens_reserved - p_reserved),
           tokens_used     = tokens_used + p_actual_tokens,
           est_spend_usd   = est_spend_usd + p_cost_usd,
           updated_at      = now()
     where user_id = p_user_id and usage_date = p_usage_date;
$$;

-- Infrastructure failure: give the learner their message allowance back.
-- A provider timeout is our fault, not theirs.
create or replace function advisor.release_turn(
    p_user_id       uuid,
    p_usage_date    date,
    p_reserved      integer,
    p_refund_message boolean
)
returns void
language sql
as $$
    update advisor.usage_counters
       set tokens_reserved = greatest(0, tokens_reserved - p_reserved),
           messages_used   = case when p_refund_message
                                  then greatest(0, messages_used - 1)
                                  else messages_used end,
           updated_at      = now()
     where user_id = p_user_id and usage_date = p_usage_date;
$$;

-- ---------------------------------------------------------------------------
-- Admin read models (FR-08)
-- ---------------------------------------------------------------------------

create or replace view advisor.v_user_usage as
select u.id                              as user_id,
       u.email,
       u.display_name,
       u.role,
       uc.usage_date,
       uc.messages_used,
       uc.tokens_used,
       uc.est_spend_usd,
       coalesce(u.daily_message_cap, 0)  as daily_message_cap,
       coalesce(u.daily_token_cap, 0)    as daily_token_cap
  from advisor.users u
  left join advisor.usage_counters uc on uc.user_id = u.id;

-- ---------------------------------------------------------------------------
-- RLS: the FastAPI backend is the only client and connects with the service
-- role, which bypasses RLS. Enabling it with zero policies means a leaked
-- anon/publishable key still reads nothing.
-- ---------------------------------------------------------------------------

alter table advisor.users           enable row level security;
alter table advisor.sessions        enable row level security;
alter table advisor.advisors        enable row level security;
alter table advisor.doc_snapshots   enable row level security;
alter table advisor.conversations   enable row level security;
alter table advisor.messages        enable row level security;
alter table advisor.usage_counters  enable row level security;
alter table advisor.events          enable row level security;

-- ---------------------------------------------------------------------------
-- Seed the single advisor for this phase.
-- ---------------------------------------------------------------------------

insert into advisor.advisors (id, name, prompt_doc_ref, grounding_doc_ref, model, temperature, max_output_tokens)
values ('career-transition',
        'Career Transition Advisor',
        'content/prompt.md',
        'content/grounding.md',
        'openai/gpt-4o-mini',
        0.40,
        900)
on conflict (id) do nothing;
