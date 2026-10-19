-- SEFIROT isolated research sync and prospective feature snapshots, no probability/EV/seal.
BEGIN;
SET LOCAL lock_timeout='3s';
SET LOCAL statement_timeout='25s';
DO $guard$
BEGIN
 IF current_user<>'postgres'
  OR to_regclass('sefirot.sports_fixture_observations') IS NULL
  OR to_regprocedure('sefirot.sports_research_form_asof(bigint,timestamptz,integer)') IS NULL
  OR to_regclass('sefirot.sports_research_input_snapshots') IS NOT NULL
 THEN RAISE EXCEPTION 'RESEARCH_INPUT_SNAPSHOT_BASELINE_REQUIRED'; END IF;
END $guard$;

CREATE TABLE sefirot.sports_research_input_snapshots (
 snapshot_id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
 fixture_id bigint NOT NULL CHECK(fixture_id>0),
 captured_at timestamptz NOT NULL,
 as_of timestamptz NOT NULL,
 kickoff timestamptz NOT NULL,
 feature_payload jsonb NOT NULL CHECK(jsonb_typeof(feature_payload)='object'),
 feature_hash text NOT NULL CHECK(feature_hash~'^[0-9a-f]{64}$'),
 status text NOT NULL DEFAULT 'RESEARCH_ONLY' CHECK(status='RESEARCH_ONLY'),
 forecast_created boolean NOT NULL DEFAULT false CHECK(NOT forecast_created),
 monetary_permission boolean NOT NULL DEFAULT false CHECK(NOT monetary_permission),
 model_fit_allowed boolean NOT NULL DEFAULT false CHECK(NOT model_fit_allowed),
 CHECK(as_of<=captured_at),
 CHECK(captured_at<kickoff),
 CHECK(feature_payload->>'schema'='sefirot-research-form-v1'),
 CHECK(feature_payload->>'decision'='PASS'),
 CHECK(feature_hash=encode(sha256(convert_to(feature_payload::text,'UTF8')),'hex'))
);
CREATE TRIGGER research_input_snapshot_immutable BEFORE UPDATE OR DELETE ON sefirot.sports_research_input_snapshots
 FOR EACH ROW EXECUTE FUNCTION sefirot.source_archive_immutable();
ALTER TABLE sefirot.sports_research_input_snapshots ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON sefirot.sports_research_input_snapshots FROM PUBLIC,anon,authenticated,service_role;

CREATE FUNCTION sefirot.record_research_form_now(
 p_fixture bigint,p_last integer DEFAULT 10
) RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $fn$
DECLARE t timestamptz:=clock_timestamp(); f jsonb; id uuid; k timestamptz;
BEGIN
 IF current_user<>'postgres' THEN RAISE EXCEPTION 'RESEARCH_SNAPSHOT_OWNER_ONLY'; END IF;
 f:=sefirot.sports_research_form_asof(p_fixture,t,p_last);
 IF f->>'research_input_ready' IS DISTINCT FROM 'true'
 OR f->>'data_stage' IS DISTINCT FROM 'STRUCTURAL_SQL_NOT_PYTHON_PIPELINE_QC'
 OR f->>'forecast_created' IS DISTINCT FROM 'false'
 OR f->>'decision' IS DISTINCT FROM 'PASS' THEN
  RETURN jsonb_build_object('recorded',false,'fixture_id',p_fixture,'reason',coalesce(f->>'reason','RESEARCH_INPUT_NOT_READY'));
 END IF;
 k:=(f->>'kickoff')::timestamptz;
 IF k<=clock_timestamp()+interval '30 seconds' THEN
  RETURN jsonb_build_object('recorded',false,'fixture_id',p_fixture,'reason','TOO_CLOSE_TO_KICKOFF');
 END IF;
 INSERT INTO sefirot.sports_research_input_snapshots(fixture_id,captured_at,as_of,kickoff,feature_payload,feature_hash)
 VALUES (p_fixture,t,t,k,f,encode(sha256(convert_to(f::text,'UTF8')),'hex'))
 RETURNING snapshot_id INTO id;
 RETURN jsonb_build_object('recorded',true,'fixture_id',p_fixture,
  'snapshot_id',id,'captured_at',t,'forecast_created',false,'probability',null,
  'model_fit_allowed',false,'money_authorized',false);
END
$fn$;
REVOKE ALL ON FUNCTION sefirot.record_research_form_now(bigint,integer) FROM PUBLIC,anon,authenticated,service_role;

