"""Run the existing forward collector against a locally verified source ledger."""
from collections import Counter, defaultdict
from contextlib import nullcontext
from datetime import timedelta
from tempfile import TemporaryDirectory

from research.football_pipeline import ingest, packets, source_only
from scripts.chat_sports_probe import collect
from sefirot.contracts import PROFILES, canonical, digest, integer, number, time
from sefirot.football_provider import MAX_PROVIDER_ID, fixture_identity
from sefirot.forward import SHADOW_OPTIONAL_FACTS, _save, capture_plan, create_plan, settle_plan
from sefirot.forward_scorecard import _score, create_scorecard
from sefirot.sports_archive import archive_packets, export_sports

QUEUE = 'prospective-shadow-queue-v1'
STATE = 'prospective-shadow-state-v1'
FETCH = 'prospective-shadow-fetch-v1'
EVALUATION = 'prospective-shadow-evaluation-v1'
BASE = {'decision': 'PASS', 'stake': 0, 'mode': 'SHADOW', 'ev': None,
        'monetary_permission': False, 'execution_enabled': False}


def _jobs(service, schema):
    return [job for job in service.repo.all('jobs') if job.get('schema') == schema]


def _assert_ledgers(service, source_repo):
    if service.repo is source_repo or not service.repo.verify():
        raise ValueError('verified separate shadow and source ledgers required')
    source_only(source_repo)
    # Never attach the worker to an existing operational prediction ledger.
    if service.repo.all('model_routes') or service.repo.all('bets') or service.repo.all('decisions'):
        raise ValueError('dedicated shadow ledger required')


def _view(source_repo, at):
    observations = defaultdict(list)
    originals = {}
    if not source_repo.db.in_transaction:
        source_repo.db.execute('BEGIN')
        transaction = source_repo.db
    else:
        transaction = nullcontext()
    with transaction:
        for record, packet in packets(source_repo, at):
            if packet['receipt']['endpoint'] != '/fixtures':
                continue
            key = digest(packet)
            proof = {'packet_hash': key, 'raw_sha256': record['raw_sha256'],
                     'available_at': record['available_at']}
            current = originals.get(key)
            if current and (time(current[0]['available_at']), current[0]['raw_sha256']) <= (
                    time(proof['available_at']), proof['raw_sha256']):
                continue
            originals[key] = (proof, packet)
    for proof, packet in originals.values():
        for row in packet['data']['response']:
            observations[row['fixture']['id']].append((row, proof, packet))
    for values in observations.values():
        values.sort(key=lambda x: (time(x[2]['receipt']['received_at']), x[1]['packet_hash']))
    return observations, originals


def _latest(observations):
    if not observations:
        return None
    last = observations[-1]
    stamp = time(last[2]['receipt']['received_at'])
    if len({digest(row) for row, _, packet in observations
            if time(packet['receipt']['received_at']) == stamp}) != 1:
        raise ValueError('CONFLICTING_SIMULTANEOUS_FIXTURE')
    return last


def _source_identity(row):
    return [row['league']['id'], row['league']['season'],
            row['teams']['home']['id'], row['teams']['away']['id']]


def _exact(packet, fixture_id):
    params = packet['receipt']['parameters']
    return set(params) == {'id'} and str(params['id']) == str(fixture_id) and len(packet['data']['response']) == 1


def _states(service):
    rows = {}
    for job in _jobs(service, STATE):
        existing = rows.get(job['queue_id'])
        if existing is None or job['step'] > existing['step']:
            rows[job['queue_id']] = job
    return rows


def _state(service, task, previous, status, reason, **fields):
    content = {'queue_id': task['id'], 'fixture_id': task['fixture_id'], 'status': status,
               'reason': reason, **fields}
    if previous and all(previous.get(k) == v for k, v in content.items()):
        return previous
    return _save(service, {'schema': STATE, 'at': service.now(),
                           'step': previous['step'] + 1 if previous else 1, **BASE, **content})


