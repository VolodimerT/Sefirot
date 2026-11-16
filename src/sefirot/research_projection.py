"""Read-only, price-after-sports projection for a future authenticated client.

This is a data contract, not an HTTP endpoint or a monetary decision service.
It recomputes the existing grid comparison to reject altered source records.
"""
from .market_grid import compare_grid


def match_research_view(grid, prediction, quotes, receipt, policy, at):
    compared = compare_grid(grid, prediction, quotes, policy, at, receipt)
    rows = []
    for row in compared['candidates']:
        rows.append({'market': row['market'], 'key': row['key'],
                     'sports_scenario': row['sports_scenario'],
                     'sport_quality': row['sport_quality'],
                     'price_review': {'status': row['price_status'],
                                      'quotes': row['prices'],
                                      'bet_value': row['bet_value']},
                     'admission': {'class': row['class'],
                                   'verdict': row['decision'],
                                   'reasons': [row['class_reason']],
                                   'stake': 0, 'bet_eligible': False}})
    return {'schema': 'sefirot-readonly-match-research-v1',
            'fixture': grid['match'], 'prediction_id': prediction['id'],
            'at': at, 'source_status': 'SYNTHETIC' if grid['synthetic'] else 'SEALED_RESEARCH',
            'sports_facts': grid['sports_facts'], 'markets': rows,
            'priced_markets': compared['priced_count'],
            'missing_sources': grid['sports_facts']['missing_metrics'],
            'decision': 'PASS', 'monetary_permission': False,
            'execution_enabled': False}
