-- Security hardening: pin `search_path` on every function.
--
-- Flagged by the Supabase database linter (`function_search_path_mutable`).
-- A function with a role-mutable search_path can be made to resolve an
-- unqualified name against a schema the caller controls. Every table reference
-- in these functions is already schema-qualified, so pinning the path to empty
-- is a no-op behaviourally — pg_catalog remains implicitly searched, which is
-- where the built-ins used here (now, make_interval, jsonb_build_object,
-- hashtextextended, pg_advisory_xact_lock) live.
--
-- The remaining `rls_enabled_no_policy` notice is intentional and documented in
-- docs/ARCHITECTURE.md §4: RLS is on with zero policies so that a leaked
-- anon/publishable key reads nothing. The backend connects with the service
-- role, which bypasses RLS.

alter function advisor.touch_conversation() set search_path = '';
alter function advisor.reserve_turn(uuid, date, integer, integer, integer, numeric, integer, integer)
    set search_path = '';
alter function advisor.settle_turn(uuid, date, integer, integer, numeric) set search_path = '';
alter function advisor.release_turn(uuid, date, integer, boolean) set search_path = '';
