"""Descriptive evidence only. Tactical claims require their own observations."""
from statistics import mean

from sefirot.contracts import time


def profile(report, fixture_id):
    targets = [row for row in report['fixtures'] if row['fixture_id'] == fixture_id
               and row['state'] == 'NS' and time(row['kickoff']) > time(report['as_of'])]
    if len(targets) != 1:
        raise ValueError('UNIQUE_FUTURE_FIXTURE_REQUIRED')
    target = targets[0]
    result = {}
    # Keep the target competition/season and the matching home/away role.
    for side, tid in target['teams'].items():
        same_context = [row for row in report['fixtures'] if row['ft_receipted']
                        and row['fixture_id'] != fixture_id and row['teams'][side] == tid
                        and (row['league'], row['season']) == (target['league'], target['season'])
                        and time(row['kickoff']) < time(report['as_of'])]
        sample = sorted(same_context, key=lambda r: (time(r['kickoff']), r['fixture_id']), reverse=True)[:10]
        opponent = 'away' if side == 'home' else 'home'
        fields = {}
        for label, field, role in (
            ('SHOT_VOLUME', 'SHOTS', side), ('ON_TARGET_VOLUME', 'SOT', side),
            ('POSSESSION', 'POSSESSION', side), ('CHANCE_QUALITY_XG', 'XG', side),
            ('DEFENSIVE_XGA', 'XG', opponent), ('CROSS_VOLUME', 'CROSSES', side)
        ):
            observations = [r['fields'][role][field] for r in sample if r['fields'][role][field] is not None]
            fields[label] = {'sample_n': len(observations), 'denominator': len(sample),
                             'mean': mean(o['value'] for o in observations) if observations else None,
                             'source_ids': sorted({s for o in observations for s in o['source_ids']}),
                             'uncertainty': 'DESCRIPTIVE_UNCALIBRATED' if observations else 'MISSING_EVIDENCE'}
        fields['VENUE_FORM'] = {'sample_n': len(sample), 'wins': sum(
            r['goals'][side] > r['goals'][opponent] for r in sample) if sample else None,
            'source_ids': sorted({s for r in sample for s in r['fixture_sources']}),
            'uncertainty': 'DESCRIPTIVE_UNCALIBRATED' if sample else 'MISSING_EVIDENCE'}
        result[side] = {'team_id': tid, 'evidence': fields}
    return {'as_of': report['as_of'], 'fixture_id': fixture_id, 'venue_split': result,
            'lineup_source_ids': target['lineups'], 'unsupported_hypotheses': {
                 k: 'MISSING_EVENT_LEVEL_EVIDENCE' for k in ('TEMPO','PRESSING','TERRITORY',
                                                           'FLANK_DEPENDENCE','GAME_STATE_SCENARIOS')
            } | {'ABSENCES': 'MISSING_VERIFIED_SQUAD_CONTEXT'},
            'tactical_fit': 'UNVERIFIED', 'decision': 'PASS'}
