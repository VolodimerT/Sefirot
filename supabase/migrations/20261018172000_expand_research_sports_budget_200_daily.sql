-- SEFIROT research API-Football budget: approved 200 calls/UTC day, 5/min max,
-- 12-minute maximum administrative window, 100 provider calls reserved.
-- Monetary decisions/autobets remain disabled. Never clears existing attempts.
BEGIN;
DO $preflight$
DECLARE
  b sefirot_budget_private.sports_budget%ROWTYPE;
  f text;
BEGIN
  IF current_user <> 'postgres' THEN
    RAISE EXCEPTION 'BUDGET_ADMIN_REQUIRED';
  END IF;
  SELECT * INTO b FROM sefirot_budget_private.sports_budget
    WHERE singleton = true FOR UPDATE;
  IF NOT FOUND OR b.enabled OR b.in_flight IS NOT NULL THEN
    RAISE EXCEPTION 'BUDGET_MUST_BE_PAUSED_AND_IDLE';
  END IF;
  SELECT pg_get_functiondef('sefirot_budget_private.arm_research_budget(integer,integer)'::regprocedure) INTO f;
  IF position('p_max_requests NOT BETWEEN 1 AND 5' IN f) = 0 THEN
    RAISE EXCEPTION 'OPERATOR_FUNCTION_DRIFT';
  END IF;
END;
$preflight$;

CREATE OR REPLACE FUNCTION sefirot_budget_private.arm_research_budget(
    p_max_requests integer DEFAULT 5, p_minutes integer DEFAULT 12
) RETURNS jsonb
LANGUAGE plpgsql
SET search_path TO ''
AS $func$
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
  IF p_max_requests IS NULL OR p_max_requests NOT BETWEEN 1 AND 200
     OR p_minutes IS NULL OR p_minutes NOT BETWEEN 1 AND 12 THEN
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
                          GREATEST(0, 200 - calls_today),
                          5 * p_minutes);
  IF approved_calls < 1 THEN
    RAISE EXCEPTION 'research operator daily allowance exhausted';
  END IF;
  protected_reserve := GREATEST(b.reserve_day, 100);

  UPDATE sefirot_budget_private.sports_budget
     SET enabled = true,
         utc_day = (t AT TIME ZONE 'UTC')::date,
         valid_until = t + p_minutes * INTERVAL '1 minute',
         reserve_day = protected_reserve,
         remaining_day = protected_reserve + approved_calls,
         minute_limit = 5,
         minute_ready_at = t,
         reason = 'READY'
   WHERE singleton = true;

  RETURN jsonb_build_object(
    'enabled', true,
    'available_calls_cap', approved_calls,
    'daily_calls_used', calls_today,
    'daily_call_cap', 200,
    'reserve_day', protected_reserve,
    'valid_until', t + p_minutes * INTERVAL '1 minute',
    'rate_limit_per_minute', 5,
    'money_authorized', false
  );
END;
$func$;

-- Defense in depth: a manual row edit or unexpected re-arm can NEVER push
-- the common reserve RPC past 200 attempts in one UTC day.
CREATE OR REPLACE FUNCTION public.sefirot_sports_budget_reserve()
RETURNS jsonb
LANGUAGE plpgsql
SET search_path TO ''
AS $func$
DECLARE
  b sefirot_budget_private.sports_budget%ROWTYPE;
  t timestamptz;
  p uuid;
  count_minute integer;
  count_day integer;
BEGIN
  SELECT * INTO b FROM sefirot_budget_private.sports_budget
    WHERE singleton FOR UPDATE;
  t := clock_timestamp();
  IF NOT FOUND OR NOT b.enabled THEN
    RETURN jsonb_build_object('allowed', false, 'reason', 'PAUSED');
  END IF;
  IF b.in_flight IS NOT NULL THEN
    IF t >= b.reserved_at + INTERVAL '30 seconds' THEN
      UPDATE sefirot_budget_private.sports_budget
        SET enabled=false, reason='UNFINISHED_ATTEMPT' WHERE singleton;
      RETURN jsonb_build_object('allowed', false, 'reason', 'UNFINISHED_ATTEMPT');
    END IF;
    RETURN jsonb_build_object('allowed', false, 'reason', 'BUSY');
  END IF;
  IF b.utc_day IS DISTINCT FROM (t AT TIME ZONE 'UTC')::date
     OR b.valid_until IS NULL OR t >= b.valid_until
     OR b.valid_until > t + INTERVAL '15 minutes' THEN
    RETURN jsonb_build_object('allowed', false, 'reason', 'STALE_BUDGET');
  END IF;
  SELECT count(*) INTO count_day FROM sefirot_budget_private.sports_attempt
   WHERE started_at >= ((t AT TIME ZONE 'UTC')::date AT TIME ZONE 'UTC')
     AND started_at < (((t AT TIME ZONE 'UTC')::date + 1) AT TIME ZONE 'UTC');
  IF count_day >= 200 OR b.remaining_day <= b.reserve_day THEN
    RETURN jsonb_build_object('allowed', false, 'reason', 'DAILY_LIMIT');
  END IF;
  SELECT count(*) INTO count_minute FROM sefirot_budget_private.sports_attempt
    WHERE started_at > t - INTERVAL '60 seconds';
  IF t < b.minute_ready_at OR count_minute >= b.minute_limit
     OR (b.last_started_at IS NOT NULL
         AND t < b.last_started_at + INTERVAL '60 seconds' / b.minute_limit) THEN
    RETURN jsonb_build_object('allowed', false, 'reason', 'MINUTE_LIMIT');
  END IF;
  p := gen_random_uuid();
  INSERT INTO sefirot_budget_private.sports_attempt(permit,started_at)
    VALUES (p,t);
  UPDATE sefirot_budget_private.sports_budget
    SET remaining_day=remaining_day-1,
        in_flight=p,reserved_at=t,last_started_at=t,reason='RESERVED'
    WHERE singleton;
  RETURN jsonb_build_object('allowed',true,'permit',p);
END;
$func$;
COMMENT ON FUNCTION sefirot_budget_private.arm_research_budget(integer,integer)
  IS 'Admin-only, short-lived shared sports API research allowance; 200/day UTC ceiling, 5/min cap, reserve>=100, no monetary permission';
COMMIT;