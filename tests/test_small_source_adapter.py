"""Synthetic archive contracts; these are not source or model validation."""
from contextlib import redirect_stdout, redirect_stderr
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'src'))
from research.small_source_adapter import import_api_archive, decode_packet, MAX_PACKET_BYTES
from research.small_observation_v2 import record_hash
from scripts.small_source_import import main
from test_operations_upgrade import packet, row, reseal, stamp

IMPORT = stamp(1)


def raw(value, indent=None):
    return json.dumps(value, ensure_ascii=False, indent=indent).encode('utf-8')


def inputs():
    p = packet([row(10, score=(1, 1)), row(11, home=3, away=4)], -1)
    p['receipt']['parameters'] = {'league': '9', 'season': '2030'}
    p['data']['parameters'] = {'league': '9', 'season': '2030'}
    schedule = raw(reseal(p))
    manifest = {'schema': 'small-league-manifest-v1', 'provider': 'API_FOOTBALL_V3',
                'competition_id': 'api-football:league:9', 'season': '2030',
                'competition_type': 'LEAGUE', 'registered_at': stamp(-1),
                'source_sha256': hashlib.sha256(schedule).hexdigest(),
                'pagination_complete': True, 'license_ref': 'SYNTHETIC_TEST_ONLY',
                'team_ids': [f'api-football:team:{i}' for i in range(1, 5)],
                'fixtures': [{'fixture_id': f"api-football:fixture:{r['fixture']['id']}",
                              'home_id': f"api-football:team:{r['teams']['home']['id']}",
                              'away_id': f"api-football:team:{r['teams']['away']['id']}",
                              'kickoff': r['fixture']['date'], 'status': 'FT', 'venue': 'HOME'}
                             for r in p['data']['response']]}
    return manifest, schedule, [raw(stats())]


def stats(fid=10, at=-.5, counts=(4, 3), teams=(1, 2)):
    rows = [{'team': {'id': tid, 'name': 'Synthetic'},
             'statistics': [{'type': label, 'value': value} for label, value in (
                 ('Corner Kicks', 0), ('Total Shots', 12), ('Shots on Goal', 3),
                 ('Yellow Cards', count), ('Red Cards', 0), ('Fouls', 11))]}
            for tid, count in zip(teams, counts)]
    p = packet(rows, at)
    p['receipt'].update(endpoint='/fixtures/statistics', parameters={'fixture': str(fid)})
    p['data'].update(get='fixtures/statistics', parameters={'fixture': str(fid)})
    return reseal(p)


