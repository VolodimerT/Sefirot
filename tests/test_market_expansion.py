"""External-feed counterexamples and frozen-universe integration checks."""
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
from sefirot.cli import main
from sefirot.contracts import Policy, digest
from sefirot.fixtures import example
from sefirot.market_grid import create_grid, validate_grid, compare_grid, universe
from sefirot.markets import market_of, market_reference, settle
from sefirot.odds_provider import quotes_from_event, event_odds, keys_for_candidates
from sefirot.repository import Repository
from sefirot.service import Service
from test_odds_provider import fixture


def expanded_event():
    prediction, event, received = fixture()
    markets = event['bookmakers'][0]['markets']
    def add(key, outcomes):
        markets.append({'key': key, 'last_update': markets[0]['last_update'], 'outcomes': outcomes})
    add('draw_no_bet', [{'name': 'Team A', 'price': 1.6}, {'name': 'Team B', 'price': 2.5}])
    add('spreads', [{'name': 'Team A', 'point': -1, 'price': 1.9},
                    {'name': 'Team B', 'point': 1, 'price': 1.9}])
    add('totals', [{'name': 'Over', 'point': 2.5, 'price': 1.9},
                   {'name': 'Under', 'point': 2.5, 'price': 1.9}])
    add('btts', [{'name': 'Yes', 'price': 1.8}, {'name': 'No', 'price': 2.0}])
    add('team_totals', [{'name': 'Over', 'description': 'Team A', 'point': 1.5, 'price': 1.9},
                        {'name': 'Under', 'description': 'Team A', 'point': 1.5, 'price': 1.9},
                        {'name': 'Over', 'description': 'Team B', 'point': .5, 'price': 1.9},
                        {'name': 'Under', 'description': 'Team B', 'point': .5, 'price': 1.9}])
    return prediction, event, received


