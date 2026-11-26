-- Additive migration after persist.sql. Apply as a single transaction before switching workers.
begin;
create table public.dq_predictor_leases (
  model_version text not null,
  cycle_started_at timestamptz not null,
  token uuid not null unique,
  started_at timestamptz not null,
  expires_at timestamptz not null,
  primary key (model_version, cycle_started_at)
);
alter table public.dq_predictor_leases enable row level security;
revoke all on public.dq_predictor_leases from public, anon, authenticated, service_role;
grant select, insert, delete on public.dq_predictor_leases to service_role;

create function public.dq_claim_predictor_run(p_model_version text)
returns jsonb language plpgsql security invoker set search_path = '' set lock_timeout = '5s' as $$
declare
  state jsonb;
  started timestamptz := date_trunc('milliseconds', statement_timestamp());
  cycle timestamptz := public.dq_predictor_cycle_start(started);
  owner uuid := gen_random_uuid();
  expiry timestamptz;
begin
  if not pg_try_advisory_xact_lock(721735, 202612) then
    return jsonb_build_object('skipped','RUN_IN_PROGRESS','retry_after_seconds',1);
  end if;
  state := public.dq_predictor_run_state(p_model_version);
  if state->>'recent_success_at' is not null then
    return state || jsonb_build_object('skipped','RECENT_SUCCESS_IN_CYCLE');
  end if;

  delete from public.dq_predictor_leases where expires_at <= started;
  select expires_at into expiry from public.dq_predictor_leases
    where model_version=p_model_version and cycle_started_at=cycle;
  if found then
    return jsonb_build_object('skipped','RUN_IN_PROGRESS','cycle_started_at',cycle,
      'retry_after_seconds',greatest(1,ceil(extract(epoch from expiry-started))));
  end if;
  -- The existing persistence RPC already rejects work older than ten minutes.
  insert into public.dq_predictor_leases values (p_model_version,cycle,owner,started,started+interval '10 minutes');
  return state || jsonb_build_object('token',owner);
end;
$$;

create function public.dq_release_predictor_run(p_token uuid)
returns void language sql security invoker set search_path = '' set lock_timeout = '5s' as $$
  delete from public.dq_predictor_leases where token=p_token;
$$;

create function public.dq_finish_predictor_run(p_token uuid,p_run jsonb,p_forecasts jsonb,p_validation jsonb,p_settlements jsonb)
returns jsonb language plpgsql security invoker set search_path = '' set lock_timeout = '5s' as $$
declare
  result jsonb;
begin
  -- Take the shared commit lock before touching a lease, in the same order as claim.
  perform pg_advisory_xact_lock(721735, 202612);
  -- Lock the lease before writing. Deletion and the existing batch commit roll back together.
  delete from public.dq_predictor_leases where token=p_token and expires_at>clock_timestamp()
    and model_version=p_run->>'model_version' and started_at=(p_run->>'started_at')::timestamptz;
  if not found then raise exception 'PREDICTOR_LEASE_LOST'; end if;
  result := public.dq_commit_predictor_run(p_run,p_forecasts,p_validation,p_settlements);
  return result;
end;
$$;

revoke all on function public.dq_claim_predictor_run(text), public.dq_release_predictor_run(uuid),
  public.dq_finish_predictor_run(uuid,jsonb,jsonb,jsonb,jsonb) from public, anon, authenticated;
grant execute on function public.dq_claim_predictor_run(text), public.dq_release_predictor_run(uuid),
  public.dq_finish_predictor_run(uuid,jsonb,jsonb,jsonb,jsonb) to service_role;
commit;
