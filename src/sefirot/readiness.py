"""Read-only pre-price view of an existing seal, never a new bet decision."""
from .contracts import time
from .decision_card import PRICE_CODES, REASON_TEXT
from .engine import code_hash, decide
from .action_plan import enrich_readiness


def inspect_readiness(service, prediction_id, at):
    service._time(at)
    p = service.repo.get('predictions', prediction_id)
    stamp = time(at)
    if stamp < time(p['sealed_at']):
        raise ValueError('readiness precedes stored probability seal')
    output = {'schema': 'readiness-v1', 'at': at, 'prediction_id': prediction_id,
              'match': p['sports']['match'],
              'identity': {'version': p['version'], 'code_hash': p['code_hash'],
                           'model_hash': p['model_hash'], 'policy_hash': p['policy_hash'],
                           'calibrator_hash': p['calibrator']['hash'] if p['calibrator'] else None},
              'recheck_source': 'SEALED_SNAPSHOT_NOT_NEW_OBSERVATIONS',
              'quotes_read': False, 'monetary_permission': False, 'execution_enabled': False,
              'markets': [], 'quote_recheck_useful': False}
    if stamp >= time(p['sports']['match']['kickoff']):
        return enrich_readiness({**output, 'status': 'PREMATCH_CLOSED',
                'next_action': 'Прематч-окно закрыто; сохранить результат и аудит.'}, p)
    if p['code_hash'] != code_hash() or p['policy_hash'] != service.policy.fingerprint:
        return enrich_readiness({**output, 'status': 'BUILD_MISMATCH',
                'next_action': 'Открыть прогноз его архивной сборкой и политикой; разрешения не переносить.'}, p)
    # Use the original evidence times. This is not a freshly observed lineup or
    # a final recheck. Empty prices cannot create an eligible market or stake.
    recheck = {'checked_at': p['as_of'], 'evidence': p['sports']['evidence']}
    context = service.context(p, at)
    decision = decide(p, [], recheck, at, context, {'bankroll': 0., 'peak': 0.}, service.policy)
    ignored = PRICE_CODES | {'NO_ADMISSIBLE_MAIN_MARKET'}
    for row in decision['decision_card']['alternatives']:
        blockers = sorted(set(row['effective_blockers']) - ignored)
        output['markets'].append({'market': row['market'], 'ready_for_price_recheck': not blockers,
            'probability_trust':row['probability_trust'],
            'blockers': [{'code': c, 'text': REASON_TEXT.get(c, c)} for c in blockers]})
    useful = any(m['ready_for_price_recheck'] for m in output['markets'])
    return enrich_readiness({**output, 'quote_recheck_useful': useful,
            'status': 'READY_FOR_PRICE_RECHECK' if useful else 'BLOCKED_BEFORE_PRICE',
            'next_action': ('Получить свежую цену и настоящую предматчевую перепроверку; затем выполнить decide.'
                            if useful else 'Сначала закрыть указанные блоки; обновление коэффициентов их не устраняет.')}, p)


def render_readiness(view):
    match = view['match']
    lines = [f"{match['home']} — {match['away']}: {view['status']} | {view.get('stage', '')}", view['next_action']]
    for row in view['markets']:
        reason = '; '.join(b['text'] for b in row['blockers']) or 'можно перейти к проверке цены'
        lines.append(f"{row['market']}: {reason}")
    for task in view.get('action_plan', []):
        lines.append(task['category'] + ': ' + task['action'])
    lines.append('Это проверка готовности; разрешения на ставку нет.')
    return '\n'.join(lines)
