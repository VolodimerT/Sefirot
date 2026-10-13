"""Counterexamples for goal conjunctions and unverified category accounting."""
import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sefirot.builder_research import builder_contract, builder_universe, joint_probability, create_builder_grid, compare_builder_singles
from sefirot.cli import main
from sefirot.contracts import Policy, digest
from sefirot.fixtures import example
from sefirot.market_grid import create_grid
from sefirot.repository import Repository
from sefirot.service import Service
from sefirot.ticket_audit import audit_tickets

NOW = datetime(2030, 1, 1, 9, tzinfo=timezone.utc)
stamp = lambda minutes=0: (NOW + timedelta(minutes=minutes)).isoformat()
BTTS = {'kind': 'BTTS', 'side': 'YES'}
OVER = {'kind': 'TOTAL', 'side': 'OVER', 'line': 2.5}


class JointBuilderTests(unittest.TestCase):
    def freeze(self, history=True):
        self.repo = Repository(':memory:'); self.addCleanup(self.repo.close)
        policy = Policy(); case = example(NOW)
        if not history: case['sports']['history'] = []
        prediction = Service(self.repo, policy, lambda: NOW).capture(case['sports'], case['markets'])
        grid = create_grid(prediction, policy, stamp(1))
        return prediction, grid, create_builder_grid(grid, prediction, policy, stamp(2))

    def prices(self, grid, minutes=3):
        q = [{'market': OVER, 'bookmaker': 'SYNTHETIC_API', 'odds': 2.,
              'observed_at': stamp(minutes), 'received_at': stamp(minutes), 'phase': 'FINAL', 'rules': 'REGULATION_90'}]
        receipt = {'provider': 'THE_ODDS_API_V4', 'quotes_hash': digest(q), 'grid_hash': grid['hash'],
                   'fixture_id': grid['match']['id'], 'bookmaker': q[0]['bookmaker'], 'received_at': stamp(minutes)}
        return q, receipt

    def test_joint_integration_differs_from_product_and_branches_reconcile(self):
        out = joint_probability([BTTS, OVER], {(0, 0): .1, (1, 1): .2, (2, 1): .4, (3, 0): .3})
        self.assertAlmostEqual(out['joint_probability_raw'], .4)
        self.assertAlmostEqual(out['independence_product_diagnostic'], .42)
        self.assertAlmostEqual(sum(out['terminal_branch_contributions'].values()), .4)
        self.assertAlmostEqual(sum(out['terminal_branches_given_win'].values()), 1.)
        self.assertAlmostEqual(out['fair_odds_raw'], 2.5)

    def test_duplicates_contradictions_redundancy_push_and_foreign_dimensions_rejected(self):
        bad = [[BTTS, BTTS], [BTTS, {'kind': 'BTTS', 'side': 'NO'}],
               [BTTS, {'kind': 'TOTAL', 'side': 'OVER', 'line': 1.5}],
               [BTTS, {'kind': 'TOTAL', 'side': 'OVER', 'line': 3.}],
               [BTTS, {'kind': 'CORNERS', 'side': 'OVER', 'line': 8.5}],
               [BTTS], [BTTS, OVER, OVER, OVER],
               [OVER, {'kind': 'TOTAL', 'side': 'OVER', 'line': 100.5}]]
        for legs in bad:
            with self.subTest(legs=legs), self.assertRaises(ValueError): builder_contract(legs)

    def test_bad_mass_rejected_and_impossible_event_has_no_fair_price(self):
        for mass in ({(1, 1): .4}, {(36, 0): 1.}, {(1, 1): True}, {(1, 1): float('nan')}, {(True, 1): 1.}):
            with self.subTest(mass=mass), self.assertRaises(ValueError): joint_probability([BTTS, OVER], mass)
        out = joint_probability([BTTS, OVER], {(0, 0): 1.})
        self.assertIsNone(out['fair_odds_raw'])
        self.assertTrue(all(p is None for p in out['terminal_branches_given_win'].values()))

    def test_fixed_fourteen_builders_do_not_mutate_seal_or_ledger(self):
        p, grid, report = self.freeze()
        before = copy.deepcopy(p)
        self.assertEqual(report['candidate_count'], 14)
        self.assertEqual(report['universe_hash'], digest(builder_universe()))
        self.assertAlmostEqual(sum(report['terminal_scenarios_raw'].values()), 1.)
        for row in report['candidates']:
            self.assertLessEqual(row['joint_probability_raw'], min(row['marginals_raw']) + 1e-12)
            self.assertEqual(len(row['history_sensitivity']), 3)
            self.assertEqual(row['stake'], 0.)
            self.assertIsNone(row['builder_ev'])
        self.assertEqual(p, before)
        self.assertEqual(self.repo.all('decisions'), [])
        self.assertTrue(self.repo.verify())
        self.assertFalse(report['monetary_permission'])

    def test_missing_history_and_unmodelled_path_are_explicit(self):
        p, grid, report = self.freeze(False)
        self.assertEqual(report['history_status'], 'INSUFFICIENT_HISTORY_DIAGNOSTIC')
        self.assertIn('FIRST_GOAL_PATH', report['unmodelled_death_tests'])
        self.assertIn('CORNERS', report['unsupported_joint_dimensions'])
        self.assertEqual(report['joint_calibration_status'], 'UNVALIDATED')

    def test_api_single_comparator_keeps_builder_price_and_superiority_unknown(self):
        p, grid, report = self.freeze(); q, receipt = self.prices(grid)
        out = compare_builder_singles(report, p, q, Policy(), stamp(3), receipt)
        self.assertEqual(out['priced_single_count'], 1)
        self.assertEqual(out['best_single_diagnostic']['market'], OVER)
        self.assertIsNone(out['builder_beats_best_single'])
        self.assertEqual(out['status'], 'MISSING_API_BUILDER_QUOTE')
        self.assertTrue(all(row['builder_odds'] is None for row in out['candidates']))

    def test_rehashed_forgery_and_altered_universe_do_not_reproduce(self):
        p, grid, report = self.freeze(); q, receipt = self.prices(grid)
        for change in ('probability', 'universe'):
            forged = copy.deepcopy(report)
            if change == 'probability': forged['candidates'][0]['joint_probability_raw'] = .99
            else: forged['candidates'].pop()
            forged['hash'] = digest({k: v for k, v in forged.items() if k != 'hash'})
            with self.assertRaisesRegex(ValueError, 'does not reproduce'):
                compare_builder_singles(forged, p, q, Policy(), stamp(3), receipt)

    def test_manual_pre_freeze_future_and_post_kickoff_prices_rejected(self):
        p, grid, report = self.freeze()
        q, receipt = self.prices(grid)
        with self.assertRaises(ValueError): compare_builder_singles(report, p, q, Policy(), stamp(3))
        q, receipt = self.prices(grid, 1.5)
        with self.assertRaisesRegex(ValueError, 'before builder freeze'):
            compare_builder_singles(report, p, q, Policy(), stamp(3), receipt)
        q, receipt = self.prices(grid, 4)
        with self.assertRaises(ValueError): compare_builder_singles(report, p, q, Policy(), stamp(3), receipt)
        with self.assertRaises(ValueError): compare_builder_singles(report, p, q, Policy(), p['sports']['match']['kickoff'], receipt)

    def test_cli_roundtrip_is_read_only_and_refuses_overwrite(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); db = root/'ledger.sqlite'
            repo = Repository(db); case = example(NOW)
            p = Service(repo, Policy(), lambda: NOW).capture(case['sports'], case['markets']); repo.close()
            grid = create_grid(p, Policy(), stamp(1)); (root/'grid.json').write_text(json.dumps(grid))
            before = db.read_bytes()
            with patch('sefirot.service.Service.now', return_value=stamp(2)), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main(['--db', str(db), 'builder-grid', str(root/'grid.json'), '--output', str(root/'builder.json')]), 0)
                self.assertEqual(main(['--db', str(db), 'builder-grid', str(root/'grid.json'), '--output', str(root/'builder.json')]), 2)
            self.assertEqual(db.read_bytes(), before)
            self.assertEqual(json.loads((root/'builder.json').read_text())['candidate_count'], 14)


