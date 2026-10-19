-- REVIEW ONLY. Quiesce scheduler/worker before reverting their matched code.
-- Preserve all archived rows/links and old queue/budget/prediction history.
begin;
set local lock_timeout='3s';
revoke all on function public.sefirot_source_begin(uuid,integer,text,jsonb),public.sefirot_source_append(text,text,uuid,integer),
 public.sefirot_source_export(text),public.sefirot_plan_collection_day(integer,integer)
 from public,anon,authenticated,service_role;
notify pgrst,'reload schema';
commit;
