"""Batch view of existing seals; no price fetching or new betting authority."""
from collections import Counter
from .contracts import digest, integer, time
from .readiness import inspect_readiness


def inspect_session(service, at, prediction_ids=None, limit=200):
    service._time(at)
    integer(limit, 'session limit', 1, 1000)
    if not service.repo.verify():
        raise ValueError('journal integrity failed')
    closed = 0
    if prediction_ids is not None:
        if (not isinstance(prediction_ids, list) or not prediction_ids
                or len(prediction_ids) > limit or len(set(prediction_ids)) != len(prediction_ids)):
            raise ValueError('bounded unique prediction ids required')
        predictions = [service.repo.get('predictions', pid) for pid in prediction_ids]
    else:
        # Latest observed seal per fixture; no ranking by prices or known results.
        newest = {}
        for p in service.repo.all('predictions', at):
            mid = p['sports']['match']['id']
            if mid not in newest or (time(p['sealed_at']), p['revision'], p['id']) > (
                    time(newest[mid]['sealed_at']), newest[mid]['revision'], newest[mid]['id']):
                newest[mid] = p
        predictions = [p for p in newest.values() if time(p['sports']['match']['kickoff']) > time(at)]
        closed = len(newest) - len(predictions)
    predictions.sort(key=lambda p: (time(p['sports']['match']['kickoff']), p['id']))
    total = len(predictions)
    rows = [inspect_readiness(service, p['id'], at) for p in predictions[:limit]]
    blockers = Counter()
    for row in rows:
        blockers.update({b['code'] for market in row['markets'] for b in market['blockers']})
    output = {'schema': 'session-readiness-v1', 'at': at,
              'status': 'EMPTY' if not rows else 'READ_ONLY_PREPRICE_REVIEW',
              'scope': 'EXPLICIT_SEALS' if prediction_ids is not None else 'LATEST_SEAL_PER_FIXTURE',
              'predictions_in_scope': total, 'closed_fixtures_excluded': closed,
              'shown': len(rows), 'truncated': total > limit,
              'status_counts': dict(sorted(Counter(r['status'] for r in rows).items())),
              'blocker_match_counts': dict(sorted(blockers.items())),
              'price_recheck_prediction_ids': [r['prediction_id'] for r in rows if r['quote_recheck_useful']],
              'rows': rows, 'new_prices_read': False, 'forecasts_created': 0,
              'monetary_permission': False, 'execution_enabled': False}
    output['hash'] = digest(output)
    return output


def render_session(view):
    lines = [f"Сессия: {view['shown']} прогнозов; готовы к проверке цены: {len(view['price_recheck_prediction_ids'])}."]
    for row in view['rows']:
        match = row['match']
        codes = sorted({b['code'] for market in row['markets'] for b in market['blockers']})
        lines.append(f"{match['home']} — {match['away']}: {row['status']}" +
                     ('; ' + ', '.join(codes) if codes else ''))
    if view['truncated']:
        lines.append('Показана только часть сессии; расширьте limit или задайте ID.')
    lines.append('Новых цен и прогнозов нет. Разрешения на ставку нет.')
    return '\n'.join(lines)
