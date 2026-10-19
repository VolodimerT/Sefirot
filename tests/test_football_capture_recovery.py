"""Owned CLI recovery checks; no provider, credential or shared-budget access."""
from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from datetime import timedelta
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from scripts import football_enrichment_collect as collector
from sefirot.contracts import digest
from sefirot.football_gateway import SportsBudgetGateError
from tests import test_football_enrichment_collect as base


class CaptureRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.case = base.OneFixtureCollectorTests()
        self.case.setUp()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name) / 'capture.json'
        self.archive = self.output.with_name(self.output.name + '.sources')
        self.originals = []
        self.moment = 1000.0
        self.waits = []
        self.request_times = []

    def sleep(self, delay):
        self.waits.append(delay)
        self.moment += delay

    def getter(self, endpoint, params, **kwargs):
        self.assertEqual(kwargs, {'require_shared_budget': True})
        self.request_times.append(self.moment)
        if endpoint == 'leagues' and self.case.fail_on == 'leagues':
            raise SportsBudgetGateError('MINUTE_LIMIT')
        value = self.case.getter(endpoint, params)
        if endpoint != 'status':
            self.originals.append(deepcopy(value))
        return value

    def run_cli(self, extra=()):
        with patch.object(collector, '_get', side_effect=self.getter), \
                patch('time.sleep', side_effect=self.sleep), \
                patch('time.monotonic', side_effect=lambda: self.moment), \
                redirect_stdout(io.StringIO()) as captured:
            result = collector.main(['--fixture-id', '50001', '--league-id', '39',
                                     '--season', '2026', '--output', str(self.output),
                                     '--execute-single-fixture', *extra])
        return result, json.loads(captured.getvalue())

    def archived(self):
        return [json.loads(p.read_text(encoding='utf-8')) for p in sorted(self.archive.glob('*.json'))]

    def assert_packets_preserved(self):
        saved = self.archived()
        self.assertCountEqual(saved, self.originals)
        for path in self.archive.glob('*.json'):
            self.assertEqual(path.stem, digest(json.loads(path.read_text(encoding='utf-8'))))
        self.assertNotIn('PRIVATE_ACCOUNT_VALUE', ''.join(p.read_text(encoding='utf-8')
                         for p in self.archive.glob('*.json')))

    def test_next_budget_denial_keeps_original_fixture_and_fixed_reason(self):
        self.case.fail_on = 'leagues'
        result, public = self.run_cli()
        self.assertEqual(result, 2)
        self.assertFalse(self.output.exists())
        self.assertEqual(len(self.archived()), 1)
        self.assert_packets_preserved()
        self.assertEqual(public['reason'], 'SHARED_BUDGET_MINUTE_LIMIT')
        self.assertEqual(public['archived_source_packets'], 1)
        self.assertEqual(len(self.request_times), 3)

    def test_later_failure_keeps_base_and_previous_enrichment_packets(self):
        original = self.case.getter
        def fail_later(endpoint, params):
            if len(self.request_times) == 5:
                raise ValueError('PRIVATE_FAILURE_VALUE')
            return original(endpoint, params)
        self.case.getter = fail_later
        result, public = self.run_cli()
        self.assertEqual(result, 2)
        self.assertEqual(len(self.archived()), 3)
        self.assert_packets_preserved()
        self.assertNotIn('PRIVATE_FAILURE_VALUE', json.dumps(public))
        self.assertEqual(len(self.request_times), 5)

    def test_unknown_quota_does_not_discard_an_already_valid_source(self):
        self.case.quota_by_call[2] = {}
        result, _ = self.run_cli()
        self.assertEqual(result, 2)
        self.assertEqual(len(self.archived()), 1)
        self.assert_packets_preserved()
        self.assertEqual(len(self.request_times), 2)

    def test_cli_waits_between_calls_and_flushes_before_next_request(self):
        getter = self.getter
        def observe(endpoint, params, **kwargs):
            if len(self.originals):
                self.assert_packets_preserved()
            return getter(endpoint, params, **kwargs)
        self.getter = observe
        result, public = self.run_cli()
        self.assertEqual(result, 0)
        self.assertEqual(len(self.request_times), 5)
        self.assertTrue(all(b - a >= 61 for a, b in zip(self.request_times, self.request_times[1:])))
        self.assertEqual(len(self.waits), 4)
        self.assert_packets_preserved()
        capture = json.loads(self.output.read_text(encoding='utf-8'))
        self.assertEqual(capture['source_archive']['format'], 'CANONICAL_GATEWAY_JSON')
        self.assertFalse(capture['source_archive']['original_http_bytes_available'])
        self.assertEqual(set(capture['source_archive']['packet_hashes']), {digest(x) for x in self.originals})
        self.assertEqual(public['archived_source_packets'], 4)

    def test_occupied_archive_refuses_before_any_network(self):
        self.archive.mkdir()
        (self.archive / 'original').write_bytes(b'UNCHANGED')
        result, _ = self.run_cli()
        self.assertEqual(result, 2)
        self.assertEqual(self.request_times, [])
        self.assertEqual((self.archive / 'original').read_bytes(), b'UNCHANGED')

    def test_packet_persistence_failure_stops_before_next_provider_call(self):
        with patch('os.fsync', side_effect=OSError('PRIVATE_DISK_ERROR')):
            result, public = self.run_cli()
        self.assertEqual(result, 2)
        self.assertEqual(len(self.request_times), 2)
        self.assertNotIn('PRIVATE_DISK_ERROR', json.dumps(public))

    def test_wait_crossing_prematch_cutoff_stops_before_fetch_and_keeps_packets(self):
        anchor = self.case.now - timedelta(hours=1)
        self.case.now = anchor
        self.case.t = anchor - timedelta(seconds=30)
        self.case.fixture['fixture']['date'] = (anchor + timedelta(seconds=180)).isoformat()
        self.archive.mkdir()
        with patch('time.sleep', side_effect=self.sleep), \
                patch('time.monotonic', side_effect=lambda: self.moment), \
                self.assertRaisesRegex(ValueError, 'prematch collection after kickoff'):
            collector.collect_one(50001, 39, 2026, pace_requests=True,
                getter=lambda endpoint, params: self.getter(endpoint, params, require_shared_budget=True),
                clock=lambda: anchor + timedelta(seconds=self.moment - 1000),
                packet_sink=lambda packet: collector._archive_packet(packet, self.archive))
        self.assertEqual(len(self.request_times), 3)
        self.assertEqual([x[0] for x in self.case.calls], ['status', 'fixtures', 'leagues'])
        self.assert_packets_preserved()
        self.assertEqual(len(self.archived()), 2)

    def test_response_after_kickoff_is_archived_but_never_completed_as_prematch(self):
        anchor = self.case.now - timedelta(hours=1)
        self.case.now = anchor
        self.case.t = anchor - timedelta(seconds=30)
        self.case.fixture['fixture']['date'] = (anchor + timedelta(seconds=200)).isoformat()
        self.archive.mkdir()
        def getter(endpoint, params):
            value = self.getter(endpoint, params, require_shared_budget=True)
            if len(self.request_times) == 4:
                self.moment += 30  # Request at183s; response at213s, after kickoff.
                value['receipt']['received_at'] = (anchor + timedelta(seconds=213)).isoformat()
                self.originals[-1] = deepcopy(value)
            return value
        with patch('time.sleep', side_effect=self.sleep), \
                patch('time.monotonic', side_effect=lambda: self.moment), \
                self.assertRaisesRegex(ValueError, 'prematch collection after kickoff'):
            collector.collect_one(50001, 39, 2026, max_requests=4, pace_requests=True,
                getter=getter, clock=lambda: anchor + timedelta(seconds=self.moment - 1000),
                packet_sink=lambda packet: collector._archive_packet(packet, self.archive))
        self.assertEqual(len(self.request_times), 4)
        self.assertEqual(self.request_times[-1] - 1000, 183)
        self.assert_packets_preserved()
        self.assertEqual(len(self.archived()), 3)

    def test_finished_fixture_still_collects_postmatch_statistics(self):
        self.case.fixture['fixture']['status']['short'] = 'FT'
        self.case.fixture['fixture']['date'] = (self.case.now - timedelta(hours=3)).isoformat()
        self.case.fixture['score'] = {'fulltime': {'home': 2, 'away': 1}}
        result, public = self.run_cli(['--max-requests', '4'])
        self.assertEqual(result, 0)
        self.assertEqual(len(self.request_times), 4)
        self.assertEqual(self.case.calls[-1], ('fixtures/statistics', {'fixture': 50001}))
        self.assertEqual(public['status'], 'COMPLETE_BOUNDED_RESEARCH_OBSERVATIONS')
        self.assert_packets_preserved()


if __name__ == '__main__':
    unittest.main()
