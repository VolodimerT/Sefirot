"""One fixture, one explicit run; quota-bounded API-Football sports observations.

Never invoked by any worker, scheduler, or betting decision. Credentials stay in
the existing encrypted Vault and authenticated gateway.
"""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sefirot.contracts import digest, integer, time
from sefirot.football_enrichment import plan_fixture_enrichment
from sefirot.football_gateway import get_sports as _get
from sefirot.football_provider import HOST, status_summary


def collect_one(fixture_id, league_id, season, *, max_requests=8, reserve=5,
                getter=None, clock=None):
    integer(fixture_id, 'fixture id', 1)
    integer(league_id, 'league id', 1)
    integer(season, 'season', 1990, 2200)
    integer(max_requests, 'max requests', 4, 11)
    integer(reserve, 'daily reserve', 5, 1000000)
    getter = _get if getter is None else getter
    clock = (lambda: datetime.now(timezone.utc)) if clock is None else clock
    # Status is the sole account probe. Its raw account payload is never stored.
    status = getter('status', {})
    account = status_summary(status)
    if account.get('subscription_active') is not True:
        raise ValueError('provider subscription not active')
    used = integer(account.get('requests_current'), 'daily usage', 0)
    limit = integer(account.get('requests_limit_day'), 'daily allowance', 1)
    if limit - used - reserve < 2:
        raise ValueError('insufficient quota for base fixture and coverage requests')
    minute = status['receipt'].get('quota', {}).get('x-ratelimit-remaining')
    if minute is not None and (not isinstance(minute, str) or not minute.isascii()
                               or not minute.isdecimal() or int(minute) < 2):
        raise ValueError('minute quota insufficient for base calls')
    # Even a temporary network failure never triggers an automatic retry.
    fixture = getter('fixtures', {'id': fixture_id})
    matching = [x for x in fixture.get('data', {}).get('response', [])
                if x.get('fixture', {}).get('id') == fixture_id]
    if (len(matching) != 1 or
            matching[0].get('league', {}).get('id') != league_id or
            matching[0].get('league', {}).get('season') != season):
        raise ValueError('fixture/league/season identity mismatch')
    league = getter('leagues', {'id': league_id})
    plan = plan_fixture_enrichment(
        fixture, league, status, fixture_id, at=clock().isoformat(),
        max_calls=min(max_requests - 3, 8), reserve=reserve,
        spent_since_status=2)
    rows = []
    for item in plan['requested']:
        # Stop on any fresh header: remaining quota beats the earlier plan.
        packet = getter(item['endpoint'], item['params'])
        receipt = packet.get('receipt', {})
        data = packet.get('data', {})
        if (receipt.get('provider_host') != HOST or
                receipt.get('provider') != 'API_FOOTBALL_V3' or
                receipt.get('endpoint') != '/' + item['endpoint'] or
                receipt.get('parameters') != item['params'] or
                receipt.get('sports_only') is not True or
                receipt.get('payload_hash') != digest(data) or
                data.get('errors') not in ([], {}) or
                (data.get('paging', {}).get('total', 1) > 1) or
                time(receipt['received_at']) > clock()):
            raise ValueError('enrichment receipt provenance or timestamp invalid')
        rows.append({'endpoint': item['endpoint'], 'params': item['params'], 'packet': packet})
        headers = receipt.get('quota', {})
        d = headers.get('x-ratelimit-requests-remaining')
        m = headers.get('x-ratelimit-remaining')
        if ((d is not None and d.isdecimal() and int(d) <= reserve) or
                (m is not None and m.isdecimal() and int(m) == 0)):
            break
    return {
        'schema': 'sefirot-enrichment-capture-v1', 'fixture_id': fixture_id,
        'league_id': league_id, 'season': season,
        'plan': plan, 'base_packets': [{'endpoint': 'fixtures', 'packet': fixture},
                                      {'endpoint': 'leagues', 'packet': league}],
        'observations': rows,
        'status': 'COMPLETE_BOUNDED_RESEARCH_OBSERVATIONS'
             if len(rows) == len(plan['requested']) else 'PARTIAL_QUOTA_STOP',
        'requests_consumed_at_most': 3 + len(rows),
        'account_status': 'SUBSCRIPTION_ACTIVE',
        'raw_account_status_saved': False,
        'monetary_permission': False, 'execution_enabled': False,
        'model_updated': False,
    }


def main(argv=None):
    p = argparse.ArgumentParser(description='Single explicit API-Football research collection')
    p.add_argument('--fixture-id', type=int, required=True)
    p.add_argument('--league-id', type=int, required=True)
    p.add_argument('--season', type=int, required=True)
    p.add_argument('--max-requests', type=int, default=8)
    p.add_argument('--reserve', type=int, default=5)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--execute-single-fixture', action='store_true')
    a = p.parse_args(argv)
    if not a.execute_single_fixture:
        print(json.dumps({'status': 'NOT_EXECUTED', 'reason': 'EXPLICIT_SINGLE_FIXTURE_FLAG_REQUIRED'}))
        return 2
    if a.output.exists():
        print(json.dumps({'status': 'NOT_EXECUTED', 'reason': 'OUTPUT_ALREADY_EXISTS'}))
        return 2
    try:
        data = collect_one(a.fixture_id, a.league_id, a.season,
                           max_requests=a.max_requests, reserve=a.reserve)
        a.output.parent.mkdir(parents=True, exist_ok=True)
        with a.output.open('x', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write('\n')
        print(json.dumps({'status': data['status'],
                          'requests_consumed_at_most': data['requests_consumed_at_most'],
                          'source_receipts': len(data['observations']) + 2,
                          'monetary_permission': False, 'execution_enabled': False}))
        return 0
    except (ValueError, OSError, KeyError, TypeError, OverflowError):
        print(json.dumps({'status': 'COLLECTION_STOPPED',
                          'reason': 'SOURCE_OR_QUOTA_GATE_FAILED',
                          'monetary_permission': False, 'execution_enabled': False}))
        return 2


if __name__ == '__main__':
    sys.exit(main())
