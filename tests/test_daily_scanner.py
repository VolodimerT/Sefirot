"""Owned synthetic regressions; never provider or production calls."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

from sefirot.contracts import digest
from sefirot.sports_archive import archive_packets
from research.daily_scanner import scan_day, calendar_day, independent_candidates, _project
from research.prematch_scenario import run_scenario

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tests/fixtures/prematch_issue59_source_v2/source.json'


def synthetic_inputs():
    source = json.loads(SOURCE.read_text(encoding='utf-8'))
    calendar = deepcopy(source['packets'][0])
    calendar['receipt']['parameters'] = {'date': '2030-01-01', 'timezone': 'UTC'}
    calendar['data']['parameters'] = dict(calendar['receipt']['parameters'])
    calendar['receipt']['payload_hash'] = digest(calendar['data'])
    return source, calendar


def projection(*, proof=True, ev=.1):
    return {'market': 'TOTAL:OVER:2.5', 'effective_blockers': [],
            'probability_trust': {'status': 'EXISTING_GATES_PASSED' if proof else 'BLOCKED',
                'components': {'calibration': {'artifact_hash': 'a'*64},
                               'holdout': {'status': 'PASSED_RECORDED_CONTEXT'}}},
            'model_probability': .6, 'push_probability': 0., 'loss_probability': .4,
            'odds': 2., 'implied_probability': .5, 'fair_odds': 1/.6, 'ev': ev, 'ev_low': ev,
            'tactical_fit': {}, 'public_trap': {}, 'death_test': {}}


class DailyScannerTests(unittest.TestCase):
    def scan(self, mutate=None, *, extra=None, database=None):
        source, calendar = synthetic_inputs()
        if mutate:
            mutate(calendar)
        with TemporaryDirectory() as tmp:
            archive_packets(source['packets'] + [calendar] + (extra or []), tmp, '2030-01-02T10:00:00+00:00')
            before = {p.name: p.read_bytes() for p in Path(tmp).iterdir()}
            result = scan_day(calendar=calendar, archive=tmp, day='2030-01-01', at=source['capture_at'],
                              profile='LOWER', database=database, synthetic=True)
            self.assertEqual(before, {p.name: p.read_bytes() for p in Path(tmp).iterdir()})
            return result

    def test_daily_report_reproducible_pass(self):
        one, two = self.scan(), self.scan()
        self.assertEqual(one, two)
        self.assertEqual(one['calendar_status'], 'STRUCTURALLY_COMPLETE_LOCAL_RECEIPT')
        self.assertEqual(one['decision'], 'PASS')
        self.assertEqual(one['candidates'], [])
        self.assertFalse(one['monetary_permission'])
        self.assertEqual(one['network_requests'], 0)
        self.assertEqual(len(one['fixtures'][0]['markets']), 7)
        self.assertEqual(len(one['fixtures'][0]['small_markets']), 4)

    def test_incomplete_calendar(self):
        source, packet = synthetic_inputs()
        packet['data']['paging']['total'] = 2
        packet['receipt']['payload_hash'] = digest(packet['data'])
        with self.assertRaises(ValueError):
            calendar_day(packet, '2030-01-01', source['capture_at'])

    def test_filtered_calendar_rejected(self):
        result = self.scan(lambda p: p['receipt'].update(parameters={'id': 900001}))
        self.assertEqual(result['calendar_status'], 'REJECTED')
        self.assertEqual(result['decision'], 'PASS')

    def test_missing_history_and_lineups(self):
        result = self.scan()
        coverage = result['fixtures'][0]['coverage']
        self.assertIsNotNone(coverage)
        self.assertIn('MISSING_LINEUP', coverage['blockers'])
        self.assertFalse(coverage['history_coverage_ready'])
        self.assertTrue(all(m['model_probability'] is None for m in result['fixtures'][0]['markets']))

    def test_wrong_identity(self):
        source, calendar = synthetic_inputs()
        conflict = deepcopy(source['packets'][0])
        conflict['data']['response'][0]['teams']['home']['id'] = 999
        conflict['receipt']['payload_hash'] = digest(conflict['data'])
        result = self.scan(extra=[conflict])
        self.assertIn('SPORTS_EXPORT_OR_IDENTITY_FAILED', result['fixtures'][0]['blockers'])

    def test_future_results_excluded(self):
        source, _ = synthetic_inputs()
        future = deepcopy(source['packets'][1])
        future['receipt']['request_started_at'] = '2030-01-02T08:00:00+00:00'
        future['receipt']['received_at'] = '2030-01-02T09:00:00+00:00'
        # Preserve gateway ordering where present.
        if 'upstream_received_at' in future['receipt']:
            future['receipt']['upstream_received_at'] = '2030-01-02T08:30:00+00:00'
        baseline, result = self.scan(), self.scan(extra=[future])
        self.assertEqual(result['excluded_future_packets'], 1)
        self.assertEqual(result['fixtures'][0]['sports_hash'], baseline['fixtures'][0]['sports_hash'])
        self.assertEqual(result['fixtures'][0]['markets'], baseline['fixtures'][0]['markets'])

    def test_missing_calibration_and_unproven_probability(self):
        for change in ('status', 'calibration', 'holdout'):
            row = projection()
            if change == 'status': row['probability_trust']['status'] = 'BLOCKED'
            if change == 'calibration': row['probability_trust']['components']['calibration'] = {}
            if change == 'holdout': row['probability_trust']['components']['holdout'] = {}
            out = _project(row, [])
            self.assertIsNone(out['model_probability'])
            self.assertIsNone(out['ev'])
            self.assertEqual(out['status'], 'PASS')

    def test_zero_value(self):
        out = _project(projection(ev=0.), [])
        self.assertEqual(out['status'], 'PASS')
        self.assertIn('NO_POSITIVE_ROBUST_VALUE', out['blockers'])

    def test_quote_origin_not_self_attested(self):
        out = _project(projection(), ['INDEPENDENT_QUOTE_ORIGIN_NOT_ATTESTED'])
        self.assertIsNone(out['ev'])
        self.assertEqual(out['status'], 'PASS')

    def test_maximum_two_independent_candidates(self):
        fixtures = []
        for n, league, teams in [(1, 1, [1, 2]), (2, 1, [3, 4]), (3, 2, [1, 5]),
                                  (4, 3, [6, 7]), (5, 4, [8, 9])]:
            fixtures.append({'fixture_id': n, 'league_id': league, 'team_ids': teams,
                             'kickoff': '2030-01-01T12:00:00+00:00',
                             'markets': [_project(projection(), [])]})
        selected = independent_candidates(fixtures)
        self.assertEqual([r['fixture_id'] for r in selected], [1, 4])
        self.assertIn('CORRELATED_CANDIDATE', fixtures[1]['markets'][0]['blockers'])
        self.assertIn('CORRELATED_CANDIDATE', fixtures[2]['markets'][0]['blockers'])

    def test_referee_gate_holds(self):
        result = self.scan()
        gate = result['fixtures'][0]['small_markets'][-1]['referee_gate']
        self.assertEqual(gate['decision'], 'PASS')
        self.assertIsNone(gate['probability'])

    def test_prematch_only(self):
        source, calendar = synthetic_inputs()
        with TemporaryDirectory() as tmp:
            archive_packets([calendar], tmp, source['capture_at'])
            result = scan_day(calendar=calendar, archive=tmp, day='2030-01-01',
                              at='2030-01-01T12:00:00+00:00', profile='LOWER')
        self.assertIn('PREMATCH_ONLY', result['fixtures'][0]['blockers'])

    def test_real_core_read_only_ledger_path(self):
        source, calendar = synthetic_inputs()
        with TemporaryDirectory() as tmp:
            work = Path(tmp) / 'scenario'
            run_scenario(work_directory=work)
            archive_packets([calendar], work / 'archive', source['capture_at'])
            db = work / 'scenario.sqlite'
            before = db.read_bytes()
            result = scan_day(calendar=calendar, archive=work / 'archive', day='2030-01-01',
                at=source['decision_at'], profile='LOWER', database=db, synthetic=True)
            self.assertEqual(before, db.read_bytes())
        self.assertEqual(result['ledger_status'], 'HASH_CHAIN_VERIFIED_LOCAL')
        self.assertEqual(result['decision'], 'PASS')
        self.assertTrue(all(m['model_probability'] is None for m in result['fixtures'][0]['markets']))

    def price_scan(self, mutate):
        source, calendar = synthetic_inputs()
        event = {'id': 'test-event-900001', 'sport_key': 'soccer_test',
                 'home_team': 'Team A', 'away_team': 'Team B',
                 'commence_time': '2030-01-01T12:00:00+00:00',
                 'bookmakers': [{'key': 'test_book', 'markets': [{'key': 'h2h',
                     'last_update': source['quote_at'], 'outcomes': [
                         {'name': 'Team A', 'price': 2.1}, {'name': 'Draw', 'price': 3.2},
                         {'name': 'Team B', 'price': 3.5}]}]}]}
        price = {'event': event, 'sport': 'soccer_test', 'event_id': event['id'],
                 'bookmaker': 'test_book', 'received_at': source['quote_at'],
                 'rules_confirmed': True, 'market_keys': ['h2h']}
        mutate(price)
        with TemporaryDirectory() as tmp:
            work = Path(tmp) / 'scenario'
            run_scenario(work_directory=work)
            archive_packets([calendar], work / 'archive', source['capture_at'])
            db = work / 'scenario.sqlite'
            before = db.read_bytes()
            result = scan_day(calendar=calendar, archive=work / 'archive', day='2030-01-01',
                at=source['decision_at'], profile='LOWER', database=db,
                prices={'900001': price}, synthetic=True)
            self.assertEqual(before, db.read_bytes())
        return result

    def test_expired_quote_rejected_by_existing_adapter(self):
        result = self.price_scan(lambda p: p['event']['bookmakers'][0]['markets'][0].update(
            last_update='2030-01-01T08:00:00+00:00'))
        self.assertEqual(result['decision'], 'PASS')
        self.assertTrue(any('stale' in b for b in result['fixtures'][0]['blockers']))
        self.assertTrue(all(m['ev'] is None for m in result['fixtures'][0]['markets']))

    def test_wrong_quote_fixture_rejected(self):
        result = self.price_scan(lambda p: p['event'].update(home_team='Different team'))
        self.assertTrue(any('mismatch' in b for b in result['fixtures'][0]['blockers']))
        self.assertEqual(result['candidates'], [])

    def test_incompatible_period_rejected(self):
        result = self.price_scan(lambda p: p.update(market_keys=['h2h_h1']))
        self.assertEqual(result['decision'], 'PASS')
        self.assertTrue(all(m['model_probability'] is None for m in result['fixtures'][0]['markets']))

    def test_incompatible_quarter_line_rejected(self):
        def mutate(p):
            p['market_keys'] = ['totals']
            p['event']['bookmakers'][0]['markets'][0].update(key='totals', outcomes=[
                {'name': 'Over', 'point': 2.25, 'price': 1.9},
                {'name': 'Under', 'point': 2.25, 'price': 1.9}])
        result = self.price_scan(mutate)
        self.assertEqual(result['decision'], 'PASS')
        self.assertTrue(any('supported' in b for b in result['fixtures'][0]['blockers']))

    def test_valid_saved_price_cannot_override_pass(self):
        result = self.price_scan(lambda p: None)
        rows = result['fixtures'][0]['markets']
        self.assertTrue(any(m['odds'] is not None for m in rows))
        self.assertTrue(all(m['model_probability'] is None and m['ev'] is None for m in rows))
        self.assertEqual(result['decision'], 'PASS')

    def test_tipster_or_probability_override_rejected(self):
        result = self.price_scan(lambda p: p.update(model_probability=.99, tipster='BET'))
        self.assertIn('SAVED_PROVIDER_EVENT_REQUIRED', result['fixtures'][0]['blockers'])
        self.assertEqual(result['decision'], 'PASS')
        self.assertTrue(all(m['model_probability'] is None for m in result['fixtures'][0]['markets']))

    def test_missing_ledger_not_created(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'missing.sqlite'
            result = self.scan(database=path)
            self.assertFalse(path.exists())
        self.assertEqual(result['ledger_status'], 'ABSENT')
        self.assertEqual(result['decision'], 'PASS')

    def test_unvalidated_death_test_does_not_leak_probability_or_ev(self):
        row = projection(proof=False)
        row['death_test'] = {'loss_branches': [{'home': 1, 'away': 1, 'probability': .1}],
                             'stress_ev_min': .25, 'under_ceiling': {'probability': .9}}
        out = _project(row, [])
        self.assertEqual(out['death_test']['loss_branches'], [{'home': 1, 'away': 1}])
        self.assertIsNone(out['death_test']['stress_ev_min'])
        self.assertIsNone(out['death_test']['under_ceiling'])
        self.assertIsNone(out['model_probability'])

    def test_no_network_even_for_complete_scan(self):
        with patch('urllib.request.urlopen', side_effect=AssertionError('NETWORK_FORBIDDEN')):
            self.assertEqual(self.scan()['decision'], 'PASS')


if __name__ == '__main__':
    unittest.main()
