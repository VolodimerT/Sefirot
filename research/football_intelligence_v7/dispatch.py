"""Single-attempt dispatch from V7 into the existing shared-budget sports probe."""
from datetime import timedelta

from research import football_pipeline as pipeline
from scripts.chat_sports_probe import _query, collect
from sefirot.contracts import canonical, digest, time
from sefirot.football_gateway import transport_status
from .data import inspect

LOCAL_RESERVE = 5


def budget_block(budget, at):
    """Require a fresh read of actual gateway state. Never arm or reset it."""
    now = time(at)
    try:
        if budget['enabled'] is not True:
            return 'SHARED_BUDGET_PAUSED'
        if time(budget['valid_until']) <= now or budget['utc_day'] != now.date().isoformat():
            return 'SHARED_BUDGET_WINDOW_EXPIRED'
        if not now - timedelta(seconds=60) <= time(budget['observed_at']) <= now:
            return 'SHARED_BUDGET_OBSERVATION_STALE'
        if budget['reservation_pending'] is not False:
            return 'SHARED_BUDGET_RESERVATION_PENDING'
        day, reserve = budget['remaining_day'], budget['reserve_day']
        if any(type(v) is not int or v < 0 for v in (day, reserve, budget['started_today'])):
            return 'SHARED_BUDGET_EVIDENCE_INVALID'
        if day <= max(reserve, LOCAL_RESERVE):
            return 'SHARED_BUDGET_DAILY_RESERVE'
        if time(budget['minute_ready_at']) > now:
            return 'SHARED_BUDGET_MINUTE_LIMIT'
    except (ValueError, TypeError, AttributeError, KeyError, OverflowError):
        return 'SHARED_BUDGET_EVIDENCE_UNAVAILABLE'
    return None


def next_plan(repo, scopes, budget, *, at):
    """Read-only handoff using the existing probe request contract."""
    queue = inspect(repo, scopes, as_of=at)['queue']
    items = queue['queries']
    query = {k: items[0][k] for k in ('endpoint', 'params')} if items else None
    if query is not None:
        _query(query)
    return {'as_of': at, 'queue': queue,
            'probe_payload': {'queries': [query]} if query is not None else None,
            'budget_block': budget_block(budget, at),
            'network_started': False, 'decision': 'PASS'}


def _spend(before, after):
    """Observe shared reservations without attributing concurrent traffic to this worker."""
    if not isinstance(after, dict):
        return {'shared_reservations_delta': None, 'attribution': 'POST_OBSERVATION_UNAVAILABLE'}
    start, finish = before['started_today'], after.get('started_today')
    try:
        same_day = before['utc_day'] == after['utc_day']
        ordered = time(before['observed_at']) <= time(after['observed_at'])
    except (KeyError, TypeError, ValueError, AttributeError):
        same_day, ordered = False, False
    if not same_day or not ordered or type(finish) is not int or finish < start:
        return {'shared_reservations_delta': None, 'attribution': 'SHARED_OBSERVATION_MISMATCH'}
    return {'shared_reservations_delta': finish - start, 'attribution': 'SHARED_COUNTER_ALL_WORKERS'}


def dispatch_once(repo, scopes, read_budget, *, approved=False, clock=None,
                  collector=None, transport=None):
    """A guarded operator invocation, never a schedule.

    The caller supplies a read-only observer for the same Gateway budget
    before/after. This observer does not authorize calls; Gateway reserves
    and checks quota independently. A committed intent holds an uncertain
    send until the original archive receipt arrives, with no transport retry.
    """
    clock = clock or pipeline.utcnow
    collector = collector or collect
    transport = transport or transport_status
    scopes = tuple(scopes)
    result = {'decision': 'PASS', 'network_started': False, 'probe_invoked': False,
              'provider_receipts': 0,
              'shared_reservations_delta': None, 'automatic_retry': False}
    if approved is not True:
        return {**result, 'status': 'OPERATOR_APPROVAL_REQUIRED'}
    try:
        before = read_budget()
    except (OSError, RuntimeError, ValueError):
        return {**result, 'status': 'SHARED_BUDGET_EVIDENCE_UNAVAILABLE'}
    now = clock()
    if reason := budget_block(before, now):
        return {**result, 'status': reason}
    state = transport()
    if state.get('transport') != 'SUPABASE_GATEWAY' or state.get('credential_configured') is not True:
        return {**result, 'status': 'PROTECTED_GATEWAY_UNAVAILABLE'}

    with repo.transaction():
        prepared = next_plan(repo, scopes, before, at=clock())
        if reason := budget_block(before, clock()):
            return {**result, 'status': reason}
        payload = prepared['probe_payload']
        if payload is None:
            return {**result, 'status': 'NO_ELIGIBLE_QUERY'}
        at = prepared['as_of']
        attempts = pipeline._records(repo, pipeline.ATTEMPT)
        if any(time(at) - time(row['at']) < timedelta(seconds=61) for row in attempts):
            return {**result, 'status': 'LOCAL_MINUTE_FENCE'}
        query = payload['queries'][0]
        item = prepared['queue']['queries'][0]
        rid = 'football-attempt:' + digest([time(at).date().isoformat(), query])
        intent = {'schema': pipeline.ATTEMPT, 'id': rid, 'at': at, 'query': query,
                  'category': item['category'], 'collection': 'V7_1'}
        if not pipeline._append(repo, intent):
            return {**result, 'status': 'INTENT_ALREADY_PRESENT'}

    receipts = []
    def persist(packet):
        receipt = packet['receipt']
        if (receipt['endpoint'] != '/' + query['endpoint'] or receipt['parameters'] != query['params']
                or time(receipt['received_at']) < time(at)):
            raise ValueError('PROBE_SOURCE_BINDING')
        stored = pipeline.ingest(repo, canonical(packet).encode(), imported_at=clock(), origin='DAILY_PROBE')
        if not stored['accepted']:
            raise ValueError('PROBE_PACKET_QC_REJECTED')
        receipts.append(stored['source_id'])

    status = 'UNCERTAIN_HOLD_FOR_ARCHIVE'
    try:
        response = collector(payload, packet_sink=persist)
        observed = response.get('queries', [])
        if (response.get('shared_budget_required') is True and len(receipts) == 1
                and len(observed) == 1 and observed[0].get('status') == 'DONE'):
            status = 'GATEWAY_RECEIPT_SAVED'
        elif (len(observed) == 1 and not receipts
              and str(observed[0].get('reason', '')).startswith('SHARED_BUDGET_')):
            status = 'GATEWAY_BUDGET_REFUSED'
    except (OSError, RuntimeError, ValueError, KeyError, TypeError, AttributeError):
        # Handle a lost reply without opening a second upstream attempt.
        pass
    try:
        after = read_budget()
    except (OSError, RuntimeError, ValueError):
        after = None
    return {**result, **_spend(before, after), 'status': status, 'probe_invoked': True,
            'network_started': True if receipts or status == 'GATEWAY_BUDGET_REFUSED' else None,
            'intent_id': rid, 'provider_receipts': len(receipts), 'source_ids': receipts}