-- Import newly archived fixture data only, never fetch API or mutate canonical matches/predictions.
CREATE FUNCTION sefirot.sync_research_fixture_sources(
 p_limit integer DEFAULT 20
) RETURNS jsonb LANGUAGE plpgsql SECURITY INVOKER SET search_path='' AS $fn$
DECLARE a record;p jsonb; ct int:=0;fixture_ct int:=0;written int;
BEGIN
 IF current_user<>'postgres' OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 20
   OR EXISTS(SELECT 1 FROM sefirot.chat_bridge_jobs WHERE status IN ('PENDING','RUNNING'))
 THEN RAISE EXCEPTION 'RESEARCH_SYNC_OWNER_QUIESCENT_REQUIRED'; END IF;
 FOR a IN
  SELECT raw_sha256,raw_source,source_packet,imported_at FROM sefirot.sports_archive x
  WHERE x.source_packet->'receipt'->>'endpoint'='/fixtures'
  AND NOT EXISTS(SELECT 1 FROM sefirot.sports_packet_structural_qc q WHERE q.source_hash=x.raw_sha256)
  ORDER BY x.imported_at,x.raw_sha256 LIMIT p_limit
 LOOP
  p:=a.source_packet;
  IF a.raw_sha256<>encode(sha256(convert_to(a.raw_source,'UTF8')),'hex')
   OR p->'receipt'->>'provider' IS DISTINCT FROM 'API_FOOTBALL_V3'
   OR p->'receipt'->>'provider_host' IS DISTINCT FROM 'v3.football.api-sports.io'
   OR p->'receipt'->>'transport' IS DISTINCT FROM 'SUPABASE_GATEWAY'
   OR p->'receipt'->'sports_only' IS DISTINCT FROM 'true'::jsonb
   OR p->'receipt'->>'http_status' IS DISTINCT FROM '200'
   OR p->'data'->>'get' IS DISTINCT FROM 'fixtures'
   OR p->'data'->'errors' NOT IN ('[]'::jsonb,'{}'::jsonb)
   OR jsonb_typeof(p->'data'->'response') IS DISTINCT FROM 'array'
   OR (p->'data'->>'results')::integer IS DISTINCT FROM jsonb_array_length(p->'data'->'response')
   OR (p->'receipt'->>'request_started_at')::timestamptz>(p->'receipt'->>'upstream_received_at')::timestamptz
   OR (p->'receipt'->>'upstream_received_at')::timestamptz>(p->'receipt'->>'received_at')::timestamptz
   OR (p->'receipt'->>'received_at')::timestamptz>a.imported_at
   OR EXISTS(SELECT 1 FROM jsonb_each_text(p->'receipt'->'parameters') r
        FULL JOIN jsonb_each_text(p->'data'->'parameters') d USING(key)
        WHERE r.value IS DISTINCT FROM d.value)
  THEN RAISE EXCEPTION 'RESEARCH_NEW_SOURCE_STRUCTURAL_QC_FAILED'; END IF;
  IF EXISTS(
   SELECT 1 FROM jsonb_array_elements(p->'data'->'response') v
   WHERE v->'fixture'->>'id' IS NULL OR v->'fixture'->>'date' IS NULL
    OR v->'league'->>'id' IS NULL OR v->'league'->>'season' IS NULL
    OR v->'teams'->'home'->>'id' IS NULL OR v->'teams'->'away'->>'id' IS NULL
    OR v->'fixture'->'status'->>'short' IS NULL
    OR v->'fixture'->'status'->>'short' !~ '^[A-Z0-9]{1,6}$'
    OR (v->'teams'->'home'->>'id')::bigint=(v->'teams'->'away'->>'id')::bigint
    OR (v->'fixture'->'status'->>'short'='FT' AND
       ((v->'score'->'fulltime'->>'home')::int NOT BETWEEN 0 AND 50
        OR (v->'score'->'fulltime'->>'away')::int NOT BETWEEN 0 AND 50
        OR (v->'fixture'->>'date')::timestamptz+interval '75 minutes'>
          (p->'receipt'->>'received_at')::timestamptz))
    OR (p->'receipt'->'parameters' ? 'league' AND
         p->'receipt'->'parameters'->>'league'<>v->'league'->>'id')
    OR (p->'receipt'->'parameters' ? 'season' AND
         p->'receipt'->'parameters'->>'season'<>v->'league'->>'season')
    OR (p->'receipt'->'parameters' ? 'id' AND
         p->'receipt'->'parameters'->>'id'<>v->'fixture'->>'id')
    OR (p->'receipt'->'parameters' ? 'team' AND
         p->'receipt'->'parameters'->>'team' NOT IN (v->'teams'->'home'->>'id',v->'teams'->'away'->>'id'))
  ) OR EXISTS(
   SELECT 1 FROM jsonb_array_elements(p->'data'->'response') v
   GROUP BY v->'fixture'->>'id' HAVING count(*)>1
  ) THEN RAISE EXCEPTION 'RESEARCH_NEW_SOURCE_FIXTURE_QC_FAILED';END IF;
  INSERT INTO sefirot.sports_packet_structural_qc(source_hash,endpoint,accepted,observed_at,available_at)
  VALUES(a.raw_sha256,'/fixtures',true,(p->'receipt'->>'received_at')::timestamptz,
    GREATEST(a.imported_at,(p->'receipt'->>'received_at')::timestamptz));
  INSERT INTO sefirot.sports_fixture_observations(source_hash,fixture_id,league_id,season,kickoff,source_received_at,available_at,home_id,away_id,home_name,away_name,status,home_goals,away_goals,source_fixture)
  SELECT a.raw_sha256,(v->'fixture'->>'id')::bigint,(v->'league'->>'id')::int,
   (v->'league'->>'season')::int,(v->'fixture'->>'date')::timestamptz,
   (p->'receipt'->>'received_at')::timestamptz,
   GREATEST(a.imported_at,(p->'receipt'->>'received_at')::timestamptz),
   (v->'teams'->'home'->>'id')::bigint,(v->'teams'->'away'->>'id')::bigint,
   v->'teams'->'home'->>'name',v->'teams'->'away'->>'name',
   v->'fixture'->'status'->>'short',
   CASE WHEN v->'fixture'->'status'->>'short'='FT' THEN (v->'score'->'fulltime'->>'home')::int END,
   CASE WHEN v->'fixture'->'status'->>'short'='FT' THEN (v->'score'->'fulltime'->>'away')::int END,v
  FROM jsonb_array_elements(p->'data'->'response') v;
  GET DIAGNOSTICS written=ROW_COUNT;fixture_ct:=fixture_ct+written;ct:=ct+1;
 END LOOP;
 RETURN jsonb_build_object('source_packets_added',ct,'fixture_observations_added',fixture_ct,
  'provider_requests',0,'forecast_created',false,'model_fit_allowed',false,'monetary_permission',false);
END
$fn$;
REVOKE ALL ON FUNCTION sefirot.sync_research_fixture_sources(integer)
 FROM PUBLIC,anon,authenticated,service_role;
COMMIT;