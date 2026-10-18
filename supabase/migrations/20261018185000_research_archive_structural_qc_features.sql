-- SEFIROT research-only SQL projections of verified archived sports sources.
-- This stage is NOT the Python football_pipeline QC, a forecast, model fit, or monetary release.
BEGIN;
SET LOCAL lock_timeout='3s';
SET LOCAL statement_timeout='25s';
DO $guard$
BEGIN
 IF current_user <> 'postgres'
    OR to_regclass('sefirot.sports_archive') IS NULL
    OR to_regclass('sefirot.sports_packet_structural_qc') IS NOT NULL
    OR to_regclass('sefirot.sports_fixture_observations') IS NOT NULL
    OR EXISTS(SELECT 1 FROM sefirot.chat_bridge_jobs WHERE status IN ('PENDING','RUNNING'))
    OR EXISTS(SELECT 1 FROM sefirot_budget_private.sports_budget
      WHERE singleton AND in_flight IS NOT NULL)
 THEN RAISE EXCEPTION 'RESEARCH_PROJECTION_SAFE_BASELINE_REQUIRED'; END IF;
END $guard$;

CREATE TABLE sefirot.sports_packet_structural_qc (
 source_hash text PRIMARY KEY REFERENCES sefirot.sports_archive(raw_sha256),
 inspected_at timestamptz NOT NULL DEFAULT clock_timestamp(),
 adapter text NOT NULL DEFAULT 'SUPABASE_STRUCTURAL_QC_V1'
   CHECK(adapter='SUPABASE_STRUCTURAL_QC_V1'),
 endpoint text NOT NULL,
 accepted boolean NOT NULL,
 reason text,
 observed_at timestamptz NOT NULL,
 available_at timestamptz NOT NULL,
 provider_origin_cryptographically_attested boolean NOT NULL DEFAULT false
   CHECK(NOT provider_origin_cryptographically_attested),
 python_pipeline_qc_passed boolean NOT NULL DEFAULT false
   CHECK(NOT python_pipeline_qc_passed),
 model_fit_allowed boolean NOT NULL DEFAULT false CHECK(NOT model_fit_allowed),
 CHECK (available_at >= observed_at),
 CHECK (accepted OR reason IS NOT NULL)
);
CREATE TABLE sefirot.sports_fixture_observations (
 source_hash text NOT NULL REFERENCES sefirot.sports_packet_structural_qc(source_hash),
 fixture_id bigint NOT NULL CHECK (fixture_id>0),
 league_id int NOT NULL CHECK(league_id>0),
 season int NOT NULL CHECK(season BETWEEN 1990 AND 2200),
 kickoff timestamptz NOT NULL,
 source_received_at timestamptz NOT NULL,
 available_at timestamptz NOT NULL,
 home_id bigint NOT NULL CHECK(home_id>0),
 away_id bigint NOT NULL CHECK(away_id>0),
 home_name text NOT NULL CHECK(length(home_name) BETWEEN 1 AND 150),
 away_name text NOT NULL CHECK(length(away_name) BETWEEN 1 AND 150),
 status text NOT NULL CHECK(status~'^[A-Z0-9]{1,6}$'),
 home_goals int,
 away_goals int,
 source_fixture jsonb NOT NULL CHECK(jsonb_typeof(source_fixture)='object'),
 model_fit_allowed boolean NOT NULL DEFAULT false CHECK(NOT model_fit_allowed),
 PRIMARY KEY(source_hash,fixture_id),
 CHECK(home_id<>away_id),
 CHECK(available_at>=source_received_at),
 CHECK ((status='FT' AND home_goals BETWEEN 0 AND 50 AND away_goals BETWEEN 0 AND 50 AND source_received_at>=kickoff+interval '75 minutes')
        OR (status<>'FT' AND home_goals IS NULL AND away_goals IS NULL))
);
CREATE INDEX sports_fixture_observations_by_fixture
 ON sefirot.sports_fixture_observations(fixture_id,source_received_at DESC,available_at DESC);
CREATE INDEX sports_fixture_observations_by_league
 ON sefirot.sports_fixture_observations(league_id,season,kickoff);
CREATE INDEX sports_fixture_observations_by_home
 ON sefirot.sports_fixture_observations(home_id,kickoff);
CREATE INDEX sports_fixture_observations_by_away
 ON sefirot.sports_fixture_observations(away_id,kickoff);
