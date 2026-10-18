-- SEFIROT: provider-confirmed API-Football Pro daily ceiling = 7500/UTC day.
-- This changes research permissions, NOT spending, odds access, model fit,
-- bet execution, API credentials, provider tier, or historical counters.
-- Operator must still arm a bounded window; queue remains idempotent.
BEGIN;
SET LOCAL lock_timeout='5s';
SET LOCAL statement_timeout='30s';
DO $preflight$
DECLARE
 b sefirot_budget_private.sports_budget%ROWTYPE;
BEGIN
 IF current_user <> 'postgres' THEN
   RAISE EXCEPTION 'DAILY_PRO_QUOTA_OWNER_REQUIRED';
 END IF;
 SELECT * INTO b FROM sefirot_budget_private.sports_budget WHERE singleton FOR UPDATE;
 IF NOT FOUND OR b.enabled OR b.in_flight IS NOT NULL THEN
   RAISE EXCEPTION 'DAILY_PRO_QUOTA_PAUSED_AND_IDLE_REQUIRED';
 END IF;
 IF EXISTS (SELECT 1 FROM sefirot.chat_bridge_jobs WHERE status IN ('PENDING','RUNNING')) THEN
   RAISE EXCEPTION 'DAILY_PRO_QUOTA_QUEUE_NOT_QUIESCENT';
 END IF;
 IF NOT EXISTS(
  SELECT 1 FROM sefirot.chat_bridge_jobs j
  WHERE j.status='DONE'
   AND j.request->'queries' @> '[{"endpoint":"status","params":{}}]'::jsonb
   AND j.response::text LIKE '%"requests_limit_day": 7500%'
   AND j.completed_at >= clock_timestamp()-INTERVAL '72 hours'
 ) THEN
   RAISE EXCEPTION 'RECENT_PROVIDER_PRO_7500_LIMIT_NOT_ATTESTED';
 END IF;
END
$preflight$;

-- Previous artificial provider reserve 100 is removed; observed provider
-- response headers still stop calls at the provider's true remaining=0.
ALTER TABLE sefirot_budget_private.sports_budget
 DROP CONSTRAINT sports_budget_reserve_day_check;
ALTER TABLE sefirot_budget_private.sports_budget
 ADD CONSTRAINT sports_budget_reserve_day_check
 CHECK (reserve_day >= 0 AND reserve_day <= 7500);
UPDATE sefirot_budget_private.sports_budget
 SET reserve_day=0,remaining_day=0,reason='PRO_7500_POLICY_INSTALLED_PAUSED'
 WHERE singleton AND NOT enabled AND in_flight IS NULL;

DO $upgrade$
DECLARE
 src text;
 signature regprocedure;
 edits jsonb;
 edit jsonb;
 needle text;
 replacement text;
 occurrences integer;
