"""Offline daily research report over existing archives and immutable CORE seals.

No fitting, seal creation, source fetching, ledger writes or monetary admission.
"""
from contextlib import closing
from copy import deepcopy
from datetime import date, timezone
from hashlib import sha256
from pathlib import Path
import sqlite3

from sefirot.contracts import Policy, digest, time
from sefirot.engine import decide
from sefirot.identity import code_hash, model_code_hash
from sefirot.markets import DEFAULT_POOL, market_of
from sefirot.odds_provider import quotes_from_event
from sefirot.repository import Repository
from sefirot.service import Service
from sefirot.sports_archive import read_archive, export_sports, validate_packet
from sefirot.football_query import validate_fixture_query
from sefirot.football_provider import fixture_identity
from research.referee_yc_shadow import inspect_referee

SMALL = ('CORNERS', 'SHOTS', 'FOULS', 'YELLOW_CARDS')


def calendar_day(packet, day, at):
    """Complete single provider date query, not a handpicked league/fixture list."""
    date.fromisoformat(day)
    validate_packet(packet, at)
    params = packet['receipt']['parameters']
    if params != {'date': day, 'timezone': 'UTC'} and params != {'date': day}:
        raise ValueError('COMPLETE_UTC_DATE_QUERY_REQUIRED')
    validate_fixture_query(packet['data'], params)
    rows = packet['data']['response']
    if any(time(r['fixture']['date']).astimezone(timezone.utc).date().isoformat() != day for r in rows):
        raise ValueError('CALENDAR_DAY_MISMATCH')
    return sorted(rows, key=lambda r: (time(r['fixture']['date']), r['fixture']['id']))


def _empty(key, blockers):
    return {'market': key, 'status': 'PASS', 'blockers': sorted(set(blockers)),
            'model_probability': None, 'push_probability': None, 'loss_probability': None,
            'implied_probability': None, 'fair_odds': None, 'ev': None, 'ev_low': None,
            'odds': None, 'tactical_fit': {'status': 'NOT_PROVEN'},
            'public_trap': {'status': 'NOT_ASSESSED', 'popularity_data': 'NOT_SUPPLIED'},
            'death_test': {'status': 'NOT_PROVEN'}, 'alternative_market': None}


def _identity(row, match):
    identity = fixture_identity(row)
    return (match['id'] == identity['id'] and match['league'] == identity['league']
            and match['home'] == row['teams']['home']['name']
            and match['away'] == row['teams']['away']['name']
            and time(match['kickoff']) == time(row['fixture']['date']))


def _project(row, blockers):
    """Only expose CORE probabilities when ALL its probability proof gates pass."""
    proof = row.get('probability_trust', {})
    components = proof.get('components', {})
    valid = (proof.get('status') == 'EXISTING_GATES_PASSED'
             and components.get('calibration', {}).get('artifact_hash')
             and components.get('holdout', {}).get('status') == 'PASSED_RECORDED_CONTEXT')
    out = _empty(row['market'], blockers + row['effective_blockers'])
    if not valid:
        out['blockers'] = sorted(set(out['blockers'] + ['VALIDATED_PROBABILITY_REQUIRED']))
    else:
        for key in ('model_probability', 'push_probability', 'loss_probability'):
            out[key] = row[key]
    for key in ('tactical_fit', 'public_trap', 'death_test'):
        out[key] = deepcopy(row[key])
    # A saved event is structurally checked by the existing adapter. It does not
    # attest provider origin or availability. Keep implied separate from value.
    if not valid:
        out['death_test'] = {'status': 'VALIDATION_BLOCKED',
            'loss_branches': [{k: branch[k] for k in ('home', 'away') if k in branch}
                              for branch in row['death_test'].get('loss_branches', [])],
            'stress_ev_min': None, 'under_ceiling': None}
    elif blockers or row['effective_blockers']:
        out['death_test']['stress_ev_min'] = None
    if out['public_trap'].get('popularity_data') == 'NOT_SUPPLIED':
        out['public_trap']['status'] = 'NOT_INDEPENDENTLY_ASSESSED'
    out['odds'] = row.get('odds')
    out['implied_probability'] = row.get('implied_probability')
    if valid and not blockers and not row['effective_blockers']:
        for key in ('fair_odds', 'ev', 'ev_low'):
            out[key] = row.get(key)
        if out['ev'] is not None and out['ev'] > 0 and out['ev_low'] is not None and out['ev_low'] > 0:
            out['status'] = 'RESEARCH_CANDIDATE'
        else:
            out['blockers'].append('NO_POSITIVE_ROBUST_VALUE')
    return out