CREATE TRIGGER research_qc_immutable BEFORE UPDATE OR DELETE ON sefirot.sports_packet_structural_qc
 FOR EACH ROW EXECUTE FUNCTION sefirot.source_archive_immutable();
CREATE TRIGGER research_fixture_observations_immutable BEFORE UPDATE OR DELETE ON sefirot.sports_fixture_observations
 FOR EACH ROW EXECUTE FUNCTION sefirot.source_archive_immutable();
ALTER TABLE sefirot.sports_packet_structural_qc ENABLE ROW LEVEL SECURITY;
ALTER TABLE sefirot.sports_fixture_observations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON sefirot.sports_packet_structural_qc,sefirot.sports_fixture_observations
 FROM PUBLIC,anon,authenticated,service_role;

-- Read-only as-of research features. No canonical prediction, no price, no refit.
-- The latest observation per fixture MUST have been available at the requested as-of.
CREATE FUNCTION sefirot.sports_research_form_asof(
 p_fixture bigint,
 p_as_of timestamptz,
 p_last integer DEFAULT 10
) RETURNS jsonb LANGUAGE plpgsql STABLE SECURITY INVOKER
SET search_path='' AS $fn$
DECLARE target record;
        home_form jsonb;
        away_form jsonb;
        conflicts integer;
