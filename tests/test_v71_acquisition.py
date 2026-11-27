"""Exact archive export checks and isolated shared-budget dispatch regressions."""
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from test_football_pipeline import fixture, packet, stats, NOW
from sefirot.contracts import canonical, digest
from sefirot.repository import Repository
from research import football_pipeline as pipeline
from research.football_intelligence_v7.archive_audit import verify_archive
from research.football_intelligence_v7.dispatch import dispatch_once, next_plan


class AcquisitionTest(unittest.TestCase):
    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)

    def store(self, source, *, linked=NOW):
        raw = canonical(source).encode()
        checksum = sha256(raw).hexdigest()
        (self.root / (checksum + '.json')).write_bytes(raw)
        receipt = source['receipt']
        return {'raw_sha256': checksum, 'characters': len(raw.decode()), 'bytes': len(raw),
                'endpoint': receipt['endpoint'], 'received_at': receipt['received_at'],
                'payload_sha256': receipt['payload_hash'], 'imported_at': NOW,
                'links': [{'job_id': '00000000-0000-0000-0000-000000000001',
                           'linked_at': linked, 'attempt': 1}]}

    def audit(self, rows):
        return verify_archive(self.root, {'packets': rows}, as_of=NOW)

    def test_archive_keeps_projection_wire_bytes_but_uses_original_packet(self):
        fixtures = self.store(packet())
        source = {**stats(), 'projection_hash': 'a' * 64, 'schema': 'guarded-probe-evidence-v2'}
        stats_ref = self.store(source)
        out = self.audit([fixtures, stats_ref, stats_ref])
        self.assertEqual(out['accepted_packets'], 2)
        self.assertEqual(out['duplicate_raw_records'], 1)
        league = next(row for row in out['leagues'] if row['league'] == 39)
        self.assertEqual(league['field_coverage']['SHOTS'], 1)
        self.assertEqual(league['field_coverage']['SOT'], 0)
        self.assertEqual(league['field_coverage']['CORNERS'], 1)
        self.assertIsNone(out['pilot']['prematch_seal'])
        self.assertEqual(out['pilot']['decision'], 'PASS')

    def test_late_archive_link_and_wire_damage_are_rejected(self):
        calendar = self.store(packet(), linked='2026-10-17T12:00:01Z')
        source = self.store(stats())
        (self.root / (source['raw_sha256'] + '.json')).write_bytes(b'{}')
        out = self.audit([calendar, source])
        self.assertEqual(out['accepted_packets'], 0)
        self.assertEqual(out['packet_rejections'],
                         {'ARCHIVE_LINK_UNBOUND': 1, 'ARCHIVE_RAW_INTEGRITY': 1})

    def test_kickoff_change_and_wrong_team_statistics_are_excluded(self):
        prior = packet()
        shifted = fixture(20, 'NS')
        shifted['fixture']['date'] = '2026-10-18T15:00:00Z'
        update = packet('fixtures', {'id': 20}, [shifted], '2026-10-17T10:00:00Z')
        wrong = stats()
        wrong['data']['response'][0]['team']['id'] = 19
        wrong['receipt']['payload_hash'] = digest(wrong['data'])
        out = self.audit([self.store(p) for p in (prior, update, wrong)])
        self.assertEqual(out['fixture_observation_issues'],
                         {'FIXTURE_IDENTITY_OR_KICKOFF_CONFLICT':1, 'STATISTICS_TEAM_MISMATCH':1})
        self.assertFalse(any(r['fixture_id'] == 20 for r in out['fixtures']))
        self.assertFalse(out['fixtures'][0]['paired_fields']['SHOTS'])


