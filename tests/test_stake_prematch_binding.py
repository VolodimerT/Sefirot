"""Owned synthetic counterexamples: no credentials or provider requests."""
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sefirot.stake_provider import exact_event, fixture_markets, research_snapshot
from sefirot import stake_provider as provider
from test_stake_provider import fixture, SequenceOpener


def receipt(start='2030-01-01T10:01:00+00:00', end='2030-01-01T10:02:00+00:00'):
    return {'provider': 'STAKE_GRAPHQL_EXPERIMENTAL', 'provider_host': 'stake.com',
            'endpoint': '/_api/graphql', 'operation_name': 'FixtureGroupMarkets',
            'request_started_at': start, 'received_at': end, 'http_status': 200,
            'payload_hash': 'a' * 64, 'credential_exposed': False,
            'monetary_permission': False}


def market_response(identifier):
    return {'data': {'slugFixture': {'id': identifier, 'groups': []}}}


class StakePrematchBindingTests(unittest.TestCase):
    def test_discovery_and_markets_cannot_change_fixture(self):
        group = {'data': {'slugFixture': {'id': 'EXPECTED', 'groups': [{'name': 'main'}]}}}
        opener = SequenceOpener([group, market_response('OTHER')])
        with self.assertRaisesRegex(ValueError, 'fixture identity'):
            fixture_markets('exact-slug', token='SYNTHETIC', opener=opener)

    def test_market_chunks_cannot_mix_fixtures(self):
        opener = SequenceOpener([market_response('EXPECTED'), market_response('OTHER')])
        with self.assertRaisesRegex(ValueError, 'fixture identity'):
            fixture_markets('exact-slug', groups=[str(i) for i in range(9)],
                            token='SYNTHETIC', opener=opener)
        self.assertEqual(len(opener.requests), 2)

    def test_missing_fixture_identity_is_rejected(self):
        opener = SequenceOpener([market_response(None)])
        with self.assertRaisesRegex(ValueError, 'fixture identity'):
            fixture_markets('exact-slug', groups=['main'], token='SYNTHETIC', opener=opener)

    def test_snapshot_cannot_predate_its_receipt(self):
        p, e, m, at = fixture()
        r = receipt(end='2030-01-01T10:04:00+00:00')
        with self.assertRaisesRegex(ValueError, 'receipt chronology'):
            research_snapshot(e, p, at, m, [r])

    def test_receipt_cannot_cross_kickoff_or_begin_before_seal(self):
        p, e, m, at = fixture()
        for r in (receipt(end=p['sports']['match']['kickoff']),
                  receipt(start='2030-01-01T09:59:00+00:00'),
                  receipt(start='2030-01-01T10:02:30+00:00'),
                  receipt(end='not-a-timestamp')):
            with self.subTest(receipt=r):
                with self.assertRaises(ValueError): research_snapshot(e, p, at, m, [r])

    def test_receipts_are_allowlisted_without_mutating_originals(self):
        p, e, m, at = fixture()
        r = {**receipt(), 'Authorization': 'SYNTHETIC_PRIVATE',
             'headers': {'x-access-token': 'SYNTHETIC_PRIVATE'}, 'credential': 'SYNTHETIC_PRIVATE'}
        original = copy.deepcopy(r)
        out = research_snapshot(e, p, at, m, [r])
        self.assertNotIn('SYNTHETIC_PRIVATE', json.dumps(out))
        self.assertEqual(r, original)
        self.assertEqual(out['retrieval_receipts'][0]['payload_hash'], 'a' * 64)

    def test_wrong_provider_and_unverified_http_receipts_are_rejected(self):
        p, e, m, at = fixture()
        for patch in ({'provider': 'THE_ODDS_API'}, {'provider_host': 'untrusted.invalid'},
                      {'endpoint': '/account'}, {'http_status': 403}, {'payload_hash': 'bad'}):
            with self.subTest(patch=patch):
                with self.assertRaises(ValueError): research_snapshot(e, p, at, m, [{**receipt(), **patch}])

    def test_known_live_event_is_not_a_prematch_match(self):
        p, e, _, at = fixture()
        for status in ('live', 'ended', 'settled'):
            with self.subTest(status=status):
                with self.assertRaises(ValueError): exact_event([{**e, 'status': status}], p, at)

    def test_explicit_expected_fixture_stops_at_wrong_discovery(self):
        group = {'data': {'slugFixture': {'id': 'OTHER', 'groups': [{'name': 'main'}]}}}
        opener = SequenceOpener([group])
        with self.assertRaisesRegex(ValueError, 'fixture identity'):
            fixture_markets('exact', expected_fixture_id='EXPECTED', token='SYNTHETIC', opener=opener)
        self.assertEqual(len(opener.requests), 1)

    def test_cutoff_guard_runs_before_every_market_chunk(self):
        opener = SequenceOpener([market_response('EXPECTED')])
        guard = unittest.mock.Mock(side_effect=[None, ValueError('KICKOFF')])
        with self.assertRaisesRegex(ValueError, 'KICKOFF'):
            fixture_markets('exact', groups=[str(i) for i in range(9)],
                            token='SYNTHETIC', opener=opener, before_request=guard)
        self.assertEqual(len(opener.requests), 1)
        self.assertEqual(guard.call_count, 2)

    def test_snapshot_flow_blocks_expired_prediction_before_any_request(self):
        p, _, _, _ = fixture()
        with patch.object(provider, 'sports_events') as fetch:
            with self.assertRaises(ValueError):
                provider.prematch_snapshot(p, clock=lambda: p['sports']['match']['kickoff'])
        fetch.assert_not_called()

    def test_snapshot_flow_records_completion_time_and_upcoming_only(self):
        p, e, m, at = fixture()
        packet = {'events': [e], 'receipt': receipt()}
        completed = '2030-01-01T10:05:00+00:00'
        market_packet = {'markets': m, 'receipts': [receipt(end='2030-01-01T10:04:00+00:00')]}
        clock = unittest.mock.Mock(side_effect=[at, completed, completed])
        with patch.object(provider, 'sports_events', return_value=packet) as catalogue, \
             patch.object(provider, 'fixture_markets', return_value=market_packet) as markets:
            out = provider.prematch_snapshot(p, first=5, clock=clock)
        self.assertEqual(catalogue.call_args.kwargs['match_type'], 'upcoming')
        self.assertEqual(markets.call_args.kwargs['expected_fixture_id'], e['id'])
        self.assertGreaterEqual(clock.call_count, 2)
        self.assertEqual(out['received_at'], completed)
        self.assertFalse(out['monetary_permission'])

    def test_snapshot_crosses_kickoff_during_catalogue_and_stops_before_groups(self):
        p, e, _, at = fixture()
        clock = unittest.mock.Mock(side_effect=[at, p['sports']['match']['kickoff']])
        with patch.object(provider, 'sports_events', return_value={'events': [e], 'receipt': receipt()}), \
             patch.object(provider, 'fixture_groups') as groups:
            with self.assertRaises(ValueError): provider.prematch_snapshot(p, clock=clock)
        groups.assert_not_called()

    def test_snapshot_flow_rejects_return_after_kickoff(self):
        p, e, m, at = fixture()
        clock = unittest.mock.Mock(side_effect=[at, p['sports']['match']['kickoff'],
                                                p['sports']['match']['kickoff']])
        with patch.object(provider, 'sports_events', return_value={'events': [e], 'receipt': receipt()}), \
             patch.object(provider, 'fixture_markets', return_value={'markets': m, 'receipts': [receipt()]}):
            with self.assertRaises(ValueError): provider.prematch_snapshot(p, clock=clock)

    def test_http_rejection_stops_without_retry(self):
        from urllib.error import HTTPError
        class Denied:
            def __init__(self, code): self.code, self.calls = code, 0
            def open(self, request, timeout):
                self.calls += 1
                raise HTTPError('https://stake.com/', self.code, 'SYNTHETIC_PRIVATE', {}, None)
        for code in (401, 403, 404, 429, 500, 503):
            with self.subTest(code=code):
                opener = Denied(code)
                with self.assertRaises(provider.StakeRequestError) as error:
                    fixture_markets('exact', groups=['main'], token='SYNTHETIC', opener=opener)
                self.assertEqual(opener.calls, 1)
                self.assertEqual(error.exception.http_status, code)
                self.assertNotIn('SYNTHETIC_PRIVATE', str(error.exception))


if __name__ == '__main__':
    unittest.main()
