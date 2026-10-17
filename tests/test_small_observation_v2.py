"""Synthetic adversarial input contracts, never predictive validation."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.small_observation_v2 import audit_dataset, validate_market, METRICS, PERIODS

AT = '2030-02-03T12:00:00+00:00'
KICK = '2030-02-01T12:00:00+00:00'
STAMP = '2030-02-01T15:00:00+00:00'


def fixture(fid='f1', home='t1', away='t2', status='FT'):
    return {'fixture_id': fid, 'home_id': home, 'away_id': away,
            'kickoff': KICK, 'status': status, 'venue': 'HOME'}


def sample():
    manifest = {'schema': 'small-league-manifest-v1', 'provider': 'SYNTHETIC',
                'competition_id': 'l1', 'season': '2030', 'competition_type': 'LEAGUE',
                'registered_at': '2030-01-01T00:00:00+00:00',
                'source_sha256': 'a' * 64, 'pagination_complete': True,
                'license_ref': 'SYNTHETIC_TEST_ONLY', 'team_ids': ['t1','t2','t3','t4'],
                'fixtures': [fixture(), fixture('f2','t3','t4')]}
    return {'schema': 'small-observation-batch-v2', 'manifest': manifest,
            'observations': [observation('f1','t1','t2'), observation('f2','t3','t4')]}


def observation(fid, home, away):
    counts = {p: {m: {'home': 0, 'away': 0} for m in METRICS} for p in PERIODS}
    return {'schema': 'small-match-observation-v2', 'provider': 'SYNTHETIC',
            'competition_id': 'l1', 'season': '2030', 'competition_type': 'LEAGUE',
            'fixture_id': fid, 'home_id': home, 'away_id': away, 'kickoff': KICK,
            'venue': 'HOME', 'status': 'FT', 'revision': 0, 'supersedes_sha256': None,
            'published_at': STAMP, 'received_at': STAMP, 'available_at': STAMP,
            'raw_sha256': hashlib.sha256(fid.encode()).hexdigest(),
            'source_kind': 'SYNTHETIC', 'license_ref': 'SYNTHETIC_TEST_ONLY',
            'metric_definitions': {m: m.lower() + ':regulation:teams-only:v1' for m in METRICS},
            'counts': counts, 'referee': None}


def market():
    return {'schema': 'small-market-contract-v1', 'fixture_id': 'f1',
            'metric': 'CORNERS', 'period': 'FT', 'kind': 'TOTAL', 'side': 'OVER',
            'team_id': None, 'line': 8.0, 'settlement': 'ASIAN_INTEGER',
            'bookmaker': 'SYNTHETIC', 'market_id': 'c8', 'rules_version': 'v1',
            'quote_at': STAMP}


class ObservationTests(unittest.TestCase):
    def check(self, data=None):
        return audit_dataset(data or sample(), AT)

    def metric(self, report, metric='CORNERS', period='FT'):
        return next(x for x in report['markets'] if x['metric']==metric and x['period']==period)

    def test_zero_is_observed_not_missing(self):
        r = self.metric(self.check())
        self.assertEqual((r['known_fixtures'],r['missing_fixtures'],r['observed_coverage']), (2,0,1.0))
        self.assertIsNone(r['verified_coverage'])
        self.assertFalse(r['fit_allowed'])

    def test_missing_not_zero(self):
        d=sample();d['observations'][0]['counts']['FT']['CORNERS']['away']=None
        self.assertEqual(self.metric(self.check(d))['missing_fixtures'],1)

    def test_mini_league_uses_manifest_denominator(self):
        d=sample();d['observations']=d['observations'][:1]
        r=self.metric(self.check(d));self.assertEqual(r['observed_coverage'],.5)
        self.assertEqual(r['missing_fixture_ids'],['f2'])
        self.assertEqual(r['team_coverage']['t3']['observed'],0)

    def test_duplicates_never_double_count(self):
        d=sample();d['observations'].append(deepcopy(d['observations'][0]))
        r=self.check(d);self.assertEqual(r['duplicates'],1)
        self.assertEqual(self.metric(r)['known_fixtures'],2)

    def test_conflicting_same_revision_quarantined(self):
        d=sample();o=deepcopy(d['observations'][0]);o['counts']['FT']['CORNERS']['home']=1
        o['counts']['1H']['CORNERS']['home']=1
        d['observations'].append(o);r=self.check(d)
        self.assertIn('REVISION_CONFLICT',str(r['quarantine']))
        self.assertEqual(self.metric(r)['known_fixtures'],1)

    def test_sot_over_shots_quarantined(self):
        d=sample();d['observations'][0]['counts']['FT']['SOT']['home']=1
        self.assertIn('SOT_EXCEEDS_SHOTS',str(self.check(d)['quarantine']))

    def test_half_over_ft_quarantined(self):
        d=sample();d['observations'][0]['counts']['1H']['CORNERS']['home']=1
        self.assertIn('HALF_EXCEEDS_FT',str(self.check(d)['quarantine']))

    def test_half_sum_mismatch_quarantined(self):
        d=sample();d['observations'][0]['counts']['FT']['CORNERS']['home']=1
        self.assertIn('PERIOD_SUM_MISMATCH',str(self.check(d)['quarantine']))

    def test_half_missing_not_borrow_ft(self):
        d=sample();d['observations'][0]['counts']['1H']['SHOTS']['home']=None
        self.assertEqual(self.metric(self.check(d),'SHOTS','1H')['known_fixtures'],1)

    def test_bool_count_rejected(self):
        d=sample();d['observations'][0]['counts']['FT']['FOULS_COMMITTED']['home']=True
        self.assertIn('INVALID_COUNT',str(self.check(d)['quarantine']))

    def test_negative_count_rejected(self):
        d=sample();d['observations'][0]['counts']['FT']['YELLOW_CARDS']['away']=-1
        self.assertIn('INVALID_COUNT',str(self.check(d)['quarantine']))

    def test_naive_time_rejected(self):
        d=sample();d['observations'][0]['received_at']='2030-02-01T15:00:00'
        self.assertIn('TIMEZONE_REQUIRED',str(self.check(d)['quarantine']))

    def test_import_time_cannot_backdate_published_time(self):
        d=sample();d['observations'][0]['received_at']='2030-02-01T14:00:00+00:00'
        self.assertIn('SOURCE_CHRONOLOGY',str(self.check(d)['quarantine']))

    def test_future_snapshot_not_used(self):
        d=sample();d['observations'][0]['available_at']='2030-03-01T15:00:00+00:00'
        self.assertEqual(self.metric(self.check(d))['known_fixtures'],1)
        self.assertEqual(self.check(d)['excluded']['NOT_AVAILABLE_AT_CUTOFF'],1)

    def test_foreign_competition_quarantined(self):
        d=sample();d['observations'][0]['competition_id']='cup'
        self.assertIn('MANIFEST_IDENTITY_MISMATCH',str(self.check(d)['quarantine']))

    def test_cup_cannot_enter_league(self):
        d=sample();d['observations'][0]['competition_type']='CUP'
        self.assertIn('MANIFEST_IDENTITY_MISMATCH',str(self.check(d)['quarantine']))

    def test_team_identity_mismatch_quarantined(self):
        d=sample();d['observations'][0]['home_id']='t3'
        self.assertIn('FIXTURE_IDENTITY_MISMATCH',str(self.check(d)['quarantine']))

    def test_foreign_fixture_quarantined(self):
        d=sample();d['observations'][0]['fixture_id']='other'
        self.assertIn('UNASSIGNED_FIXTURE',str(self.check(d)['quarantine']))

    def test_void_and_aet_excluded(self):
        for status in ('VOID','AET','PEN','PST','ABD'):
            d=sample();d['manifest']['fixtures'][0]['status']=status;d['observations'][0]['status']=status
            self.assertEqual(self.metric(self.check(d))['eligible_denominator'],1)

    def test_empty_manifest_not_green(self):
        d=sample();d['manifest']['fixtures']=[];d['observations']=[]
        r=self.metric(self.check(d));self.assertIsNone(r['observed_coverage']);self.assertEqual(r['qc'],'RED')

    def test_partial_pagination_not_coverage_proof(self):
        d=sample();d['manifest']['pagination_complete']=False
        self.assertEqual(self.metric(self.check(d))['qc'],'RED')

    def test_duplicate_manifest_rejected(self):
        d=sample();d['manifest']['fixtures'].append(deepcopy(d['manifest']['fixtures'][0]))
        with self.assertRaisesRegex(ValueError,'DUPLICATE_MANIFEST_FIXTURE'):self.check(d)

    def test_revision_missing_parent_rejected(self):
        d=sample();d['observations'][0]['revision']=1;d['observations'][0]['supersedes_sha256']='c'*64
        self.assertIn('REVISION_PARENT_MISSING',str(self.check(d)['quarantine']))

    def test_revision_uses_latest_without_filling_missing(self):
        from research.small_observation_v2 import record_hash
        d=sample();old=d['observations'][0];o=deepcopy(old);o['revision']=1
        o['supersedes_sha256']=record_hash(old);o['raw_sha256']='d'*64
        for field in ('published_at','received_at','available_at'):o[field]='2030-02-02T15:00:00+00:00'
        o['counts']['FT']['CORNERS']['home']=None;d['observations'].append(o)
        r=self.check(d);self.assertEqual(r['revisions'],1)
        self.assertEqual(self.metric(r)['known_fixtures'],1)

    def test_late_revision_does_not_hide_original(self):
        from research.small_observation_v2 import record_hash
        d=sample();old=d['observations'][0];o=deepcopy(old);o['revision']=1
        o['supersedes_sha256']=record_hash(old);o['raw_sha256']='e'*64
        for field in ('published_at','received_at','available_at'):o[field]='2030-03-02T15:00:00+00:00'
        d['observations'].append(o);self.assertEqual(self.metric(self.check(d))['known_fixtures'],2)

    def test_future_bad_counts_cannot_quarantine_current_snapshot(self):
        d=sample();o=deepcopy(d['observations'][0])
        o['available_at']='2030-03-02T15:00:00+00:00'
        o['counts']['FT']['CORNERS']['home']=-9;d['observations'].append(o)
        self.assertEqual(self.metric(self.check(d))['known_fixtures'],2)

    def test_missing_definition_not_valid_measurement(self):
        d=sample();d['observations'][0]['metric_definitions']['SHOTS']=None
        r=self.metric(self.check(d),'SHOTS')
        self.assertIn('METRIC_DEFINITION_MISSING',r['blockers'])
        self.assertEqual(r['known_fixtures'],1)

    def test_manifest_cutoff_cannot_precede_registration(self):
        d=sample();d['manifest']['registered_at']='2030-03-01T00:00:00+00:00'
        with self.assertRaisesRegex(ValueError,'FUTURE_MANIFEST_REGISTRATION'):self.check(d)

    def test_manifest_home_away_venue_split(self):
        r=self.metric(self.check())
        self.assertEqual(r['team_coverage']['t1']['home'],1)
        self.assertEqual(r['team_coverage']['t1']['away'],0)

    def test_unregistered_team_rejected(self):
        d=sample();d['manifest']['team_ids'].remove('t4')
        with self.assertRaisesRegex(ValueError,'UNREGISTERED_TEAM'):self.check(d)

    def test_source_claim_cannot_attest_origin(self):
        d=sample()
        for o in d['observations']:o['source_kind']='ARCHIVE_UNATTESTED'
        self.assertFalse(self.check(d)['source_attested'])

    def test_referee_postmatch_prior_rejected(self):
        d=sample();d['observations'][0]['referee']={
            'referee_id':'r1','competition_id':'l1','season':'2030',
            'yc_per_game':4.0,'yc_per_foul':.2,'sample_matches':30,
            'available_at':STAMP,'raw_sha256':'a'*64}
        self.assertIn('REFEREE_PRIOR_POST_KICKOFF',str(self.check(d)['quarantine']))

    def test_negative_quarter_handicap(self):
        m=market();m.update(kind='HANDICAP',side='AWAY',line=-1.25,settlement='ASIAN_QUARTER')
        self.assertEqual(validate_market(m)['line'],-1.25)

    def test_definition_mismatch_is_metric_local(self):
        d=sample();d['observations'][0]['metric_definitions']['SHOTS']='other-definition'
        r=self.check(d);self.assertEqual(self.metric(r,'SHOTS')['known_fixtures'],0)
        self.assertEqual(self.metric(r,'CORNERS')['known_fixtures'],2)

    def test_cards_require_referee_evidence(self):
        r=self.metric(self.check(),'YELLOW_CARDS');self.assertIn('REFEREE_EVIDENCE_MISSING',r['blockers'])

    def test_caller_verified_flag_rejected(self):
        d=sample();d['observations'][0]['source_verified']=True
        self.assertIn('EXACT_OBSERVATION_FIELDS',str(self.check(d)['quarantine']))

    def test_no_probabilities_or_holdout_from_synthetic(self):
        r=self.check();self.assertEqual(r['status'],'INSUFFICIENT_REAL_DATA')
        self.assertIsNone(r['scores']['brier']);self.assertEqual(r['cohorts']['HOLDOUT'],0)
        self.assertFalse(r['monetary_permission'])

    def test_deterministic_and_no_input_mutation(self):
        d=sample();before=deepcopy(d);r=self.check(d)
        self.assertEqual(r,self.check(d));self.assertEqual(d,before)

    def test_market_integer_push_exact(self):
        self.assertEqual(validate_market(market())['settlement'],'ASIAN_INTEGER')

    def test_market_half_line_not_integer(self):
        m=market();m['line']=8.5
        with self.assertRaisesRegex(ValueError,'SETTLEMENT_LINE_MISMATCH'):validate_market(m)

    def test_market_quarter_split_explicit(self):
        m=market();m['line']=8.25;m['settlement']='ASIAN_QUARTER'
        self.assertEqual(validate_market(m)['settlement'],'ASIAN_QUARTER')

    def test_corner_double_chance_not_goal_dc(self):
        m=market();m.update(kind='DOUBLE_CHANCE',side='X2',line=None,settlement='WIN_LOSS')
        self.assertEqual(validate_market(m)['metric'],'CORNERS')
        m['metric']='GOALS'
        with self.assertRaises(ValueError):validate_market(m)

    def test_unknown_foul_unit_rejected(self):
        m=market();m['metric']='FOULS_SUFFERED'
        with self.assertRaises(ValueError):validate_market(m)

    def test_unknown_rules_rejected(self):
        m=market();m['rules_version']=''
        with self.assertRaises(ValueError):validate_market(m)

    def test_market_nan_and_bool_rejected(self):
        for bad in (float('nan'),float('inf'),True):
            m=market();m['line']=bad
            with self.assertRaises(ValueError):validate_market(m)

    def test_report_no_external_api_calls(self):
        import unittest.mock as mock
        with mock.patch('socket.socket',side_effect=AssertionError('network forbidden')):
            self.check()


class OfflineQCCommandTests(unittest.TestCase):
    def test_missing_archive_null_denominator(self):
        sys.path.insert(0,str(ROOT/'scripts'))
        from small_market_qc import readiness_without_archive
        r=readiness_without_archive(AT)
        self.assertFalse(r['archive_audited'])
        self.assertEqual(len(r['markets']),len(METRICS)*len(PERIODS))
        self.assertTrue(all(m['eligible_denominator'] is None for m in r['markets']))

    def test_cli_report_roundtrip_and_overwrite_refused(self):
        import subprocess,tempfile
        with tempfile.TemporaryDirectory() as root:
            src=Path(root)/'input.json';out=Path(root)/'report.json'
            src.write_text(json.dumps(sample()),encoding='utf-8')
            cmd=[sys.executable,str(ROOT/'scripts/small_market_qc.py'),'--input',str(src),
                 '--as-of',AT,'--output',str(out)]
            r=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(r.returncode,0,r.stderr)
            before=out.read_bytes()
            self.assertEqual(json.loads(before)['schema'],'small-market-coverage-v2')
            r=subprocess.run(cmd,capture_output=True,text=True)
            self.assertEqual(r.returncode,2)
            self.assertEqual(out.read_bytes(),before)

    def test_duplicate_json_keys_rejected_before_audit(self):
        sys.path.insert(0,str(ROOT/'scripts'))
        from small_market_qc import strict_json
        import tempfile
        with tempfile.TemporaryDirectory() as root:
            p=Path(root)/'x.json';p.write_text('{"x":1,"x":2}',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'DUPLICATE_JSON_KEY'):strict_json(p)
            p.write_text('{"x":NaN}',encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'NONFINITE_JSON_NUMBER'):strict_json(p)

    def test_schema_names_match_validator(self):
        schema=json.loads((ROOT/'schema/small_observation_v2.json').read_text())
        obs=schema['properties']['observations']['items']
        from research.small_observation_v2 import OBS_FIELDS
        self.assertEqual(set(obs['required']),OBS_FIELDS)
        self.assertFalse(obs['additionalProperties'])
        self.assertEqual(set(obs['properties']['counts']['required']),set(PERIODS))


if __name__ == '__main__':unittest.main()
