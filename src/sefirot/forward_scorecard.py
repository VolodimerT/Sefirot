"""Read-only evaluation of every predeclared fixture; never refit or certify."""
from collections import Counter, defaultdict

from .contracts import digest, integer, time
from .evaluation import metrics, probability_vector
from .football_provider import HOST
from .forward import _plan
from .identity import code_hash, model_code_hash
from .markets import market_of, settle

ORDER = ('WIN', 'PUSH', 'LOSS')


def _receipt(receipt, at, endpoint='/fixtures'):
    return (isinstance(receipt, dict) and receipt.get('provider') == 'API_FOOTBALL_V3'
            and receipt.get('provider_host') == HOST and receipt.get('endpoint') == endpoint
            and receipt.get('sports_only') is True and receipt.get('http_status') == 200
            and time(receipt['request_started_at']) <= time(receipt['received_at']) <= time(at))


def _bound_job(job):
    return job.get('id') == digest({k: v for k, v in job.items() if k != 'id'})


def _history_reference(prediction, market):
    """Laplace counts on the exact history IDs frozen in the original seal."""
    used = prediction['model']['used_history']
    history = prediction['sports']['history']
    by_id = {r['id']: r for r in history}
    if len(by_id) != len(history) or len(set(used)) != len(used) or not set(used) <= by_id.keys():
        raise ValueError('invalid frozen history identity')
    if not used: return None
    counts = [1., 1. if market.push_possible else 0., 1.]
    for rid in used:
        row = by_id[rid]
        if (time(row['kickoff']) >= time(prediction['sports']['as_of']) or
                time(row['received_at']) > time(prediction['sports']['as_of'])):
            raise ValueError('frozen history contains future knowledge')
        counts[ORDER.index(settle(market, row['home_goals'], row['away_goals']))] += 1
    return {'probabilities': [v / sum(counts) for v in counts], 'history_n': len(used),
            'history_ids_hash': digest(used)}


def _forecast_valid(prediction, plan, member, assignment):
    return (prediction.get('id') == digest({k: v for k, v in prediction.items() if k != 'id'})
            and prediction['captured_prematch'] and not prediction['reconstructed']
            and not prediction['synthetic'] and prediction['parent'] is None and prediction['revision'] == 0
            and prediction['code_hash'] == plan['code_hash'] and prediction['model_hash'] == plan['model_hash']
            and prediction['policy_hash'] == plan['policy_hash'] and prediction['sports']['match'] == member['match']
            and prediction['model_id'] == digest([plan['code_hash'], plan['policy_hash'], plan['calibrator_id'], None])
            and prediction.get('goal_model') is None and time(prediction['sports']['as_of']) <= time(prediction['sealed_at'])
            and prediction['market_pool'] == plan['markets']
            and (prediction['calibrator']['hash'] if prediction['calibrator'] else None) == plan['calibrator_id']
            and assignment.get('role') == plan['role'] and assignment.get('at') == plan['at']
            and time(plan['at']) <= time(prediction['sealed_at']) < time(member['match']['kickoff']))


def _score(rows, field):
    selected = [r for r in rows if r.get(field) is not None]
    if not selected: return {'n': 0, 'brier': None, 'log_loss': None, 'ece_macro': None, 'classwise': []}
    return metrics([r[field] for r in selected], [ORDER.index(r['outcome']) for r in selected], bins=10)