def independent_candidates(fixtures):
    """Conservative independence: no shared fixture/team/league-day cluster."""
    rows = [(f, m) for f in fixtures for m in f['markets']
            if m['status'] == 'RESEARCH_CANDIDATE' and not m['blockers']
            and m['ev'] is not None and m['ev'] > 0 and m['ev_low'] is not None and m['ev_low'] > 0]
    rows.sort(key=lambda v: (-v[1]['ev_low'], -v[1]['ev'], str(v[0]['fixture_id']), v[1]['market']))
    selected, teams, clusters = [], set(), set()
    for fixture, market in rows:
        cluster = (fixture['league_id'], fixture['kickoff'][:10])
        members = set(fixture['team_ids'])
        if members & teams or cluster in clusters:
            market['status'] = 'PASS'
            market['blockers'].append('CORRELATED_CANDIDATE')
            continue
        if len(selected) == 2:
            continue
        selected.append({'fixture_id': fixture['fixture_id'], 'market': market['market'],
                         'ev': market['ev'], 'ev_low': market['ev_low']})
        teams.update(members); clusters.add(cluster)
    return selected


def _sealed_markets(repo, fixture, at, price):
    service = Service(repo, clock=lambda: time(at))
    predictions = [p for p in repo.all('predictions', at)
                   if _identity(fixture, p['sports']['match']) and time(p['sealed_at']) <= time(at)]
    if not predictions:
        raise ValueError('EXACT_PREMATCH_SEAL_REQUIRED')
    prediction = max(predictions, key=lambda p: (time(p['sealed_at']), p['id']))
    if prediction['code_hash'] != code_hash() or prediction['policy_hash'] != service.policy.fingerprint:
        raise ValueError('SEALED_BUILD_MISMATCH')
    if not prediction['captured_prematch'] or time(at) >= time(prediction['sports']['match']['kickoff']):
        raise ValueError('PREMATCH_ONLY')
    # Do not fabricate a lineup/recheck. Reuse the latest stored evidence at cutoff.
    decisions = [d for d in repo.all('decisions', at) if d['prediction_id'] == prediction['id']]
    if not decisions:
        raise ValueError('SAVED_PREMATCH_RECHECK_REQUIRED')
    original = max(decisions, key=lambda d: (time(d['at']), d['id']))
    if not service.replay(original['id'])['matches']:
        raise ValueError('ORIGINAL_REPLAY_FAILED')
    quotes, blockers = [], ['INDEPENDENT_QUOTE_ORIGIN_NOT_ATTESTED']
    if price is not None:
        # No arbitrary probability, tipster input, or pre-normalized quote allowed.
        required = {'event', 'sport', 'event_id', 'bookmaker', 'received_at', 'rules_confirmed', 'market_keys'}
        if not isinstance(price, dict) or set(price) != required:
            raise ValueError('SAVED_PROVIDER_EVENT_REQUIRED')
        if time(price['received_at']) > time(at):
            raise ValueError('FUTURE_QUOTE')
        imported = quotes_from_event(price['event'], prediction, price['sport'], price['event_id'],
            price['bookmaker'], price['received_at'], rules_confirmed=price['rules_confirmed'],
            market_keys=price['market_keys'])
        quotes = imported['quotes']
    else:
        blockers.append('MISSING_CURRENT_PRICE')
    context = service.context(prediction, at)
    result = decide(prediction, quotes, original['inputs']['recheck'], at, context,
                    {'bankroll': 0., 'peak': 0.}, service.policy)
    return [_project(row, blockers) for row in result['decision_card']['alternatives']]