class SourceAdapterTests(unittest.TestCase):
    def run_import(self, values=None, **kw):
        return import_api_archive(*(values or inputs()), kw.get('imported_at', IMPORT),
                                  kw.get('evaluated_at', IMPORT))

    def changed_schedule(self, change):
        m, s, stats_raw = inputs()
        p = json.loads(s)
        change(p)
        s = raw(reseal(p))
        m['source_sha256'] = hashlib.sha256(s).hexdigest()
        return m, s, stats_raw

    def metric(self, report, metric='CORNERS', period='FT'):
        return next(x for x in report['coverage']['markets'] if x['metric'] == metric and x['period'] == period)

    def test_end_to_end_expected_calendar_retains_missing_fixture(self):
        r = self.run_import()
        self.assertEqual(self.metric(r)['eligible_denominator'], 2)
        self.assertEqual(self.metric(r)['known_fixtures'], 1)
        self.assertEqual(self.metric(r)['missing_fixture_ids'], ['api-football:fixture:11'])

    def test_zero_null_and_unverified_scores_remain_distinct(self):
        r = self.run_import()
        counts = r['batch']['observations'][0]['counts']
        self.assertEqual(counts['FT']['CORNERS']['home'], 0)
        self.assertIsNone(counts['1H']['CORNERS']['home'])
        self.assertFalse(r['fit_allowed']); self.assertFalse(r['monetary_permission'])
        self.assertFalse(r['binding']['source_attested']); self.assertFalse(r['holdout_eligible'])
        self.assertIsNone(self.metric(r)['verified_coverage'])
        self.assertIsNone(self.metric(r)['probability']); self.assertIsNone(self.metric(r)['ev'])
        self.assertEqual(r['coverage']['cohorts'], {'TRAIN': 0, 'CALIBRATION': 0, 'HOLDOUT': 0})

    def test_cards_not_score_and_fouls_not_referee(self):
        r = self.run_import()
        o = r['batch']['observations'][0]
        self.assertEqual(o['counts']['FT']['YELLOW_CARDS'], {'home': 4, 'away': 3})
        self.assertNotIn('goals', o)
        self.assertIsNone(o['referee'])
        for m in ('FOULS_COMMITTED', 'SECOND_YELLOW', 'BOOKING_POINTS'):
            self.assertIsNone(o['metric_definitions'][m])
            self.assertEqual(o['counts']['FT'][m], {'home': None, 'away': None})
        self.assertIn('REFEREE_EVIDENCE_MISSING', self.metric(r, 'YELLOW_CARDS')['blockers'])

    def test_exact_saved_byte_hash_and_json_pointers(self):
        m, s, stats_raw = inputs()
        r = self.run_import((m, s, stats_raw))
        b = r['binding']['observations'][0]
        self.assertEqual(b['statistic_packet_sha256'], hashlib.sha256(stats_raw[0]).hexdigest())
        self.assertEqual(b['schedule_sha256'], hashlib.sha256(s).hexdigest())
        self.assertEqual(b['schedule_row_pointer'], '/data/response/0')
        self.assertEqual(b['statistic_team_pointers']['home'], '/data/response/0')
        self.assertEqual(b['emitted_normalized_sha256'], record_hash(r['batch']['observations'][0]))
        self.assertTrue(r['binding']['saved_packet_bytes_bound'])
        self.assertFalse(r['binding']['original_http_bytes_bound'])

    def test_replay_deterministic_and_does_not_mutate_inputs(self):
        values = inputs(); before = deepcopy(values)
        self.assertEqual(self.run_import(values), self.run_import(values))
        self.assertEqual(values, before)

    def test_saved_bytes_cannot_inherit_historical_availability(self):
        r = self.run_import(); o = r['batch']['observations'][0]
        self.assertEqual(o['available_at'], IMPORT)
        self.assertEqual(o['received_at'], IMPORT)
        self.assertEqual(o['published_at'], stamp(-.5))
        with self.assertRaisesRegex(ValueError, 'CUTOFF_PRECEDES_LOCAL_IMPORT'):
            self.run_import(evaluated_at=stamp())

    def test_old_provider_receipt_is_not_license_attestation(self):
        r = self.run_import()
        self.assertFalse(r['binding']['license_verified'])
        self.assertFalse(r['binding']['manifest_completeness_attested'])
        self.assertIn('INDEPENDENT_NEW_HOLDOUT', r['missing_inputs'])

    def test_missing_license_blocks_import(self):
        m, s, stats_raw = inputs(); m['license_ref'] = None
        with self.assertRaisesRegex(ValueError, 'LICENSE_REFERENCE_REQUIRED'):
            self.run_import((m, s, stats_raw))

    def test_unknown_venue_not_guessed(self):
        m, s, stats_raw = inputs(); m['fixtures'][0]['venue'] = 'UNKNOWN'
        with self.assertRaises(ValueError): self.run_import((m, s, stats_raw))

    def test_neutral_venue_preserved_as_operator_assertion(self):
        m, s, stats_raw = inputs(); m['fixtures'][0]['venue'] = 'NEUTRAL'
        r = self.run_import((m, s, stats_raw))
        self.assertEqual(r['batch']['observations'][0]['venue'], 'NEUTRAL')
        self.assertEqual(r['binding']['venue_provenance'], 'EXPECTED_MANIFEST_OPERATOR_ASSERTION')

    def test_team_filter_cannot_impersonate_full_league(self):
        d = self.changed_schedule(lambda p: (p['receipt']['parameters'].update(team='1'),
                                             p['data']['parameters'].update(team='1')))
        with self.assertRaisesRegex(ValueError, 'UNFILTERED_QUERY'): self.run_import(d)

    def test_schedule_partial_rows_and_foreign_rows_rejected(self):
        m, s, stats_raw = inputs(); m['fixtures'].pop()
        with self.assertRaisesRegex(ValueError, 'NOT_IN_EXPECTED'): self.run_import((m, s, stats_raw))
        m, s, stats_raw = inputs(); p = json.loads(s); p['data']['response'].pop(); p['data']['results'] = 1
        s = raw(reseal(p)); m['source_sha256'] = hashlib.sha256(s).hexdigest()
        with self.assertRaisesRegex(ValueError, 'SCHEDULE_FIXTURES_MISSING'):
            self.run_import((m, s, stats_raw))

    def test_schedule_partial_page_rejected(self):
        d = self.changed_schedule(lambda p: p['data']['paging'].update(total=2))
        with self.assertRaises(ValueError): self.run_import(d)

    def test_wrong_season_or_league_rejected(self):
        for field, value in (('season', 2029), ('id', 20)):
            d = self.changed_schedule(lambda p: p['data']['response'][0]['league'].update({field: value}))
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'FOREIGN_LEAGUE'):
                self.run_import(d)

    def test_manifest_teams_and_kickoff_must_match_raw(self):
        for field, value in (('home_id', 'api-football:team:3'), ('kickoff', stamp(-47))):
            m, s, stats_raw = inputs(); m['fixtures'][0][field] = value
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, 'IDENTITY_MISMATCH'):
                self.run_import((m, s, stats_raw))

    def test_schedule_byte_tamper_even_with_canonical_payload_hash(self):
        m, s, stats_raw = inputs(); s += b'\n'
        with self.assertRaisesRegex(ValueError, 'RAW_SCHEDULE_HASH'): self.run_import((m, s, stats_raw))

    def test_query_echo_conflict_rejected(self):
        d = self.changed_schedule(lambda p: p['data']['parameters'].update(league='99'))
        with self.assertRaisesRegex(ValueError, 'QUERY_ECHO'): self.run_import(d)

    def test_provider_errors_never_become_data(self):
        d = self.changed_schedule(lambda p: p['data'].update(errors={'access': 'account suspended'}))
        with self.assertRaises(ValueError): self.run_import(d)

    def test_foreign_team_and_fixture_rejected(self):
        for p in (stats(teams=(99, 2)), stats(fid=99)):
            m, s, _ = inputs()
            with self.assertRaises(ValueError): self.run_import((m, s, [raw(p)]))

    def test_live_aet_and_void_never_supply_ft_counts(self):
        for status, normalized in (('1H', 'LIVE'), ('AET', 'AET'), ('CANC', 'VOID')):
            m, s, stats_raw = self.changed_schedule(lambda p: p['data']['response'][0]['fixture']['status'].update(short=status))
            m['fixtures'][0]['status'] = normalized
            with self.subTest(status=status), self.assertRaisesRegex(ValueError, 'REGULATION_FT'):
                self.run_import((m, s, stats_raw))

    def test_unknown_status_rejected_without_guess(self):
        d = self.changed_schedule(lambda p: p['data']['response'][0]['fixture']['status'].update(short='TBD'))
        with self.assertRaisesRegex(ValueError, 'UNSUPPORTED_PROVIDER_STATUS'): self.run_import(d)

    def test_statistics_before_ft_receipt_rejected(self):
        m, s, _ = inputs()
        with self.assertRaisesRegex(ValueError, 'REQUESTED_AFTER_FT'):
            self.run_import((m, s, [raw(stats(at=-2))]))

    def test_statistics_future_receipt_rejected(self):
        m, s, _ = inputs()
        with self.assertRaisesRegex(ValueError, 'AFTER_LOCAL_IMPORT'):
            self.run_import((m, s, [raw(stats(at=2))]))

    def test_half_or_team_or_type_filter_rejected(self):
        for key, value in (('half', 'true'), ('team', '1'), ('type', 'Corner Kicks')):
            m, s, _ = inputs(); p = stats()
            p['receipt']['parameters'][key] = value; p['data']['parameters'][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.run_import((m, s, [raw(reseal(p))]))

    def test_invalid_red_card_count_rejected(self):
        for value in (-1, True, '0', 1.5):
            m, s, _ = inputs(); p = stats()
            p['data']['response'][0]['statistics'][4]['value'] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.run_import((m, s, [raw(reseal(p))]))

    def test_sot_cannot_exceed_shots(self):
        m, s, _ = inputs(); p = stats(); p['data']['response'][0]['statistics'][2]['value'] = 20
        with self.assertRaisesRegex(ValueError, 'SOT_EXCEEDS_SHOTS'):
            self.run_import((m, s, [raw(reseal(p))]))

    def test_empty_and_one_sided_stats_not_filled(self):
        m, s, _ = inputs(); p = stats(); p['data']['response'] = []; p['data']['results'] = 0
        r = self.run_import((m, s, [raw(reseal(p))]))
        self.assertEqual(self.metric(r)['known_fixtures'], 0)
        p = stats(); p['data']['response'].pop(); p['data']['results'] = 1
        with self.assertRaisesRegex(ValueError, 'BOTH_STATISTIC_TEAMS'):
            self.run_import((m, s, [raw(reseal(p))]))

    def test_duplicate_packets_do_not_multiply_fixtures(self):
        m, s, raws = inputs(); r = self.run_import((m, s, raws * 3))
        self.assertEqual(r['binding']['duplicate_packets'], 2)
        self.assertEqual(len(r['batch']['observations']), 1)
        self.assertEqual(self.metric(r)['known_fixtures'], 1)

    def test_correction_uses_latest_snapshot_without_forward_fill(self):
        m, s, raws = inputs(); p = stats(at=0, counts=(5, 3))
        p['data']['response'][0]['statistics'][0]['value'] = None
        raws.append(raw(reseal(p))); r = self.run_import((m, s, raws))
        o = r['batch']['observations'][0]
        self.assertEqual(o['counts']['FT']['YELLOW_CARDS']['home'], 5)
        self.assertIsNone(o['counts']['FT']['CORNERS']['home'])
        self.assertEqual((o['revision'], o['supersedes_sha256']), (0, None))
        self.assertEqual(r['binding']['archived_statistic_revisions'], 1)
        self.assertEqual([x['emitted'] for x in r['binding']['observations']], [False, True])
        self.assertEqual(self.metric(r)['known_fixtures'], 0)
        self.assertEqual(r, self.run_import((m, s, list(reversed(raws)))))

    def test_simultaneous_conflict_fails_closed(self):
        m, s, raws = inputs(); raws.append(raw(stats(counts=(5, 3))))
        with self.assertRaisesRegex(ValueError, 'SIMULTANEOUS_STATISTIC_CONFLICT'):
            self.run_import((m, s, raws))

    def test_equivalent_serializations_are_deterministic(self):
        m, s, raws = inputs(); raws.append(raw(json.loads(raws[0]), 2))
        self.assertEqual(self.run_import((m, s, raws)), self.run_import((m, s, list(reversed(raws)))))

    def test_strict_json_rejects_duplicate_nan_and_bad_encoding(self):
        for b in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e309}', b'\xff', b'[]'):
            with self.subTest(raw=b), self.assertRaises(ValueError): decode_packet(b)

    def test_bounded_packet_and_archive_types(self):
        for b in (b'', b' ' * (MAX_PACKET_BYTES + 1), 'not bytes'):
            with self.assertRaises(ValueError): decode_packet(b)
        m, s, _ = inputs()
        with self.assertRaises(ValueError): self.run_import((m, s, 'bad'))

    def test_explicit_raw_cup_rejected(self):
        d = self.changed_schedule(lambda p: p['data']['response'][0]['league'].update(type='Cup'))
        with self.assertRaisesRegex(ValueError, 'RAW_CUP_NOT_A_LEAGUE'): self.run_import(d)

    def test_no_network_or_core_write(self):
        with patch('sefirot.football_provider.request_json', side_effect=AssertionError('NETWORK')) as network:
            r = self.run_import()
        network.assert_not_called()
        self.assertEqual((r['network_requests'], r['core_writes']), (0, 0))

    def test_cli_exclusive_output_and_current_import_time(self):
        m, s, raws = inputs()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'm.json').write_text(json.dumps(m), encoding='utf-8')
            (root / 's.json').write_bytes(s); (root / 't.json').write_bytes(raws[0])
            args = ['--manifest', str(root / 'm.json'), '--schedule', str(root / 's.json'),
                    '--statistics', str(root / 't.json'), '--output', str(root / 'out.json')]
            with patch('scripts.small_source_import.datetime') as clock, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                clock.now.return_value.isoformat.return_value = IMPORT
                self.assertEqual(main(args), 0)
                before = (root / 'out.json').read_bytes()
                self.assertEqual(main(args), 2)
                self.assertEqual((root / 'out.json').read_bytes(), before)
            o = json.loads(before)['batch']['observations'][0]
            self.assertEqual(o['available_at'], IMPORT)

    def test_cli_bad_input_no_partial_output_no_raw_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); (root / 'm.json').write_text('{"private-token":NaN}')
            err = io.StringIO()
            with redirect_stderr(err):
                rc = main(['--manifest', str(root / 'm.json'), '--schedule', str(root / 'missing'),
                           '--output', str(root / 'out.json')])
            self.assertEqual(rc, 2); self.assertFalse((root / 'out.json').exists())
            self.assertNotIn('private-token', err.getvalue())


if __name__ == '__main__':
    unittest.main()
