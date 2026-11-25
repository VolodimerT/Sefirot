-- Apply to December Quest only after staging acceptance.
alter table public.sefirot_december_quest_auto_validation
  add column previous_versions jsonb not null default '{}';

alter table public.sefirot_december_quest_auto_settlements
  add column details jsonb not null default '{}',
  alter column model_brier drop not null,
  alter column model_logloss drop not null;

create function public.dq_reject_snapshot_change()
returns trigger language plpgsql set search_path = '' as $$
begin
  raise exception 'PREMATCH_SEAL_IMMUTABLE' using errcode = '23514';
end;
$$;

create trigger dq_auto_snapshot_immutable
before update or delete or truncate on public.sefirot_december_quest_auto_snapshots
for each statement execute function public.dq_reject_snapshot_change();

revoke all on function public.dq_reject_snapshot_change() from public;
revoke update, delete, truncate on public.sefirot_december_quest_auto_snapshots from anon, authenticated, service_role;

-- A new cycle starts at the production cron time in Kyiv.
create function public.dq_predictor_cycle_start(p_at timestamptz)
returns timestamptz language sql stable set search_path = '' as $$
  select (date_trunc('day', (p_at at time zone 'Europe/Kyiv') - interval '19 hours')
          + interval '19 hours') at time zone 'Europe/Kyiv';
$$;

create function public.dq_predictor_run_state(p_model_version text)
returns jsonb language sql stable security invoker set search_path = '' as $$
  with clock as (select statement_timestamp() as checked_at),
  cycle as (select checked_at, public.dq_predictor_cycle_start(checked_at) as starts_at from clock)
  select jsonb_build_object('checked_at', c.checked_at, 'cycle_started_at', c.starts_at,
    'recent_success_at', max(r.completed_at))
  from cycle c
  left join public.sefirot_december_quest_auto_runs r
    on r.model_version=p_model_version and r.run_status='OK'
    and r.started_at between c.starts_at and c.checked_at
    and r.completed_at > c.checked_at - interval '6 hours'
  group by c.checked_at, c.starts_at;
$$;

revoke all on function public.dq_predictor_cycle_start(timestamptz), public.dq_predictor_run_state(text)
  from public, anon, authenticated;
grant execute on function public.dq_predictor_cycle_start(timestamptz), public.dq_predictor_run_state(text)
  to service_role;

create function public.dq_commit_predictor_run(
  p_run jsonb, p_forecasts jsonb, p_validation jsonb, p_settlements jsonb
)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  stamped timestamptz := statement_timestamp();
  version text := p_run->>'model_version';
  selected_status text := p_run->>'run_status';
  run_started timestamptz := (p_run->>'started_at')::timestamptz;
  cycle_started timestamptz := public.dq_predictor_cycle_start(run_started);
  forecast_rows integer;
  model_rows integer;
  seal_rows integer;
  settlement_rows integer;