def enqueue(service, source_repo, fixture_id, profile, source_reliability, *,
            synthetic_test_only=False):
    integer(fixture_id, 'fixture ID', 1, MAX_PROVIDER_ID)
    if profile not in PROFILES or profile == 'UNKNOWN':
        raise ValueError('explicit competition profile required')
    number(source_reliability, 'asserted source reliability', 0, 1)
    _assert_ledgers(service, source_repo)
    observations, _ = _view(source_repo, service.now())
    with service.repo.transaction():
        tasks = _jobs(service, QUEUE)
        if any(task['synthetic_test_only'] != synthetic_test_only for task in tasks):
            raise ValueError('test and original observations require different ledgers')
        prior = next((task for task in tasks if task['fixture_id'] == fixture_id), None)
        if prior:
            if (prior['profile'], prior['source_reliability']) != (profile, source_reliability):
                raise ValueError('fixture already queued with different settings')
            return prior
        selected = _latest(observations.get(fixture_id, []))
        if not selected:
            raise ValueError('fixture absent from qualified source archive')
        row, proof, _ = selected
        match = fixture_identity(row)
        at = service.now()
        if row['fixture']['status']['short'] != 'NS' or time(match['kickoff']) <= time(at):
            raise ValueError('future NS fixture required')
        if service.repo.all('predictions', match_id=match['id']):
            raise ValueError('fixture already has an original prediction')
        return _save(service, {'schema': QUEUE, 'at': at, 'fixture_id': fixture_id,
                               'profile': profile, 'source_reliability': source_reliability,
                               'synthetic_test_only': synthetic_test_only, 'match': match,
                               'initial_source': proof, 'source_identity': _source_identity(row), **BASE})


def _preflight(service, archive, fid, profile, reliability, observations, at, expected=None, expected_identity=None):
    def block(status, reason, **detail):
        return {'status': status, 'reason': reason, **detail}, None

    if expected and time(expected['kickoff']) <= time(at):
        return block('REJECTED', 'MISSED_PREMATCH_WINDOW')
    try:
        selected = _latest(observations)
    except ValueError:
        return block('REJECTED', 'CONFLICTING_SIMULTANEOUS_FIXTURE')
    if not selected:
        return block('NEEDS_DATA', 'FIXTURE_UNAVAILABLE')
    row, proof, packet = selected
    match = fixture_identity(row)
    if (row['fixture']['status']['short'] != 'NS' or time(match['kickoff']) <= time(at)
            or (expected and match != expected)
            or (expected_identity and _source_identity(row) != expected_identity)):
        return block('REJECTED', 'FIXTURE_CHANGED', source=proof)
    freshness = timedelta(minutes=service.policy.fact_max_age_minutes)
    if time(at) - time(packet['receipt']['received_at']) > freshness:
        return block('NEEDS_DATA', 'STALE_TARGET_OBSERVATION', source=proof)
    exact = [obs for obs in observations if _exact(obs[2], fid) and digest(obs[0]) == digest(row)
             and time(at) - time(obs[2]['receipt']['received_at']) <= freshness]
    try:
        data = export_sports(archive, fid, at, profile=profile,
                             source_reliability=reliability, policy=service.policy)
    except ValueError:
        return block('REJECTED', 'SOURCE_IDENTITY_OR_CHRONOLOGY', source=proof)
    history = data['coverage']['teams']
    blockers = set(data['coverage']['blockers']) - SHADOW_OPTIONAL_FACTS
    if not exact:
        blockers.add('EXACT_FIXTURE_RECEIPT_REQUIRED')
    if blockers:
        return block('NEEDS_DATA', ', '.join(sorted(blockers)), source=proof, history=history)
    _, selection, original = exact[-1]
    return ({'status': 'QUALIFIED', 'reason': 'SHADOW_DATA_READY', 'source': selection, 'history': history},
            (row, selection, original, data))


