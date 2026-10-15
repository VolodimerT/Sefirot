-- Operator-only, fail-closed research window for the existing API-Football shared quota.
-- This migration only defines a private function. It NEVER enables the budget on deployment.
-- Invoke it explicitly from Supabase SQL Editor as the postgres administrator:
--   SELECT sefirot_budget_private.arm_research_budget(5, 12);
-- Do not expose via a public Edge Function or PostgREST RPC.

CREATE OR REPLACE FUNCTION sefirot_budget_private.arm_research_budget(
    p_max_requests integer DEFAULT 5,
    p_minutes integer DEFAULT 12
) RETURNS jsonb
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = ''
AS $function$
DECLARE
    b sefirot_budget_private.sports_budget%rowtype;
    t timestamptz := clock_timestamp();
    calls_today integer;
    approved_calls integer;
BEGIN
    -- Extra defense beyond PostgreSQL function EXECUTE grants and private schema access.
    IF current_user <> 'postgres' THEN
        RAISE EXCEPTION 'research budget administrator required' USING ERRCODE = '42501';
    END IF;
    IF p_max_requests IS NULL OR p_max_requests NOT BETWEEN 1 AND 5
       OR p_minutes IS NULL OR p_minutes NOT BETWEEN 1 AND 12 THEN
        RAISE EXCEPTION 'research window outside approved bounds' USING ERRCODE = '22023';
    END IF;

    SELECT * INTO b
    FROM sefirot_budget_private.sports_budget
    WHERE singleton = true FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'research budget missing';
    END IF;
    IF b.in_flight IS NOT NULL THEN
        RAISE EXCEPTION 'cannot re-arm an in-flight provider request';
    END IF;
    IF b.enabled AND b.valid_until IS NOT NULL AND t < b.valid_until THEN
        RAISE EXCEPTION 'another research window is already active';
    END IF;

    -- Strict daily ceiling for this operator workflow; never reset the attempt history.
    SELECT count(*)::integer INTO calls_today
    FROM sefirot_budget_private.sports_attempt
    WHERE started_at >= ((t AT TIME ZONE 'UTC')::date AT TIME ZONE 'UTC')
      AND started_at < (((t AT TIME ZONE 'UTC')::date + 1) AT TIME ZONE 'UTC');

    approved_calls := LEAST(p_max_requests, GREATEST(0, 5 - calls_today));
    IF approved_calls < 1 THEN
        RAISE EXCEPTION 'research operator daily allowance exhausted';
    END IF;

    UPDATE sefirot_budget_private.sports_budget
    SET enabled = true,
        utc_day = (t AT TIME ZONE 'UTC')::date,
        valid_until = t + p_minutes * interval '1 minute',
        remaining_day = b.reserve_day + approved_calls,
        minute_limit = 1,
        minute_ready_at = t,
        reason = 'READY'
    WHERE singleton = true;

    -- The existing reserve/finish RPC remains authoritative. In particular,
    -- failed upstream authentication and unknown quota headers still stop the gate.
    RETURN jsonb_build_object(
        'enabled', true,
        'available_calls_cap', approved_calls,
        'reserve_day', b.reserve_day,
        'valid_until', t + p_minutes * interval '1 minute',
        'rate_limit_per_minute', 1,
        'money_authorized', false
    );
END;
$function$;

-- Restrict both registration and execution to the SQL Editor administrator.
REVOKE ALL ON FUNCTION sefirot_budget_private.arm_research_budget(integer, integer)
FROM PUBLIC, anon, authenticated, service_role;