BEGIN
 IF current_user <> 'postgres'
   OR p_fixture IS NULL OR p_fixture<1
   OR p_as_of IS NULL OR p_as_of>clock_timestamp()
   OR p_last IS NULL OR p_last NOT BETWEEN 1 AND 20
 THEN RAISE EXCEPTION 'RESEARCH_FORM_OWNER_INPUT_REQUIRED'; END IF;

 SELECT * INTO target
 FROM sefirot.sports_fixture_observations o
 WHERE o.fixture_id=p_fixture AND o.available_at<=p_as_of
 ORDER BY o.source_received_at DESC,o.available_at DESC,o.source_hash DESC LIMIT 1;
 IF NOT FOUND THEN
   RETURN jsonb_build_object('schema','sefirot-research-form-v1','fixture_id',p_fixture,
     'as_of',p_as_of,'decision','PASS','reason','NO_TARGET_KNOWN_AS_OF',
     'probability',null,'ev',null,'monetary_permission',false);
 END IF;
 IF p_as_of>=target.kickoff THEN
   RETURN jsonb_build_object('schema','sefirot-research-form-v1','fixture_id',p_fixture,
     'as_of',p_as_of,'decision','PASS','reason','NOT_PREMATCH_AS_OF',
     'probability',null,'ev',null,'monetary_permission',false);
 END IF;
 IF target.status<>'NS' THEN
   RETURN jsonb_build_object('schema','sefirot-research-form-v1','fixture_id',p_fixture,
     'as_of',p_as_of,'decision','PASS','reason','TARGET_NOT_NS_AS_OF',
     'probability',null,'ev',null,'monetary_permission',false);
 END IF;
 SELECT count(*)::integer INTO conflicts FROM (
   SELECT fixture_id
   FROM sefirot.sports_fixture_observations
   WHERE available_at<=p_as_of
   GROUP BY fixture_id
   HAVING count(DISTINCT jsonb_build_array(league_id,season,kickoff,home_id,away_id))>1
      OR count(DISTINCT CASE WHEN status='FT'
         THEN jsonb_build_array(home_goals,away_goals) END)>1
 ) c WHERE c.fixture_id=p_fixture;
 IF conflicts>0 THEN
   RETURN jsonb_build_object('schema','sefirot-research-form-v1','fixture_id',p_fixture,
     'as_of',p_as_of,'decision','PASS','reason','TARGET_IDENTITY_OR_RESULT_CONFLICT',
     'probability',null,'ev',null,'monetary_permission',false);
 END IF;

 WITH latest AS (
  SELECT DISTINCT ON(o.fixture_id) o.*
  FROM sefirot.sports_fixture_observations o
  WHERE o.available_at<=p_as_of
  ORDER BY o.fixture_id,o.source_received_at DESC,o.available_at DESC,o.source_hash DESC
 ), conflict_ids AS (
  SELECT fixture_id FROM sefirot.sports_fixture_observations
  WHERE available_at<=p_as_of GROUP BY fixture_id
  HAVING count(DISTINCT jsonb_build_array(league_id,season,kickoff,home_id,away_id))>1
      OR count(DISTINCT CASE WHEN status='FT'
         THEN jsonb_build_array(home_goals,away_goals) END)>1
 ), eligible AS (
  SELECT l.* FROM latest l WHERE l.status='FT' AND l.kickoff<target.kickoff
   AND l.available_at<=p_as_of AND l.source_received_at>=l.kickoff+interval '75 minutes'
   AND l.league_id=target.league_id AND l.season=target.season
   AND NOT EXISTS(SELECT 1 FROM conflict_ids x WHERE x.fixture_id=l.fixture_id)
 ), sides AS (
  SELECT 'HOME' side,target.home_id team_id
  UNION ALL SELECT 'AWAY',target.away_id
 ), games AS (
  SELECT s.side,e.fixture_id,e.kickoff,e.source_hash,e.available_at,
    CASE WHEN e.home_id=s.team_id THEN e.home_goals ELSE e.away_goals END gf,
    CASE WHEN e.home_id=s.team_id THEN e.away_goals ELSE e.home_goals END ga,
    (e.home_id=s.team_id) as home_venue,
    row_number() OVER(PARTITION BY s.side ORDER BY e.kickoff DESC,e.fixture_id DESC) rn
  FROM sides s JOIN eligible e ON e.home_id=s.team_id OR e.away_id=s.team_id
 ), bounded AS (
  SELECT * FROM games WHERE rn<=p_last
 ), metrics AS (
  SELECT side,count(*) sample_size,
    count(*) FILTER(WHERE gf>ga) wins,
    count(*) FILTER(WHERE gf=ga) draws,
    count(*) FILTER(WHERE gf<ga) losses,
    sum(gf) goals_for,sum(ga) goals_against,
    count(*) FILTER(WHERE gf+ga>=3) over25,
    count(*) FILTER(WHERE gf>0 AND ga>0) btts,
    count(*) FILTER(WHERE gf>=2) team_2plus,
    coalesce(jsonb_agg(jsonb_build_object('fixture_id',fixture_id,'kickoff',kickoff,
      'gf',gf,'ga',ga,'source_hash',source_hash,'available_at',available_at)
       ORDER BY kickoff DESC,fixture_id DESC),'[]'::jsonb) provenance_history
  FROM bounded GROUP BY side
 )
 SELECT
  coalesce((SELECT jsonb_build_object('team_id',target.home_id,'name',target.home_name,
      'sample_size',sample_size,'wins',wins,'draws',draws,'losses',losses,
      'goals_for',goals_for,'goals_against',goals_against,'over25',over25,
      'btts',btts,'team_2plus',team_2plus,'history',provenance_history)
     FROM metrics WHERE side='HOME'),
    jsonb_build_object('team_id',target.home_id,'name',target.home_name,'sample_size',0,'history','[]'::jsonb)),
  coalesce((SELECT jsonb_build_object('team_id',target.away_id,'name',target.away_name,
      'sample_size',sample_size,'wins',wins,'draws',draws,'losses',losses,
      'goals_for',goals_for,'goals_against',goals_against,'over25',over25,
      'btts',btts,'team_2plus',team_2plus,'history',provenance_history)
     FROM metrics WHERE side='AWAY'),
    jsonb_build_object('team_id',target.away_id,'name',target.away_name,'sample_size',0,'history','[]'::jsonb))
 INTO home_form,away_form;

 RETURN jsonb_build_object(
  'schema','sefirot-research-form-v1',
  'fixture_id',p_fixture,'league_id',target.league_id,'season',target.season,
  'kickoff',target.kickoff,'as_of',p_as_of,
  'target_source_hash',target.source_hash,'target_available_at',target.available_at,
  'home',home_form,'away',away_form,
  'data_stage','STRUCTURAL_SQL_NOT_PYTHON_PIPELINE_QC',
  'research_input_ready',true,'forecast_created',false,
  'probability',null,'ev',null,'fit_allowed',false,
  'monetary_permission',false,'decision','PASS'
 );
END
$fn$;
REVOKE ALL ON FUNCTION sefirot.sports_research_form_asof(bigint,timestamptz,integer)
 FROM PUBLIC,anon,authenticated,service_role;
COMMENT ON FUNCTION sefirot.sports_research_form_asof(bigint,timestamptz,integer)
 IS 'Owner-only read-only research features with as-of source availability, not SEFIROT CORE/model forecast or money authorization';
COMMIT;