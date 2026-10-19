-- Immutable research record of actual pre-kickoff SEFIROT engine SHADOW runs.
-- Imported from authenticated operator inspection of Render logs. This is NOT
-- canonical prediction seal, calibrated forecast, or monetary authorization.
BEGIN;
SET LOCAL lock_timeout='3s';
DO $g$
BEGIN
 IF current_user<>'postgres'
    OR to_regclass('sefirot.sports_shadow_run_archive') IS NOT NULL
    OR to_regclass('sefirot.sports_research_input_snapshots') IS NULL
 THEN RAISE EXCEPTION 'SHADOW_RUN_ARCHIVE_BASELINE_REQUIRED'; END IF;
END $g$;
CREATE TABLE sefirot.sports_shadow_run_archive(
 run_hash text PRIMARY KEY CHECK(run_hash ~ '^[0-9a-f]{64}$'),
 first_recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 computed_at timestamptz NOT NULL,
 worker_log_at timestamptz NOT NULL,
 payload jsonb NOT NULL,
 source_type text NOT NULL DEFAULT 'WORKER_LOG_OPERATOR_CAPTURE'
   CHECK(source_type='WORKER_LOG_OPERATOR_CAPTURE'),
 core_prediction_seal boolean NOT NULL DEFAULT false CHECK(NOT core_prediction_seal),
 market_calibration_verified boolean NOT NULL DEFAULT false CHECK(NOT market_calibration_verified),
 model_fit_allowed boolean NOT NULL DEFAULT false CHECK(NOT model_fit_allowed),
 monetary_permission boolean NOT NULL DEFAULT false CHECK(NOT monetary_permission),
 CHECK(run_hash=encode(sha256(convert_to(payload::text,'UTF8')),'hex')),
 CHECK(computed_at<=worker_log_at),
 CHECK(worker_log_at<=first_recorded_at),
 CHECK(payload->>'schema'='sefirot-core-shadow-preview-v1'),
 CHECK(payload->>'status'='SHADOW_PREVIEW_COMPLETE'),
 CHECK(payload->'monetary_permission'='false'::jsonb),
 CHECK(payload->'calibration_fit_allowed'='false'::jsonb),
 CHECK(payload->'probability_calibrated'='false'::jsonb),
 CHECK(payload->'execution_enabled'='false'::jsonb),
 CHECK(payload->'canonical_predictions_written'='0'::jsonb),
 CHECK(payload->'provider_requests'='0'::jsonb)
);
CREATE TRIGGER research_shadow_run_immutable
 BEFORE UPDATE OR DELETE ON sefirot.sports_shadow_run_archive
 FOR EACH ROW EXECUTE FUNCTION sefirot.source_archive_immutable();
ALTER TABLE sefirot.sports_shadow_run_archive ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON sefirot.sports_shadow_run_archive
 FROM PUBLIC,anon,authenticated,service_role;

CREATE FUNCTION sefirot.record_research_shadow_log(p_payload jsonb,p_worker_log_at timestamptz)
RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $f$
DECLARE t timestamptz:=clock_timestamp(); runat timestamptz;
        expected int; entry jsonb; game int; begin_at timestamptz;
        contract jsonb; p_win numeric; p_push numeric; p_loss numeric;
        h text; stored boolean;
