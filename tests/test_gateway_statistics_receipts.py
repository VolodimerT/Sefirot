"""Real gateway receipt shape with mocked I/O; never provider/model evidence."""
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src'), str(ROOT / 'scripts')]
import chat_sports_probe as probe
from sefirot import football_gateway
from sefirot.contracts import digest
from sefirot.small_market import validate_statistics_packet
from research.small_source_adapter import import_api_archive
from test_small_source_adapter import inputs, stats, raw, IMPORT
from test_operations_upgrade import stamp


def gateway(packet):
    packet = deepcopy(packet)
    packet['receipt'].update(transport='SUPABASE_GATEWAY',
                             upstream_received_at=packet['receipt']['received_at'])
    return packet


def collect(packet):
    # Probe request schema uses integer IDs; match the SDK's resulting receipt.
    packet = deepcopy(packet)
    params = {k: int(v) for k, v in packet['receipt']['parameters'].items()}
    packet['receipt']['parameters'] = params
    packet['data']['parameters'] = deepcopy(params)
    packet['receipt']['payload_hash'] = digest(packet['data'])
    endpoint = packet['receipt']['endpoint'].lstrip('/')
    with patch.object(probe, 'get_sports', return_value=packet), \
         patch.object(probe, 'transport_status', return_value={}):
        return probe.collect({'queries': [{'endpoint': endpoint,
            'params': packet['receipt']['parameters']}]})['queries'][0]