BEGIN
 signature:='sefirot_budget_private.arm_research_budget(integer,integer)'::regprocedure;
 src:=pg_get_functiondef(signature);
 IF position('daily_call_cap' in src)=0 OR position('research budget administrator required' in src)=0
 OR position('5 * p_minutes' in src)=0 OR position('protected_reserve := GREATEST(b.reserve_day, 100)' in src)=0
 THEN RAISE EXCEPTION 'RESEARCH_OPERATOR_200_BASELINE_DRIFT';END IF;
 edits:=jsonb_build_array(
  jsonb_build_object('old','p_max_requests NOT BETWEEN 1 AND 200','new','p_max_requests NOT BETWEEN 1 AND 7500'),
  jsonb_build_object('old','p_minutes NOT BETWEEN 1 AND 12','new','p_minutes NOT BETWEEN 1 AND 360'),
  jsonb_build_object('old','200 - calls_today','new','7500 - calls_today'),
  jsonb_build_object('old','5 * p_minutes','new','60 * p_minutes'),
  jsonb_build_object('old','protected_reserve := GREATEST(b.reserve_day, 100);','new','protected_reserve := 0;'),
  jsonb_build_object('old','valid_until = t + p_minutes * INTERVAL ''1 minute'',','new',
     'valid_until = LEAST(t + p_minutes * INTERVAL ''1 minute'', date_trunc(''day'',t)+ INTERVAL ''1 day''),'),
  jsonb_build_object('old','''valid_until'', t + p_minutes * INTERVAL ''1 minute'',','new',
     '''valid_until'', LEAST(t + p_minutes * INTERVAL ''1 minute'', date_trunc(''day'',t)+ INTERVAL ''1 day''),'),
  jsonb_build_object('old','minute_limit = 5,','new','minute_limit = 60,'),
  jsonb_build_object('old','''daily_call_cap'', 200,','new','''daily_call_cap'', 7500,'),
  jsonb_build_object('old','''rate_limit_per_minute'', 5,','new','''rate_limit_per_minute'', 60,')
 );
 FOR edit IN SELECT value FROM jsonb_array_elements(edits) LOOP
   needle:=edit->>'old';replacement:=edit->>'new';
   occurrences := (length(src)-length(replace(src,needle,'')))/length(needle);
   IF occurrences<>1 THEN RAISE EXCEPTION 'RESEARCH_OPERATOR_PATCH_DRIFT: % (%)',needle,occurrences;END IF;
   src:=replace(src,needle,replacement);
 END LOOP;
 EXECUTE src;

 signature:='public.sefirot_sports_budget_reserve()'::regprocedure;
 src:=pg_get_functiondef(signature);
 IF position('UNFINISHED_ATTEMPT' in src)=0 OR position('MINUTE_LIMIT' in src)=0 THEN
   RAISE EXCEPTION 'RESEARCH_RESERVE_DRIFT';
 END IF;
 edits:=jsonb_build_array(
  jsonb_build_object('old','count_day >= 200','new','count_day >= 7500'),
  jsonb_build_object('old','b.valid_until > t + INTERVAL ''15 minutes''','new','b.valid_until > t + INTERVAL ''365 minutes''')
 );
 FOR edit IN SELECT value FROM jsonb_array_elements(edits) LOOP
   needle:=edit->>'old';replacement:=edit->>'new';
   occurrences := (length(src)-length(replace(src,needle,'')))/length(needle);
   IF occurrences<>1 THEN RAISE EXCEPTION 'RESEARCH_RESERVE_PATCH_DRIFT: % (%)',needle,occurrences;END IF;
   src:=replace(src,needle,replacement);
 END LOOP;
 EXECUTE src;

 signature:='public.sefirot_source_begin(uuid,integer,text,jsonb)'::regprocedure;
 src:=pg_get_functiondef(signature);
 needle:='(started_at at time zone ''UTC'')::date=today)>=200';
 occurrences:=(length(src)-length(replace(src,needle,'')))/length(needle);
 IF occurrences<>2 OR position('SOURCE_DISPATCH_LEASE_REQUIRED' in src)=0
 OR position('SOURCE_DISPATCH_ALREADY_ATTEMPTED' in src)=0 THEN
   RAISE EXCEPTION 'SOURCE_DISPATCH_200_DRIFT';
 END IF;
 EXECUTE replace(src,needle,'(started_at at time zone ''UTC'')::date=today)>=7500');

 -- Legacy owner-only planner: remove 5/day hard stop. One invocation still
 -- creates at most 20 jobs and never activates the budget or refetches uncertain attempts.
 signature:='public.sefirot_plan_collection_day(integer,integer)'::regprocedure;
 src:=pg_get_functiondef(signature);
 IF position('SOURCE_PLANNER_OWNER_REQUIRED' in src)=0 THEN
   RAISE EXCEPTION 'SOURCE_PLANNER_DRIFT';
 END IF;
 edits:=jsonb_build_array(
  jsonb_build_object('old','if used>=5 then return jsonb_build_object(''queued'',0,''reason'',''DAILY_FIVE_ATTEMPT_CAP'');end if;',
     'new','if used>=7500 then return jsonb_build_object(''queued'',0,''reason'',''DAILY_PRO_7500_ATTEMPT_CAP'');end if;'),
  jsonb_build_object('old','exit when used+added>=5;',
     'new','exit when used+added>=7500 or added>=20;'),
  jsonb_build_object('old','''daily_cap'',5,''minute_limit'',1,''reserve'',5',
     'new','''daily_cap'',7500,''minute_limit'',60,''reserve'',0')
 );
 FOR edit IN SELECT value FROM jsonb_array_elements(edits) LOOP
   needle:=edit->>'old';replacement:=edit->>'new';
   occurrences := (length(src)-length(replace(src,needle,'')))/length(needle);
   IF occurrences<>1 THEN RAISE EXCEPTION 'SOURCE_PLANNER_PATCH_DRIFT: % (%)',needle,occurrences;END IF;
   src:=replace(src,needle,replacement);
 END LOOP;
 EXECUTE src;
END
$upgrade$;

COMMENT ON FUNCTION sefirot_budget_private.arm_research_budget(integer,integer)
 IS 'Owner-only opt-in API-Football Pro 7500/UTC-day HARD global limit, bounded <=360-minute window, <=60/min below provider 300/min; no bets';
COMMENT ON FUNCTION public.sefirot_sports_budget_reserve()
 IS 'Global provider single-flight budget: max 7500/UTC-day successful or attempted, real provider header clamp and minute pacer; no money';
COMMENT ON FUNCTION public.sefirot_source_begin(uuid,integer,text,jsonb)
 IS 'One attempt per leased source job; shared total attempts and dispatches each <7500 per UTC day; no automatic retry';
COMMENT ON FUNCTION public.sefirot_plan_collection_day(integer,integer)
 IS 'Owner-only inert daily planner, max 20 queued queries per invocation, no quota activation, never retry uncertain attempts';

DO $postflight$
DECLARE f text;
BEGIN
 IF current_user <> 'postgres' THEN RAISE EXCEPTION 'DAILY_PRO_QUOTA_OWNER_REQUIRED';END IF;
 SELECT pg_get_functiondef('sefirot_budget_private.arm_research_budget(integer,integer)'::regprocedure) INTO f;
 IF position('7500 - calls_today' in f)=0 OR position('p_max_requests NOT BETWEEN 1 AND 7500' in f)=0 OR position('minute_limit = 60' in f)=0 THEN
  RAISE EXCEPTION 'DAILY_PRO_QUOTA_OPERATOR_PATCH_UNCONFIRMED';END IF;
 IF has_function_privilege('anon','public.sefirot_source_begin(uuid,integer,text,jsonb)','EXECUTE')
 OR has_function_privilege('service_role','sefirot_budget_private.arm_research_budget(integer,integer)','EXECUTE')
 OR has_function_privilege('anon','sefirot_budget_private.arm_research_budget(integer,integer)','EXECUTE') THEN
  RAISE EXCEPTION 'DAILY_PRO_QUOTA_ACL_UNEXPECTED';END IF;
 IF NOT EXISTS(SELECT 1 FROM sefirot_budget_private.sports_budget
  WHERE singleton AND NOT enabled AND reserve_day=0 AND remaining_day=0 AND in_flight IS NULL) THEN
  RAISE EXCEPTION 'DAILY_PRO_QUOTA_POSTFLIGHT_NOT_PAUSED';END IF;
END
$postflight$;
COMMIT;