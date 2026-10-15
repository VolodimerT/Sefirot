-- Runs after upgrade; executed identically by WASM and native PostgreSQL.
create function public.assert_probe_rollout_originals() returns void language plpgsql as $$
begin
 if (select response from sefirot.chat_bridge_jobs where id='00000000-0000-0000-0000-000000000070')
     is distinct from '{"original_receipt":"SYNTHETIC_PRESERVE_ME","monetary_permission":false}'::jsonb
     or (select completed_at from sefirot.chat_bridge_jobs where id='00000000-0000-0000-0000-000000000070')
       is distinct from '2026-10-14T10:00:00Z'::timestamptz then raise exception 'ORIGINAL_CHANGED';end if;
 if (select jsonb_agg(to_jsonb(p)) from sefirot.predictions p)
    is distinct from '[{"id":"canonical-untouched","payload":{"sealed":true}}]'::jsonb then raise exception 'CANONICAL_CHANGED';end if;
 if not exists(select 1 from sefirot_budget_private.sports_budget where singleton=true and enabled=false
    and in_flight is null and reason='SYNTHETIC_QUOTA_STOP') then raise exception 'BUDGET_CHANGED';end if;
end $$;
select public.assert_probe_rollout_originals();
do $$ begin
 if not exists(select 1 from pg_constraint where conrelid='sefirot.chat_bridge_jobs'::regclass
    and conname='chat_bridge_jobs_kind_check' and pg_get_constraintdef(oid) like '%stake_snapshot%') then raise exception 'LOST_STAKE_KIND';end if;
 if to_regclass('sefirot.chat_situation_receipts') is not null then raise exception 'UNRELATED_TABLE_CREATED';end if;
 if has_function_privilege('service_role','sefirot.chat_complete_before_probe_fence(uuid,boolean,jsonb,text)','EXECUTE')
    or has_function_privilege('anon','public.sefirot_probe_complete(uuid,integer,boolean,jsonb,text)','EXECUTE')
    or has_function_privilege('authenticated','public.sefirot_probe_complete(uuid,integer,boolean,jsonb,text)','EXECUTE') then raise exception 'RPC_ACCESS_WIDENED';end if;
end $$;
-- Existing non-probe completion retains the exact original delegate logic.
insert into sefirot.chat_bridge_jobs(id,kind,request,status,attempts)
 values('00000000-0000-0000-0000-000000000073','stake_snapshot','{}','RUNNING',1);
select public.sefirot_chat_complete('00000000-0000-0000-0000-000000000073',true,'{"synthetic_legacy_result":true}',null);
do $$ begin
 if (select status from sefirot.chat_bridge_jobs where id='00000000-0000-0000-0000-000000000073')<>'DONE' then raise exception 'LEGACY_DELEGATE_CHANGED';end if;
end $$;
