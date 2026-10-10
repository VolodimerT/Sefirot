"""Offline query/date counterexamples; these are not football experiments."""
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import unittest
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sefirot.football_provider import get
from sefirot.football_query import FootballQueryError, validate_fixture_query
from test_operations_upgrade import packet, row


def payload(params, rows=None):
    data = packet([row(10)] if rows is None else rows)['data']
    data['parameters'] = dict(params)
    return data


def dated(value, zone):
    item = row(10)
    item['fixture'].update(date=value, timezone=zone,
                          timestamp=int(datetime.fromisoformat(value).timestamp()))
    return item


class FixtureQueryContractTests(unittest.TestCase):
    def reject(self, data, params, code):
        original = copy.deepcopy(data)
        with self.assertRaises(FootballQueryError) as error:
            validate_fixture_query(data, params)
        self.assertEqual(error.exception.code, code)
        self.assertEqual(str(error.exception), code)
        self.assertEqual(data, original)

    def test_integer_echo_can_be_string_without_changing_provider_payload(self):
        params = {'id': 10, 'timezone': 'UTC'}
        data = payload(params); data['parameters']['id'] = '10'
        original = copy.deepcopy(data)
        validate_fixture_query(data, params)
        self.assertEqual(data, original)

    def test_timezone_fallback_is_rejected_before_any_row_conversion(self):
        params = {'date': '2026-10-05', 'timezone': 'Europe/Kyiv'}
        data = payload(params, []); data['parameters']['timezone'] = 'UTC'
        self.reject(data, params, 'QUERY_ECHO_MISMATCH')

    def test_endpoint_echo_cannot_be_missing_wrong_or_private(self):
        for endpoint in (None, 'odds', 'PRIVATE_VALUE'):
            data = payload({}, []); data['get'] = endpoint
            self.reject(data, {}, 'ENDPOINT_ECHO_MISMATCH')

    def test_missing_extra_or_composite_echo_is_not_a_match(self):
        params = {'id': 10}
        for echoed in (None, [], {}, {'id': []}, {'id': {}}, {'id': 'PRIVATE_VALUE'},
                       {'id': 10, 'token': 'PRIVATE_VALUE'}):
            data = payload(params, []); data['parameters'] = echoed
            self.reject(data, params, 'QUERY_ECHO_MISMATCH')

    def test_boolean_echo_is_not_an_integer(self):
        data = payload({'id': 1}, []); data['parameters']['id'] = True
        self.reject(data, {'id': 1}, 'QUERY_ECHO_MISMATCH')

    def test_timezone_aliases_are_not_silently_relabelled(self):
        params = {'timezone': 'Europe/Kyiv'}
        data = payload(params, []); data['parameters']['timezone'] = 'Europe/Kiev'
        self.reject(data, params, 'QUERY_ECHO_MISMATCH')

    def test_empty_packet_does_not_hide_invalid_timezone(self):
        for zone in ('Invalid/PRIVATE_VALUE', '', '../UTC', 1):
            params = {'timezone': zone}
            self.reject(payload(params, []), params, 'QUERY_TIMEZONE_UNSUPPORTED')

    def test_empty_packet_does_not_hide_invalid_dates_or_reversed_range(self):
        for params in ({'date': '2026-02-30'}, {'date': '2026-2-01'}, {'date': 1},
                       {'from': 'PRIVATE_VALUE'}, {'to': '2030-01-01T00:00:00Z'},
                       {'from': '2030-01-02', 'to': '2030-01-01'}):
            self.reject(payload(params, []), params, 'QUERY_DATE_INVALID')

    def test_local_calendar_crosses_utc_midnight(self):
        params = {'date': '2026-10-05', 'timezone': 'Europe/Kyiv'}
        item = dated('2026-10-05T00:30:00+03:00', 'Europe/Kyiv')
        self.assertEqual(datetime.fromtimestamp(item['fixture']['timestamp'],
            timezone.utc).date().isoformat(), '2026-10-04')
        validate_fixture_query(payload(params, [item]), params)

    def test_same_utc_day_can_be_outside_requested_kyiv_day(self):
        params = {'date': '2026-10-05', 'timezone': 'Europe/Kyiv'}
        item = dated('2026-10-06T00:30:00+03:00', 'Europe/Kyiv')
        self.reject(payload(params, [item]), params, 'QUERY_RESPONSE_MISMATCH')

    def test_echo_does_not_hide_wrong_response_offset(self):
        params = {'date': '2026-10-05', 'timezone': 'Europe/Kyiv'}
        item = dated('2026-10-05T12:00:00+00:00', 'Europe/Kyiv')
        self.reject(payload(params, [item]), params, 'QUERY_TIMEZONE_RESPONSE_MISMATCH')

    def test_correct_offset_does_not_hide_wrong_timezone_label(self):
        params = {'timezone': 'Europe/Kyiv'}
        item = dated('2026-10-05T12:00:00+03:00', 'UTC')
        self.reject(payload(params, [item]), params, 'QUERY_TIMEZONE_RESPONSE_MISMATCH')

    def test_naive_or_invalid_date_has_a_safe_rejection(self):
        for value in ('2026-10-05T12:00:00', 'PRIVATE_VALUE', None):
            item = row(10); item['fixture']['date'] = value
            self.reject(payload({}, [item]), {}, 'QUERY_RESPONSE_MALFORMED')

    def test_kyiv_spring_and_autumn_offsets_follow_actual_instant(self):
        # Explicit values at both sides of each 2026 transition. Autumn's
        # repeated 03:30 has two different, valid UTC instants.
        values = ['2026-03-29T02:30:00+02:00', '2026-03-29T04:30:00+03:00',
                  '2026-10-25T03:30:00+03:00', '2026-10-25T03:30:00+02:00']
        for value in values:
            params = {'date': value[:10], 'timezone': 'Europe/Kyiv'}
            validate_fixture_query(payload(params, [dated(value, 'Europe/Kyiv')]), params)

    def test_spring_gap_is_rejected_even_when_echo_matches(self):
        params = {'date': '2026-03-29', 'timezone': 'Europe/Kyiv'}
        item = dated('2026-03-29T03:30:00+02:00', 'Europe/Kyiv')
        self.reject(payload(params, [item]), params, 'QUERY_TIMEZONE_RESPONSE_MISMATCH')

    def test_inclusive_range_uses_requested_zone(self):
        params = {'from': '2026-10-05', 'to': '2026-10-06', 'timezone': 'Europe/Kyiv'}
        rows = [dated('2026-10-05T00:00:00+03:00', 'Europe/Kyiv'),
                dated('2026-10-06T23:59:59+03:00', 'Europe/Kyiv')]
        validate_fixture_query(payload(params, rows), params)
        rows.append(dated('2026-10-07T00:00:00+03:00', 'Europe/Kyiv'))
        self.reject(payload(params, rows), params, 'QUERY_RESPONSE_MISMATCH')

    def test_exact_fixture_league_season_team_and_status_scope(self):
        for params in ({'id': 11}, {'ids': '11-12'}, {'league': 10},
                       {'season': 2029}, {'team': 99}, {'status': 'NS'}):
            self.reject(payload(params), params, 'QUERY_RESPONSE_MISMATCH')
        params = {'id': '10', 'ids': '10-11', 'league': 9, 'season': 2030, 'team': 2, 'status': 'FT-AET'}
        validate_fixture_query(payload(params), params)

    def test_utc_z_suffix_and_etc_utc_remain_supported(self):
        for zone in ('UTC', 'Etc/UTC'):
            params = {'date': '2026-10-05', 'timezone': zone}
            item = dated('2026-10-05T12:00:00+00:00', zone)
            item['fixture']['date'] = '2026-10-05T12:00:00Z'
            validate_fixture_query(payload(params, [item]), params)