def scan_day(*, calendar, archive, day, at, profile='UNKNOWN', database=None, prices=None,
             synthetic=False):
    time(at)
    report = {'schema': 'daily-prematch-scanner-v0', 'day': day, 'as_of': at,
              'data_label': 'SYNTHETIC_TEST_ONLY' if synthetic else 'SAVED_OFFLINE_NOT_EXTERNALLY_ATTESTED',
              'input_hash': digest(calendar), 'code_hash': code_hash(), 'model_hash': model_code_hash(),
              'scanner_sha256': sha256(Path(__file__).read_bytes()).hexdigest(),
              'calendar_status': 'REJECTED', 'calendar_scope': 'PROVIDER_AVAILABLE_UTC_DAY',
              'worldwide_completeness': 'NOT_ATTESTED', 'decision': 'PASS', 'candidates': [],
              'fixtures': [], 'fixture_counts': {'calendar': None, 'reported': 0, 'prematch': 0, 'excluded_prematch': 0},
              'archive_status': 'NOT_CHECKED', 'blockers': [], 'ledger_status': 'REQUESTED' if database is not None else 'NOT_SUPPLIED',
              'network_requests': 0, 'model_fits': 0, 'ledger_writes': 0,
              'monetary_permission': False, 'execution_enabled': False, 'stake': 0.0}
    try:
        fixtures = calendar_day(calendar, day, at)
    except (ValueError, KeyError, TypeError, OSError) as exc:
        report['blockers'] = ['CALENDAR_INVALID', type(exc).__name__]
        report['report_hash'] = digest(report)
        return report
    report['calendar_status'] = 'STRUCTURALLY_COMPLETE_LOCAL_RECEIPT'
    report['fixture_counts']['calendar'] = len(fixtures)
    prematch = sum(f['fixture']['status']['short'] == 'NS' and time(at) < time(f['fixture']['date'])
                   for f in fixtures)
    report['fixture_counts'].update(prematch=prematch, excluded_prematch=len(fixtures)-prematch)
    try:
        packets = read_archive(archive)
        # A valid calendar remains visible even when the sporting archive fails.
        if not any(digest(p) == digest(calendar) for p in packets):
            raise ValueError('CALENDAR_NOT_IN_ARCHIVE')
    except (ValueError, KeyError, TypeError, OSError):
        report['archive_status'] = 'REJECTED'
        report['blockers'].append('ARCHIVE_UNAVAILABLE_OR_INVALID')
        report['excluded_future_packets'] = None
    else:
        report['archive_status'] = 'VERIFIED_LOCAL_STRUCTURE'
        report['excluded_future_packets'] = sum(time(p['receipt']['received_at']) > time(at) for p in packets)
    if prices is not None and not isinstance(prices, dict):
        report['blockers'].append('PRICES_INPUT_INVALID')
    if database is not None and report['blockers']:
        report['ledger_status'] = 'NOT_READ_INPUT_REJECTED'
    for fixture in fixtures:
        fid = fixture['fixture']['id']
        item = {'fixture_id': fid, 'league_id': fixture['league']['id'],
                'team_ids': [fixture['teams'][s]['id'] for s in ('home', 'away')],
                'home': fixture['teams']['home']['name'], 'away': fixture['teams']['away']['name'],
                'kickoff': fixture['fixture']['date'], 'blockers': list(report['blockers']), 'markets': [], 'coverage': None}
        if fixture['fixture']['status']['short'] != 'NS' or time(at) >= time(item['kickoff']):
            item['blockers'].append('PREMATCH_ONLY')
        elif report['archive_status'] == 'VERIFIED_LOCAL_STRUCTURE':
            try:
                exported = export_sports(archive, fid, at, profile=profile, source_reliability=0.)
                item['coverage'] = exported['coverage']
                item['blockers'].extend(exported['coverage']['blockers'])
                item['sports_hash'] = digest(exported['sports'])
                # Archive source reliability is NOT an external attestation.
                item['blockers'].append('INDEPENDENT_SPORTS_ORIGIN_NOT_ATTESTED')
            except (ValueError, KeyError, TypeError, OSError):
                item['blockers'].append('SPORTS_EXPORT_OR_IDENTITY_FAILED')
        if database is not None and not report['blockers'] and 'PREMATCH_ONLY' not in item['blockers']:
            try:
                if not Path(database).is_file():
                    report['ledger_status'] = 'ABSENT'
                    raise ValueError('LEDGER_ABSENT')
                with closing(Repository(str(database), read_only=True)) as repo:
                    repo.db.execute('BEGIN')
                    try:
                        if not repo.verify():
                            report['ledger_status'] = 'INTEGRITY_FAILED'
                            raise ValueError('JOURNAL_INTEGRITY')
                        report['ledger_status'] = 'HASH_CHAIN_VERIFIED_LOCAL'
                        item['markets'] = _sealed_markets(repo, fixture, at, (prices or {}).get(str(fid)))
                    finally:
                        repo.db.rollback()
            except (ValueError, KeyError, TypeError, OSError, sqlite3.Error) as exc:
                if report['ledger_status'] == 'REQUESTED':
                    report['ledger_status'] = 'UNREADABLE'
                item['blockers'].append(str(exc) if isinstance(exc, ValueError) else 'LEDGER_OR_MODEL_INVALID')
        if not item['markets']:
            item['markets'] = [_empty(market_of(m).key, item['blockers'] +
                ['VALIDATED_PROBABILITY_REQUIRED', 'HISTORY_AND_LINEUP_PROOF_REQUIRED']) for m in DEFAULT_POOL]
        present = {m['market'] for m in item['markets']}
        item['markets'].extend(_empty(market_of(m).key, ['MARKET_NOT_IN_SEALED_POOL'])
                               for m in DEFAULT_POOL if market_of(m).key not in present)
        item['information_status'] = 'BLOCKED' if item['blockers'] else 'EXISTING_DATA_GATES_PASSED'
        # Global data gates also apply to every sealed market.
        for market in item['markets']:
            market['blockers'] = sorted(set(market['blockers'] + item['blockers']))
            if market['blockers']:
                market['status'] = 'PASS'
                market['ev'] = market['ev_low'] = market['fair_odds'] = None
        for market in item['markets']:
            alternatives = [m for m in item['markets'] if m is not market and not m['blockers']
                            and m['status'] == 'RESEARCH_CANDIDATE']
            market['alternative_market'] = alternatives[0]['market'] if alternatives else None
            market['alternative_status'] = 'EXISTING_GATES_PASSED' if alternatives else 'NO_PROVEN_ALTERNATIVE'
        referee = inspect_referee()
        item['small_markets'] = [{**_empty(k, ['SMALL_MODEL_UNVALIDATED']),
                                 'referee_gate': referee if k in ('FOULS', 'YELLOW_CARDS') else {'status': 'NOT_APPLICABLE', 'reason': 'DIRECT_COUNT_MODEL_REQUIRED'}} for k in SMALL]
        report['fixtures'].append(item)
    report['fixture_counts']['reported'] = len(report['fixtures'])
    report['candidates'] = independent_candidates(report['fixtures']) if not synthetic else []
    report['decision'] = 'RESEARCH_SHORTLIST' if report['candidates'] else 'PASS'
    report['report_hash'] = digest(report)
    return report


def render_report(report):
    lines = [f"DAILY REPORT {report['day']} — {report['data_label']}",
             f"{report['decision']} | candidates={len(report['candidates'])} | stake=0",
             f"Calendar: {report['calendar_status']}; worldwide completeness NOT_ATTESTED.",
             f"Fixtures: {report['fixture_counts']}; archive: {report['archive_status']}."]
    for fixture in report['fixtures']:
        lines.append(f"{fixture['fixture_id']}: {fixture['home']} — {fixture['away']}: PASS")
        for row in fixture['markets'] + fixture['small_markets']:
            lines.append(f"  {row['market']}: {row['status']}; P={row['model_probability']}; EV={row['ev']}; " + ', '.join(row['blockers']))
    lines.append('PREMATCH / OFFLINE / monetary_permission=false / execution_enabled=false')
    return '\n'.join(lines) + '\n'
