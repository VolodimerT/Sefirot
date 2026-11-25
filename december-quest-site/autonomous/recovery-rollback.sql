begin;
do $rollback$
declare
  j record;
  original text;
begin
  select * into strict j from cron.job where jobname='dq-autonomous-dec2026-19kyiv';
  original:=split_part(j.command,'$dq_original$',2);
  if j.schedule<>'0,12,24 17 * * *' or original='' or
    j.command<>('select public.dq_scheduled_predictor($dq_original$'||original||'$dq_original$)') then
    raise exception 'UNEXPECTED_DQ_CRON_CONFIGURATION';
  end if;
  perform cron.alter_job(j.jobid,schedule:='0 17 * * *',command:=original);
end;
$rollback$;
drop function public.dq_scheduled_predictor(text);
drop table public.dq_predictor_dispatch_slots;
drop function public.dq_finish_scheduled_predictor(uuid,timestamptz,jsonb,jsonb,jsonb,jsonb);
commit;