class ExpandedFeedTests(unittest.TestCase):
    keys = ('h2h', 'draw_no_bet', 'spreads', 'totals', 'btts', 'team_totals')

    def convert(self, event=None):
        p, e, at = expanded_event()
        return quotes_from_event(e if event is None else event, p, 'soccer_epl', 'event1234',
                                 'testbook', at, rules_confirmed=True, market_keys=self.keys)

    def test_six_families_preserve_contracts_and_complete_references(self):
        result = self.convert(); quotes = result['quotes']
        self.assertEqual(len(quotes), 15)
        self.assertEqual(len(result['receipt']['lines']), 7)
        self.assertEqual(result['receipt']['rejected_lines'], [])
        by_key = {market_of(q['market']).key: q for q in quotes}
        for key in ('DNB:HOME', 'HANDICAP:HOME:-1', 'TOTAL:OVER:2.5', 'BTTS:YES', 'TEAM_TOTAL:AWAY_OVER:0.5'):
            self.assertEqual(market_reference(quotes, by_key[key], .5, .1)['method'],
                             'PROPORTIONAL_COMPLETE_BOOKMAKER_LINE')
        self.assertEqual(settle(market_of(by_key['HANDICAP:HOME:-1']['market']), 2, 1), 'PUSH')
        self.assertEqual(settle(market_of(by_key['DNB:HOME']['market']), 1, 1), 'PUSH')

    def test_opposite_handicaps_and_same_total_points_required(self):
        for key, point in (('spreads', .5), ('totals', 3.5)):
            _, event, _ = expanded_event()
            block = next(m for m in event['bookmakers'][0]['markets'] if m['key'] == key)
            block['outcomes'][1]['point'] = point
            result = self.convert(event)
            self.assertFalse(any(line['provider_market'] == key for line in result['receipt']['lines']))
            self.assertTrue(any(r['reason'] == 'INCOMPLETE_OR_DUPLICATE_LINE' for r in result['receipt']['rejected_lines']))

    def test_quarter_bool_unknown_team_and_duplicate_rejected(self):
        for change in ('quarter', 'bool', 'wrong_team', 'duplicate'):
            _, event, _ = expanded_event()
            block = next(m for m in event['bookmakers'][0]['markets'] if m['key'] == 'team_totals')
            if change == 'quarter': block['outcomes'][0]['point'] = 1.25
            if change == 'bool': block['outcomes'][0]['point'] = True
            if change == 'wrong_team': block['outcomes'][0]['description'] = 'Team A FC'
            if change == 'duplicate': block['outcomes'].append(copy.deepcopy(block['outcomes'][0]))
            result = self.convert(event)
            self.assertFalse(any(q['market'].get('side', '').startswith('HOME_') for q in result['quotes']))

    def test_non_json_nan_payload_rejects_the_entire_import(self):
        _, event, _ = expanded_event()
        event['bookmakers'][0]['markets'][2]['outcomes'][0]['price'] = float('nan')
        with self.assertRaises(ValueError): self.convert(event)

    def test_partial_coverage_lists_unavailable_and_missing_candidates(self):
        p, event, at = expanded_event()
        p['candidates'].append({'market': {'kind': 'DOUBLE_CHANCE', 'side': '1X'}})
        event['bookmakers'][0]['markets'] = event['bookmakers'][0]['markets'][:1]
        result = quotes_from_event(event, p, 'soccer_epl', 'event1234', 'testbook', at,
                                   rules_confirmed=True, market_keys=self.keys)
        self.assertEqual(len(result['quotes']), 3)
        self.assertEqual(len(result['receipt']['rejected_lines']), 5)
        self.assertEqual(result['receipt']['missing_candidates'], ['DOUBLE_CHANCE:1X'])

    def test_one_stale_family_does_not_invalidate_fresh_partitions(self):
        _, event, _ = expanded_event()
        event['bookmakers'][0]['markets'][4]['last_update'] = '2030-01-01T09:00:00Z'
        result = self.convert(event)
        self.assertFalse(any(q['market']['kind'] == 'BTTS' for q in result['quotes']))
        self.assertEqual(len(result['quotes']), 13)

    def test_alternate_lines_are_isolated_and_featured_duplicate_not_shopped(self):
        p, event, at = expanded_event()
        block = copy.deepcopy(event['bookmakers'][0]['markets'][3]); block['key'] = 'alternate_totals'
        for row in block['outcomes']: row['price'] = 2.0
        block['outcomes'] += [{'name': 'Over', 'point': 3, 'price': 1.9}, {'name': 'Under', 'point': 3, 'price': 1.9}]
        event['bookmakers'][0]['markets'].append(block)
        result = quotes_from_event(event, p, 'soccer_epl', 'event1234', 'testbook', at,
                                   rules_confirmed=True, market_keys=('totals', 'alternate_totals'))
        self.assertEqual(len(result['quotes']), 4)
        self.assertEqual(next(q['odds'] for q in result['quotes'] if q['market'] == {'kind':'TOTAL','side':'OVER','line':2.5}), 1.9)
        self.assertEqual(len({q['line_id'] for q in result['quotes']}), 2)

    def test_api_request_uses_only_explicit_allowed_main_keys(self):
        paths = []
        class Reply:
            status = 200
            def read(self, limit): return b'{}'
        class Connection:
            def __init__(self, host, timeout): pass
            def request(self, method, path, headers): paths.append(path)
            def getresponse(self): return Reply()
            def close(self): pass
        event_odds('soccer_epl', 'event1234', 'eu', api_key='dummy', connection_factory=Connection,
                   market_keys=('totals','btts','draw_no_bet'))
        self.assertIn('markets=draw_no_bet%2Ctotals%2Cbtts', paths[0])
        for keys in (('totals_h1',), ('player_cards',), ('totals','totals')):
            with self.assertRaises(ValueError):
                event_odds('soccer_epl', 'event1234', 'eu', api_key='dummy', connection_factory=Connection, market_keys=keys)
        self.assertEqual(len(paths), 1)

    def test_double_chance_is_never_fabricated_from_1x2_odds(self):
        with self.assertRaises(ValueError):keys_for_candidates([{'market':{'kind':'DOUBLE_CHANCE','side':'1X'}}])


class FrozenGridTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2030, 1, 1, 10, tzinfo=timezone.utc)
        self.policy = Policy(); self.repo = Repository(':memory:')
        self.case = example(at=self.now)
        self.service = Service(self.repo, self.policy, lambda: self.now)
        self.prediction = self.service.capture(self.case['sports'], self.case['markets'])
        self.at = (self.now + timedelta(minutes=1)).isoformat()
        self.grid = create_grid(self.prediction, self.policy, self.at)

    def tearDown(self): self.repo.close()

    def quotes(self, odds=2.0):
        at = (self.now + timedelta(minutes=2)).isoformat()
        return [{'market': {'kind':'TOTAL','side':side,'line':2.5}, 'bookmaker':'API_BOOK',
                 'odds':odds, 'observed_at':at, 'received_at':at, 'phase':'FINAL',
                 'rules':'REGULATION_90', 'line_id':'api-total-line'} for side in ('OVER','UNDER')]

    def compare(self, quotes, at):
        receipt={'provider':'THE_ODDS_API_V4','quotes_hash':digest(quotes),'grid_hash':self.grid['hash'],
                 'fixture_id':self.grid['match']['id'],'bookmaker':'API_BOOK','received_at':quotes[0]['received_at']}
        return compare_grid(self.grid,self.prediction,quotes,self.policy,at,receipt)

    def test_api_receipt_is_required_and_altered_quotes_rejected(self):
        quotes=self.quotes();at=quotes[0]['received_at']
        with self.assertRaisesRegex(ValueError,'API receipt'):
            compare_grid(self.grid,self.prediction,quotes,self.policy,at)
        receipt={'provider':'THE_ODDS_API_V4','quotes_hash':digest(quotes),'grid_hash':self.grid['hash'],
                 'fixture_id':self.grid['match']['id'],'bookmaker':'API_BOOK','received_at':at}
        quotes[0]['odds']=10.0
        with self.assertRaisesRegex(ValueError,'API receipt'):
            compare_grid(self.grid,self.prediction,quotes,self.policy,at,receipt)

    def test_fifty_contracts_and_sealed_candidates_agree_without_journal_writes(self):
        self.assertEqual(len(universe()), 50)
        self.assertEqual(len({c['key'] for c in self.grid['candidates']}), 50)
        self.assertFalse(self.grid['monetary_permission'])
        by_key = {c['key']: c for c in self.grid['candidates']}
        for c in self.prediction['candidates']:
            self.assertEqual(by_key[c['key']]['raw'], c['raw'])
            self.assertEqual(by_key[c['key']]['base'], c['base'])
        self.assertEqual(len(self.repo.all('predictions')), 1)
        self.assertEqual(self.repo.all('decisions'), [])
        self.assertTrue(self.repo.verify())

    def test_raw_totals_monotone_and_no_impossible_push(self):
        rows = {c['key']: c for c in self.grid['candidates']}
        probabilities = [rows['TOTAL:OVER:'+str(line)]['raw'][0] for line in ('1.5','2','2.5','3','3.5')]
        self.assertEqual(probabilities, sorted(probabilities, reverse=True))
        for c in rows.values():
            self.assertAlmostEqual(sum(c['raw']), 1)
            if not market_of(c['market']).push_possible:
                self.assertEqual(c['raw'][1], 0.)
                self.assertEqual(c['calibration_high'][1], 0.)

    def test_grid_tampering_rejected_even_with_recomputed_checksum(self):
        for field in ('probability', 'universe', 'permission'):
            changed = copy.deepcopy(self.grid)
            if field == 'probability': changed['candidates'][0]['raw'] = [.9,0,.1]
            if field == 'universe': changed['candidates'].pop()
            if field == 'permission': changed['monetary_permission'] = True
            changed.pop('hash'); changed['hash'] = digest(changed)
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'differs'):
                validate_grid(changed, self.prediction, self.policy, self.at)

    def test_future_started_wrong_build_and_reconstructed_fail(self):
        with self.assertRaises(ValueError):validate_grid(self.grid,self.prediction,self.policy,self.prediction['sealed_at'])
        with self.assertRaises(ValueError):create_grid(self.prediction,self.policy,self.prediction['sports']['match']['kickoff'])
        for key, value in (('code_hash','wrong'), ('reconstructed',True)):
            broken = {**self.prediction,key:value}
            with self.assertRaises(ValueError):create_grid(broken,self.policy,self.at)

    def test_price_changes_ev_but_cannot_change_sports_or_admission(self):
        at = (self.now + timedelta(minutes=2)).isoformat()
        a = self.compare(self.quotes(2.0),at)
        b = self.compare(self.quotes(2.2),at)
        ar = next(c for c in a['candidates'] if c['key']=='TOTAL:OVER:2.5')
        br = next(c for c in b['candidates'] if c['key']=='TOTAL:OVER:2.5')
        self.assertEqual(ar['base'],br['base']);self.assertEqual(a['grid_hash'],b['grid_hash'])
        self.assertGreater(br['prices'][0]['ev_base'],ar['prices'][0]['ev_base'])
        self.assertAlmostEqual(ar['prices'][0]['ev_raw'], 2*ar['raw'][0]-1)
        self.assertFalse(a['monetary_permission']);self.assertEqual(ar['stake'],0.)
        self.assertEqual(a['priced_count'],2);self.assertEqual(a['candidate_count'],50)

    def test_price_received_before_grid_rejected_and_stale_retained_as_missing(self):
        quotes=self.quotes();early=self.prediction['sealed_at']
        for q in quotes:q['observed_at']=early;q['received_at']=early
        with self.assertRaisesRegex(ValueError,'after probability seal'):
            self.compare(quotes,self.at)
        later=(self.now+timedelta(minutes=5)).isoformat()
        result=self.compare(self.quotes(),later)
        self.assertEqual(result['priced_count'],0)

    def test_cli_full_grid_import_comparison_preserves_ledger(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);now=datetime.now(timezone.utc)
            case=example(at=now,match_id='grid-cli');repo=Repository(root/'db.sqlite')
            prediction=Service(repo).capture(case['sports'],case['markets']);repo.close()
            common=['--db',str(root/'db.sqlite')]
            with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                self.assertEqual(main(common+['market-grid',prediction['id'],'--output',str(root/'grid.json')]),0)
            event={'id':'event1234','sport_key':'soccer_epl','home_team':'A','away_team':'B',
                   'commence_time':case['sports']['match']['kickoff'],'bookmakers':[{'key':'testbook',
                   'markets':[{'key':'totals','last_update':datetime.now(timezone.utc).isoformat(),
                              'outcomes':[{'name':'Over','point':2.5,'price':1.9},{'name':'Under','point':2.5,'price':1.9}]}]}]}
            args=common+['fetch-odds',prediction['id'],'--sport','soccer_epl','--event-id','event1234',
                         '--bookmaker','testbook','--rules-confirmed','--grid',str(root/'grid.json'),
                         '--output',str(root/'quotes.json')]
            with patch('sefirot.odds_provider.events',return_value=[event]), \
                 patch('sefirot.odds_provider.event_odds',return_value=event) as request, \
                 redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):
                self.assertEqual(main(args),0)
                self.assertIn('alternate_totals',request.call_args.kwargs['market_keys'])
                self.assertEqual(main(common+['compare-grid',str(root/'grid.json'),str(root/'quotes.json'),
                                             '--output',str(root/'comparison.json')]),0)
            report=json.loads((root/'comparison.json').read_text())
            self.assertEqual(report['priced_count'],2);self.assertFalse(report['monetary_permission'])
            repo=Repository(root/'db.sqlite',read_only=True)
            self.assertEqual(len(repo.all('predictions')),1);self.assertEqual(repo.all('decisions'),[])
            self.assertTrue(repo.verify());repo.close()


if __name__ == '__main__': unittest.main()