BEGIN
 IF current_user<>'postgres' OR p_payload IS NULL OR p_worker_log_at IS NULL
   OR p_payload->>'schema' IS DISTINCT FROM 'sefirot-core-shadow-preview-v1'
   OR p_payload->>'status' IS DISTINCT FROM 'SHADOW_PREVIEW_COMPLETE'
   OR p_payload->'probability_calibrated' IS DISTINCT FROM 'false'::jsonb
   OR p_payload->'calibration_fit_allowed' IS DISTINCT FROM 'false'::jsonb
   OR p_payload->'monetary_permission' IS DISTINCT FROM 'false'::jsonb
   OR p_payload->'execution_enabled' IS DISTINCT FROM 'false'::jsonb
   OR p_payload->'canonical_predictions_written' IS DISTINCT FROM '0'::jsonb
   OR p_payload->'provider_requests' IS DISTINCT FROM '0'::jsonb
   OR jsonb_typeof(p_payload->'previews') IS DISTINCT FROM 'array'
 THEN RAISE EXCEPTION 'SHADOW_RECORD_RESEARCH_ONLY_CONTRACT';END IF;
 runat:=(p_payload->>'at')::timestamptz;
 expected:=jsonb_array_length(p_payload->'previews');
 IF runat IS NULL OR runat>p_worker_log_at OR p_worker_log_at>t
    OR runat<t-interval '60 minutes'
    OR expected<1 OR expected>4
    OR (p_payload->>'inputs_evaluated')::integer IS DISTINCT FROM expected
 THEN RAISE EXCEPTION 'SHADOW_RUN_TIME_OR_COUNT_INVALID'; END IF;

 FOR entry IN SELECT value FROM jsonb_array_elements(p_payload->'previews')
 LOOP
  IF entry->>'status' IS DISTINCT FROM 'UNVALIDATED_SHADOW'
     OR entry->>'decision' IS DISTINCT FROM 'PASS'
     OR entry->'fit_allowed' IS DISTINCT FROM 'false'::jsonb
     OR entry->>'calibration_status' IS DISTINCT FROM 'NOT_FITTED'
     OR entry->'raw_model_only' IS DISTINCT FROM 'true'::jsonb
     OR entry->'ev' IS DISTINCT FROM 'null'::jsonb
     OR entry->'stake' IS DISTINCT FROM '0'::jsonb
     OR entry->>'model_code_hash' !~ '^[0-9a-f]{64}$'
     OR entry->>'policy_hash' !~ '^[0-9a-f]{64}$'
     OR entry->>'input_adapter_hash' !~ '^[0-9a-f]{64}$'
     OR entry->>'profile_and_reliability' IS DISTINCT FROM 'MEN/0.8 RESEARCH ASSUMPTIONS'
     OR jsonb_typeof(entry->'markets') IS DISTINCT FROM 'array'
     OR jsonb_array_length(entry->'markets') NOT BETWEEN 1 AND 7
  THEN RAISE EXCEPTION 'SHADOW_FORECAST_CONTRACT_INVALID'; END IF;
  game:=(entry->>'fixture_id')::integer;
  begin_at:=(entry->>'kickoff')::timestamptz;
  IF game IS NULL OR game<=0 OR begin_at<=t+interval '30 seconds'
     OR runat>=begin_at OR (entry->>'as_of')::timestamptz>=begin_at
     OR NOT EXISTS (SELECT 1 FROM sefirot.sports_research_input_snapshots s
        WHERE s.fixture_id=game AND s.kickoff=begin_at AND s.captured_at<=runat)
  THEN RAISE EXCEPTION 'SHADOW_NOT_PROSPECTIVE_OR_UNBOUND'; END IF;
  FOR contract IN SELECT value FROM jsonb_array_elements(entry->'markets')
  LOOP
   IF contract->>'calibration' IS DISTINCT FROM 'UNCALIBRATED'
      OR contract->>'key' IS NULL
      OR NOT (contract ? 'raw_win' AND contract ? 'raw_push' AND contract ? 'raw_loss')
   THEN RAISE EXCEPTION 'SHADOW_MARKET_UNCALIBRATED_REQUIRED';END IF;
   p_win:=(contract->>'raw_win')::numeric;
   p_push:=(contract->>'raw_push')::numeric;
   p_loss:=(contract->>'raw_loss')::numeric;
   IF p_win NOT BETWEEN 0 AND 1 OR p_push NOT BETWEEN 0 AND 1
     OR p_loss NOT BETWEEN 0 AND 1
     OR abs(p_win+p_push+p_loss-1)>0.000001
   THEN RAISE EXCEPTION 'SHADOW_MARKET_MASS_INVALID';END IF;
  END LOOP;
 END LOOP;
 h:=encode(sha256(convert_to(p_payload::text,'UTF8')),'hex');
 INSERT INTO sefirot.sports_shadow_run_archive(run_hash,first_recorded_at,computed_at,worker_log_at,payload)
 VALUES(h,t,runat,p_worker_log_at,p_payload)
 ON CONFLICT (run_hash) DO NOTHING RETURNING true INTO stored;
 RETURN jsonb_build_object('stored',coalesce(stored,false),'run_hash',h,
   'fixture_reports',expected,'recorded_at',t,'monetary_permission',false,
   'calibrated',false,'canonical_predictions_written',0);
END
$f$;
REVOKE ALL ON FUNCTION sefirot.record_research_shadow_log(jsonb,timestamptz)
 FROM PUBLIC,anon,authenticated,service_role;
COMMENT ON TABLE sefirot.sports_shadow_run_archive
 IS 'Research-only immutable operator-captured Render SHADOW output, no original CORE seal or independent calibration authority';
COMMIT;