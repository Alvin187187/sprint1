-- Verification for the guardrail critical section (FR-05, FR-06).
--
-- The Python suite cannot cover these: the enforcement logic lives in Postgres.
-- Run against the target database, inspect the `ok` column, then it cleans up
-- after itself.
--
--   psql "$DATABASE_URL" -f tests/sql/verify_guardrails.sql
--
-- Each row asserts one behaviour. Any `false` in `ok` is a real defect.

create or replace function advisor.verify_guardrails()
returns table (step text, ok boolean, detail text)
language plpgsql
as $fn$
declare
    u_msg   uuid;
    u_tok   uuid;
    u_rate  uuid;
    today   date := current_date;
    r       record;
    counter integer;
begin
    -- isolated probe accounts
    delete from advisor.events where user_id in (
        select id from advisor.users where email like '%@guardrail-probe.local'
    );
    delete from advisor.users where email like '%@guardrail-probe.local';

    insert into advisor.users (email, display_name, password_hash)
         values ('msg@guardrail-probe.local', 'probe', 'x') returning id into u_msg;
    insert into advisor.users (email, display_name, password_hash)
         values ('tok@guardrail-probe.local', 'probe', 'x') returning id into u_tok;
    insert into advisor.users (email, display_name, password_hash)
         values ('rate@guardrail-probe.local', 'probe', 'x') returning id into u_rate;

    -- ---------------------------------------------------------------
    -- Message cap: 3 allowed, 4th blocked. Rate limit disabled (0).
    -- ---------------------------------------------------------------
    counter := 0;
    for i in 1..3 loop
        select * into r from advisor.reserve_turn(u_msg, today, 100, 3, 0, 0, 0, 60);
        if r.allowed then counter := counter + 1; end if;
    end loop;
    return query select 'message_cap: first 3 allowed',
                        counter = 3,
                        format('%s of 3 allowed', counter);

    select * into r from advisor.reserve_turn(u_msg, today, 100, 3, 0, 0, 0, 60);
    return query select 'message_cap: 4th blocked',
                        (not r.allowed) and r.reason = 'message_cap',
                        format('allowed=%s reason=%s', r.allowed, r.reason);

    -- A blocked request must not consume allowance itself.
    select messages_used into counter from advisor.usage_counters
     where user_id = u_msg and usage_date = today;
    return query select 'message_cap: block does not increment counter',
                        counter = 3,
                        format('messages_used=%s (expected 3)', counter);

    -- ---------------------------------------------------------------
    -- Token cap via reservations: 2000-token turns against a 5000 cap.
    -- This is the race the PRD's check-then-call design cannot prevent —
    -- usage is still 0 here, so only the reservation can block the 3rd.
    -- ---------------------------------------------------------------
    select * into r from advisor.reserve_turn(u_tok, today, 2000, 0, 5000, 0, 0, 60);
    return query select 'token_cap: 1st reservation allowed', r.allowed, format('reason=%s', r.reason);

    select * into r from advisor.reserve_turn(u_tok, today, 2000, 0, 5000, 0, 0, 60);
    return query select 'token_cap: 2nd reservation allowed', r.allowed, format('reason=%s', r.reason);

    select * into r from advisor.reserve_turn(u_tok, today, 2000, 0, 5000, 0, 0, 60);
    return query select 'token_cap: 3rd blocked on reserved total alone',
                        (not r.allowed) and r.reason = 'token_cap',
                        format('allowed=%s reason=%s (tokens_used still 0)', r.allowed, r.reason);

    select tokens_reserved into counter from advisor.usage_counters
     where user_id = u_tok and usage_date = today;
    return query select 'token_cap: 4000 held in reservation',
                        counter = 4000,
                        format('tokens_reserved=%s (expected 4000)', counter);

    -- ---------------------------------------------------------------
    -- settle: reservation converts to real usage
    -- ---------------------------------------------------------------
    perform advisor.settle_turn(u_tok, today, 2000, 1500, 0.004);
    select tokens_reserved into counter from advisor.usage_counters
     where user_id = u_tok and usage_date = today;
    return query select 'settle: reservation released',
                        counter = 2000,
                        format('tokens_reserved=%s (expected 2000)', counter);

    select tokens_used into counter from advisor.usage_counters
     where user_id = u_tok and usage_date = today;
    return query select 'settle: actual tokens recorded',
                        counter = 1500,
                        format('tokens_used=%s (expected 1500)', counter);

    return query select 'settle: spend accumulated',
                        (select est_spend_usd = 0.004 from advisor.usage_counters
                          where user_id = u_tok and usage_date = today),
                        'est_spend_usd = 0.004';

    -- ---------------------------------------------------------------
    -- release with refund: a provider failure is not the learner's fault
    -- ---------------------------------------------------------------
    select messages_used into counter from advisor.usage_counters
     where user_id = u_tok and usage_date = today;
    perform advisor.release_turn(u_tok, today, 2000, true);
    return query select 'release: message allowance refunded',
                        (select messages_used = counter - 1 from advisor.usage_counters
                          where user_id = u_tok and usage_date = today),
                        format('messages_used went %s -> %s', counter, counter - 1);

    return query select 'release: reservation cleared',
                        (select tokens_reserved = 0 from advisor.usage_counters
                          where user_id = u_tok and usage_date = today),
                        'tokens_reserved = 0';

    -- ---------------------------------------------------------------
    -- Rate limit: 2 per 60s window
    -- ---------------------------------------------------------------
    select * into r from advisor.reserve_turn(u_rate, today, 100, 0, 0, 0, 2, 60);
    return query select 'rate_limit: 1st allowed', r.allowed, format('reason=%s', r.reason);

    select * into r from advisor.reserve_turn(u_rate, today, 100, 0, 0, 0, 2, 60);
    return query select 'rate_limit: 2nd allowed', r.allowed, format('reason=%s', r.reason);

    select * into r from advisor.reserve_turn(u_rate, today, 100, 0, 0, 0, 2, 60);
    return query select 'rate_limit: 3rd blocked',
                        (not r.allowed) and r.reason = 'rate_limited',
                        format('allowed=%s reason=%s', r.allowed, r.reason);

    return query select 'rate_limit: retry_after is actionable',
                        r.retry_after_seconds between 1 and 60,
                        format('retry_after_seconds=%s', r.retry_after_seconds);

    -- A wide window with a high limit must not block.
    select * into r from advisor.reserve_turn(u_rate, today, 100, 0, 0, 0, 99, 60);
    return query select 'rate_limit: high limit does not block', r.allowed, format('reason=%s', r.reason);

    -- ---------------------------------------------------------------
    -- Unlimited semantics: 0 means no cap
    -- ---------------------------------------------------------------
    select * into r from advisor.reserve_turn(u_msg, today, 999999, 0, 0, 0, 0, 60);
    return query select 'zero caps mean unlimited',
                        r.allowed,
                        format('allowed=%s with 999999 est tokens and all caps 0', r.allowed);

    -- ---------------------------------------------------------------
    -- Telemetry: exactly one message_sent per *allowed* reserve (PRD §8).
    -- A blocked reserve must not log one — it is not a sent message, and
    -- counting it would make the rate-limit window self-reinforcing: a
    -- rate-limited user would stay rate-limited by their own rejections.
    --
    -- Allowed reserves above: u_msg 3 + 1 unlimited, u_tok 2, u_rate 2 + 1 = 9.
    -- ---------------------------------------------------------------
    select count(*) into counter from advisor.events e
     where e.user_id in (u_msg, u_tok, u_rate) and e.event_type = 'message_sent';
    return query select 'telemetry: one message_sent per allowed reserve, none per block',
                        counter = 9,
                        format('%s message_sent events (expected 9 allowed, 3 blocks excluded)',
                               counter);

    -- cleanup
    delete from advisor.events where user_id in (u_msg, u_tok, u_rate);
    delete from advisor.users where id in (u_msg, u_tok, u_rate);
end;
$fn$;

select * from advisor.verify_guardrails();

drop function advisor.verify_guardrails();