class CategoryAccountingTests(unittest.TestCase):
    def input(self):
        rows = []
        # Fictional scaled reconciliation, unrelated to any user's live ledger.
        for i, (odds, stake, outcome, category) in enumerate(((1.84, 20, 'WIN', 'MAIN'),
                (1.68, 20, 'WIN', 'MAIN'), (1.66, 20, 'LOSS', 'BUILDER'),
                (1.73, 15, 'PUSH', 'MAIN'), (2., 15, 'LOSS', 'MAIN'),
                (1.77, 10, 'WIN', 'SMALL'), (1.61, 10, 'LOSS', 'SMALL'), (1.66, 10, 'LOSS', 'SMALL'))):
            ticket = {'id': 'fictional-'+str(i), 'match_id': 'event-'+str(i if i < 7 else 6),
                      'day': '2030-01-01', 'odds': odds, 'stake': stake, 'outcome': outcome, 'category': category}
            if category == 'MAIN': ticket['market'] = {'kind': 'DNB', 'side': 'HOME'}
            else: ticket['reported_market'] = 'unsupported research contract'
            rows.append(ticket)
        return {'schema': 'ticket-audit-input-v1', 'status': 'REPORTED_UNVERIFIED', 'source': 'fictional test',
                'currency': 'UAH', 'timezone': 'Europe/Kyiv', 'tickets': rows}

    def test_categories_reconcile_and_shots_win_is_not_relabelled(self):
        out = audit_tickets(self.input())
        self.assertEqual(out['turnover'], 120.)
        self.assertEqual(out['returns'], 103.1)
        self.assertEqual(out['pnl'], -16.9)
        groups = {r['category']: r for r in out['categories']}
        self.assertEqual(groups['MAIN']['pnl'], 15.4)
        self.assertEqual(groups['SMALL']['pnl'], -12.3)
        self.assertEqual(groups['BUILDER']['pnl'], -20.)
        self.assertEqual(out['rows'][5]['outcome'], 'WIN')
        self.assertEqual(out['distinct_events'], 7)
        self.assertFalse(out['holdout_eligible'])

    def test_unsupported_main_and_mislabelled_canonical_contract_rejected(self):
        for index, category in ((0, 'BUILDER'), (2, 'MAIN'), (2, 'EXPRESS')):
            data = self.input(); data['tickets'][index]['category'] = category
            with self.assertRaises(ValueError): audit_tickets(data)

    def test_pending_category_does_not_turn_into_loss(self):
        data = self.input(); data['tickets'][2]['outcome'] = 'PENDING'
        out = audit_tickets(data)
        group = next(r for r in out['categories'] if r['category'] == 'BUILDER')
        self.assertEqual(group['pending_stake'], 20.)
        self.assertIsNone(group['roi_on_settled_turnover'])
        self.assertIsNone(out['rows'][2]['pnl'])
