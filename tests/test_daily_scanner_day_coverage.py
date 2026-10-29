"""Whole-day retention and adversarial offline archive regressions."""
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
import json
import unittest
from unittest.mock import patch

from sefirot.contracts import digest, time
from sefirot.sports_archive import archive_packets, export_sports
from research.daily_scanner import scan_day

SOURCE = Path(__file__).resolve().parents[1] / 'tests/fixtures/prematch_issue59_source_v2/source.json'


def inputs():
    source = json.loads(SOURCE.read_text(encoding='utf-8'))
    packet = deepcopy(source['packets'][0])
    packet['receipt']['parameters'] = {'date': '2030-01-01', 'timezone': 'UTC'}
    packet['data']['parameters'] = dict(packet['receipt']['parameters'])
    template = packet['data']['response'][0]
    rows = []
    for n, status in enumerate(('NS', 'NS', 'PST')):
        row = deepcopy(template)
        row['fixture'].update(id=900001+n, date=f'2030-01-01T{12+n}:00:00+00:00', status={'short': status})
        row['fixture']['timestamp'] = int(time(row['fixture']['date']).timestamp())
        for side, offset in (('home', 1), ('away', 2)):
            row['teams'][side] = {'id': n*10+offset, 'name': f'Test {n} {side}'}
        rows.append(row)
    packet['data'].update(response=rows, results=len(rows))
    packet['receipt']['payload_hash'] = digest(packet['data'])
    return source, packet


def run(packet, directory, **kwargs):
    return scan_day(calendar=packet, archive=directory, day='2030-01-01',
                    at='2030-01-01T09:00:00+00:00', profile='LOWER', synthetic=True, **kwargs)