def plan_next(service, source_repo, league, profile, source_reliability, *, limit=20, synthetic_test_only=False):
    integer(league, 'league ID', 1, MAX_PROVIDER_ID)
    integer(limit, 'discovery limit', 1, 100)
    if profile not in PROFILES or profile == 'UNKNOWN':
        raise ValueError('explicit competition profile required')
    number(source_reliability, 'asserted source reliability', 0, 1)
    _assert_ledgers(service, source_repo)
    at = service.now()
    observed, originals = _view(source_repo, at)
    selected = None
    reviews = []
    with TemporaryDirectory(prefix='sefirot-shadow-plan-') as archive, service.repo.transaction():
        queued = {t['fixture_id'] for t in _jobs(service, QUEUE)}
        upcoming = sorted((time(values[-1][0]['fixture']['date']), fid)
                          for fid, values in observed.items()
                          if fid not in queued and values[-1][0]['league']['id'] == league
                          and time(values[-1][0]['fixture']['date']) > time(at))
        if upcoming:
            archive_packets([packet for _, packet in originals.values()], archive, at)
        for _, fid in upcoming[:limit]:
            review, admissible = _preflight(service, archive, fid, profile, source_reliability,
                                             observed[fid], at)
            reviews.append({'fixture_id': fid, **review})
            if admissible:
                selected = enqueue(service, source_repo, fid, profile, source_reliability,
                                   synthetic_test_only=synthetic_test_only)
                break
    return {'at': at, 'selected': selected, 'candidates': reviews, 'network_requests': 0, **BASE}


def _capture(service, archive, task, previous, observations, originals, at):
    fid = task['fixture_id']
    review, admissible = _preflight(service, archive, fid, task['profile'], task['source_reliability'],
                                     observations, at, expected=task['match'], expected_identity=task['source_identity'])
    if not admissible:
        return _state(service, task, previous, **review)
    row, selection, original, data = admissible
    if time(task['match']['kickoff']) <= time(service.now()):
        return _state(service, task, previous, 'REJECTED', 'MISSED_PREMATCH_WINDOW')
    # Key the retry to frozen, admitted inputs. A new packet can unblock it.
    fingerprint = digest([selection['packet_hash'], data['receipt']['sports_hash']])
    if previous and previous.get('rejected_input') == fingerprint:
        return previous
    try:
        with service.repo.transaction():
            plan = create_plan(service, original, {row['league']['id']: task['profile']},
                               source_reliability=task['source_reliability'], shadow=True,
                               synthetic_test_only=task['synthetic_test_only'])
            attempt = capture_plan(service, plan['id'], archive)['attempts'][0]
            if attempt['status'] != 'SEALED_RESEARCH':
                raise _CaptureStopped(attempt['status'])
    except _CaptureStopped as exc:
        return _state(service, task, previous, 'NEEDS_DATA', str(exc), source=selection,
                      rejected_input=fingerprint, history=data['coverage']['teams'])
    except (ValueError, ArithmeticError):
        reason = 'MISSED_PREMATCH_WINDOW' if time(task['match']['kickoff']) <= time(service.now()) else 'PLAN_REJECTED'
        return _state(service, task, previous, 'REJECTED', reason, source=selection)
    receipts = {digest(r) for r in attempt['source_receipts']}
    used = [p for p, packet in originals.values() if digest(packet['receipt']) in receipts]
    return _state(service, task, previous, 'AWAITING_FT', 'SHADOW_ONLY',
                  plan_id=plan['id'], prediction_id=attempt['prediction_id'],
                  source=selection, source_cutoff=at, sources=used, history=data['coverage']['teams'],
                  optional_facts_missing=sorted(set(attempt['coverage']['blockers']) & SHADOW_OPTIONAL_FACTS))


class _CaptureStopped(ValueError):
    pass