begin
  if run_started is null or run_started < stamped - interval '10 minutes' or run_started > stamped then
    raise exception 'INVALID_RUN_STARTED_AT' using errcode='22023';
  end if;
  if not pg_try_advisory_xact_lock(721735, 202612) then
    return jsonb_build_object('skipped', 'COMMIT_IN_PROGRESS');
  end if;
  if exists (
    select 1 from public.sefirot_december_quest_auto_runs r
    where r.model_version=version and r.run_status=selected_status
      and r.started_at >= cycle_started
      and public.dq_predictor_cycle_start(r.started_at)=cycle_started
      and r.completed_at > stamped - interval '6 hours'
  ) then
    return jsonb_build_object('skipped', 'RUN_ALREADY_RECORDED', 'cycle_started_at', cycle_started);
  end if;

  with eligible as (
    select x.*, f.timing_status
    from jsonb_populate_recordset(null::public.sefirot_december_quest_auto_forecasts, p_forecasts) x
    join public.sefirot_december_quest_fixtures f
      on f.fixture_key=x.fixture_key and f.kickoff=x.kickoff and f.competition=x.competition
    where x.source_cutoff <= stamped and x.source_cutoff > stamped - interval '10 minutes'
      and x.kickoff > stamped and x.model_version=version
      and (x.kickoff at time zone 'Europe/Kyiv')::date between date '2026-12-01' and date '2026-12-31'
      and (x.kickoff at time zone 'Europe/Kyiv')::time between time '21:00' and time '23:00'
  ), saved as (
    insert into public.sefirot_december_quest_auto_forecasts (
      fixture_key, competition, kickoff, generated_at, source_cutoff, model_version,
      status, verdict, risk_class, probabilities, markets, best_candidate, evidence, sample_n, notes
    )
    select fixture_key, competition, kickoff, stamped, source_cutoff, model_version,
      status, verdict, risk_class, probabilities, markets, best_candidate, evidence, sample_n, notes
    from eligible
    on conflict (fixture_key) do update set
      competition=excluded.competition, kickoff=excluded.kickoff, generated_at=excluded.generated_at,
      source_cutoff=excluded.source_cutoff, model_version=excluded.model_version, status=excluded.status,
      verdict=excluded.verdict, risk_class=excluded.risk_class, probabilities=excluded.probabilities,
      markets=excluded.markets, best_candidate=excluded.best_candidate, evidence=excluded.evidence,
      sample_n=excluded.sample_n, notes=excluded.notes
    where sefirot_december_quest_auto_forecasts.source_cutoff < excluded.source_cutoff
    returning fixture_key, status
  ), sealed as (
    insert into public.sefirot_december_quest_auto_snapshots (
      fixture_key, kickoff, generated_at, generated_day, model_version, status, probabilities, markets, evidence
    )
    -- generated_day is the Kyiv operating day for this collector. generated_at is the actual server timestamp.
    select e.fixture_key, e.kickoff, stamped, (cycle_started at time zone 'Europe/Kyiv')::date,
      e.model_version, e.status, e.probabilities, e.markets,
      e.evidence || jsonb_build_object('source_cutoff', e.source_cutoff, 'cycle_started_at', cycle_started, 'decision',
        jsonb_build_object('verdict',e.verdict,'risk_class',e.risk_class,'notes',e.notes,'best_candidate',e.best_candidate))
    from eligible e join saved s using (fixture_key)
    where e.timing_status='confirmed' and e.evidence->>'fixture_timing_status'='confirmed'
      and e.evidence->>'kickoff_gate'='CONFIRMED'
    on conflict (fixture_key, generated_day, model_version) do nothing
    returning id
  )
  select (select count(*) from saved),
         (select count(*) from saved where status in ('MODEL_ONLY','WAITING_ODDS')),
         (select count(*) from sealed)
  into forecast_rows, model_rows, seal_rows;

  insert into public.sefirot_december_quest_auto_validation (
    competition, model_version, generated_at, sample_n, model_brier, baseline_brier,
    model_logloss, baseline_logloss, relative_skill, status, source, rationale
  )
  select competition, model_version, stamped, sample_n, model_brier, baseline_brier,
    model_logloss, baseline_logloss, relative_skill, status, 'football-data.co.uk', rationale
  from jsonb_populate_recordset(null::public.sefirot_december_quest_auto_validation,p_validation)
  where model_version=version
  on conflict (competition) do update set generated_at=excluded.generated_at,
    model_version=excluded.model_version,
    previous_versions=case
      when sefirot_december_quest_auto_validation.model_version=excluded.model_version
        then sefirot_december_quest_auto_validation.previous_versions
      else sefirot_december_quest_auto_validation.previous_versions
        || jsonb_build_object(sefirot_december_quest_auto_validation.model_version,
            to_jsonb(sefirot_december_quest_auto_validation) - 'previous_versions')
    end,
    sample_n=excluded.sample_n, model_brier=excluded.model_brier, baseline_brier=excluded.baseline_brier,
    model_logloss=excluded.model_logloss, baseline_logloss=excluded.baseline_logloss,
    relative_skill=excluded.relative_skill, status=excluded.status, rationale=excluded.rationale;

  insert into public.sefirot_december_quest_auto_settlements (
    fixture_key, snapshot_id, kickoff, actual_home_goals, actual_away_goals, result,
    model_brier, model_logloss, source_quality, source_url, settled_at, details
  )
  select x.fixture_key, x.snapshot_id, x.kickoff, x.actual_home_goals, x.actual_away_goals, x.result,
    x.model_brier, x.model_logloss, x.source_quality, x.source_url, stamped, x.details
  from jsonb_populate_recordset(null::public.sefirot_december_quest_auto_settlements,p_settlements) x
  join public.sefirot_december_quest_auto_snapshots s
    on s.id=x.snapshot_id and s.fixture_key=x.fixture_key and s.kickoff=x.kickoff
      and s.generated_at < s.kickoff and s.model_version=version
  join public.sefirot_december_quest_fixtures f on f.fixture_key=x.fixture_key and f.kickoff=x.kickoff
  where x.kickoff < stamped - interval '3 hours'
  on conflict (fixture_key) do nothing;
  get diagnostics settlement_rows = row_count;

  insert into public.sefirot_december_quest_auto_runs (
    started_at, completed_at, model_version, provider, fetch_ok, sources_attempted,
    scanned, forecasted, insufficient, errors, run_status
  )
  select x.started_at, stamped, version, 'football-data.co.uk', x.fetch_ok, x.sources_attempted,
    forecast_rows, model_rows, forecast_rows-model_rows, x.errors, selected_status
  from jsonb_populate_record(null::public.sefirot_december_quest_auto_runs,p_run) x;

  return jsonb_build_object('saved',forecast_rows,'modeled',model_rows,
    'pass',forecast_rows,'sealed',seal_rows,'settled',settlement_rows,'cycle_started_at',cycle_started);
end;
$$;

revoke all on function public.dq_commit_predictor_run(jsonb,jsonb,jsonb,jsonb) from public, anon, authenticated;
grant execute on function public.dq_commit_predictor_run(jsonb,jsonb,jsonb,jsonb) to service_role;

create function public.dq_pending_predictor_snapshots(p_fixture_keys text[], p_model_version text)
returns setof public.sefirot_december_quest_auto_snapshots
language sql stable security invoker set search_path = '' as $$
  select s.*
  from public.sefirot_december_quest_fixtures f
  cross join lateral (
    select candidate.*
    from public.sefirot_december_quest_auto_snapshots candidate
    where candidate.fixture_key=f.fixture_key and candidate.kickoff=f.kickoff
      and candidate.model_version=p_model_version and candidate.generated_at < candidate.kickoff
    order by candidate.generated_at desc, candidate.id desc
    limit 1
  ) s
  where f.fixture_key=any(p_fixture_keys)
    and cardinality(p_fixture_keys)<=300
    and f.kickoff < statement_timestamp() - interval '3 hours'
    and not exists (
      select 1 from public.sefirot_december_quest_auto_settlements settled
      where settled.fixture_key=f.fixture_key
    );
$$;

revoke all on function public.dq_pending_predictor_snapshots(text[],text) from public, anon, authenticated;
grant execute on function public.dq_pending_predictor_snapshots(text[],text) to service_role;