def create_scorecard(service, plan_id, at):
    service._time(at)
    plan = _plan(service, plan_id, current=False)
    if time(plan['at']) > time(at): raise ValueError('scorecard cutoff precedes plan')
    if plan['model_hash'] != model_code_hash():
        raise ValueError('scorecard requires compatible archived probability/settlement code')
    repo = service.repo
    jobs = [j for j in repo.all('jobs', at) if j.get('plan_id') == plan_id]
    assignments = {a['match_id']: a for a in repo.all('split_assignments', at)}
    results = {r['match_id']: r for r in repo.all('results', at)}
    capture_proofs = defaultdict(list); result_proofs = defaultdict(list); attempts = defaultdict(list)
    for job in jobs:
        if not _bound_job(job): raise ValueError('forward job identity mismatch')
        if job['schema'] == 'api-forward-capture-v1':
            for attempt in job['attempts']:
                attempts[attempt['match_id']].append((job['at'], job['id'], attempt))
                if attempt['status'] == 'SEALED_RESEARCH': capture_proofs[attempt['prediction_id']].append((attempt, job['at']))
        elif job['schema'] == 'api-forward-result-source-v1':
            if not _receipt(job['receipt'], job['at']): continue
            for result in job['api_results']:
                if (result['source'] == 'API_FOOTBALL_V3:' + job['packet_hash'] and
                        time(result['received_at']) == time(job['receipt']['received_at'])):
                    result_proofs[result['match_id']].append(result)
    fixtures, records = [], []
    for member in plan['members']:
        mid = member['match']['id']; kickoff = member['match']['kickoff']
        predictions = repo.all('predictions', at, match_id=mid)
        row = {'match_id': mid, 'kickoff': kickoff, 'league': member['match']['league'],
               'competition_profile': member['match']['competition_profile'],
               'prediction_id': None, 'status': 'NO_SEAL', 'last_capture_status': None}
        if attempts[mid]: row['last_capture_status'] = max(attempts[mid], key=lambda x: (time(x[0]), x[1]))[2]['status']
        if not predictions:
            if time(at) >= time(kickoff): row['status'] = 'MISSED_PREMATCH_WINDOW'
        elif len(predictions) != 1 or not _forecast_valid(predictions[0], plan, member, assignments.get(mid, {})):
            row['status'] = 'INVALID_OR_REVISED_SEAL'
        else:
            p = predictions[0]; row['prediction_id'] = p['id']
            proof = [a for a, finished in capture_proofs[p['id']] if a.get('sports_hash') == digest(p['sports'])
                     and time(a['at']) <= time(p['sealed_at']) <= time(finished)
                     and a.get('source_receipts') and all(_receipt(r, p['sealed_at']) for r in a['source_receipts'])]
            result = results.get(mid)
            if not proof: row['status'] = 'UNVERIFIED_API_CAPTURE'
            elif result is None: row['status'] = 'AWAITING_RESULT'
            elif result['status'] == 'VOID': row['status'] = 'VOID_NOT_SCORED'
            elif result not in result_proofs[mid]: row['status'] = 'UNVERIFIED_API_RESULT'
            else:
                integer(result['home_goals'], 'FT home goals', 0, 50)
                integer(result['away_goals'], 'FT away goals', 0, 50)
                if not time(kickoff) < time(result['finished_at']) <= time(result['received_at']) <= time(at):
                    raise ValueError('scorecard result chronology')
                expected = {market_of(m).key for m in plan['markets']}
                candidates = p['candidates']
                if len(candidates) != len(expected) or {c['key'] for c in candidates} != expected:
                    raise ValueError('scorecard candidate universe differs from plan')
                for c in candidates:
                    market = market_of(c['market'])
                    if market.key != c['key']: raise ValueError('scorecard contract/key mismatch')
                    raw = probability_vector(c['raw']); base = probability_vector(c['base'])
                    if not market.push_possible and (raw[1] != 0 or base[1] != 0):
                        raise ValueError('impossible scorecard PUSH probability')
                    historical = _history_reference(p, market)
                    records.append({'match_id': mid, 'prediction_id': p['id'], 'league': row['league'],
                                    'competition_profile': row['competition_profile'], 'market': market.key,
                                    'kickoff': kickoff, 'outcome': settle(market, result['home_goals'], result['away_goals']),
                                    'raw': raw, 'base': base, 'calibration_status': c['calibration'],
                                    'neutral': [(1-raw[1])/2, raw[1], (1-raw[1])/2],
                                    'history_reference': historical['probabilities'] if historical else None,
                                    'history_reference_n': historical['history_n'] if historical else 0})
                row['status'] = 'SCORED'; row['source_blockers'] = sorted({i['code'] for i in p['issues'] if i['severity'] == 'BLOCK'})
        fixtures.append(row)
    groups = []
    # Seven contracts from one game remain seven dependent observations, never seven independent matches.
    group_keys = {(r['league'], r['competition_profile'], market_of(m).key) for r in fixtures for m in plan['markets']}
    for league, profile, key in sorted(group_keys):
        selected = [r for r in records if (r['league'], r['competition_profile'], r['market']) == (league, profile, key)]
        denominator = sum((r['league'], r['competition_profile']) == (league, profile) for r in fixtures)
        raw, base, neutral, historical = [_score(selected, field) for field in ('raw', 'base', 'neutral', 'history_reference')]
        paired = [r for r in selected if r['history_reference'] is not None]
        paired_base = _score(paired, 'base')
        groups.append({'league': league, 'competition_profile': profile, 'market': key,
                       'planned_fixtures': denominator, 'scored_fixtures': len(selected),
                       'coverage': len(selected)/denominator,
                       'outcomes': dict(Counter(r['outcome'] for r in selected)),
                       'calibration_status_counts': dict(Counter(r['calibration_status'] for r in selected)),
                       'raw': raw, 'base': base, 'neutral_reference': neutral,
                       'frozen_history_reference': historical,
                       'paired_base_minus_history_brier': paired_base['brier']-historical['brier'] if paired else None,
                       'base_minus_neutral_brier': base['brier']-neutral['brier'] if selected else None,
                       'market_reference': None, 'market_comparison_status': 'NO_BOUND_API_MARKET_REFERENCE'})
    scored = sum(r['status'] == 'SCORED' for r in fixtures)
    output = {'schema': 'forward-scorecard-v1', 'at': at, 'plan_id': plan_id, 'role': plan['role'],
              'frozen_build': {k: plan[k] for k in ('code_hash', 'model_hash', 'policy_hash', 'calibrator_id')},
              'report_code_hash': code_hash(), 'same_current_build': plan['code_hash'] == code_hash(),
              'planned_fixtures': len(fixtures), 'scored_fixtures': scored,
              'fixture_coverage': scored/len(fixtures), 'market_observations': len(records),
              'status_counts': dict(sorted(Counter(r['status'] for r in fixtures).items())),
              'last_capture_status_counts': dict(sorted(Counter(r['last_capture_status'] for r in fixtures if r['last_capture_status']).items())),
              'fixtures': fixtures, 'groups': groups, 'observations': records,
              'status': 'NO_SCORABLE_API_RESULTS' if not scored else 'PARTIAL_RESEARCH_SCORECARD' if scored < len(fixtures) else 'RESEARCH_SCORECARD',
              'outcome_order': list(ORDER), 'brier_normalization': 'half sum squared multiclass errors',
              'reliability_bins': 10, 'history_reference_method': 'Laplace counts on original frozen input history; no refit or result-driven tuning',
              'forecast_provenance': 'Local content-bound forward API capture and FT result jobs; no provider signature or external timestamp',
              'forecasts_recomputed': 0, 'monetary_permission': False, 'execution_enabled': False,
              'holdout_passed': False, 'statistical_profitability_proven': False,
              'limitations': ['Coverage of scored results may be selective; missing fixtures remain in the denominator.',
                              'History climatology describes the supplied snapshot, not complete league strength or professional bookmaker odds.',
                              'Brier/log loss and ECE measure forecast diagnostics, not executable EV or profitability.',
                              'Reliability groups on small samples are noisy; no confidence interval or independent sample count is claimed.',
                              'No market benchmark, Builder validation, or certification gate is supplied by this report.']}
    output['hash'] = digest(output)
    return output


def render_scorecard(report):
    lines = [f"Выборка {report['role']}: оценено {report['scored_fixtures']}/{report['planned_fixtures']} матчей ({report['fixture_coverage']:.1%}).",
             f"Статус: {report['status']}; наблюдений рынков: {report['market_observations']} — они не независимы."]
    if not report['same_current_build']: lines.append('Архивная сборка: сохранённые вероятности прочитаны без пересчёта и переподписи.')
    for group in report['groups']:
        if not group['scored_fixtures']: continue
        lines.append(f"{group['league']} | {group['market']}: n={group['scored_fixtures']}; Brier={group['base']['brier']:.4f}; log loss={group['base']['log_loss']:.4f}.")
    if report['last_capture_status_counts']: lines.append('Последние попытки: '+str(report['last_capture_status_counts']))
    lines.append('Сравнение с линией БК отсутствует. Доходность и holdout не подтверждены; разрешения на ставку нет.')
    return '\n'.join(lines)
