"""Frozen sporting denials survive prices, rechecks and research ranking."""
import copy
from datetime import timedelta
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import test_core2 as core_fixture
from sefirot.builder_research import create_builder_grid, compare_builder_singles
from sefirot.contracts import Policy, digest
from sefirot.engine import prepare, decide
from sefirot.fixtures import example
from sefirot.goal_robustness import create_robustness, compare_robustness
from sefirot.market_grid import create_grid, validate_grid
from sefirot.readiness import inspect_readiness
from sefirot.repository import Repository
from sefirot.service import Service

NOW = core_fixture.NOW
stamp = lambda minutes=0: (NOW + timedelta(minutes=minutes)).isoformat()
TOTAL = {'kind': 'TOTAL', 'side': 'OVER', 'line': 2.5}


def add_constraint(evidence):
    fact = next(e for e in evidence if e['key'] == 'tactics')
    signal = {**fact, 'id': fact['id'] + '-avoid-result', 'key': 'matchup_signal',
              'kind': 'INFERENCE', 'supports': [fact['id']],
              'value': {'status': 'CONSISTENT', 'selection_constraint': {'avoid_result': True}}}
    evidence.append(signal)
    return signal


class ScenarioConstraintTests(unittest.TestCase):
    def controlled(self, market=None, constraint=True):
        baseline, case, quotes, context = core_fixture.AdmissionTests().setup_case()
        if constraint:
            add_constraint(case['sports']['evidence'])
            add_constraint(case['recheck']['evidence'])
        market = market or baseline['market_pool'][0]
        prediction = prepare(case['sports'], [market], Policy())
        prediction.update(sealed_at=stamp(), model_id='controlled-test-model')
        row = prediction['candidates'][0]
        for key in ('base', 'low', 'high', 'calibration', 'calibration_n', 'stress_probabilities'):
            row[key] = copy.deepcopy(baseline['candidates'][0][key])
        old_key, key = baseline['candidates'][0]['key'], row['key']
        for field in ('health', 'releases', 'sephirot_ratings'):
            context[field] = {key: context[field][old_key]}
        quotes[0]['market'] = market
        return prediction, case, quotes, context

    def run_decision(self, data):
        p, case, quotes, context = data
        return decide(p, quotes, case['recheck'], case['decision_at'], context,
                      {'bankroll': 1000., 'peak': 1000.}, Policy())

    def freeze(self, constraint=True):
        case = example(NOW)
        if constraint: add_constraint(case['sports']['evidence'])
        repo = Repository(':memory:'); self.addCleanup(repo.close)
        service = Service(repo, Policy(), lambda: NOW)
        p = service.capture(case['sports'], case['markets'])
        grid = create_grid(p, Policy(), stamp(1))
        return service, p, grid, create_builder_grid(grid, p, Policy(), stamp(2))

    def prices(self, grid, result=True, total=True):
        markets = ([{'kind': 'DOUBLE_CHANCE', 'side': '1X'}] if result else []) + ([TOTAL] if total else [])
        quotes = [{'market': m, 'bookmaker': 'SYNTHETIC_API', 'odds': 100. if m['kind'] == 'DOUBLE_CHANCE' else 2.,
                   'observed_at': stamp(3), 'received_at': stamp(3), 'phase': 'FINAL', 'rules': 'REGULATION_90'}
                  for m in markets]
        receipt = {'provider': 'THE_ODDS_API_V4', 'quotes_hash': digest(quotes), 'grid_hash': grid['hash'],
                   'fixture_id': grid['match']['id'], 'bookmaker': 'SYNTHETIC_API', 'received_at': stamp(3)}
        return quotes, receipt

    def test_positive_ev_cannot_override_sports_denial_or_cleared_candidate_marker(self):
        self.assertEqual(self.run_decision(self.controlled(constraint=False))['decision'], 'BET')
        data = self.controlled(); data[0]['candidates'][0]['selection_issues'] = []
        out = self.run_decision(data)
        self.assertEqual(out['decision'], 'PASS'); self.assertEqual(out['risk']['stake'], 0.)
        self.assertGreater(out['candidates'][0]['ev'], 0.)
        self.assertIn('SCENARIO_MARKET_CONFLICT', out['limiting_factors'])
        self.assertIsNone(out['decision_card']['research_candidate'])
        task = next(t for t in out['decision_card']['action_plan'] if t['category'] == 'SCENARIO')
        self.assertFalse(task['price_can_resolve'])

    def test_goal_total_remains_admissible_with_explicit_avoid_result(self):
        out = self.run_decision(self.controlled(TOTAL))
        self.assertEqual(out['decision'], 'BET')
        self.assertFalse(out['candidates'][0]['selection_issues'])

    def test_added_or_removed_constraint_requires_new_seal(self):
        for originally_present in (True, False):
            data = self.controlled(constraint=originally_present)
            evidence = data[1]['recheck']['evidence']
            if originally_present: evidence[:] = [e for e in evidence if e['key'] != 'matchup_signal']
            else: add_constraint(evidence)
            out = self.run_decision(data)
            self.assertEqual(out['decision'], 'PASS')
            self.assertIn('SPORTS_CHANGED_RECALCULATE', out['limiting_factors'])

    def test_refreshed_support_ids_preserve_the_same_constraint(self):
        data = self.controlled(TOTAL)
        self.assertEqual(self.run_decision(data)['decision'], 'BET')
        self.assertNotEqual(data[0]['scenario']['selection_constraints']['evidence_ids'],
                            [data[1]['recheck']['evidence'][-1]['id']])

    def test_changed_optional_support_premise_requires_a_new_seal(self):
        data = self.controlled(TOTAL)
        # Optional context facts are outside the old eight-key change detector.
        for evidence, prefix in ((data[1]['sports']['evidence'], 'fact'), (data[1]['recheck']['evidence'], 'recheck')):
            template = next(e for e in evidence if e['key'] == 'tactics')
            fact = {**template, 'id': prefix + '-context', 'key': 'context', 'value': 'sporting premise A'}
            evidence.append(fact)
            next(e for e in evidence if e['key'] == 'matchup_signal')['supports'] = [fact['id']]
        original_row = copy.deepcopy(data[0]['candidates'][0])
        p = prepare(data[1]['sports'], [TOTAL], Policy()); p.update(sealed_at=stamp(), model_id='controlled-test-model')
        for key in ('base', 'low', 'high', 'calibration', 'calibration_n', 'stress_probabilities'): p['candidates'][0][key] = original_row[key]
        data = (p, *data[1:])
        next(e for e in data[1]['recheck']['evidence'] if e['key'] == 'context')['value'] = 'sporting premise B'
        out = self.run_decision(data)
        self.assertEqual(out['decision'], 'PASS')
        self.assertIn('SPORTS_CHANGED_RECALCULATE', out['limiting_factors'])

    def test_malformed_or_price_bearing_constraint_is_rejected(self):
        for value in (False, 1, 'true', None):
            case = example(NOW); signal = add_constraint(case['sports']['evidence'])
            signal['value']['selection_constraint']['avoid_result'] = value
            with self.subTest(value=value), self.assertRaises(ValueError): prepare(case['sports'], case['markets'], Policy())
        case = example(NOW); signal = add_constraint(case['sports']['evidence'])
        signal['value']['selection_constraint']['odds'] = 4.12
        with self.assertRaises(ValueError): prepare(case['sports'], case['markets'], Policy())

    def test_stale_or_unreliable_inference_blocks_and_keeps_the_denial(self):
        for weakness in ('stale', 'source', 'support'):
            case = example(NOW); signal = add_constraint(case['sports']['evidence'])
            if weakness == 'stale': signal['observed_at'] = stamp(-Policy().fact_max_age_minutes - 10)
            elif weakness == 'source':
                case['sports']['sources'].append({'id': 'weak', 'independence_group': 'weak', 'reliability': .1, 'enabled': True})
                signal['source_id'] = 'weak'
            else: signal['supports'] = []
            p = prepare(case['sports'], case['markets'], Policy())
            self.assertIn('SCENARIO_CONSTRAINT_UNVERIFIED', [i['code'] for i in p['issues']])
            self.assertTrue(p['scenario']['selection_constraints']['avoid_result'])
            self.assertTrue(p['candidates'][0]['selection_issues'])

    def test_superseded_or_conflicting_fact_cannot_support_a_constraint(self):
        for weakness in ('superseded', 'conflicting'):
            case = example(NOW); add_constraint(case['sports']['evidence'])
            fact = next(e for e in case['sports']['evidence'] if e['key'] == 'tactics')
            newer = {**copy.deepcopy(fact), 'id': 'new-tactics', 'received_at': stamp(-1), 'published_at': stamp(-1)}
            if weakness == 'superseded': newer['supersedes'] = [fact['id']]
            else: newer['value']['key_factor'] = 'different sporting premise'
            case['sports']['evidence'].append(newer)
            p = prepare(case['sports'], case['markets'], Policy())
            self.assertIn('SCENARIO_CONSTRAINT_UNVERIFIED', [i['code'] for i in p['issues']])

    def test_readiness_exposes_conflict_before_price_and_does_not_write(self):
        service, p, _, _ = self.freeze()
        before = service.repo.all('decisions')
        out = inspect_readiness(service, p['id'], stamp())
        row = next(r for r in out['markets'] if r['market'] == p['candidates'][0]['key'])
        self.assertIn('SCENARIO_MARKET_CONFLICT', [b['code'] for b in row['blockers']])
        self.assertFalse(row['ready_for_price_recheck'])
        self.assertEqual(service.repo.all('decisions'), before)
        self.assertFalse(out['quotes_read'])

    def test_research_keeps_all_rows_and_marks_each_result_family_and_builder_leg(self):
        _, p, grid, report = self.freeze()
        before = copy.deepcopy(p)
        self.assertEqual(len(grid['candidates']), 50); self.assertEqual(len(report['candidates']), 14)
        for row in grid['candidates']:
            expected = row['market']['kind'] in ('1X2', 'DOUBLE_CHANCE', 'DNB', 'HANDICAP')
            self.assertEqual(bool(row['selection_issues']), expected)
        for row in report['candidates']:
            expected = any(leg['kind'] in ('1X2', 'DOUBLE_CHANCE') for leg in row['legs'])
            self.assertEqual(bool(row['selection_issues']), expected)
            self.assertEqual(row['stake'], 0.); self.assertFalse(row['monetary_permission'])
        self.assertEqual(p, before)

    def test_high_price_result_single_is_excluded_from_builder_comparator(self):
        _, p, grid, report = self.freeze(); quotes, receipt = self.prices(grid)
        out = compare_builder_singles(report, p, quotes, Policy(), stamp(3), receipt)
        self.assertEqual(out['priced_single_count'], 2)
        self.assertEqual(out['best_single_diagnostic']['market'], TOTAL)
        self.assertFalse(out['monetary_permission']); self.assertEqual(out['stake'], 0.)
        quotes, receipt = self.prices(grid, total=False)
        out = compare_builder_singles(report, p, quotes, Policy(), stamp(3), receipt)
        self.assertIsNone(out['best_single_diagnostic'])

    def test_history_sensitivity_comparison_preserves_scenario_block(self):
        _, p, grid, _ = self.freeze(); quotes, receipt = self.prices(grid)
        report = create_robustness(grid, p, Policy(), stamp(2))
        out = compare_robustness(report, p, quotes, Policy(), stamp(3), receipt)
        row = next(r for r in out['candidates'] if r['market']['kind'] == 'DOUBLE_CHANCE' and r['prices'])
        self.assertEqual(row['selection_status'], 'BLOCKED_BY_SCENARIO')
        self.assertTrue(row['selection_issues'])
        self.assertTrue(row['prices'][0]['research_review_required'])

    def test_rehashed_grid_or_builder_cannot_remove_constraint(self):
        _, p, grid, report = self.freeze()
        forged = copy.deepcopy(grid); forged['candidates'][0]['selection_issues'] = []
        forged['hash'] = digest({k: v for k, v in forged.items() if k != 'hash'})
        with self.assertRaises(ValueError): validate_grid(forged, p, Policy(), stamp(3))
        forged = copy.deepcopy(report); forged['candidates'][0]['selection_issues'] = []
        forged['hash'] = digest({k: v for k, v in forged.items() if k != 'hash'})
        quotes, receipt = self.prices(grid)
        with self.assertRaises(ValueError): compare_builder_singles(forged, p, quotes, Policy(), stamp(3), receipt)

    def test_no_directive_preserves_score_probabilities_and_no_loss_branch_veto(self):
        case = example(NOW); original = prepare(case['sports'], case['markets'], Policy())
        add_constraint(case['sports']['evidence']); constrained = prepare(case['sports'], case['markets'], Policy())
        self.assertEqual(original['model'], constrained['model'])
        for before, after in zip(original['candidates'], constrained['candidates']):
            for key in ('raw', 'base', 'low', 'high', 'stress_probabilities', 'counterexamples'):
                self.assertEqual(before[key], after[key])
        data = self.controlled(constraint=False)
        self.assertTrue(data[0]['candidates'][0]['counterexamples'])
        self.assertEqual(self.run_decision(data)['decision'], 'BET')


if __name__ == '__main__': unittest.main()
