"""Offline filesystem contention must never replace another quote or receipt."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import sys
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sefirot.cli import write_quotes


class QuotePublicationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.quotes = self.root / 'quotes.json'
        self.receipt = Path(str(self.quotes) + '.receipt.json')

    def payload(self, owner='ours'):
        return {'quotes': [{'owner': owner}],
                'receipt': {'owner': owner, 'overround': 1.04}}

    def assert_no_staged_files(self):
        self.assertEqual(list(self.root.glob('.sefirot-*.staged')), [])

    def test_success_publishes_matching_pair_and_cleans_staging(self):
        result = write_quotes(self.quotes, self.payload())
        self.assertEqual(json.loads(self.quotes.read_text()), [{'owner': 'ours'}])
        self.assertEqual(json.loads(self.receipt.read_text())['owner'], 'ours')
        self.assertFalse(result['execution_price_verified'])
        self.assert_no_staged_files()

    def test_either_existing_path_is_unchanged(self):
        for existing in (self.quotes, self.receipt):
            with self.subTest(existing=existing.name):
                existing.write_bytes(b'original bytes')
                with self.assertRaisesRegex(ValueError, 'already exists'):
                    write_quotes(self.quotes, self.payload())
                self.assertEqual(existing.read_bytes(), b'original bytes')
                existing.unlink()
                self.assert_no_staged_files()

    def test_competitor_after_preflight_is_never_overwritten(self):
        original = tempfile.NamedTemporaryFile
        raced = [False]
        def concurrent_write(*args, **kwargs):
            if not raced[0]:
                raced[0] = True
                self.quotes.write_bytes(b'competitor quote')
                self.receipt.write_bytes(b'competitor receipt')
            return original(*args, **kwargs)
        with patch('sefirot.cli.tempfile.NamedTemporaryFile', side_effect=concurrent_write):
            with self.assertRaises(FileExistsError):
                write_quotes(self.quotes, self.payload())
        self.assertEqual(self.quotes.read_bytes(), b'competitor quote')
        self.assertEqual(self.receipt.read_bytes(), b'competitor receipt')
        self.assert_no_staged_files()

    def test_receipt_collision_never_creates_quote(self):
        original = os.link
        def collide(source, target):
            self.receipt.write_bytes(b'competitor receipt')
            return original(source, target)
        with patch('sefirot.cli.os.link', side_effect=collide):
            with self.assertRaises(FileExistsError):
                write_quotes(self.quotes, self.payload())
        self.assertEqual(self.receipt.read_bytes(), b'competitor receipt')
        self.assertFalse(self.quotes.exists())
        self.assert_no_staged_files()

    def test_quote_collision_rolls_back_only_own_receipt(self):
        original = os.link
        def collide(source, target):
            if Path(target) == self.quotes:
                self.assertTrue(self.receipt.exists())
                self.quotes.write_bytes(b'competitor quote')
            return original(source, target)
        with patch('sefirot.cli.os.link', side_effect=collide):
            with self.assertRaises(FileExistsError):
                write_quotes(self.quotes, self.payload())
        self.assertEqual(self.quotes.read_bytes(), b'competitor quote')
        self.assertFalse(self.receipt.exists())
        self.assert_no_staged_files()

    def test_replaced_receipt_is_never_removed_by_failed_owner(self):
        original = os.link
        def collide(source, target):
            if Path(target) == self.quotes:
                self.receipt.unlink()
                self.receipt.write_bytes(b'new competitor receipt')
                self.quotes.write_bytes(b'new competitor quote')
            return original(source, target)
        with patch('sefirot.cli.os.link', side_effect=collide):
            with self.assertRaises(FileExistsError):
                write_quotes(self.quotes, self.payload())
        self.assertEqual(self.receipt.read_bytes(), b'new competitor receipt')
        self.assertEqual(self.quotes.read_bytes(), b'new competitor quote')
        self.assert_no_staged_files()

    def test_io_failure_at_quote_publication_rolls_back_owned_receipt(self):
        original = os.link
        def fail(source, target):
            if Path(target) == self.quotes:
                raise OSError('injected filesystem error')
            return original(source, target)
        with patch('sefirot.cli.os.link', side_effect=fail):
            with self.assertRaisesRegex(OSError, 'injected filesystem'):
                write_quotes(self.quotes, self.payload())
        self.assertFalse(self.receipt.exists())
        self.assertFalse(self.quotes.exists())
        self.assert_no_staged_files()

    def test_unsupported_hardlinks_fail_closed_without_replace_fallback(self):
        with patch('sefirot.cli.os.link', side_effect=OSError('hardlinks unsupported')):
            with self.assertRaisesRegex(OSError, 'hardlinks unsupported'):
                write_quotes(self.quotes, self.payload())
        self.assertEqual(list(self.root.iterdir()), [])

    def test_serialization_failure_cleans_both_staged_files(self):
        payload = self.payload()
        payload['quotes'][0]['price'] = float('nan')
        with self.assertRaises(ValueError):
            write_quotes(self.quotes, payload)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_bad_return_metadata_fails_before_any_file(self):
        payload = self.payload()
        del payload['receipt']['overround']
        with self.assertRaises(KeyError):
            write_quotes(self.quotes, payload)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_two_real_competing_publishers_have_one_matching_winner(self):
        original = os.link
        simultaneous = Barrier(2)
        def coordinated_link(source, target):
            if Path(target) == self.receipt:
                simultaneous.wait(timeout=10)
            return original(source, target)
        def publish(owner):
            try:
                write_quotes(self.quotes, self.payload(owner))
                return ('success', owner)
            except FileExistsError:
                return ('collision', owner)
        with patch('sefirot.cli.os.link', side_effect=coordinated_link):
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(publish, ('first', 'second')))
        winner = [owner for status, owner in results if status == 'success']
        self.assertEqual(len(winner), 1, results)
        self.assertEqual(sum(status == 'collision' for status, _ in results), 1)
        self.assertEqual(json.loads(self.quotes.read_text())[0]['owner'], winner[0])
        self.assertEqual(json.loads(self.receipt.read_text())['owner'], winner[0])
        self.assert_no_staged_files()


if __name__ == '__main__':
    unittest.main()
