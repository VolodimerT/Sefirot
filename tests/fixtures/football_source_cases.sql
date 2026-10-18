-- Owned PostgreSQL assertions shared by native CI; all rows synthetic.
do $$
declare uid uuid:='00000000-0000-0000-0000-000000000088';p jsonb;r text;h text;before_budget jsonb;ack jsonb;
begin
 select to_jsonb(b) into before_budget from sefirot_budget_private.sports_budget b;
 if (public.sefirot_source_status()->>'ready')::boolean then raise exception 'EXPECTED_PARKED';end if;
 insert into sefirot.chat_bridge_jobs(id,kind,request,status,attempts,submitted_at)
 values(uid,'sports_probe','{"queries":[{"endpoint":"fixtures","params":{"league":39,"season":2026}}]}','ERROR',1,'2026-01-01Z');
 p='{"data":{"get":"fixtures","parameters":{"league":"39","season":"2026"},"errors":[],"results":0,"paging":{"current":1,"total":1},"response":[]},"receipt":{"provider":"API_FOOTBALL_V3","provider_host":"v3.football.api-sports.io","transport":"SUPABASE_GATEWAY","endpoint":"/fixtures","parameters":{"league":39,"season":2026},"sports_only":true,"http_status":200,"request_started_at":"2026-02-01Z","upstream_received_at":"2026-02-01Z","received_at":"2026-02-01Z","payload_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}}';
 r=p::text;h=encode(sha256(convert_to(r,'UTF8')),'hex');
 ack=public.sefirot_source_append(r,h,uid,1);
 if ack is distinct from public.sefirot_source_append(r,h,uid,1) or (select count(*) from sefirot.sports_archive)<>1 then raise exception 'IDEMPOTENCE_FAILED';end if;
 if public.sefirot_source_export('')->>'raw_source' is distinct from r then raise exception 'ORIGINAL_BYTES_CHANGED';end if;
 begin perform public.sefirot_source_append(r,h,uid,2);raise exception 'ACCEPTED_WRONG_ATTEMPT';
 exception when others then if sqlerrm<>'SOURCE_JOB_BINDING_REQUIRED' then raise;end if;end;
 begin
  r=jsonb_set(p,'{receipt,quota}','{"A P I K E Y":"SYNTHETIC_PRIVATE"}')::text;
  perform public.sefirot_source_append(r,encode(sha256(convert_to(r,'UTF8')),'hex'),uid,1);
  raise exception 'UNSAFE_LABEL_ACCEPTED';
 exception when others then if sqlerrm<>'SOURCE_UNSAFE_JSON_KEY' then raise;end if;end;
 begin delete from sefirot.sports_archive;raise exception 'ACCEPTED_DELETE';
 exception when others then if sqlerrm<>'SOURCE_ARCHIVE_IMMUTABLE' then raise;end if;end;
 if has_table_privilege('service_role','sefirot.sports_archive','SELECT')
  or has_function_privilege('anon','public.sefirot_source_append(text,text,uuid,integer)','EXECUTE')
  or has_function_privilege('service_role','public.sefirot_plan_collection_day(integer,integer)','EXECUTE') then raise exception 'PRIVATE_ACCESS_DRIFT';end if;
 update sefirot.chat_bridge_jobs set status='RUNNING' where chat_bridge_jobs.id=uid;
 if public.sefirot_source_begin(uid,1,'fixtures','{"league":39,"season":2026}')->>'authorized'<>'true' then raise exception 'DISPATCH_DENIED';end if;
 begin perform public.sefirot_source_begin(uid,1,'fixtures','{"league":39,"season":2026}');raise exception 'DUPLICATE_FETCH_ALLOWED';
 exception when others then if sqlerrm<>'SOURCE_DISPATCH_ALREADY_ATTEMPTED' then raise;end if;end;
 insert into sefirot_budget_private.sports_attempt select clock_timestamp() from generate_series(1,5);
 if public.sefirot_plan_collection_day(39,2026)->>'reason'<>'DAILY_FIVE_ATTEMPT_CAP' then raise exception 'DAILY_CAP_FAILED';end if;
 if (select to_jsonb(b) from sefirot_budget_private.sports_budget b) is distinct from before_budget then raise exception 'BUDGET_MUTATED';end if;
end $$;
