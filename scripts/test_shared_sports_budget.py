"""Exercise the candidate SQL on an isolated LOCAL PostgreSQL database only.

Explicit opt-in, never part of production startup, no provider/network requests.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import subprocess
from threading import Barrier
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DSN = os.environ.get('SEFIROT_TEST_POSTGRES_URL', '')
parsed = urlparse(DSN)
if (parsed.scheme not in ('postgres', 'postgresql')
        or parsed.hostname not in ('127.0.0.1', 'localhost', '::1')
        or parsed.path != '/sefirot_budget_test' or parsed.query or parsed.fragment):
    raise SystemExit('LOCAL_TEST_DATABASE_REQUIRED')


def sql(statement, *, role=None):
    if role:
        statement = 'set role ' + role + '; ' + statement
    result = subprocess.run(['psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1',
                             DSN, '-c', statement], capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise RuntimeError(result.stderr)
    return result.stdout.strip()


def reserve():
    return json.loads(sql('select public.sefirot_sports_budget_reserve();', role='service_role'))


def finish(permit, outcome='SUCCESS', day=90, minute=299, limit=300):
    return json.loads(sql("select public.sefirot_sports_budget_finish('" + permit + "','" +
                          outcome + "'," + str(day) + ',' + str(minute) + ',' + str(limit) + ');', role='service_role'))


def arm(day=100):
    sql('delete from sefirot_budget_private.sports_attempt; '
        'update sefirot_budget_private.sports_budget set enabled=true, '
        "utc_day=(clock_timestamp() at time zone 'UTC')::date, "
        "valid_until=clock_timestamp()+interval '5 minutes', "
        f'remaining_day={day}, reserve_day=5, minute_limit=300, '
        "minute_ready_at=clock_timestamp()-interval '60 seconds', "
        "in_flight=null, reserved_at=null, last_started_at=null, reason='READY';")


def stop(reason):
    value = reserve()
    assert value == {'allowed': False, 'reason': reason}, value


sql("do $$ begin "
    "if not exists(select from pg_roles where rolname='anon') then create role anon; end if; "
    "if not exists(select from pg_roles where rolname='authenticated') then create role authenticated; end if; "
    "if not exists(select from pg_roles where rolname='service_role') then create role service_role bypassrls; end if; "
    "end $$; drop function if exists public.sefirot_sports_budget_reserve(); "
    "drop function if exists public.sefirot_sports_budget_finish(uuid,text,bigint,integer,integer); "
    "drop schema if exists sefirot_budget_private cascade;")
sql((ROOT / 'server/migrations/20261012_shared_sports_budget.sql').read_text())
checks = 0


def check(name, fn):
    global checks
    fn()
    checks += 1
    print('ok ' + name, flush=True)


check('migration starts paused', lambda: stop('PAUSED'))


def permission_checks():
    for role in ('anon', 'authenticated'):
        for statement in ('select public.sefirot_sports_budget_reserve();',
                          'select * from sefirot_budget_private.sports_budget;',
                          "select public.sefirot_sports_budget_finish(null,'SUCCESS',10,10,10);"):
            try:
                sql(statement, role=role)
            except RuntimeError as exc:
                assert 'permission denied' in str(exc)
            else:
                raise AssertionError('unauthorized database access')


check('anon and authenticated cannot read or reserve or finish', permission_checks)


def simultaneous():
    arm(day=6)
    barrier = Barrier(16)
    def caller(_):
        barrier.wait(timeout=10)
        return reserve()
    with ThreadPoolExecutor(max_workers=16) as pool:
        values = list(pool.map(caller, range(16)))
    allowed = [v for v in values if v['allowed']]
    assert len(allowed) == 1, values
    assert all(v['allowed'] or v['reason'] == 'BUSY' for v in values)
    assert sql('select remaining_day from sefirot_budget_private.sports_budget;') == '5'
    assert sql('select count(*) from sefirot_budget_private.sports_attempt;') == '1'
    assert finish(allowed[0]['permit']) == {'ok': True}
    stop('PAUSED')


check('sixteen concurrent runners cannot spend the daily reserve', simultaneous)


def conservative():
    arm()
    p = reserve()['permit']
    assert finish(p, day=1000)['ok']
    assert sql('select remaining_day from sefirot_budget_private.sports_budget;') == '99'
    assert finish(p) == {'ok': False}
    assert finish('00000000-0000-0000-0000-000000000001') == {'ok': False}


check('completion never raises budget and permits cannot be reused', conservative)


def failures():
    for outcome, day, minute in [('FAILURE', 99, 299), ('SUCCESS', 'null', 'null'),
                                  ('SUCCESS', -1, 1), ('SUCCESS', 1000001, 1),
                                  ('SUCCESS', 99, 301), ('SUCCESS', 0, 1),
                                  ('SUCCESS', 99, 0)]:
        arm()
        p = reserve()['permit']
        assert finish(p, outcome, day, minute)['ok']
        stop('PAUSED')
        assert sql('select remaining_day from sefirot_budget_private.sports_budget;') in ('99', '0')


check('unknown failures and exhausted observed quota latch the circuit', failures)


def crashed():
    arm()
    p = reserve()['permit']
    sql("update sefirot_budget_private.sports_budget set reserved_at=clock_timestamp()-interval '31 seconds';")
    stop('UNFINISHED_ATTEMPT')
    stop('PAUSED')
    # A late success can clear the outstanding permit but cannot re-enable a latched circuit.
    assert finish(p)['ok']
    stop('PAUSED')
    assert sql('select remaining_day from sefirot_budget_private.sports_budget;') == '90'


check('crashed runners never refund or auto-reopen after late completion', crashed)


def stale():
    for patch in ("utc_day=utc_day-1", "valid_until=clock_timestamp()-interval '1 second'",
                  'valid_until=null', "valid_until=clock_timestamp()+interval '1 day'"):
        arm()
        sql('update sefirot_budget_private.sports_budget set ' + patch + ';')
        stop('STALE_BUDGET')
        assert sql('select count(*) from sefirot_budget_private.sports_attempt;') == '0'


check('UTC rollover and stale approvals cannot silently reset quota', stale)


def throttle():
    arm()
    p = reserve()['permit']
    assert finish(p)['ok']
    sql("update sefirot_budget_private.sports_budget set minute_limit=1, "
        "last_started_at=clock_timestamp()-interval '59 seconds';")
    stop('MINUTE_LIMIT')
    sql("update sefirot_budget_private.sports_budget set last_started_at=clock_timestamp()-interval '61 seconds', "
        "minute_ready_at=clock_timestamp()-interval '61 seconds';")
    # Sliding window still has the original attempt even if spacing is cleared.
    stop('MINUTE_LIMIT')
    sql("update sefirot_budget_private.sports_attempt set started_at=clock_timestamp()-interval '61 seconds';")
    assert reserve()['allowed']


check('spacing and rolling sixty-second limits apply across runners', throttle)


def cooldown():
    arm()
    sql("update sefirot_budget_private.sports_budget set minute_ready_at=clock_timestamp()+interval '60 seconds';")
    stop('MINUTE_LIMIT')
    arm(day=5)
    stop('DAILY_LIMIT')


check('external-window cooldown and daily reserve block before reservation', cooldown)
def lowered_minute_limit():
    arm()
    p = reserve()['permit']
    assert finish(p, minute=1, limit=1)['ok']
    assert sql('select minute_limit from sefirot_budget_private.sports_budget;') == '1'
    stop('MINUTE_LIMIT')
    arm()
    p = reserve()['permit']
    assert finish(p, minute=2, limit=1)['ok']
    stop('PAUSED')


check('observed minute limit lowers cap and inconsistent counters stop collection', lowered_minute_limit)
def operator_contract():
    # Disposable local DB only, validated by local_probe DSN above. The production
    # operator function itself is unchanged; run its real SQL without provider IO.
    sql('delete from sefirot_budget_private.sports_attempt; '
        "update sefirot_budget_private.sports_budget set enabled=false,in_flight=null,reserved_at=null,"
        "remaining_day=0,reserve_day=5,minute_limit=1,minute_ready_at=clock_timestamp(),"
        "last_started_at=null,valid_until=null,utc_day=null,reason='TEST_ONLY';")
    sql((ROOT/'supabase/migrations/20261015_research_api_budget_operator.sql').read_text())
    sql((ROOT/'tests/fixtures/research_operator_budget_cases.sql').read_text())

check('operator arm enforces five/day twelve minutes one/minute reserve5 without resetting history',operator_contract)
print('SHARED_BUDGET_POSTGRES_PASSED=' + str(checks))
