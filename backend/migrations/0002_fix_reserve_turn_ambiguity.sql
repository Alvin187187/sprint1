-- Fix: `reserve_turn` failed at runtime with
--   42702: column reference "messages_used" is ambiguous
--
-- `RETURNS TABLE (... messages_used integer ...)` declares those names as
-- PL/pgSQL variables, so the bare `messages_used + 1` on the right-hand side of
-- the UPDATE could mean either the OUT parameter or the column. Postgres only
-- raises this when the statement actually executes, so the function created
-- cleanly and then broke on first use.
--
-- Qualifying every column reference against an alias resolves it. The OUT
-- parameter names are kept, since the application reads them by name.

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
    -- Serialize every guardrail decision for this user, so concurrent sends
    -- cannot both read the same pre-call total and both pass the cap check.
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

    -- FR-05: daily caps. 0 or negative means unlimited.
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

    update advisor.usage_counters uc
       set messages_used   = uc.messages_used + 1,
           tokens_reserved = uc.tokens_reserved + p_est_tokens,
           updated_at      = now()
     where uc.user_id = p_user_id and uc.usage_date = p_usage_date;

    insert into advisor.events (event_type, user_id, payload)
    values ('message_sent', p_user_id,
            jsonb_build_object('est_tokens', p_est_tokens, 'usage_date', p_usage_date));

    return query select true, null::text, v_messages + 1, v_tokens, v_spend, 0;
end;
$$;

-- Same hazard does not apply to these two (SQL functions, no OUT parameters),
-- but alias them anyway so the pattern is consistent and a future edit to add a
-- return value cannot reintroduce the bug.
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
    update advisor.usage_counters uc
       set tokens_reserved = greatest(0, uc.tokens_reserved - p_reserved),
           tokens_used     = uc.tokens_used + p_actual_tokens,
           est_spend_usd   = uc.est_spend_usd + p_cost_usd,
           updated_at      = now()
     where uc.user_id = p_user_id and uc.usage_date = p_usage_date;
$$;

create or replace function advisor.release_turn(
    p_user_id       uuid,
    p_usage_date    date,
    p_reserved      integer,
    p_refund_message boolean
)
returns void
language sql
as $$
    update advisor.usage_counters uc
       set tokens_reserved = greatest(0, uc.tokens_reserved - p_reserved),
           messages_used   = case when p_refund_message
                                  then greatest(0, uc.messages_used - 1)
                                  else uc.messages_used end,
           updated_at      = now()
     where uc.user_id = p_user_id and uc.usage_date = p_usage_date;
$$;