def _settle(service, task, previous, observations, at):
    if not previous or previous['status'] not in {'AWAITING_FT', 'SETTLED', 'RESULT_REVIEW'}:
        return previous
    if previous['status'] == 'RESULT_REVIEW':
        return previous
    kickoff = time(task['match']['kickoff'])
    bindings = {k: previous[k] for k in ('plan_id', 'prediction_id', 'source', 'source_cutoff', 'sources',
                                         'history', 'optional_facts_missing')}
    changes = [proof for row, proof, _ in observations
               if time(proof['available_at']) > time(previous['source_cutoff'])
               and (fixture_identity(row) != task['match'] or _source_identity(row) != task['source_identity']
                    or row['fixture']['status']['short'] in ('PST', 'CANC', 'ABD', 'AWD', 'WO'))]
    if changes:
        return _state(service, task, previous, 'RESULT_REVIEW', 'SEALED_FIXTURE_CHANGED',
                      disputed_sources=changes, **bindings)
    if time(at) < kickoff + timedelta(minutes=90):
        return previous
    post = [o for o in observations if time(o[2]['receipt']['received_at']) >= kickoff + timedelta(minutes=90)]
    finals = [o for o in post if o[0]['fixture']['status']['short'] == 'FT']
    if not finals:
        return previous
    score_values = {digest(row['score']['fulltime']) for row, _, _ in finals}
    try:
        latest = _latest(post)
        if (latest[0]['fixture']['status']['short'] != 'FT' or len(score_values) != 1
                or any(fixture_identity(row) != task['match'] or _source_identity(row) != task['source_identity']
                       for row, _, _ in finals)):
            raise ValueError('FT revision conflict')
    except ValueError:
        return _state(service, task, previous, 'RESULT_REVIEW', 'FT_REVISED_OR_IDENTITY_CHANGED',
                      disputed_sources=[proof for _, proof, _ in post], **bindings)
    if previous['status'] == 'SETTLED':
        return previous
    exact = [o for o in finals if _exact(o[2], task['fixture_id'])]
    if not exact:
        return _state(service, task, previous, 'AWAITING_FT', 'EXACT_FT_RECEIPT_REQUIRED', **bindings)
    _, proof, packet = exact[0]
    try:
        with service.repo.transaction():
            settle_plan(service, previous['plan_id'], packet)
            card = create_scorecard(service, previous['plan_id'], service.now())
            if card['scored_fixtures'] != 1:
                raise ValueError('scorecard has no verified result')
            evaluation = _save(service, {'schema': EVALUATION, 'at': service.now(), 'queue_id': task['id'],
                                         'result_source': proof, 'scorecard': card, **BASE})
    except ValueError:
        return _state(service, task, previous, 'RESULT_REVIEW', 'FT_OR_SCORECARD_REJECTED', **bindings)
    return _state(service, task, previous, 'SETTLED', 'SCORED_SHADOW', evaluation_id=evaluation['id'],
                  result_source=proof, **bindings)


def run(service, source_repo, stage, *, limit=20):
    integer(limit, 'batch limit', 1, 100)
    if stage not in {'capture', 'settle'}:
        raise ValueError('capture or settle required')
    _assert_ledgers(service, source_repo)
    at = service.now()
    observed, originals = _view(source_repo, at)
    results = []
    with TemporaryDirectory(prefix='sefirot-shadow-') as archive:
        if stage == 'capture' and originals:
            archive_packets([p for _, p in originals.values()], archive, at)
        with service.repo.transaction():
            tasks = sorted(_jobs(service, QUEUE), key=lambda t: (time(t['match']['kickoff']), t['fixture_id']))
            states = _states(service)
            if stage == 'settle':
                eligible = [t for t in tasks if states.get(t['id'], {}).get('status') in ('AWAITING_FT', 'SETTLED')]
                eligible.sort(key=lambda task: states[task['id']]['status'] == 'SETTLED')
            else:
                eligible = [t for t in tasks if states.get(t['id'], {}).get('status') in (None, 'NEEDS_DATA')]
            for task in eligible:
                previous = states.get(task['id'])
                obs = observed.get(task['fixture_id'], [])
                if stage == 'capture':
                    result = _capture(service, archive, task, previous, obs, originals, at)
                else:
                    result = _settle(service, task, previous, obs, at)
                if result and result is not previous:
                    results.append(result)
                    if len(results) == limit:
                        break
    return {'stage': stage, 'at': at, 'processed': results, 'network_requests': 0, **BASE}


