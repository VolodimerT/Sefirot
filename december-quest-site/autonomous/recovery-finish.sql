begin;
create function public.dq_finish_scheduled_predictor(p_token uuid,p_until timestamptz,p_run jsonb,p_forecasts jsonb,p_validation jsonb,p_settlements jsonb)
returns jsonb language plpgsql security invoker set search_path='' set lock_timeout='5s' as $$
declare
  earliest timestamptz;
  result jsonb;
begin
  perform pg_advisory_xact_lock(721735,202612);
  select min((item->>'kickoff')::timestamptz) into earliest from jsonb_array_elements(p_forecasts) item;
  if p_until is null or p_until> (p_run->>'started_at')::timestamptz + interval '10 minutes'
    or clock_timestamp()>=p_until or earliest<=clock_timestamp()+interval '20 minutes' then
    raise exception 'RECOVERY_WINDOW_CLOSED';
  end if;
  result:=public.dq_finish_predictor_run(p_token,p_run,p_forecasts,p_validation,p_settlements);
  if clock_timestamp()>=p_until or earliest<=clock_timestamp()+interval '20 minutes' then
    raise exception 'RECOVERY_WINDOW_CLOSED';
  end if;
  return result;
end;
$$;
revoke all on function public.dq_finish_scheduled_predictor(uuid,timestamptz,jsonb,jsonb,jsonb,jsonb) from public,anon,authenticated;
grant execute on function public.dq_finish_scheduled_predictor(uuid,timestamptz,jsonb,jsonb,jsonb,jsonb) to service_role;
commit;
