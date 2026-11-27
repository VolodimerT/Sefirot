BEGIN;
-- Apply while the research window is inactive and the worker queue is empty.
SET LOCAL lock_timeout = '5s';
DO $rollback$
DECLARE budget sefirot_budget_private.sports_budget%ROWTYPE;
BEGIN
  IF current_user <> 'postgres' THEN
    RAISE EXCEPTION 'RESEARCH_BUDGET_OWNER_REQUIRED' USING ERRCODE = '42501';
  END IF;
  SELECT * INTO budget FROM sefirot_budget_private.sports_budget WHERE singleton FOR UPDATE;
  IF NOT FOUND OR budget.in_flight IS NOT NULL
     OR (budget.enabled AND budget.valid_until > clock_timestamp())
     OR EXISTS (SELECT 1 FROM sefirot.chat_bridge_jobs WHERE status IN ('PENDING','QUEUED','RUNNING')) THEN
    RAISE EXCEPTION 'RESEARCH_BUDGET_WINDOW_NOT_IDLE';
  END IF;
  IF to_regprocedure('sefirot_budget_private.arm_research_budget(integer,integer,integer)') IS NULL
     OR position('NULL::integer' in pg_get_functiondef(
        'sefirot_budget_private.arm_research_budget(integer,integer)'::regprocedure))=0 THEN
    RAISE EXCEPTION 'RESEARCH_BUDGET_WINDOW_ROLLBACK_DRIFT';
  END IF;
END
$rollback$;

CREATE OR REPLACE FUNCTION sefirot_budget_private.arm_research_budget(p_max_requests integer DEFAULT 5, p_minutes integer DEFAULT 12)
 RETURNS jsonb
 LANGUAGE plpgsql
 SET search_path TO ''
AS $function$
DECLARE
  b sefirot_budget_private.sports_budget%ROWTYPE;
  t timestamptz;
  calls_today integer;
  approved_calls integer;
  protected_reserve integer;
BEGIN
  IF current_user <> 'postgres' THEN
    RAISE EXCEPTION 'research budget administrator required' USING ERRCODE = '42501';
  END IF;
  IF p_max_requests IS NULL OR p_max_requests NOT BETWEEN 1 AND 7500
     OR p_minutes IS NULL OR p_minutes NOT BETWEEN 1 AND 360 THEN
    RAISE EXCEPTION 'research window outside approved bounds' USING ERRCODE = '22023';
  END IF;

  SELECT * INTO b FROM sefirot_budget_private.sports_budget
    WHERE singleton = true FOR UPDATE;
  t := clock_timestamp();
  IF NOT FOUND THEN RAISE EXCEPTION 'research budget missing'; END IF;
  IF b.in_flight IS NOT NULL THEN
    RAISE EXCEPTION 'cannot re-arm an in-flight provider request';
  END IF;
  IF b.enabled AND b.valid_until IS NOT NULL AND t < b.valid_until THEN
    RAISE EXCEPTION 'another research window is already active';
  END IF;

  SELECT count(*)::integer INTO calls_today
    FROM sefirot_budget_private.sports_attempt
   WHERE started_at >= ((t AT TIME ZONE 'UTC')::date AT TIME ZONE 'UTC')
     AND started_at < (((t AT TIME ZONE 'UTC')::date + 1) AT TIME ZONE 'UTC');

  -- Global hard daily allowance, even after many short re-arming windows.
  approved_calls := LEAST(p_max_requests,
                          GREATEST(0, 7500 - calls_today),
                          60 * p_minutes);
  IF approved_calls < 1 THEN
    RAISE EXCEPTION 'research operator daily allowance exhausted';
  END IF;
  protected_reserve := 0;

  UPDATE sefirot_budget_private.sports_budget
     SET enabled = true,
         utc_day = (t AT TIME ZONE 'UTC')::date,
         valid_until = LEAST(t + p_minutes * INTERVAL '1 minute', date_trunc('day',t)+ INTERVAL '1 day'),
         reserve_day = protected_reserve,
         remaining_day = protected_reserve + approved_calls,
         minute_limit = 60,
         minute_ready_at = t,
         reason = 'READY'
   WHERE singleton = true;

  RETURN jsonb_build_object(
    'enabled', true,
    'available_calls_cap', approved_calls,
    'daily_calls_used', calls_today,
    'daily_call_cap', 7500,
    'reserve_day', protected_reserve,
    'valid_until', LEAST(t + p_minutes * INTERVAL '1 minute', date_trunc('day',t)+ INTERVAL '1 day'),
    'rate_limit_per_minute', 60,
    'money_authorized', false
  );
END;
$function$;

COMMENT ON FUNCTION sefirot_budget_private.arm_research_budget(integer,integer) IS
  'Owner-only opt-in API-Football Pro 7500/UTC-day HARD global limit, bounded <=360-minute window, <=60/min below provider 300/min; no bets';
DROP FUNCTION sefirot_budget_private.arm_research_budget(integer,integer,integer);
COMMIT;
