"""Boundary tests for live-feed isolation, bookmaker completeness and key safety."""
import copy
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sefirot.cli import main
from sefirot.contracts import Policy
from sefirot.fixtures import example
from sefirot.markets import complete_overround, validate_quote
from sefirot.odds_provider import event_candidates, event_odds, events, quotes_from_event
from sefirot.repository import Repository
from sefirot.service import Service


def fixture():
    start = datetime(2030, 1, 1, 10, tzinfo=timezone.utc)
    stamp = lambda minutes: (start + timedelta(minutes=minutes)).isoformat()
    match = {'id': 'M-1', 'home': 'Team A', 'away': 'Team B', 'league': 'PL',
             'kickoff': stamp(180), 'sport': 'football', 'format': 'REGULATION_90'}
    prediction = {'sports': {'match': match}, 'sealed_at': stamp(0),
                  'captured_prematch': True, 'reconstructed': False,
                  'candidates': [{'market': {'kind': '1X2', 'side': 'HOME'}}]}
    event = {'id': 'event1234', 'sport_key': 'soccer_epl', 'home_team': match['home'],
             'away_team': match['away'], 'commence_time': match['kickoff'],
             'bookmakers': [{'key': 'testbook', 'last_update': stamp(1), 'markets': [
                 {'key': 'h2h', 'last_update': stamp(2), 'outcomes': [
                     {'name': 'Team B', 'price': 3.8}, {'name': 'Draw', 'price': 3.4},
                     {'name': 'Team A', 'price': 2.1}]}]}]}
    return prediction, event, stamp(3)