class DirectFixtureTransportTests(unittest.TestCase):
    def call(self, data, params):
        owner = self; self.closed = False
        class Reply:
            status = 200
            def read(self, limit): return json.dumps(data).encode()[:limit]
        class Connection:
            def __init__(self, host, timeout): owner.host = host
            def request(self, method, path, headers): owner.path = path
            def getresponse(self): return Reply()
            def close(self): owner.closed = True
        return get('fixtures', params, api_key='FICTIONAL_PRIVATE_AUTH', connection_factory=Connection)

    def test_encoded_request_and_receipt_match_original_provider_echo(self):
        params = {'date': '2026-10-05', 'timezone': 'Europe/Kyiv'}
        data = payload(params, [dated('2026-10-05T00:30:00+03:00', 'Europe/Kyiv')])
        out = self.call(data, params)
        self.assertEqual(parse_qs(urlsplit(self.path).query), {k: [v] for k, v in params.items()})
        self.assertIn('timezone=Europe%2FKyiv', self.path)
        self.assertEqual(out['receipt']['parameters'], params); self.assertEqual(out['data'], data)
        self.assertNotIn('FICTIONAL_PRIVATE_AUTH', json.dumps(out)); self.assertTrue(self.closed)

    def test_direct_transport_rejects_fallback_without_retry_and_closes(self):
        params = {'date': '2026-10-05', 'timezone': 'Europe/Kyiv'}
        data = payload(params, []); data['parameters']['timezone'] = 'UTC'
        with self.assertRaises(FootballQueryError) as error:
            self.call(data, params)
        self.assertEqual(error.exception.code, 'QUERY_ECHO_MISMATCH'); self.assertTrue(self.closed)

    def test_direct_transport_rejects_rows_outside_date_before_return(self):
        params = {'date': '2026-10-05', 'timezone': 'Europe/Kyiv'}
        data = payload(params, [dated('2026-10-06T00:30:00+03:00', 'Europe/Kyiv')])
        with self.assertRaises(FootballQueryError) as error:
            self.call(data, params)
        self.assertEqual(error.exception.code, 'QUERY_RESPONSE_MISMATCH'); self.assertTrue(self.closed)

    def test_invalid_calendar_query_never_opens_connection(self):
        for params in ({'timezone':'Invalid/Zone'}, {'date':'2026-02-30'},
                       {'from':'2030-01-02', 'to':'2030-01-01'}):
            with self.assertRaises(FootballQueryError):
                get('fixtures', params, api_key='FICTIONAL_PRIVATE_AUTH',
                    connection_factory=lambda *a,**k:self.fail('network called'))
