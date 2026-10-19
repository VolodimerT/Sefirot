"""One fixture, one explicit run; quota-bounded API-Football sports observations.

Never invoked by any worker, scheduler, or betting decision. Credentials stay in
the existing encrypted Vault and authenticated gateway.
"""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import sys
import tempfile
import time as pacing

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sefirot.contracts import canonical, digest, integer, time
from sefirot.football_enrichment import plan_fixture_enrichment, observed_quota
from sefirot.football_gateway import SportsBudgetGateError, get_sports as _get
from sefirot.football_provider import HOST, status_summary, validate_provider_data


def _check_packet(packet, endpoint, params, now, packet_sink=None):
    """Fresh quota evidence is checked after every base and enrichment call."""
    receipt, data = packet.get('receipt', {}), packet.get('data', {})
    if (receipt.get('provider_host') != HOST or receipt.get('provider') != 'API_FOOTBALL_V3'
            or receipt.get('endpoint') != '/' + endpoint or receipt.get('parameters') != params
            or receipt.get('http_status') != 200 or receipt.get('sports_only') is not True
            or receipt.get('payload_hash') != digest(data)
            or time(receipt['received_at']) > now):
        raise ValueError('receipt provenance or timestamp invalid')
    validate_provider_data(endpoint, data)
    # Preserve each successful sports response before quota/identity planning or
    # another request can fail. Account status is deliberately never archived.
    if packet_sink is not None and endpoint != 'status':
        packet_sink(packet)
    return observed_quota(receipt)


def _require_next_call(allowance, reserve, needed=1):
    if allowance['remaining_day'] - reserve < needed or allowance['remaining_minute'] < needed:
        raise ValueError('insufficient quota for next bounded request')


def collect_one(fixture_id, league_id, season, *, max_requests=5, reserve=5,
                getter=None, clock=None, packet_sink=None, pace_requests=False):
    integer(fixture_id, 'fixture id', 1)
    integer(league_id, 'league id', 1)
    integer(season, 'season', 1990, 2200)
    integer(max_requests, 'max requests', 4, 5)
    integer(reserve, 'daily reserve', 5, 1000000)
    if type(pace_requests) is not bool:
        raise ValueError('explicit pacing mode required')
    # The bounded runner must not silently fall back to a direct provider path.
    # Ordinary single-call transports remain compatible; this executor requires
    # the guarded server response on every call. Offline tests inject a getter.
    getter = (lambda endpoint, params: _get(endpoint, params, require_shared_budget=True)) if getter is None else getter
    clock = (lambda: datetime.now(timezone.utc)) if clock is None else clock
    finished = None
    cutoff = None
    def require_prematch():
        if cutoff is not None and clock() >= cutoff:
            raise ValueError('prematch collection after kickoff is forbidden')
    def fetch(endpoint, params):
        nonlocal finished
        require_prematch()
        if pace_requests and finished is not None:
            delay = finished + 61 - pacing.monotonic()
            if delay > 0:
                pacing.sleep(delay)
        # Check after waiting: a schedule delay cannot authorize a call after
        # the selected NS fixture's kickoff. Previous packets remain archived.
        require_prematch()
        packet = getter(endpoint, params)
        finished = pacing.monotonic()
        return packet
    # Status is the sole account probe. Its raw account payload is never stored.
    status = fetch('status', {})
    allowance = _check_packet(status, 'status', {}, clock())
    account = status_summary(status)
    if account.get('subscription_active') is not True:
        raise ValueError('provider subscription not active')
    used = integer(account.get('requests_current'), 'daily usage', 0)
    limit = integer(account.get('requests_limit_day'), 'daily allowance', 1)
    if limit - used - reserve < 2:
        raise ValueError('insufficient quota for base fixture and coverage requests')
    if allowance['limit_day'] != limit:
        raise ValueError('quota status inconsistent')
    _require_next_call(allowance, reserve, needed=2)
    # Even a temporary network failure never triggers an automatic retry.
    fixture = fetch('fixtures', {'id': fixture_id})
    allowance = _check_packet(fixture, 'fixtures', {'id': fixture_id}, clock(), packet_sink)
    matching = [x for x in fixture.get('data', {}).get('response', [])
                if x.get('fixture', {}).get('id') == fixture_id]
    if (len(matching) != 1 or
            matching[0].get('league', {}).get('id') != league_id or
            matching[0].get('league', {}).get('season') != season):
        raise ValueError('fixture/league/season identity mismatch')
    if matching[0]['fixture'].get('status', {}).get('short') == 'NS':
        cutoff = time(matching[0]['fixture']['date'])
    require_prematch()
    _require_next_call(allowance, reserve)
    league = fetch('leagues', {'id': league_id})
    allowance = _check_packet(league, 'leagues', {'id': league_id}, clock(), packet_sink)
    require_prematch()
    plan = plan_fixture_enrichment(
        fixture, league, status, fixture_id, at=clock().isoformat(),
        max_calls=min(max_requests - 3, 8), reserve=reserve,
        spent_since_status=2)
    rows = []
    for item in plan['requested']:
        if allowance['remaining_day'] <= reserve or allowance['remaining_minute'] == 0:
            break
        # Stop on any fresh header: remaining quota beats the earlier plan.
        packet = fetch(item['endpoint'], item['params'])
        allowance = _check_packet(packet, item['endpoint'], item['params'], clock(), packet_sink)
        require_prematch()
        rows.append({'endpoint': item['endpoint'], 'params': item['params'], 'packet': packet})
        if allowance['remaining_day'] <= reserve or allowance['remaining_minute'] == 0:
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


