"""Audit counterexamples: false permission, history leakage and forged diagnostics."""
import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stdout, redirect_stderr
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sefirot.action_plan import action_plan
from sefirot.cli import main
from sefirot.contracts import Policy, digest
from sefirot.engine import prepare
from sefirot.fixtures import example
from sefirot.goal_robustness import create_robustness, compare_robustness
from sefirot.identity import model_code_hash
from sefirot.market_grid import create_grid
from sefirot.markets import market_of
from sefirot.readiness import inspect_readiness
from sefirot.repository import Repository
from sefirot.service import Service
from test_audit_upgrade import controlled, decision

NOW = datetime(2026, 10, 4, 12, tzinfo=timezone.utc)
stamp = lambda minutes=0: (NOW + timedelta(minutes=minutes)).isoformat()


class ActionPlanTests(unittest.TestCase):
    def test_model_block_defers_price_without_pretending_it_can_finish_before_kickoff(self):
        tasks = action_plan(['HOLDOUT_UNVALIDATED', 'PRICE_STALE'], stamp(120), stamp())
        self.assertEqual([t['category'] for t in tasks], ['MODEL_VALIDATION', 'PRICE'])
        self.assertIsNone(tasks[0]['deadline'])
        self.assertTrue(tasks[1]['deferred'])
        self.assertFalse(tasks[1]['price_can_resolve'])

    def test_unknown_block_fails_closed_instead_of_becoming_a_price_task(self):
        tasks = action_plan(['NEW_UNKNOWN_BLOCK', 'MISSING_CURRENT_PRICE'], stamp(120), stamp())
        self.assertEqual(tasks[0]['category'], 'REVIEW')
        self.assertFalse(tasks[1]['price_can_resolve'])

    def test_price_only_case_and_closed_window_have_different_actions(self):
        tasks = action_plan(['PRICE_STALE'], stamp(120), stamp())
        self.assertTrue(tasks[0]['price_can_resolve'])
        closed = action_plan(['PRICE_STALE'], stamp(), stamp())
        self.assertEqual(closed[0]['category'], 'CLOSED')
        self.assertFalse(closed[0]['price_can_resolve'])

    def test_recorded_card_contains_exact_original_data_and_fit_identity(self):
        prediction, case, quotes, context = controlled()
        out = decision(prediction, case, quotes, context)
        card = out['decision_card']
        self.assertEqual(card['passport']['data_hash'], digest(prediction['sports']))
        self.assertEqual(card['passport']['model_hash'], prediction['model_hash'])
        self.assertEqual(card['stage'], 'FINAL')
        self.assertFalse(card['execution_enabled'])
        self.assertEqual(card['selected_market'], out['selected_market'])


