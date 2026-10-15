-- Owned synthetic regression cases, shared by PostgreSQL WASM and native CI.
create table public.probe_test_cases(name text primary key);
create function public.probe_expect_rejected(statement text) returns void
language plpgsql as $$
begin
  begin
    execute statement;
  exception when sqlstate '22023' then return;
  end;
  raise exception 'EXPECTED_PROBE_REJECTION';
end $$;
create function public.probe_terminal_no_update() returns trigger language plpgsql as $$
begin raise exception 'TERMINAL_RECEIPT_MUST_NOT_BE_UPDATED';end $$;
do $$
declare
  uid uuid := '00000000-0000-0000-0000-000000000099';
  req_body jsonb := '{"queries":[{"endpoint":"fixtures","params":{"id":123}}]}';
  resp_body jsonb := '{"stage":"SPORTS_API_PROBE","provider":"API_FOOTBALL_V3","mode":"RESEARCH_ONLY","monetary_permission":false,"execution_enabled":false,"automatic_execution":false,"model_calibrated":false,"shared_budget_required":true,"queries":[{"endpoint":"fixtures","params":{"id":123},"status":"DONE","receipt":{"payload_hash":"synthetic-unchanged"}}]}';
  value jsonb; before_time timestamptz; saved jsonb; variant jsonb; field text;
begin
  insert into sefirot.chat_bridge_jobs(id,kind,request,status,attempts)
    values(uid,'sports_probe',req_body,'RUNNING',1);
  perform public.probe_expect_rejected(format('select public.sefirot_chat_complete(%L,true,%L,null)',uid,resp_body));
  insert into public.probe_test_cases values('legacy_probe_bypass_denied');
  value=public.sefirot_probe_complete(uid,1,true,resp_body,null);
  if value<>jsonb_build_object('completed',true,'id',uid,'attempts',1) then raise exception 'WRONG_ACK';end if;
  select completed_at into before_time from sefirot.chat_bridge_jobs where id=uid;
  create trigger probe_terminal_no_update before update on sefirot.chat_bridge_jobs
    for each row when (old.status='DONE') execute function public.probe_terminal_no_update();
  perform public.sefirot_probe_complete(uid,1,true,resp_body,null);
  select response into saved from sefirot.chat_bridge_jobs where id=uid;
  if saved<>resp_body or (select completed_at from sefirot.chat_bridge_jobs where id=uid)<>before_time then
    raise exception 'REPLAY_MUTATED_RECEIPT';end if;
  insert into public.probe_test_cases values('identical_terminal_replay_preserves_original');
  perform public.probe_expect_rejected(format('select public.sefirot_probe_complete(%L,1,true,%L,null)',uid,resp_body||'{"extra":"conflict"}'));
  insert into public.probe_test_cases values('conflicting_terminal_replay_denied');
  drop trigger probe_terminal_no_update on sefirot.chat_bridge_jobs;
  update sefirot.chat_bridge_jobs set status='RUNNING',attempts=2,response=null,completed_at=null where id=uid;
  perform public.probe_expect_rejected(format('select public.sefirot_probe_complete(%L,1,true,%L,null)',uid,resp_body));
  perform public.probe_expect_rejected(format('select public.sefirot_probe_complete(%L,2,true,%L,null)',uid,resp_body));
  value=public.sefirot_probe_complete(uid,2,false,null,'PROVIDER_FETCH_RETRY_REQUIRES_REVIEW');
  perform public.sefirot_probe_complete(uid,2,false,null,'PROVIDER_FETCH_RETRY_REQUIRES_REVIEW');
  if value->>'attempts'<>'2' or (select status from sefirot.chat_bridge_jobs where id=uid)<>'ERROR' then raise exception 'WRONG_RECLAIM';end if;
  insert into public.probe_test_cases values('stale_lease_denied_and_reclaim_has_no_fetch');
  update sefirot.chat_bridge_jobs set status='RUNNING',attempts=1,response=null,error=null where id=uid;
  for field in select unnest(array['stage','provider','mode','monetary_permission','execution_enabled',
    'automatic_execution','model_calibrated','shared_budget_required','queries']) loop
    perform public.probe_expect_rejected(format('select public.sefirot_probe_complete(%L,1,true,%L,null)',uid,resp_body-field));
  end loop;
  for field in select unnest(array['monetary_permission','execution_enabled','automatic_execution','model_calibrated']) loop
    perform public.probe_expect_rejected(format('select public.sefirot_probe_complete(%L,1,true,%L,null)',uid,jsonb_set(resp_body,array[field],'true')));
  end loop;
  perform public.probe_expect_rejected(format('select public.sefirot_probe_complete(%L,1,true,%L,null)',uid,resp_body||jsonb_build_object('oversized',repeat('x',900000))));
  insert into public.probe_test_cases values('missing_fields_financial_flags_and_size_denied');
  for variant in select element from jsonb_array_elements('[[],[{"endpoint":"status","params":{},"status":"DONE"}],[{"endpoint":"fixtures","params":{"id":999},"status":"DONE"}],[{"endpoint":"fixtures","params":{"id":123}}],[{"endpoint":"fixtures","params":{"id":123},"status":"DONE"},{"endpoint":"fixtures","params":{"id":123},"status":"DONE"}]]') as rows(element) loop
    perform public.probe_expect_rejected(format('select public.sefirot_probe_complete(%L,1,true,%L,null)',uid,jsonb_set(resp_body,'{queries}',variant)));
  end loop;
  insert into public.probe_test_cases values('query_identity_shape_and_count_denied');
  update sefirot.chat_bridge_jobs set request=jsonb_set(req_body,'{queries}',(req_body->'queries')||(req_body->'queries')) where id=uid;
  perform public.probe_expect_rejected(format('select public.sefirot_probe_complete(%L,1,true,%L,null)',uid,resp_body));
  perform public.probe_expect_rejected(format('select public.sefirot_probe_complete(%L,1,true,%L,null)',uid,
    jsonb_set(resp_body,'{queries}',jsonb_build_array(jsonb_set(resp_body->'queries'->0,'{status}','"ERROR"'),resp_body->'queries'->0))));
  perform public.sefirot_probe_complete(uid,1,true,jsonb_set(resp_body,'{queries,0,status}','"ERROR"'),null);
  insert into public.probe_test_cases values('partial_batch_requires_terminal_error');
  update sefirot.chat_bridge_jobs set status='RUNNING',request=req_body where id=uid;
  perform public.probe_expect_rejected(format('select public.sefirot_probe_complete(%L,1,false,null,%L)',uid,'ARBITRARY_SECRET'));
  perform public.probe_expect_rejected(format('select public.sefirot_probe_complete(%L,1,false,%L,%L)',uid,resp_body,'RESEARCH_RUNNER_ERROR'));
  perform public.probe_expect_rejected(format('select public.sefirot_probe_complete(%L,null,false,null,%L)',uid,'RESEARCH_RUNNER_ERROR'));
  perform public.probe_expect_rejected(format('select public.sefirot_probe_complete(%L,1,null,null,null)',uid));
  perform public.probe_expect_rejected(format('select public.sefirot_probe_complete(%L,1,false,null,%L)','00000000-0000-0000-0000-000000000098','RESEARCH_RUNNER_ERROR'));
  update sefirot.chat_bridge_jobs set kind='status' where id=uid;
  perform public.probe_expect_rejected(format('select public.sefirot_probe_complete(%L,1,false,null,%L)',uid,'RESEARCH_RUNNER_ERROR'));
  update sefirot.chat_bridge_jobs set kind='sports_probe' where id=uid;
  insert into public.probe_test_cases values('wrong_kind_unknown_job_null_lease_and_error_denied');