def _archive_packet(packet, directory):
    """Publish one complete, exclusive canonical JSON packet before next fetch."""
    key = digest(packet)
    raw = (canonical(packet) + '\n').encode('utf-8')
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=directory, prefix='.pending-', delete=False) as out:
            temporary = Path(out.name)
            out.write(raw)
            out.flush()
            os.fsync(out.fileno())
        # Publish complete bytes without overwriting an existing packet name.
        os.link(temporary, directory / (key + '.json'))
    finally:
        if temporary is not None:
            temporary.unlink()
    return key


def main(argv=None):
    p = argparse.ArgumentParser(description='Single explicit API-Football research collection')
    p.add_argument('--fixture-id', type=int, required=True)
    p.add_argument('--league-id', type=int, required=True)
    p.add_argument('--season', type=int, required=True)
    p.add_argument('--max-requests', type=int, default=5)
    p.add_argument('--reserve', type=int, default=5)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--execute-single-fixture', action='store_true')
    a = p.parse_args(argv)
    if not a.execute_single_fixture:
        print(json.dumps({'status': 'NOT_EXECUTED', 'reason': 'EXPLICIT_SINGLE_FIXTURE_FLAG_REQUIRED'}))
        return 2
    if os.path.lexists(a.output):
        print(json.dumps({'status': 'NOT_EXECUTED', 'reason': 'OUTPUT_ALREADY_EXISTS'}))
        return 2
    archive = a.output.with_name(a.output.name + '.sources')
    if os.path.lexists(archive):
        print(json.dumps({'status': 'NOT_EXECUTED', 'reason': 'SOURCE_ARCHIVE_ALREADY_EXISTS'}))
        return 2
    archived = []
    try:
        # Reserve this run's directory before any paid/provider operation.
        # A failed run keeps its originals; another run must choose a new name.
        archive.parent.mkdir(parents=True, exist_ok=True)
        archive.mkdir(mode=0o700)
        def persist(packet):
            archived.append(_archive_packet(packet, archive))
        data = collect_one(a.fixture_id, a.league_id, a.season,
                           max_requests=a.max_requests, reserve=a.reserve,
                           pace_requests=True, packet_sink=persist)
        data['source_archive'] = {'format': 'CANONICAL_GATEWAY_JSON',
                                  'packet_hashes': archived,
                                  'original_http_bytes_available': False}
        a.output.parent.mkdir(parents=True, exist_ok=True)
        with a.output.open('x', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write('\n')
        print(json.dumps({'status': data['status'],
                          'requests_consumed_at_most': data['requests_consumed_at_most'],
                          'source_receipts': len(data['observations']) + 2,
                          'archived_source_packets': len(archived),
                          'monetary_permission': False, 'execution_enabled': False}))
        return 0
    except SportsBudgetGateError as exc:
        print(json.dumps({'status': 'COLLECTION_STOPPED', 'reason': exc.code,
                          'archived_source_packets': len(archived),
                          'monetary_permission': False, 'execution_enabled': False}))
        return 2
    except (ValueError, OSError, KeyError, TypeError, OverflowError):
        print(json.dumps({'status': 'COLLECTION_STOPPED',
                          'reason': 'SOURCE_OR_QUOTA_GATE_FAILED',
                          'archived_source_packets': len(archived),
                          'monetary_permission': False, 'execution_enabled': False}))
        return 2


if __name__ == '__main__':
    sys.exit(main())