class RobustnessTests(unittest.TestCase):
    def setUp(self):
        self.policy = Policy()
        self.repo = Repository(':memory:')
        self.addCleanup(self.repo.close)
        self.service = Service(self.repo, self.policy, lambda: NOW)
        self.case = example(NOW)

    def freeze(self, sports=None):
        prediction = self.service.capture(sports or self.case['sports'], self.case['markets'])
        grid = create_grid(prediction, self.policy, stamp(1))
        return prediction, grid, create_robustness(grid, prediction, self.policy, stamp(2))

    def prices(self, grid, report, odds=2.):
        quotes = [{'market': {'kind': 'TEAM_TOTAL', 'side': side, 'line': 1.5},
                   'bookmaker': 'SYNTHETIC_API_BOOK', 'odds': odds,
                   'observed_at': stamp(3), 'received_at': stamp(3),
                   'phase': 'FINAL', 'rules': 'REGULATION_90', 'line_id': 'pair-it'}
                  for side in ('HOME_OVER', 'HOME_UNDER')]
        receipt = {'provider': 'THE_ODDS_API_V4', 'quotes_hash': digest(quotes),
                   'grid_hash': grid['hash'], 'fixture_id': grid['match']['id'],
                   'bookmaker': quotes[0]['bookmaker'], 'received_at': stamp(3)}
        return quotes, receipt

    def test_original_prediction_and_ledger_are_unchanged_and_all_contracts_preserve_push(self):
        prediction, grid, report = self.freeze()
        before = copy.deepcopy(prediction)
        self.assertEqual(report['passport']['model_hash'], model_code_hash())
        self.assertEqual(len(report['scenarios']), 3)
        for scenario in report['scenarios']:
            self.assertEqual(len(scenario['candidates']), 50)
            for candidate in scenario['candidates']:
                self.assertAlmostEqual(sum(candidate['raw']), 1.)
                if not market_of(candidate['market']).push_possible:
                    self.assertEqual(candidate['raw'][1], 0.)
        self.assertEqual(digest(self.repo.get('predictions', prediction['id'])), digest(before))
        self.assertEqual(self.repo.all('decisions'), [])
        self.assertEqual(len(self.repo.all('predictions')), 1)
        self.assertTrue(self.repo.verify())
        self.assertFalse(report['monetary_permission'])

    def test_9_1_outlier_is_visible_as_counterfactual_not_a_corrected_api_result(self):
        sports = copy.deepcopy(self.case['sports'])
        sports['history'][-1].update(home_goals=9, away_goals=1)
        prediction, grid, report = self.freeze(sports)
        removed = report['scenarios'][1]
        self.assertEqual(removed['changes'][0]['id'], sports['history'][-1]['id'])
        self.assertEqual(removed['changes'][0]['original_score'], [9, 1])
        self.assertTrue(removed['counterfactual'])
        self.assertLess(removed['rates']['home'], report['scenarios'][0]['rates']['home'])
        self.assertGreater(len(report['scenarios'][2]['changes']), 0)
        self.assertEqual(prediction['sports']['history'][-1]['home_goals'], 9)

    def test_late_foreign_profile_and_league_outliers_cannot_select_outlier_or_raise_caps(self):
        original = prepare(self.case['sports'], self.case['markets'], self.policy)
        sports = copy.deepcopy(self.case['sports'])
        for index, changed in enumerate(({'received_at': stamp(20)}, {'competition_profile': 'WOMEN'}, {'league': 'FOREIGN'})):
            row = copy.deepcopy(sports['history'][0])
            row.update(id='excluded-' + str(index), home_goals=50, away_goals=50, **changed)
            sports['history'].append(row)
        prediction, grid, report = self.freeze(sports)
        self.assertEqual(report['eligible_history'], 40)
        self.assertEqual(len(report['excluded_history_ids']), 3)
        self.assertNotIn('excluded', report['scenarios'][1]['changes'][0]['id'])
        self.assertLess(max(report['cap_thresholds'].values()), 50)
        self.assertEqual(prediction['model']['rates'], original['model']['rates'])

    def test_target_result_and_duplicate_history_ids_are_rejected(self):
        for change in ('target', 'duplicate'):
            sports = copy.deepcopy(self.case['sports'])
            if change == 'target': sports['history'][0]['id'] = sports['match']['id']
            else: sports['history'].append(copy.deepcopy(sports['history'][0]))
            with self.assertRaises(ValueError): self.freeze(sports)

    def test_no_history_does_not_produce_a_false_stability_certificate(self):
        sports = copy.deepcopy(self.case['sports']); sports['history'] = []
        prediction, grid, report = self.freeze(sports)
        self.assertEqual(report['status'], 'INSUFFICIENT_HISTORY_DIAGNOSTIC')
        self.assertFalse(report['scenarios'][1]['available'])
        quotes, receipt = self.prices(grid, report)
        out = compare_robustness(report, prediction, quotes, self.policy, stamp(3), receipt)
        self.assertEqual(out['status'], 'RESEARCH_REVIEW_REQUIRED')
        self.assertEqual(out['candidate_count'], 50)
        self.assertEqual(out['priced_count'], 2)
        self.assertFalse(out['monetary_permission'])

    def test_eight_games_drop_to_seven_and_are_not_claimed_sufficient(self):
        sports = copy.deepcopy(self.case['sports']); sports['history'] = sports['history'][-8:]
        prediction, grid, report = self.freeze(sports)
        self.assertTrue(report['scenarios'][0]['history_sufficient'])
        self.assertFalse(report['scenarios'][1]['history_sufficient'])
        self.assertEqual(report['status'], 'INSUFFICIENT_HISTORY_DIAGNOSTIC')

    def test_ev_class_can_change_but_stake_and_admission_remain_zero(self):
        sports = copy.deepcopy(self.case['sports'])
        for row in sports['history']: row.update(home_goals=0, away_goals=0)
        sports['history'][-1].update(home='A', away='B', home_goals=10)
        prediction, grid, report = self.freeze(sports)
        before = copy.deepcopy(prediction)
        quotes, receipt = self.prices(grid, report, 20.)
        out = compare_robustness(report, prediction, quotes, self.policy, stamp(3), receipt)
        self.assertGreater(out['class_changed_contracts'], 0)
        self.assertEqual(out['status'], 'RESEARCH_REVIEW_REQUIRED')
        self.assertEqual(out['stake'], 0.)
        self.assertFalse(out['execution_enabled'])
        self.assertEqual(prediction, before)
        self.assertEqual(self.repo.all('decisions'), [])

    def test_rehashed_altered_history_report_still_fails_reproduction(self):
        prediction, grid, report = self.freeze()
        report['scenarios'][1]['candidates'][0]['raw'] = [.99, 0, .01]
        report['hash'] = digest({k: v for k, v in report.items() if k != 'hash'})
        quotes, receipt = self.prices(grid, report)
        with self.assertRaisesRegex(ValueError, 'does not reproduce'):
            compare_robustness(report, prediction, quotes, self.policy, stamp(3), receipt)

    def test_manual_quotes_wrong_receipt_and_price_before_probe_are_rejected(self):
        prediction, grid, report = self.freeze()
        quotes, receipt = self.prices(grid, report)
        with self.assertRaisesRegex(ValueError, 'API receipt'):
            compare_robustness(report, prediction, quotes, self.policy, stamp(3))
        bad = copy.deepcopy(receipt); bad['grid_hash'] = 'wrong'
        with self.assertRaises(ValueError):
            compare_robustness(report, prediction, quotes, self.policy, stamp(3), bad)
        for quote in quotes: quote.update(observed_at=stamp(1.5), received_at=stamp(1.5))
        receipt.update(quotes_hash=digest(quotes), received_at=stamp(1.5))
        with self.assertRaises(ValueError):
            compare_robustness(report, prediction, quotes, self.policy, stamp(3), receipt)

    def test_archived_build_wrong_policy_and_closed_prematch_are_rejected(self):
        prediction, grid, report = self.freeze()
        for policy, at in ((replace(self.policy, min_team_games=9), stamp(2)), (self.policy, stamp(120))):
            with self.assertRaises(ValueError): create_robustness(grid, prediction, policy, at)
        prediction['code_hash'] = 'archived'
        with self.assertRaises(ValueError): create_robustness(grid, prediction, self.policy, stamp(2))

    def test_readiness_has_tasks_and_original_passport_without_writes(self):
        prediction, grid, report = self.freeze()
        self.service.clock = lambda: NOW + timedelta(minutes=2)
        view = inspect_readiness(self.service, prediction['id'], self.service.now())
        self.assertEqual(view['stage'], 'PREVIEW')
        self.assertIn('MODEL_VALIDATION', {t['category'] for t in view['action_plan']})
        self.assertEqual(view['passport']['data_hash'], digest(prediction['sports']))
        self.assertFalse(view['quote_recheck_useful'])
        self.assertEqual(self.repo.all('decisions'), [])

    def test_cli_uses_read_only_ledger_refuses_overwrite_and_closes_sqlite(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder); database = directory / 'ledger.sqlite'
            with closing(Repository(database)) as repo:
                service = Service(repo, self.policy, lambda: NOW)
                prediction = service.capture(self.case['sports'], self.case['markets'])
                grid = create_grid(prediction, self.policy, stamp(1))
            grid_file = directory / 'grid.json'; grid_file.write_text(json.dumps(grid))
            output = directory / 'robust.json'; before = database.read_bytes()
            argv = ['--db', str(database), 'goal-robustness', str(grid_file), '--output', str(output)]
            with patch.object(Service, 'now', return_value=stamp(2)), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main(argv), 0)
                payload = output.read_bytes()
                self.assertEqual(main(argv), 2)
            self.assertEqual(output.read_bytes(), payload)
            self.assertEqual(database.read_bytes(), before)
            # Windows must be able to remove the directory immediately.
            output.unlink(); grid_file.unlink(); database.unlink()

    def test_comparison_cli_writes_fifty_contracts_without_creating_a_decision(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder); database = directory / 'ledger.sqlite'
            with closing(Repository(database)) as repo:
                service = Service(repo, self.policy, lambda: NOW)
                prediction = service.capture(self.case['sports'], self.case['markets'])
                grid = create_grid(prediction, self.policy, stamp(1))
                report = create_robustness(grid, prediction, self.policy, stamp(2))
            quotes, receipt = self.prices(grid, report)
            for name, data in [('report.json', report), ('quotes.json', quotes), ('quotes.json.receipt.json', receipt)]:
                (directory / name).write_text(json.dumps(data))
            output = directory / 'comparison.json'
            argv = ['--db', str(database), 'compare-robustness', str(directory / 'report.json'),
                    str(directory / 'quotes.json'), '--output', str(output)]
            with patch.object(Service, 'now', return_value=stamp(3)), redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main(argv), 0)
            comparison = json.loads(output.read_text())
            self.assertEqual(comparison['candidate_count'], 50)
            self.assertEqual(comparison['priced_count'], 2)
            with closing(Repository(database, read_only=True)) as repo:
                self.assertEqual(repo.all('decisions'), [])
                self.assertTrue(repo.verify())

    def test_missing_ledger_does_not_create_a_database_or_output(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            database = directory / 'missing.sqlite'; output = directory / 'result.json'
            argv = ['--db', str(database), 'goal-robustness', str(directory / 'missing-grid.json'), '--output', str(output)]
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(main(argv), 2)
            self.assertFalse(database.exists()); self.assertFalse(output.exists())