class GatewayStatisticsReceiptTests(unittest.TestCase):
    def test_current_gateway_packet_passes_statistics_validator_unchanged(self):
        p = gateway(stats()); original = deepcopy(p)
        self.assertEqual(validate_statistics_packet(p), 10)
        self.assertEqual(p, original)

    def test_actual_sdk_output_passes_validator_without_stripping_receipt(self):
        p = stats()
        wrapper = {'ok': True, 'provider': 'API_FOOTBALL_V3',
                   'provider_host': 'v3.football.api-sports.io',
                   'endpoint': '/fixtures/statistics', 'params': {'fixture': '10'},
                   'sports_only': True, 'monetary_permission': False,
                   'execution_enabled': False, 'shared_budget_guard': 'POSTGRES_RESERVATION_V1',
                   'received_at': p['receipt']['received_at'], 'data': p['data']}
        class Reply:
            status = 200
            closed = False
            def read(self, size): return json.dumps(wrapper).encode()
            def close(self): self.closed = True
        reply = Reply()
        clock = iter([datetime.fromisoformat(p['receipt']['request_started_at']),
                      datetime.fromisoformat(p['receipt']['received_at'])])
        with patch.dict(os.environ, {'SEFIROT_SPORTS_GATEWAY_URL':
                'https://' + 'a'*20 + '.supabase.co/functions/v1/sefirot-sports-gateway'}), \
             patch.object(football_gateway, 'credential', return_value='SYNTHETIC_TEST_ONLY'):
            packet = football_gateway.get_sports('fixtures/statistics', {'fixture': '10'},
                     opener=lambda *a, **k: reply, clock=lambda: next(clock), require_shared_budget=True)
        self.assertTrue(reply.closed)
        self.assertEqual(validate_statistics_packet(packet), 10)
        self.assertEqual(packet['receipt']['transport'], 'SUPABASE_GATEWAY')

    def test_gateway_packets_import_with_same_counts_and_no_fit(self):
        m, s, t = inputs()
        schedule = raw(gateway(json.loads(s)))
        m['source_sha256'] = hashlib.sha256(schedule).hexdigest()
        statistical = raw(gateway(json.loads(t[0])))
        r = import_api_archive(m, schedule, [statistical], IMPORT, IMPORT)
        self.assertEqual(r['batch']['observations'][0]['counts']['FT']['CORNERS'], {'home': 0, 'away': 0})
        self.assertEqual(r['binding']['observations'][0]['statistic_packet_sha256'],
                         hashlib.sha256(statistical).hexdigest())
        self.assertFalse(r['fit_allowed']); self.assertFalse(r['holdout_eligible'])
        self.assertFalse(r['monetary_permission'])

    def test_probe_preserves_required_sports_receipt_marker(self):
        p = gateway(stats()); before = deepcopy(p)
        q = collect(p)
        self.assertIs(q['source_packet']['receipt'].get('sports_only'), True)
        self.assertEqual(q['source_packet']['receipt']['request_started_at'], p['receipt']['request_started_at'])
        self.assertEqual(p, before)

    def test_probe_packets_remain_importable_as_exact_data_receipt_envelopes(self):
        m, s, t = inputs()
        q_schedule = collect(gateway(json.loads(s)))
        q_stats = collect(gateway(json.loads(t[0])))
        def envelope(q):
            self.assertEqual(probe.verify_evidence(q)['status'], 'CANONICAL_PACKET_ARCHIVED')
            saved = q['source_packet']
            return raw({'data': saved['data'], 'receipt': saved['receipt']})
        schedule, statistical = envelope(q_schedule), envelope(q_stats)
        m['source_sha256'] = hashlib.sha256(schedule).hexdigest()
        r = import_api_archive(m, schedule, [statistical], IMPORT, IMPORT)
        self.assertEqual(len(r['batch']['observations']), 1)
        self.assertFalse(r['binding']['source_attested'])
        self.assertFalse(r['monetary_permission'])

    def test_probe_missing_sports_marker_is_not_complete_archived_receipt(self):
        p = gateway(stats()); p['receipt'].pop('sports_only')
        q = collect(p)
        self.assertNotIn('source_packet', q)
        self.assertEqual(q['source_evidence']['status'], 'SOURCE_NOT_ARCHIVED')

    def test_probe_missing_request_time_is_not_complete_archived_receipt(self):
        p = gateway(stats()); p['receipt'].pop('request_started_at')
        self.assertNotIn('source_packet', collect(p))

    def test_probe_missing_upstream_time_is_not_complete_archived_receipt(self):
        p = gateway(stats()); p['receipt'].pop('upstream_received_at')
        self.assertNotIn('source_packet', collect(p))

    def test_probe_impossible_chronology_is_not_archived(self):
        p = gateway(stats()); p['receipt']['upstream_received_at'] = stamp(2)
        self.assertNotIn('source_packet', collect(p))

    def test_integer_http_status_required_for_statistics(self):
        p = stats(); p['receipt']['http_status'] = 200.0
        with self.assertRaises(ValueError): validate_statistics_packet(p)

    def test_legacy_direct_statistics_remain_compatible(self):
        p = stats()
        self.assertEqual(validate_statistics_packet(p), 10)
        self.assertNotIn('transport', p['receipt'])

    def test_partial_foreign_or_impossible_gateway_receipts_fail(self):
        mutations = [lambda r: r.pop('upstream_received_at'), lambda r: r.pop('transport'),
                     lambda r: r.update(transport='DIRECT'),
                     lambda r: r.update(upstream_received_at=stamp(-2)),
                     lambda r: r.update(upstream_received_at=stamp(2))]
        for change in mutations:
            p = gateway(stats()); change(p['receipt'])
            with self.subTest(receipt=p['receipt']), self.assertRaises(ValueError):
                validate_statistics_packet(p)

    def test_unknown_receipt_fields_and_wrong_sports_marker_fail(self):
        for extra in ({'authorization': 'SYNTHETIC_TEST_ONLY'}, {'sports_only': 1}):
            p = gateway(stats()); p['receipt'].update(extra)
            with self.subTest(extra=extra), self.assertRaises(ValueError): validate_statistics_packet(p)

    def test_numeric_whitelisted_quota_retained_without_mutation(self):
        p = gateway(stats()); p['receipt']['quota'] = {'x-requests-remaining': '17'}
        before = deepcopy(p)
        self.assertEqual(validate_statistics_packet(p), 10)
        self.assertEqual(p, before)

    def test_invalid_quota_cannot_pass_as_receipt(self):
        for value in ({'authorization': 'SYNTHETIC_TEST_ONLY'}, {'x-requests-remaining': 17},
                      {'x-requests-remaining': '-1'}, ['17']):
            p = stats(); p['receipt']['quota'] = value
            with self.subTest(quota=value), self.assertRaises(ValueError): validate_statistics_packet(p)

    def test_older_schema_is_not_silently_upgraded(self):
        q = collect(gateway(stats()))
        q['source_packet']['schema'] = 'guarded-probe-evidence-v1'
        q['source_packet_hash'] = digest(q['source_packet'])
        before = deepcopy(q)
        self.assertEqual(probe.verify_evidence(q)['status'], 'SOURCE_IDENTITY_MISMATCH')
        self.assertEqual(q, before)

    def test_current_archive_has_explicit_v2_schema(self):
        q = collect(gateway(stats()))
        self.assertEqual(q['source_packet']['schema'], 'guarded-probe-evidence-v2')
        self.assertFalse(q['source_evidence']['model_fit_eligible'])


if __name__ == '__main__': unittest.main()