class DispatchTest(unittest.TestCase):
    selected = ((39, 2026),)
    at = '2026-10-17T12:00:00Z'

    def setUp(self):
        tmp = TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db = Path(tmp.name) / 'sources.sqlite'
        self.repo = Repository(self.db)
        self.addCleanup(self.repo.close)
        pipeline.ingest(self.repo, canonical(packet(at='2026-10-17T11:00:00Z')).encode(), imported_at=NOW)

    def budget(self, **updates):
        return {'enabled': True, 'valid_until': '2026-10-17T14:00:00Z',
                'observed_at': self.at, 'utc_day': '2026-10-17', 'reservation_pending': False,
                'remaining_day': 10, 'reserve_day': 5, 'started_today': 0,
                'minute_ready_at': '2026-10-17T11:59:00Z', **updates}

    @staticmethod
    def transport():
        return {'transport': 'SUPABASE_GATEWAY', 'credential_configured': True}

    def run_dispatch(self, reader, collector, **kwargs):
        return dispatch_once(self.repo, self.selected, reader, clock=lambda: self.at,
                             collector=collector, transport=self.transport, **kwargs)

    def test_expired_enabled_budget_stops_before_io(self):
        def unreachable(*args, **kwargs):
            self.fail('unexpected collector')
        stale = self.budget(valid_until='2026-10-16T12:00:00Z')
        future = next_plan(self.repo, self.selected, stale, at=self.at)
        self.assertEqual(future['budget_block'], 'SHARED_BUDGET_WINDOW_EXPIRED')
        self.assertEqual(future['probe_payload'],
                         {'queries': [{'endpoint': 'fixtures/statistics', 'params': {'fixture': 10}}]})
        outcome = self.run_dispatch(lambda: stale, unreachable, approved=True)
        self.assertEqual(outcome['status'], 'SHARED_BUDGET_WINDOW_EXPIRED')
        self.assertFalse(outcome['network_started'])
        self.assertEqual(pipeline._records(self.repo, pipeline.ATTEMPT), [])

    def test_source_saved_once_and_shared_counter_separate(self):
        def collector(payload, *, packet_sink):
            self.assertEqual(payload['queries'][0]['params'], {'fixture': 10})
            packet_sink(stats(self.at))
            return {'queries': [{'status':'DONE'}], 'shared_budget_required':True}
        budget = iter([self.budget(), self.budget(started_today=2)])
        result = self.run_dispatch(lambda: next(budget), collector, approved=True)
        self.assertEqual(result['status'], 'GATEWAY_RECEIPT_SAVED')
        self.assertEqual(result['provider_receipts'], 1)
        self.assertEqual(result['shared_reservations_delta'], 2)
        self.assertEqual(result['attribution'], 'SHARED_COUNTER_ALL_WORKERS')
        self.assertEqual(next_plan(self.repo, self.selected, self.budget(), at=self.at)['probe_payload'], None)

    def test_uncertain_send_is_parked_until_archive_recovery(self):
        def lost(*args, **kwargs):
            raise TimeoutError()
        result = self.run_dispatch(lambda: self.budget(), lost, approved=True)
        self.assertEqual(result['status'], 'UNCERTAIN_HOLD_FOR_ARCHIVE')
        self.assertEqual(next_plan(self.repo, self.selected, self.budget(),
                                   at=self.at)['queue']['unresolved_queries'], 1)
        self.assertEqual(self.run_dispatch(lambda:self.budget(), lost, approved=True)['status'],
                         'NO_ELIGIBLE_QUERY')
        later = '2026-10-17T12:01:30Z'
        pipeline.ingest(self.repo, canonical(stats(later)).encode(), imported_at=later)
        self.assertEqual(next_plan(self.repo, self.selected, self.budget(),
                                   at=later)['queue']['unresolved_queries'], 0)

    def test_concurrent_workers_do_not_resend_the_same_query(self):
        def worker(_):
            repo = Repository(self.db)
            def lost(*args, **kwargs):
                raise TimeoutError()
            try:
                return dispatch_once(repo, self.selected, self.budget, clock=lambda:self.at,
                                     collector=lost, transport=self.transport, approved=True)
            finally:
                repo.close()
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(worker, range(2)))
        self.assertEqual(sum(r['probe_invoked'] for r in results), 1)
        self.assertEqual(len(pipeline._records(self.repo, pipeline.ATTEMPT)), 1)
