-- Candidate only: deployment is a separate operation. Starts paused.
begin;
create schema sefirot_budget_private;
revoke all on schema sefirot_budget_private from public, anon, authenticated;
grant usage on schema sefirot_budget_private to service_role;

create table sefirot_budget_private.sports_budget (
  singleton boolean primary key default true check (singleton),
  enabled boolean not null default false,
  utc_day date,
  valid_until timestamptz,
  remaining_day bigint not null default 0 check (remaining_day between 0 and 1000000),
  reserve_day integer not null default 5 check (reserve_day between 1 and 1000000),
  minute_limit integer not null default 1 check (minute_limit between 1 and 300),
  minute_ready_at timestamptz not null default 'infinity',
  in_flight uuid,
  reserved_at timestamptz,
  last_started_at timestamptz,
  reason text not null default 'PAUSED',
  check ((in_flight is null) = (reserved_at is null))
);
insert into sefirot_budget_private.sports_budget(singleton) values (true);
create table sefirot_budget_private.sports_attempt (
  permit uuid primary key,
  started_at timestamptz not null,
  finished_at timestamptz,
  outcome text check (outcome in ('SUCCESS', 'FAILURE'))
);
create index sports_attempt_started on sefirot_budget_private.sports_attempt(started_at);
alter table sefirot_budget_private.sports_budget enable row level security;
alter table sefirot_budget_private.sports_attempt enable row level security;
revoke all on all tables in schema sefirot_budget_private from public, anon, authenticated;
grant select, update on sefirot_budget_private.sports_budget to service_role;
grant select, insert, update on sefirot_budget_private.sports_attempt to service_role;

create function public.sefirot_sports_budget_reserve()
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  b sefirot_budget_private.sports_budget%rowtype;
  t timestamptz;
  p uuid;
  count_minute integer;
begin
  select * into b from sefirot_budget_private.sports_budget where singleton for update;
  t := clock_timestamp(); -- AFTER lock acquisition: caller clocks cannot reserve.
  if not found or not b.enabled then
    return jsonb_build_object('allowed', false, 'reason', 'PAUSED');
  end if;
  if b.in_flight is not null then
    if t >= b.reserved_at + interval '30 seconds' then
      update sefirot_budget_private.sports_budget set enabled=false, reason='UNFINISHED_ATTEMPT'
        where singleton;
      return jsonb_build_object('allowed', false, 'reason', 'UNFINISHED_ATTEMPT');
    end if;
    return jsonb_build_object('allowed', false, 'reason', 'BUSY');
  end if;
  if b.utc_day is distinct from (t at time zone 'UTC')::date
      or b.valid_until is null or t >= b.valid_until
      or b.valid_until > t + interval '15 minutes' then
    return jsonb_build_object('allowed', false, 'reason', 'STALE_BUDGET');
  end if;
  if b.remaining_day <= b.reserve_day then
    return jsonb_build_object('allowed', false, 'reason', 'DAILY_LIMIT');
  end if;
  select count(*) into count_minute from sefirot_budget_private.sports_attempt
    where started_at > t - interval '60 seconds';
  if t < b.minute_ready_at or count_minute >= b.minute_limit
      or (b.last_started_at is not null
          and t < b.last_started_at + interval '60 seconds' / b.minute_limit) then
    return jsonb_build_object('allowed', false, 'reason', 'MINUTE_LIMIT');
  end if;
  p := gen_random_uuid();
  insert into sefirot_budget_private.sports_attempt(permit, started_at) values (p,t);
  update sefirot_budget_private.sports_budget set remaining_day=remaining_day-1,
    in_flight=p, reserved_at=t, last_started_at=t, reason='RESERVED' where singleton;
  return jsonb_build_object('allowed', true, 'permit', p);
end;
$$;

create function public.sefirot_sports_budget_finish(
  permit uuid, outcome text, remaining_day bigint, remaining_minute integer)
returns jsonb language plpgsql security invoker set search_path = '' as $$
declare
  b sefirot_budget_private.sports_budget%rowtype;
  t timestamptz;
  success boolean;
begin
  select * into b from sefirot_budget_private.sports_budget where singleton for update;
  t := clock_timestamp();
  if not found or b.in_flight is distinct from permit or permit is null then
    return jsonb_build_object('ok', false);
  end if;
  success := outcome = 'SUCCESS' and remaining_day between 0 and 1000000
    and remaining_minute between 0 and 300;
  success := coalesce(success, false);
  update sefirot_budget_private.sports_attempt set finished_at=t,
    outcome=case when success then 'SUCCESS' else 'FAILURE' end
    where sports_attempt.permit=sefirot_sports_budget_finish.permit;
  update sefirot_budget_private.sports_budget set
    remaining_day=case when success then least(sports_budget.remaining_day,
      sefirot_sports_budget_finish.remaining_day) else sports_budget.remaining_day end,
    enabled=b.enabled and success and b.remaining_day > b.reserve_day
      and sefirot_sports_budget_finish.remaining_day > b.reserve_day
      and sefirot_sports_budget_finish.remaining_minute > 0,
    reason=case when not success then 'CIRCUIT_OPEN'
      when b.remaining_day <= b.reserve_day
        or sefirot_sports_budget_finish.remaining_day <= b.reserve_day
        or sefirot_sports_budget_finish.remaining_minute = 0 then 'QUOTA_STOP'
      else 'READY' end,
    minute_ready_at=greatest(b.minute_ready_at, t + interval '60 seconds' / b.minute_limit),
    in_flight=null, reserved_at=null
    where singleton;
  return jsonb_build_object('ok', true);
end;
$$;
revoke execute on function public.sefirot_sports_budget_reserve() from public, anon, authenticated;
revoke execute on function public.sefirot_sports_budget_finish(uuid,text,bigint,integer) from public, anon, authenticated;
grant execute on function public.sefirot_sports_budget_reserve() to service_role;
grant execute on function public.sefirot_sports_budget_finish(uuid,text,bigint,integer) to service_role;
commit;
