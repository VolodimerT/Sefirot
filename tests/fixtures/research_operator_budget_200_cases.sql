-- SYNTHETIC ONLY. Disposable PGlite/PostgreSQL test DB, never production.
-- Run AFTER original operator fixture and a synthetic idle/reset of its in-flight token.
do $$
declare
  before_attempts integer;
  armed jsonb;
  permit uuid;
  denial jsonb;
  fault record;
begin
  select count(*) into before_attempts from sefirot_budget_private.sports_attempt;
  if before_attempts<>5 then raise exception 'SYNTHETIC_BASELINE_DRIFT';end if;
  if has_function_privilege('service_role','sefirot_budget_private.arm_research_budget(integer,integer)','EXECUTE')
     or has_function_privilege('anon','sefirot_budget_private.arm_research_budget(integer,integer)','EXECUTE')
     or has_function_privilege('authenticated','sefirot_budget_private.arm_research_budget(integer,integer)','EXECUTE') then
    raise exception 'RESEARCH_OWNER_ACL_DRIFT';
  end if;
  for fault in select * from (values
    (0,12),(201,12),(200,0),(200,13),(null::integer,12),(200,null::integer)
  ) v(calls,minutes) loop
    begin
      perform sefirot_budget_private.arm_research_budget(fault.calls,fault.minutes);
      raise exception 'EXPANDED_BOUND_ACCEPTED';
    exception when sqlstate '22023' then null;
    end;
  end loop;
  armed=sefirot_budget_private.arm_research_budget(200,12);
  if armed->>'available_calls_cap'<>'60' or armed->>'daily_call_cap'<>'200'
     or armed->>'daily_calls_used'<>'5' or armed->>'reserve_day'<>'100'
     or armed->>'rate_limit_per_minute'<>'5' or armed->>'money_authorized'<>'false'
     or (select remaining_day<>160 or reserve_day<>100 or minute_limit<>5
         from sefirot_budget_private.sports_budget where singleton)
     or (select count(*) from sefirot_budget_private.sports_attempt)<>5 then
     raise exception 'EXPANDED_RESEARCH_CONTRACT_FAILED';
  end if;
  begin
    perform sefirot_budget_private.arm_research_budget(1,1);
    raise exception 'ACTIVE_APPROVAL_OVERWRITTEN';
  exception when others then
    if sqlerrm<>'another research window is already active' then raise;end if;
  end;
  denial=public.sefirot_sports_budget_reserve();
  permit=(denial->>'permit')::uuid;
  if permit is null or denial->>'allowed'<>'true' then
    raise exception 'EXPANDED_FIRST_REQUEST_DENIED';
  end if;
  perform public.sefirot_sports_budget_finish(permit,'SUCCESS',7499,299,300);
  denial=public.sefirot_sports_budget_reserve();
  if denial->>'reason'<>'MINUTE_LIMIT' then raise exception 'FIVE_PER_MINUTE_GATE_BYPASSED';end if;

  -- Fill attempt history to the 200/day ceiling using synthetic rows.
  insert into sefirot_budget_private.sports_attempt(permit,started_at,finished_at,outcome)
    select gen_random_uuid(),clock_timestamp()-interval '3 minutes',
           clock_timestamp()-interval '2 minutes','SUCCESS'
      from generate_series(1,194);
  update sefirot_budget_private.sports_budget set
      remaining_day=150,minute_ready_at=clock_timestamp()-interval '2 minutes',
      last_started_at=clock_timestamp()-interval '2 minutes'
    where singleton;
  denial=public.sefirot_sports_budget_reserve();
  if denial->>'reason'<>'DAILY_LIMIT'
     or (select count(*) from sefirot_budget_private.sports_attempt)<>200 then
    raise exception 'HARD_200_DAY_GATE_BYPASSED';
  end if;
  update sefirot_budget_private.sports_budget set
      valid_until=clock_timestamp()-interval '1 second' where singleton;
  begin
    perform sefirot_budget_private.arm_research_budget(200,12);
    raise exception '200_DAY_REARM_BYPASSED';
  exception when others then
    if sqlerrm<>'research operator daily allowance exhausted' then raise;end if;
  end;
  if (select count(*) from sefirot_budget_private.sports_attempt)<>200 then
    raise exception 'ATTEMPT_HISTORY_RESET';
  end if;
end $$;
