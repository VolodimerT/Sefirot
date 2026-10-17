"""Explicit odds confirmation flags, owned CLI ledger, no genuine provider."""
from contextlib import closing, redirect_stdout, redirect_stderr
import copy
from datetime import datetime, timezone
import io
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from sefirot.cli import main
from sefirot.contracts import digest
from sefirot.fixtures import example
from sefirot.odds_provider import event_candidates, quotes_from_event, require_prematch_seal
from sefirot.repository import Repository
from sefirot.service import Service
from test_odds_provider import fixture
from test_market_expansion import expanded_event


INVALID_TRUE = (None, False, 0, 1, 1.0, 'false', 'true', [], [False], {}, {'confirmed': False})
INVALID_FALSE = (None, True, 0, 0.0, 1, '', 'false', [], [False], {}, {'reconstructed': False})


class OddsConfirmationContractTests(unittest.TestCase):
    def test_settlement_confirmation_requires_exact_true_for_both_import_paths(self):
        for keys in (('h2h',), ('h2h', 'btts')):
            for value in INVALID_TRUE:
                p, e, at = expanded_event()
                original = copy.deepcopy((p, e))
                with self.subTest(keys=keys, value=value):
                    with self.assertRaisesRegex(ValueError, 'settlement'):
                        quotes_from_event(e, p, 'soccer_epl', 'event1234', 'testbook', at,
                            rules_confirmed=value, market_keys=keys)
                    self.assertEqual((p, e), original)

    def test_prospective_flags_require_exact_true_and_false_for_all_entrypoints(self):
        for field, values in (('captured_prematch', INVALID_TRUE), ('reconstructed', INVALID_FALSE)):
            for value in values:
                for entry in ('seal', 'directory', 'quotes'):
                    p, e, at = fixture()
                    p[field] = copy.deepcopy(value)
                    original = copy.deepcopy((p, e))
                    with self.subTest(field=field, value=value, entry=entry):
                        with self.assertRaisesRegex(ValueError, 'prematch'):
                            if entry == 'seal':
                                require_prematch_seal(p, at)
                            elif entry == 'directory':
                                event_candidates([e], p, 'soccer_epl', at)
                            else:
                                quotes_from_event(e, p, 'soccer_epl', 'event1234', 'testbook', at,
                                    rules_confirmed=True)
                        self.assertEqual((p, e), original)

    def test_missing_prospective_flags_remain_unknown_and_refuse(self):
        for field in ('captured_prematch', 'reconstructed'):
            p, _, at = fixture()
            del p[field]
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'prematch'):
                require_prematch_seal(p, at)

    def test_valid_boolean_flags_keep_original_receipt_and_source_identity(self):
        p, e, at = fixture()
        out = quotes_from_event(e, p, 'soccer_epl', 'event1234', 'testbook', at,
            rules_confirmed=True)
        self.assertEqual(out['receipt']['provider'], 'THE_ODDS_API_V4')
        self.assertIs(out['receipt']['rules_verified_by_operator'], True)
        self.assertEqual(out['receipt']['available_at_bookmaker'], 'UNVERIFIED')
        self.assertEqual(out['receipt']['quotes_hash'], digest(out['quotes']))
        self.assertEqual(out['receipt']['payload_hash'], digest(e))
        self.assertEqual([q['market']['side'] for q in out['quotes']], ['HOME', 'DRAW', 'AWAY'])
        self.assertEqual(require_prematch_seal(p, at), p['sports']['match'])
        self.assertEqual(event_candidates([e], p, 'soccer_epl', at)['event_id'], 'event1234')

    def test_valid_expanded_flags_preserve_supported_lines_and_unverified_bookmaker(self):
        p, e, at = expanded_event()
        out = quotes_from_event(e, p, 'soccer_epl', 'event1234', 'testbook', at,
            rules_confirmed=True, market_keys=('h2h', 'btts'))
        self.assertEqual(len(out['quotes']), 5)
        self.assertEqual(out['receipt']['provider'], 'THE_ODDS_API_V4')
        self.assertIs(out['receipt']['rules_verified_by_operator'], True)
        self.assertEqual(out['receipt']['available_at_bookmaker'], 'UNVERIFIED')
        self.assertEqual(out['receipt']['rejected_lines'], [])

    def test_cli_refuses_malformed_flags_before_event_or_price_lookup(self):
        with tempfile.TemporaryDirectory(prefix='owned-odds-gate-') as directory:
            root = Path(directory)
            database = root / 'owned.sqlite'
            case = example(at=datetime.now(timezone.utc), match_id='owned-odds-confirmation')
            with closing(Repository(database)) as repo:
                prediction = Service(repo).capture(case['sports'], case['markets'])
            before = database.read_bytes()
            original_get = Repository.get
            for command in ('odds-events', 'fetch-odds'):
                for field, value in (('captured_prematch', 'false'), ('captured_prematch', 1),
                                     ('reconstructed', 0), ('reconstructed', None)):
                    def get(repo, table, key):
                        result = original_get(repo, table, key)
                        if table == 'predictions':
                            result = {**result, field: value}
                        return result
                    args = ['--db', str(database), command, prediction['id'], '--sport', 'soccer_epl']
                    output = root / 'quotes.json'
                    if command == 'fetch-odds':
                        args += ['--event-id', 'event1234', '--bookmaker', 'testbook',
                                 '--rules-confirmed', '--output', str(output)]
                    stdout, stderr = io.StringIO(), io.StringIO()
                    with self.subTest(command=command, field=field, value=value), \
                         patch.object(Repository, 'get', get), \
                         patch('sefirot.odds_provider.events', return_value=[]) as events, \
                         patch('sefirot.odds_provider.event_odds') as odds, \
                         patch('sefirot.odds_provider._api_key', side_effect=AssertionError('credential lookup')) as key, \
                         redirect_stdout(stdout), redirect_stderr(stderr):
                        self.assertEqual(main(args), 2)
                        events.assert_not_called()
                        odds.assert_not_called()
                        key.assert_not_called()
                        self.assertIn('prematch', stdout.getvalue()+stderr.getvalue())
                        self.assertFalse(output.exists())
                        self.assertFalse(Path(str(output)+'.receipt.json').exists())
                        self.assertEqual(database.read_bytes(), before)

    def test_odds_read_commands_never_create_a_missing_ledger_or_parent(self):
        with tempfile.TemporaryDirectory(prefix='owned-missing-odds-') as directory:
            root = Path(directory)
            for command in ('odds-events', 'fetch-odds'):
                database = root / command / 'absent.sqlite'
                args = ['--db', str(database), command, 'absent-prediction', '--sport', 'soccer_epl']
                if command == 'fetch-odds':
                    args += ['--event-id', 'event1234', '--bookmaker', 'testbook',
                             '--rules-confirmed', '--output', str(root/'quotes.json')]
                with self.subTest(command=command), \
                     patch('sefirot.odds_provider.events') as events, \
                     patch('sefirot.odds_provider.event_odds') as odds, \
                     redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    self.assertEqual(main(args), 2)
                    self.assertFalse(database.parent.exists())
                    self.assertEqual(list(root.iterdir()), [])
                    events.assert_not_called()
                    odds.assert_not_called()


if __name__ == '__main__':
    unittest.main()
