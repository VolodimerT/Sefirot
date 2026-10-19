-- Align the opt-in durable source dispatch fence with the separately
-- approved 200/UTC-day shared provider budget. This DOES NOT arm the
-- budget, change reserved allowance, or grant runtime RPC permissions.
BEGIN;
SET LOCAL lock_timeout='3s';
DO $patch$
DECLARE original text;
        token text := '(started_at at time zone ''UTC'')::date=today)>=5';
        found_count integer;
BEGIN
 IF current_user <> 'postgres'
    OR EXISTS(SELECT 1 FROM sefirot.chat_bridge_jobs WHERE status IN ('PENDING','RUNNING'))
    OR NOT EXISTS(SELECT 1 FROM sefirot_budget_private.sports_budget
       WHERE singleton AND NOT enabled AND in_flight IS NULL)
    OR to_regprocedure('public.sefirot_source_begin(uuid,integer,text,jsonb)') IS NULL
 THEN RAISE EXCEPTION 'SOURCE_DISPATCH_BUDGET_PATCH_BASELINE_REQUIRED'; END IF;
 SELECT pg_get_functiondef('public.sefirot_source_begin(uuid,integer,text,jsonb)'::regprocedure)
   INTO original;
 found_count := (length(original)-length(replace(original,token,''))) / length(token);
 IF found_count <> 2 OR position('SOURCE_DISPATCH_DAILY_CAP' in original)=0
   OR position('SOURCE_DISPATCH_LEASE_REQUIRED' in original)=0
 THEN RAISE EXCEPTION 'SOURCE_DISPATCH_FUNCTION_DRIFT';END IF;
 EXECUTE replace(original,token,replace(token,'>=5','>=200'));
END;
$patch$;
COMMENT ON FUNCTION public.sefirot_source_begin(uuid,integer,text,jsonb)
 IS 'Archive opt-in: exactly one leased source attempt; <=200 total UTC-day dispatches and shared budget sports_attempts, without resetting quota.';
COMMIT;