def fetch_approved(service, source_repo, params, *, phase, expires_at, approval_id):
    """One gateway probe per operator approval. A lost reply is not retried."""
    _assert_ledgers(service, source_repo)
    at = service.now()
    expiry = time(expires_at)
    if not time(at) < expiry <= time(at) + timedelta(minutes=15):
        raise ValueError('approval must expire within 15 minutes')
    if not isinstance(approval_id, str) or not 1 <= len(approval_id) <= 64 or not approval_id.isascii() or not approval_id.isalnum():
        raise ValueError('bounded alphanumeric approval ID required')
    if phase == 'calendar':
        if set(params) != {'date', 'league', 'season'}:
            raise ValueError('one scoped calendar query required')
    elif phase in ('NS', 'FT'):
        if set(params) != {'id'}:
            raise ValueError('one exact fixture query required')
        task = next((j for j in _jobs(service, QUEUE) if j['fixture_id'] == params['id']), None)
        if not task or task['synthetic_test_only']:
            raise ValueError('queued original fixture required')
        kickoff = time(task['match']['kickoff'])
        saved = _states(service).get(task['id'], {})
        if phase == 'NS' and (not kickoff - timedelta(hours=24) <= time(at) < kickoff
                              or saved.get('status') not in (None, 'NEEDS_DATA')):
            raise ValueError('NS requires an eligible fixture in its last 24 hours')
        if phase == 'FT' and (time(at) < kickoff + timedelta(minutes=90) or saved.get('status') not in ('AWAITING_FT', 'SETTLED')):
            raise ValueError('FT requires a sealed fixture past regulation time')
    else:
        raise ValueError('unknown approval purpose')
    from scripts.chat_sports_probe import _query
    query = {'endpoint': 'fixtures', 'params': params}
    _query(query)
    approval = digest(approval_id)
    with service.repo.transaction():
        if any(j['approval'] == approval for j in _jobs(service, FETCH)):
            raise ValueError('approval already used or interrupted; no automatic retry')
        if time(service.now()) >= expiry:
            raise ValueError('approval expired')
        request = _save(service, {'schema': FETCH, 'at': service.now(), 'approval': approval,
                                  'query': query, 'phase': phase, 'state': 'STARTED', **BASE})

    def persist(packet):
        qc = ingest(source_repo, canonical({k: packet[k] for k in ('data', 'receipt')}).encode(),
                    imported_at=service.now(), origin='DAILY_PROBE')
        if not qc['accepted']:
            raise ValueError('source QC rejected')

    if time(service.now()) >= expiry:
        result = {'status': 'ERROR', 'reason': 'OPERATOR_APPROVAL_EXPIRED'}
    else:
        result = collect({'queries': [query]}, packet_sink=persist)['queries'][0]
    return _save(service, {'schema': FETCH, 'at': service.now(), 'approval': approval,
                           'request_id': request['id'], 'query': query, 'phase': phase,
                           'state': result['status'], 'reason': result.get('reason'),
                           'receipt': result.get('receipt'), **BASE})