class DayCoverageTests(unittest.TestCase):
    def assert_full_pass(self, result):
        self.assertEqual([f['fixture_id'] for f in result['fixtures']], [900001, 900002, 900003])
        self.assertEqual(result['decision'], 'PASS')
        self.assertEqual(result['candidates'], [])
        self.assertEqual(result['fixture_counts'], {'calendar': 3, 'reported': 3, 'prematch': 2, 'excluded_prematch': 1})
        for fixture in result['fixtures']:
            self.assertEqual(len(fixture['markets']), 7)
            self.assertTrue(all(m['status']=='PASS' and m['model_probability'] is None and m['ev'] is None
                                for m in fixture['markets']+fixture['small_markets']))
        self.assertFalse(result['monetary_permission'])
        self.assertEqual(result['ledger_writes'], 0)

    def test_all_calendar_fixtures_retained_including_postponed(self):
        _, packet = inputs()
        with TemporaryDirectory() as tmp:
            archive_packets([packet], tmp, '2030-01-01T09:00:00+00:00')
            one, two = run(packet, tmp), run(packet, tmp)
        self.assert_full_pass(one)
        self.assertEqual(one, two)
        self.assertIn('PREMATCH_ONLY', one['fixtures'][2]['blockers'])

    def test_missing_archive_does_not_erase_valid_calendar(self):
        _, packet = inputs()
        with TemporaryDirectory() as tmp:
            missing = Path(tmp)/'absent'
            result = run(packet, missing)
            self.assertFalse(missing.exists())
        self.assert_full_pass(result)
        self.assertEqual(result['calendar_status'], 'STRUCTURALLY_COMPLETE_LOCAL_RECEIPT')
        self.assertEqual(result['archive_status'], 'REJECTED')
        self.assertIn('ARCHIVE_UNAVAILABLE_OR_INVALID', result['blockers'])

    def test_corrupt_archive_keeps_calendar_and_never_reads_ledger(self):
        _, packet = inputs()
        with TemporaryDirectory() as tmp:
            archive_packets([packet], tmp, '2030-01-01T09:00:00+00:00')
            (Path(tmp)/('a'*64+'.json')).write_text('{', encoding='utf-8')
            with patch('research.daily_scanner.Repository', side_effect=AssertionError('LEDGER_MUST_NOT_OPEN')):
                result = run(packet, tmp, database=Path(tmp)/'unused.sqlite')
        self.assert_full_pass(result)
        self.assertEqual(result['archive_status'], 'REJECTED')
        self.assertEqual(result['ledger_status'], 'NOT_READ_INPUT_REJECTED')

    def test_calendar_not_in_archive_keeps_fixtures_but_blocks_models(self):
        source, packet = inputs()
        with TemporaryDirectory() as tmp:
            archive_packets(source['packets'], tmp, '2030-01-01T09:00:00+00:00')
            result = run(packet, tmp)
        self.assert_full_pass(result)
        self.assertEqual(result['archive_status'], 'REJECTED')

    def test_one_export_io_error_does_not_abort_the_day(self):
        _, packet = inputs()
        def export(directory, fid, at, **kwargs):
            if fid==900001:
                raise OSError('OWNED_TEST_IO_ERROR')
            return export_sports(directory, fid, at, **kwargs)
        with TemporaryDirectory() as tmp:
            archive_packets([packet], tmp, '2030-01-01T09:00:00+00:00')
            with patch('research.daily_scanner.export_sports', side_effect=export):
                result = run(packet, tmp)
        self.assert_full_pass(result)
        self.assertIn('SPORTS_EXPORT_OR_IDENTITY_FAILED', result['fixtures'][0]['blockers'])
        self.assertIsNotNone(result['fixtures'][1]['coverage'])

    def test_invalid_prices_container_is_an_explicit_pass(self):
        _, packet = inputs()
        with TemporaryDirectory() as tmp:
            archive_packets([packet], tmp, '2030-01-01T09:00:00+00:00')
            with patch('research.daily_scanner.Repository', side_effect=AssertionError('LEDGER_MUST_NOT_OPEN')):
                result = run(packet, tmp, prices=['INVALID'], database=Path(tmp)/'unused.sqlite')
        self.assert_full_pass(result)
        self.assertIn('PRICES_INPUT_INVALID', result['blockers'])
        self.assertEqual(result['ledger_status'], 'NOT_READ_INPUT_REJECTED')

    def test_empty_provider_day_is_explicit_zero_not_data_loss(self):
        _, packet = inputs()
        packet['data'].update(response=[], results=0)
        packet['receipt']['payload_hash'] = digest(packet['data'])
        with TemporaryDirectory() as tmp:
            archive_packets([packet], tmp, '2030-01-01T09:00:00+00:00')
            result = run(packet, tmp)
        self.assertEqual(result['calendar_status'], 'STRUCTURALLY_COMPLETE_LOCAL_RECEIPT')
        self.assertEqual(result['fixture_counts'], {'calendar': 0, 'reported': 0, 'prematch': 0, 'excluded_prematch': 0})
        self.assertEqual(result['decision'], 'PASS')

    def test_future_changed_results_never_affect_earlier_sports(self):
        source = json.loads(SOURCE.read_text(encoding='utf-8'))
        packet = deepcopy(source['packets'][0])
        packet['receipt']['parameters'] = {'date': '2030-01-01'}
        packet['data']['parameters'] = dict(packet['receipt']['parameters'])
        packet['receipt']['payload_hash'] = digest(packet['data'])
        future = deepcopy(source['packets'][1])
        future['data']['response'][0]['score']['fulltime'] = {'home': 49, 'away': 48}
        future['receipt']['payload_hash'] = digest(future['data'])
        future['receipt'].update(request_started_at='2030-01-02T08:00:00+00:00', received_at='2030-01-02T09:00:00+00:00')
        if 'upstream_received_at' in future['receipt']:
            future['receipt']['upstream_received_at'] = '2030-01-02T08:30:00+00:00'
        with TemporaryDirectory() as tmp:
            archive_packets(source['packets']+[packet], tmp, source['capture_at'])
            before = run(packet, tmp)
            archive_packets([future], tmp, '2030-01-02T10:00:00+00:00')
            after = run(packet, tmp)
        self.assertEqual(after['excluded_future_packets'], 1)
        self.assertEqual(before['fixtures'], after['fixtures'])


if __name__=='__main__':
    unittest.main()
