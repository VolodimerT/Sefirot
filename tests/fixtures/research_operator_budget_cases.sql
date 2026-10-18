-- SYNTHETIC ONLY: execute exclusively inside a disposable local test database.
-- Never run against Supabase. Clock/counter mutations below are test fixtures.
do $$
declare before_state jsonb;active_until timestamptz;armed jsonb;permit uuid;fault record;
begin
 if (select enabled from sefirot_budget_private.sports_budget where singleton) then raise exception 'INSTALL_AUTO_ARMED';end if;
 if has_function_privilege('service_role','sefirot_budget_private.arm_research_budget(integer,integer)','EXECUTE')
   or has_function_privilege('anon','sefirot_budget_private.arm_research_budget(integer,integer)','EXECUTE')
   or has_function_privilege('authenticated','sefirot_budget_private.arm_research_budget(integer,integer)','EXECUTE') then raise exception 'OPERATOR_ACCESS_DRIFT';end if;
 select to_jsonb(b) into before_state from sefirot_budget_private.sports_budget b;
 for fault in select * from (values(0,12),(6,12),(5,0),(5,13),(null::integer,12),(5,null::integer)) v(calls,minutes) loop
  begin perform sefirot_budget_private.arm_research_budget(fault.calls,fault.minutes);raise exception 'OUTSIDE_BOUNDS_ACCEPTED';
  exception when sqlstate '22023' then null;end;
 end loop;
 if (select to_jsonb(b) from sefirot_budget_private.sports_budget b) is distinct from before_state then raise exception 'REJECT_CHANGED_BUDGET';end if;
 armed=sefirot_budget_private.arm_research_budget(5,12);
 if armed->>'available_calls_cap'<>'5' or armed->>'reserve_day'<>'5'
   or (select remaining_day<>10 or minute_limit<>1 or utc_day<>(clock_timestamp() at time zone 'UTC')::date
     or valid_until>clock_timestamp()+interval '12 minutes' or valid_until<clock_timestamp()+interval '11 minutes'
     from sefirot_budget_private.sports_budget where singleton)
   or (select count(*) from sefirot_budget_private.sports_attempt)<>0 then raise exception 'ARM_CONTRACT_FAILED';end if;
 select valid_until into active_until from sefirot_budget_private.sports_budget where singleton;
 begin perform sefirot_budget_private.arm_research_budget(5,12);raise exception 'ACTIVE_WINDOW_REARMED';
 exception when others then if sqlerrm<>'another research window is already active' then raise;end if;end;
 if (select valid_until from sefirot_budget_private.sports_budget where singleton)<>active_until then raise exception 'WINDOW_CHANGED';end if;
 permit=(public.sefirot_sports_budget_reserve()->>'permit')::uuid;
 if permit is null then raise exception 'FIRST_RESERVE_DENIED';end if;
 perform public.sefirot_sports_budget_finish(permit,'SUCCESS',7500,299,300);
 if public.sefirot_sports_budget_reserve()->>'reason'<>'MINUTE_LIMIT' then raise exception 'MINUTE_GATE_BYPASSED';end if;
 -- Expired local approval may re-arm only the REMAINING daily allowance.
 update sefirot_budget_private.sports_budget set valid_until=clock_timestamp()-interval '1 second';
 armed=sefirot_budget_private.arm_research_budget(5,12);
 if armed->>'available_calls_cap'<>'4' or (select count(*) from sefirot_budget_private.sports_attempt)<>1 then raise exception 'HISTORY_RESET';end if;
 if public.sefirot_sports_budget_reserve()->>'reason'<>'MINUTE_LIMIT' then raise exception 'REARM_BYPASSED_MINUTE';end if;
 insert into sefirot_budget_private.sports_attempt(permit,started_at,finished_at,outcome)
 select gen_random_uuid(),clock_timestamp()-interval '2 minutes',clock_timestamp()-interval '1 minute','SUCCESS' from generate_series(1,4);
 update sefirot_budget_private.sports_budget set valid_until=clock_timestamp()-interval '1 second';
 begin perform sefirot_budget_private.arm_research_budget(5,12);raise exception 'DAILY_CAP_BYPASSED';
 exception when others then if sqlerrm<>'research operator daily allowance exhausted' then raise;end if;end;
 update sefirot_budget_private.sports_budget set enabled=false,in_flight=gen_random_uuid(),reserved_at=clock_timestamp();
 begin perform sefirot_budget_private.arm_research_budget(5,12);raise exception 'INFLIGHT_REARMED';
 exception when others then if sqlerrm<>'cannot re-arm an in-flight provider request' then raise;end if;end;
end $$;