def report(service, source_repo, *, upcoming_limit=20):
    _assert_ledgers(service, source_repo)
    at = service.now()
    observed, _ = _view(source_repo, at)
    upcoming = []
    for fid, values in observed.items():
        try:
            selected = _latest(values)
        except ValueError:
            continue
        row, proof, packet = selected
        if row['fixture']['status']['short'] != 'NS' or time(row['fixture']['date']) <= time(at):
            continue
        upcoming.append({'fixture_id': fid, 'match': fixture_identity(row), 'source': proof,
                         'received_at': packet['receipt']['received_at'],
                         'fresh': time(at) - time(packet['receipt']['received_at']) <= timedelta(minutes=service.policy.fact_max_age_minutes),
                         'exact': _exact(packet, fid),
                         'readiness': 'NEEDS_DATA' if time(at) - time(packet['receipt']['received_at'])
                         > timedelta(minutes=service.policy.fact_max_age_minutes) else 'UNASSESSED'})
    upcoming.sort(key=lambda r: (time(r['match']['kickoff']), r['fixture_id']))
    states = _states(service)
    fixtures, groups = [], defaultdict(list)
    scored = set()
    for task in _jobs(service, QUEUE):
        state = states.get(task['id'], {'status': 'NEEDS_DATA', 'reason': 'QUEUED'})
        stage = state['status']
        readiness = ('QUALIFIED' if stage in ('AWAITING_FT', 'SETTLED') else
                     'REJECTED' if stage in ('REJECTED', 'RESULT_REVIEW') else 'NEEDS_DATA')
        fixtures.append({'fixture_id': task['fixture_id'], 'match': task['match'],
                         'status': stage, 'reason': state['reason'], 'readiness': readiness,
                         'test_only': task['synthetic_test_only'], 'seal': state.get('prediction_id'),
                         'source': state.get('source', task['initial_source']), 'history': state.get('history')})
        if stage == 'SETTLED':
            card = service.repo.get('jobs', state['evaluation_id'])['scorecard']
            if not card.get('synthetic_test_only'):
                scored.add(task['fixture_id'])
            for row in card['observations']:
                build = card['frozen_build']
                key = (task['synthetic_test_only'], card['role'], build['code_hash'], build['model_hash'],
                       build['policy_hash'], row['league'], row['competition_profile'], row['market'])
                groups[key].append(row)
    metrics = []
    for key, rows in sorted(groups.items()):
        test, role, build, model, policy, league, profile, market = key
        paired = [r for r in rows if r['history_reference'] is not None]
        metrics.append({'test_only': test, 'role': role, 'build': build, 'model': model, 'policy': policy,
                        'league': league, 'profile': profile, 'market': market, 'fixtures': len(rows),
                        'raw': _score(rows, 'raw'), 'paired_raw': _score(paired, 'raw'),
                        'frozen_history_baseline': _score(paired, 'history_reference')})
    fetches = _jobs(service, FETCH)
    latest = max(enumerate(fetches), key=lambda pair: (time(pair[1]['at']), pair[1]['state'] != 'STARTED', pair[0]))[1] if fetches else None
    budget = {'status': 'NO_CURRENT_RUNTIME_RECEIPT', 'shared_remaining': None}
    if latest:
        budget = {'status': latest.get('reason') or latest['state'], 'observed_at': latest['at'],
                  'last_provider_quota': (latest.get('receipt') or {}).get('quota'),
                  'shared_remaining': None}
    return {'at': at, 'upcoming': upcoming[:upcoming_limit], 'fixtures': fixtures,
            'counts': dict(Counter(row['status'] for row in fixtures)), 'metrics': metrics,
            'scored_original_fixtures': len(scored), 'holdout_passed': False, 'api_budget': budget, **BASE}


def render(report_data):
    lines = ['SEFIROT · SHADOW · PASS · 0', report_data['at'],
             'API budget: ' + report_data['api_budget']['status'],
             'Оценённых оригинальных матчей: ' + str(report_data['scored_original_fixtures'])]
    for row in report_data['fixtures']:
        lines += ['', f"{row['fixture_id']} · {row['match']['home']} — {row['match']['away']}",
                  f"{row['match']['kickoff']} · {row['readiness']} · {row['status']}", row['reason']]
        if row['seal']:
            lines.append('Seal ' + row['seal'])
    lines += ['', 'Ближайшие в архиве']
    lines.extend(f"{row['fixture_id']} · {row['match']['home']} — {row['match']['away']} "
                 f"· {row['match']['kickoff']} · " + ('свежий' if row['fresh'] else 'устарел')
                 for row in report_data['upcoming'])
    lines += ['', 'Brier / log loss · модель / история']
    for metric in report_data['metrics']:
        raw, baseline = metric['paired_raw'], metric['frozen_history_baseline']
        if raw['n'] and baseline['n']:
            lines.append(f"{metric['market']} · n={metric['fixtures']} · "
                         f"{raw['brier']:.4f} / {raw['log_loss']:.4f} · "
                         f"{baseline['brier']:.4f} / {baseline['log_loss']:.4f}"
                         + (' · SYNTHETIC_TEST_ONLY' if metric['test_only'] else ''))
    return '\n'.join(lines)
