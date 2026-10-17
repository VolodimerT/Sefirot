"""Unattested count sanity preview, never fitted probability or source admission."""
METRICS = ('CORNERS', 'SHOTS', 'SOT', 'FOULS', 'YELLOW_CARDS', 'RED_CARDS', 'BOOKING_POINTS')
COUNT_FIELDS = ('shots', 'sot', 'corners_ft', 'corners_1h', 'fouls_committed',
                'yellow_cards', 'red_cards', 'booking_points')
REQUIRED_COUNT = dict(zip(METRICS, ('corners_ft', 'shots', 'sot', 'fouls_committed',
                                  'yellow_cards', 'red_cards', 'booking_points')))


def preview(data):
    if not isinstance(data, dict) or set(data) != {'metric', 'period', 'counts'}:
        raise ValueError('EXACT_SMALL_READINESS_FIELDS_REQUIRED')
    if data['metric'] not in METRICS or data['period'] not in ('FT', '1H', '2H'):
        raise ValueError('UNSUPPORTED_METRIC_OR_PERIOD')
    counts = data['counts']
    if not isinstance(counts, dict) or set(counts) != set(COUNT_FIELDS):
        raise ValueError('EXPLICIT_NULLABLE_COUNTS_REQUIRED')
    if any(v is not None and (type(v) is not int or not 0 <= v <= 10000) for v in counts.values()):
        raise ValueError('INTEGER_COUNTS_OR_NULL_REQUIRED')
    contradictions = []
    if counts['shots'] is not None and counts['sot'] is not None and counts['sot'] > counts['shots']:
        contradictions.append('SOT_EXCEEDS_SHOTS')
    if (counts['corners_1h'] is not None and counts['corners_ft'] is not None
            and counts['corners_1h'] > counts['corners_ft']):
        contradictions.append('HALF_CORNERS_EXCEED_FT')
    required = REQUIRED_COUNT[data['metric']]
    # This preview has only explicit FT/1H corner fields. A different period
    # must not borrow the FT count; period-aware observations are Step B.
    if data['metric'] == 'CORNERS' and data['period'] == '1H': required = 'corners_1h'
    missing = [required] if counts[required] is None else []
    blockers = ['SOURCE_ORIGIN_NOT_ATTESTED', 'FULL_LEAGUE_COVERAGE_NOT_ATTESTED',
                'SETTLEMENT_NOT_ATTESTED', 'SMALL_MARKET_MODEL_UNVALIDATED',
                'NO_INDEPENDENT_HOLDOUT']
    if data['period'] != 'FT' and not (data['metric'] == 'CORNERS' and data['period'] == '1H'):
        blockers.append('PERIOD_COUNT_NOT_AVAILABLE')
    if data['metric'] in ('YELLOW_CARDS', 'RED_CARDS', 'BOOKING_POINTS'):
        blockers.append('REFEREE_NOT_ATTESTED')
    if missing: blockers.append('METRIC_COUNT_MISSING')
    return {'schema': 'small-market-readiness-preview-v1',
            'metric': data['metric'], 'period': data['period'],
            'status': 'QUARANTINED' if contradictions else 'INSUFFICIENT_REAL_DATA',
            'missing_counts': missing, 'blockers': sorted(blockers + contradictions),
            'source_attested': False, 'fit_allowed': False, 'probability': None, 'ev': None,
            'monetary_permission': False}