class OddsProviderTests(unittest.TestCase):
    def convert(self, event=None, prediction=None, received_at=None):
        p, e, received = fixture()
        return quotes_from_event(event or e, prediction or p, 'soccer_epl', 'event1234', 'testbook',
                                 received_at or received, rules_confirmed=True)

    def test_complete_line_from_one_book_and_one_timestamp(self):
        p, e, received = fixture()
        value = self.convert(e, p, received)
        quotes = value['quotes']
        self.assertEqual([q['market']['side'] for q in quotes], ['HOME', 'DRAW', 'AWAY'])
        self.assertEqual([q['odds'] for q in quotes], [2.1, 3.4, 3.8])
        self.assertEqual(len({(q['bookmaker'], q['observed_at'], q['line_id']) for q in quotes}), 1)
        self.assertEqual(len(complete_overround(quotes)), 1)
        for q in quotes:
            validate_quote(q, p['sports']['match']['kickoff'], received, p['sealed_at'])
        self.assertEqual(value['receipt']['available_at_bookmaker'], 'UNVERIFIED')

    def test_missing_settlement_confirmation_fails_before_import(self):
        p, e, received = fixture()
        with self.assertRaisesRegex(ValueError, 'settlement'):
            quotes_from_event(e, p, 'soccer_epl', 'event1234', 'testbook', received)

    def test_wrong_fixture_and_no_guessing_aliases(self):
        p, e, received = fixture()
        for key, altered in [('home_team', 'Team A FC'), ('away_team', 'Team A'),
                             ('commence_time', '2030-01-01T13:01:00+00:00'), ('id', 'other')]:
            wrong = copy.deepcopy(e);wrong[key] = altered
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.convert(event=wrong)

    def test_live_unsealed_reconstructed_and_future_prices_rejected(self):
        p, e, received = fixture()
        for key, altered in [('captured_prematch', False), ('reconstructed', True)]:
            broken = copy.deepcopy(p);broken[key] = altered
            with self.subTest(key=key), self.assertRaises(ValueError):self.convert(prediction=broken)
        with self.assertRaisesRegex(ValueError, 'prematch'):
            self.convert(received_at='2030-01-01T13:01:00+00:00')
        with self.assertRaisesRegex(ValueError, 'future'):
            self.convert(received_at='2030-01-01T10:01:00+00:00')

    def test_incomplete_duplicated_underround_and_stale_rejected(self):
        for change in ('missing', 'duplicate', 'underround', 'stale', 'missing_time'):
            _, e, _ = fixture()
            market = e['bookmakers'][0]['markets'][0]
            if change == 'missing':market['outcomes'].pop()
            if change == 'duplicate':market['outcomes'][2]['name'] = 'Draw'
            if change == 'underround':
                for outcome in market['outcomes']:outcome['price'] = 4.5
            if change == 'stale':market['last_update'] = '2030-01-01T09:00:00Z'
            if change == 'missing_time':
                market.pop('last_update');e['bookmakers'][0].pop('last_update')
            with self.subTest(change=change), self.assertRaises(ValueError):self.convert(event=e)

    def test_same_event_two_books_never_mix(self):
        _, e, _ = fixture()
        e['bookmakers'][0]['markets'][0]['outcomes'].pop()
        other = copy.deepcopy(e['bookmakers'][0]);other['key'] = 'otherbook'
        other['markets'][0]['outcomes'] = [{'name': 'Team A', 'price': 2.0}]
        e['bookmakers'].append(other)
        with self.assertRaises(ValueError):self.convert(event=e)

    def test_exact_event_directory_excludes_live_and_ambiguous(self):
        p, e, received = fixture()
        self.assertEqual(event_candidates([e], p, 'soccer_epl', received)['event_id'], e['id'])
        with self.assertRaises(ValueError):event_candidates([e, e], p, 'soccer_epl', received)
        with self.assertRaises(ValueError):event_candidates([e], p, 'soccer_epl', p['sports']['match']['kickoff'])

    def test_network_errors_and_redirect_never_expose_secret(self):
        paths = []
        class Reply:
            status = 302
            def read(self, limit):return b'ignored'
        class Connection:
            def __init__(self, host, timeout):self.host = host
            def request(self, method, path, headers):paths.append((self.host, method, path, headers))
            def getresponse(self):return Reply()
            def close(self):pass
        with self.assertRaises(ValueError) as caught:
            event_odds('soccer_epl', 'event1234', 'eu', api_key='DO_NOT_LOG_ME', connection_factory=Connection)
        self.assertNotIn('DO_NOT_LOG_ME', str(caught.exception))
        self.assertEqual(paths[0][0], 'api.the-odds-api.com')
        self.assertIn('apiKey=DO_NOT_LOG_ME', paths[0][2])
        self.assertEqual(len(paths), 1)

    def test_real_response_shape_and_credential_from_environment(self):
        p, e, _ = fixture()
        class Reply:
            status = 200
            def read(self, limit):return json.dumps(e).encode()
        class Connection:
            def __init__(self, host, timeout):self.host = host
            def request(self, method, path, headers):self.path = path
            def getresponse(self):return Reply()
            def close(self):pass
        with patch.dict('os.environ', {'SEFIROT_ODDS_API_KEY': 'dummy'}):
            self.assertEqual(event_odds('soccer_epl', 'event1234', 'eu', connection_factory=Connection), e)
        with self.assertRaises(ValueError):events('../escape', api_key='dummy', connection_factory=Connection)

    def test_cli_writes_quotes_only_after_capture_and_cannot_overwrite(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td);now = datetime.now(timezone.utc)
            case = example(at=now, match_id='test-provider-cli')
            repo = Repository(path/'local.sqlite')
            prediction = Service(repo, Policy()).capture(case['sports'], case['markets'])
            repo.close()
            event = {'id': 'event1234', 'sport_key': 'soccer_epl',
                     'home_team': case['sports']['match']['home'],
                     'away_team': case['sports']['match']['away'],
                     'commence_time': case['sports']['match']['kickoff'],
                     'bookmakers': [{'key': 'testbook', 'markets': [{'key': 'h2h',
                         'last_update': datetime.now(timezone.utc).isoformat(),
                         'outcomes': [{'name': 'A', 'price': 2.1}, {'name': 'Draw', 'price': 3.4},
                                      {'name': 'B', 'price': 3.8}]}]}]}
            args = ['--db', str(path/'local.sqlite'), 'fetch-odds', prediction['id'],
                    '--sport', 'soccer_epl', '--event-id', 'event1234', '--bookmaker', 'testbook',
                    '--rules-confirmed', '--output', str(path/'quotes.json')]
            with patch('sefirot.odds_provider.events', return_value=[event]), \
                 patch('sefirot.odds_provider.event_odds', return_value=event), redirect_stdout(io.StringIO()) as output:
                self.assertEqual(main(args), 0)
            self.assertFalse(json.loads(output.getvalue())['execution_price_verified'])
            self.assertEqual(len(json.loads((path/'quotes.json').read_text())), 3)
            self.assertEqual(json.loads((path/'quotes.json.receipt.json').read_text())['event_id'], 'event1234')
            with patch('sefirot.odds_provider.events', side_effect=AssertionError('no event lookup')), \
                 patch('sefirot.odds_provider.event_odds', side_effect=AssertionError('no second API request')):
                self.assertEqual(main(args), 2)

    def test_cli_wrong_event_does_not_purchase_price_query(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td);case=example(at=datetime.now(timezone.utc),match_id='no-wrong-provider-event')
            repo=Repository(path/'db.sqlite');prediction=Service(repo).capture(case['sports'],case['markets']);repo.close()
            match=case['sports']['match'];listed={'id':'correct123','sport_key':'soccer_epl',
                'home_team':match['home'],'away_team':match['away'],'commence_time':match['kickoff']}
            args=['--db',str(path/'db.sqlite'),'fetch-odds',prediction['id'],'--sport','soccer_epl',
                  '--event-id','wrong123','--bookmaker','testbook','--rules-confirmed',
                  '--output',str(path/'quotes.json')]
            with patch('sefirot.odds_provider.events',return_value=[listed]), \
                 patch('sefirot.odds_provider.event_odds',side_effect=AssertionError('price request')), \
                 redirect_stdout(io.StringIO()):
                self.assertEqual(main(args),2)
            self.assertFalse((path/'quotes.json').exists())


if __name__ == '__main__':unittest.main()
