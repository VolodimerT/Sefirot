-- Owned production-shaped fixture, not an exact production database copy.
-- The existing private queue also permits stake_snapshot: preserve that kind.
alter table sefirot.chat_bridge_jobs drop constraint chat_bridge_jobs_kind_check;
alter table sefirot.chat_bridge_jobs add constraint chat_bridge_jobs_kind_check
 check(kind in ('status','demo','capture','decide','result','report','stake_snapshot','sports_probe'));
create schema sefirot_budget_private;
revoke all on schema sefirot_budget_private from public,anon,authenticated,service_role;
create table sefirot_budget_private.sports_budget(
 singleton boolean primary key, enabled boolean not null, in_flight uuid, reason text);
insert into sefirot_budget_private.sports_budget values(true,false,null,'SYNTHETIC_QUOTA_STOP');
insert into sefirot.chat_bridge_jobs(id,kind,request,status,attempts,completed_at,response)
 values('00000000-0000-0000-0000-000000000070','sports_probe','{}','DONE',1,'2026-10-14T10:00:00Z',
        '{"original_receipt":"SYNTHETIC_PRESERVE_ME","monetary_permission":false}');