end $$;
set role anon;
do $$ begin
  begin perform public.sefirot_probe_complete(null,1,false,null,'RESEARCH_RUNNER_ERROR');
    raise exception 'ANON_EXECUTED';exception when insufficient_privilege then null;end;
end $$;
reset role;
set role authenticated;
do $$ begin
  begin perform public.sefirot_probe_complete(null,1,false,null,'RESEARCH_RUNNER_ERROR');
    raise exception 'AUTHENTICATED_EXECUTED';exception when insufficient_privilege then null;end;
end $$;
reset role;
insert into public.probe_test_cases values('public_roles_denied');
set role service_role;
do $$ begin
  perform public.sefirot_probe_complete('00000000-0000-0000-0000-000000000099',1,false,null,'RESEARCH_RUNNER_ERROR');
  begin perform * from sefirot.chat_bridge_jobs;raise exception 'DIRECT_READ_ALLOWED';
    exception when insufficient_privilege then null;end;
  begin update sefirot.chat_bridge_jobs set attempts=2;raise exception 'DIRECT_WRITE_ALLOWED';
    exception when insufficient_privilege then null;end;
end $$;
reset role;
do $$ begin
  if (select jsonb_agg(to_jsonb(p)) from sefirot.predictions p)<> '[{"id":"canonical-untouched","payload":{"sealed":true}}]'::jsonb then raise exception 'CANONICAL_CHANGED';end if;
  if not (select prosecdef and proconfig=array['search_path=""'] from pg_proc where oid='public.sefirot_probe_complete(uuid,integer,boolean,jsonb,text)'::regprocedure) then raise exception 'UNSAFE_FUNCTION';end if;
end $$;
insert into public.probe_test_cases values('service_rpc_only_and_canonical_unchanged');
