"""Owned C2 fixtures test contracts only; they are not the requested real bundle."""
from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from sefirot.contracts import canonical,digest,time
from sefirot.repository import Repository
from sefirot.sports_archive import archive_packets
from research.football_pipeline import ingest
from research.day_calendar import day_window,calendar_day
from research.day_bundle import qualify_day,_role_reviews
from research.daily_scanner import scan_day
from test_football_pipeline import packet,fixture


def row(fid, kickoff, state='NS'):
    r=fixture(fid,state);r['fixture']['date']=kickoff
    r['fixture']['timestamp']=int(time(kickoff).timestamp())
    if state=='FT':r['score']['fulltime']={'home':2,'away':1}
    return r


def calendar(zone='UTC', day='2026-10-18', kickoff='2026-10-18T12:00:00+00:00'):
    return packet(params={'date':day,'timezone':zone},rows=[row(20,kickoff)],at='2026-10-13T10:00:00+00:00')


class CalendarC2Tests(unittest.TestCase):
    def test_kyiv_winter_midnight_in_previous_utc_day(self):
        p=calendar('Europe/Kyiv','2026-10-29','2026-10-29T00:30:00+02:00');before=deepcopy(p)
        self.assertEqual(calendar_day(p,'2026-10-29','2026-10-28T20:00:00Z','Europe/Kyiv')[0]['fixture']['id'],20)
        self.assertEqual(p,before)
        self.assertEqual(day_window('2026-10-29','Europe/Kyiv')['start_utc'],'2026-10-28T22:00:00+00:00')

    def test_kyiv_summer_offset_and_half_open_end(self):
        w=day_window('2026-07-01','Europe/Kyiv');self.assertEqual(w['start_utc'],'2026-06-30T21:00:00+00:00')
        p=calendar('Europe/Kyiv','2026-07-01','2026-07-01T00:30:00+03:00')
        for key in ('request_started_at','received_at','upstream_received_at'):
            p['receipt'][key]='2026-06-30T19:00:00+00:00'
        self.assertEqual(len(calendar_day(p,'2026-07-01','2026-06-30T20:00:00Z','Europe/Kyiv')),1)
        p['data']['response'][0]['fixture']['date']='2026-07-02T00:00:00+03:00'
        p['data']['response'][0]['fixture']['timestamp']=int(time('2026-07-02T00:00:00+03:00').timestamp())
        p['receipt']['payload_hash']=digest(p['data'])
        with self.assertRaises(ValueError):calendar_day(p,'2026-07-01','2026-06-30T20:00:00Z','Europe/Kyiv')

    def test_dst_transition_days_are_not_forced_to_24_hours(self):
        self.assertEqual(day_window('2026-03-29','Europe/Kyiv')['duration_hours'],23)
        self.assertEqual(day_window('2026-10-25','Europe/Kyiv')['duration_hours'],25)

    def test_utc_packet_cannot_claim_kyiv_day(self):
        with self.assertRaises(ValueError):calendar_day(calendar(),'2026-10-18','2026-10-17T10:00:00Z','Europe/Kyiv')

    def test_unsupported_zone_and_timezone_echo_rejected(self):
        with self.assertRaises(ValueError):day_window('2026-10-18','Europe/Kiev')
        p=calendar('Europe/Kyiv',kickoff='2026-10-18T12:00:00+03:00');p['data']['parameters']['timezone']='UTC'
        p['receipt']['payload_hash']=digest(p['data'])
        with self.assertRaises(ValueError):calendar_day(p,'2026-10-18','2026-10-17T10:00:00Z','Europe/Kyiv')

    def test_scanner_kyiv_day_and_referee_applies_only_to_yc(self):
        p=calendar('Europe/Kyiv','2026-10-29','2026-10-29T00:30:00+02:00')
        with TemporaryDirectory() as tmp:
            archive_packets([p],tmp,'2026-10-28T20:00:00Z')
            r=scan_day(calendar=p,archive=tmp,day='2026-10-29',at='2026-10-28T20:00:00Z',profile='MEN',timezone='Europe/Kyiv')
        self.assertEqual(r['fixture_counts']['reported'],1)
        markets={m['market']:m for m in r['fixtures'][0]['small_markets']}
        self.assertEqual(markets['FOULS']['referee_gate']['status'],'NOT_APPLICABLE')
        self.assertEqual(markets['YELLOW_CARDS']['referee_gate']['status'],'HOLD')
        self.assertIn('DIRECT_COMMITTED_SUFFERED_COUNTS_REQUIRED',markets['FOULS']['blockers'])


class QualificationC2Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.root=Path(self.tmp.name)
        self.archive=self.root/'archive';self.db=self.root/'source.sqlite'
        self.cal=calendar()
        self.ns=packet(params={'id':10},rows=[row(10,'2026-10-14T12:00:00+00:00')],at='2026-10-14T10:00:00+00:00')
        self.ft=packet(params={'id':10},rows=[row(10,'2026-10-14T12:00:00+00:00','FT')],at='2026-10-14T14:00:00+00:00')

    def put(self,p,at):
        repo=Repository(str(self.db))
        try:self.assertTrue(ingest(repo,canonical(p).encode(),imported_at=at)['accepted'])
        finally:repo.close()

    def report(self,**kwargs):
        defaults=dict(day='2026-10-18',as_of='2026-10-17T10:00:00Z',timezone='UTC',calendar=self.cal,archive=self.archive,snapshot=self.db)
        defaults.update(kwargs);return qualify_day(**defaults)

    def prepare(self,late=False):
        for p,at in [(self.ns,'2026-10-14T13:00:00Z' if late else '2026-10-14T10:01:00Z'),
                     (self.ft,'2026-10-14T14:01:00Z'),(self.cal,'2026-10-13T10:01:00Z')]:self.put(p,at)
        archive_packets([self.ns,self.ft,self.cal],self.archive,'2026-10-17T10:00:00Z')

    def test_missing_inputs_never_fall_back_to_c1_synthetic_snapshots(self):
        r=qualify_day(day='2026-10-29',as_of='2026-10-29T09:00:00Z')
        self.assertEqual(r['fixtures'],[]);self.assertFalse(r['model_fit_allowed'])
        self.assertEqual(r['snapshot']['status'],'NOT_SUPPLIED')
        self.assertEqual(r['next_blocker'],'SUPPLY_REAL_DAY_ARCHIVE_AND_CHECKPOINTED_SQLITE')
        self.assertIsNone(r['model_probability']);self.assertIsNone(r['ev'])
        self.assertIsNone(r['day_fixture_count'])
        self.assertIsNone(r['coverage_by_market']['1X2']['saved_day_fixtures'])
        self.assertEqual(r['qualification_status'],'INPUTS_MISSING_OR_REJECTED')

    def test_identity_map_local_availability_labels_and_history(self):
        self.prepare();r=self.report();items={f['provider_fixture_id']:f for f in r['fixtures']}
        self.assertEqual(r['snapshot']['status'],'VERIFIED_OFFLINE_SNAPSHOT')
        self.assertTrue(items[10]['prematch_observations'])
        self.assertEqual(items[10]['label_available_at'],'2026-10-14T14:01:00Z')
        self.assertEqual(items[20]['pre_kickoff_history_fixture_ids'],['api-football:fixture:10'])
        self.assertEqual(r['day_fixture_ids'],['api-football:fixture:20'])
        self.assertFalse(items[10]['roles']['HOLDOUT']['qualified'])

    def test_late_import_cannot_backdate_a_prematch_receipt(self):
        self.prepare(late=True);r=self.report();item=next(f for f in r['fixtures'] if f['provider_fixture_id']==10)
        self.assertEqual(item['prematch_observations'],[])
        self.assertIn('NO_LOCALLY_AVAILABLE_PREMATCH_SNAPSHOT',item['roles']['TRAIN']['reasons'])

    def test_archive_receipt_alone_does_not_prove_local_first_availability(self):
        archive_packets([self.ns,self.ft,self.cal],self.archive,'2026-10-17T10:00:00Z')
        r=self.report(snapshot=None);item=next(f for f in r['fixtures'] if f['provider_fixture_id']==10)
        self.assertIsNone(item['label_available_at']);self.assertEqual(item['prematch_observations'],[])

    def test_snapshot_and_archive_unchanged_no_sidecar_created(self):
        self.prepare();before={p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        one,two=self.report(),self.report()
        self.assertEqual(one,two)
        self.assertEqual(before,{p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertTrue(one['snapshot']['unchanged'])

    def test_live_wal_is_rejected_without_ignoring_it(self):
        self.prepare();wal=Path(str(self.db)+'-wal');wal.write_bytes(b'OWNED_TEST_WAL')
        r=self.report();self.assertEqual(r['snapshot']['status'],'SNAPSHOT_REJECTED');self.assertEqual(wal.read_bytes(),b'OWNED_TEST_WAL')

    def test_future_labels_are_not_prematch_features(self):
        self.prepare();before=self.report(as_of='2026-10-14T11:00:00Z')
        item=next(f for f in before['fixtures'] if f['provider_fixture_id']==10)
        self.assertIsNone(item['label_available_at'])
        self.assertTrue(before['future_exclusions'])
        self.assertFalse(item['roles']['TRAIN']['chronology_usable'])

    def test_conflicting_teams_and_revised_results_are_quarantined(self):
        self.prepare();wrong=deepcopy(self.ft);wrong['data']['response'][0]['teams']['home']['id']=999
        wrong['receipt']['payload_hash']=digest(wrong['data']);self.put(wrong,'2026-10-14T15:00:00Z')
        r=self.report();item=next(f for f in r['fixtures'] if f['provider_fixture_id']==10)
        self.assertIn('FIXTURE_IDENTITY_CONFLICT',item['blockers'])
        self.assertFalse(item['roles']['TRAIN']['chronology_usable'])

    def test_missing_sources_and_fouls_yc_separation(self):
        self.prepare();r=self.report()
        self.assertIn('DOCUMENTED_XG_PROVIDER_WITH_TIMESTAMP_AND_DEFINITION',r['missing_sources'])
        self.assertFalse(r['coverage_by_market']['FOULS']['referee_gate_required'])
        self.assertTrue(r['coverage_by_market']['YELLOW_CARDS']['referee_gate_required'])
        self.assertEqual(r['coverage_by_league']['39']['saved_day_fixtures'],1)
        self.assertEqual(r['coverage_by_market']['1X2']['fixtures_with_local_sports_inputs'],1)
        self.assertEqual(r['coverage_by_market']['FOULS']['fixtures_with_local_sports_inputs'],0)

    def test_train_excludes_reserved_calibration_and_holdout(self):
        item={'fixture_id':'m','kickoff':'2026-10-14T12:00:00Z','blockers':[],
              'prematch_observations':['hash'],'label_available_at':'2026-10-14T14:00:00Z','synthetic_detected':False}
        for role in ('CALIBRATION','HOLDOUT'):
            snap={'assignments':{'m':{'role':role,'at':'2026-10-14T10:00:00Z'}},'predictions':[],'bindings':{}}
            reviews=_role_reviews(item,snap,'2026-10-17T10:00:00Z')
            self.assertIn('RESERVED_ROLE_NOT_TRAINABLE',reviews['TRAIN']['reasons'])
            self.assertFalse(reviews['HOLDOUT']['model_fit_allowed'])

    def test_holdout_fit_overlap_and_late_reservation_block(self):
        item={'fixture_id':'m','kickoff':'2026-10-14T12:00:00Z','blockers':[],
              'prematch_observations':['hash'],'label_available_at':'2026-10-14T14:00:00Z','synthetic_detected':False}
        p={'sports':{'match':{'id':'m'}},'captured_prematch':True,'reconstructed':False,
           'sealed_at':'2026-10-14T11:00:00Z','calibrator':{'synthetic':False,'fit_at':'2026-10-14T10:00:00Z','fit_ids':['m']}}
        snap={'assignments':{'m':{'role':'HOLDOUT','at':'2026-10-14T13:00:00Z'}},'predictions':[p],'bindings':{'m':'seal'}}
        r=_role_reviews(item,snap,'2026-10-17T10:00:00Z')['HOLDOUT']
        self.assertIn('CALIBRATION_HOLDOUT_OVERLAP',r['reasons']);self.assertIn('ROLE_RESERVED_AFTER_KICKOFF',r['reasons'])
        self.assertFalse(r['qualified'])

    def test_role_reservation_must_precede_the_seal(self):
        item={'fixture_id':'m','kickoff':'2026-10-14T12:00:00Z','blockers':[],
              'prematch_observations':['hash'],'label_available_at':'2026-10-14T14:00:00Z','synthetic_detected':False}
        p={'sports':{'match':{'id':'m'}},'captured_prematch':True,'reconstructed':False,
           'sealed_at':'2026-10-14T10:00:00Z','calibrator':None}
        snap={'assignments':{'m':{'role':'CALIBRATION','at':'2026-10-14T11:00:00Z'}},'predictions':[p],'bindings':{'m':'seal'}}
        r=_role_reviews(item,snap,'2026-10-17T10:00:00Z')['CALIBRATION']
        self.assertIn('ROLE_RESERVED_AFTER_SEAL',r['reasons']);self.assertFalse(r['chronology_usable'])

    def test_calibrator_cannot_contain_another_reserved_holdout(self):
        item={'fixture_id':'m','kickoff':'2026-10-14T12:00:00Z','blockers':[],
              'prematch_observations':['hash'],'label_available_at':'2026-10-14T14:00:00Z','synthetic_detected':False}
        p={'sports':{'match':{'id':'m'}},'captured_prematch':True,'reconstructed':False,
           'sealed_at':'2026-10-14T11:00:00Z','calibrator':{'synthetic':False,'fit_at':'2026-10-14T10:00:00Z',
           'last_result_at':'2026-10-13T10:00:00Z','fit_ids':['other']}}
        snap={'assignments':{'m':{'role':'HOLDOUT','at':'2026-10-14T09:00:00Z'},
              'other':{'role':'HOLDOUT','at':'2026-10-10T09:00:00Z'}},'predictions':[p],'bindings':{'m':'seal'}}
        r=_role_reviews(item,snap,'2026-10-17T10:00:00Z')['HOLDOUT']
        self.assertIn('CALIBRATION_HOLDOUT_OVERLAP',r['reasons']);self.assertFalse(r['qualified'])

    def test_malformed_frozen_calibration_is_blocked_not_trusted(self):
        from research.day_bundle import _frozen_at_seal
        self.assertFalse(_frozen_at_seal({'synthetic':False,'fit_ids':[]},{'sealed_at':'2026-10-14T11:00:00Z'}))
        self.assertFalse(_frozen_at_seal({'synthetic':False,'fit_ids':[], 'fit_at':'2026-10-14T12:00:00Z',
            'last_result_at':'2026-10-13T10:00:00Z'},{'sealed_at':'2026-10-14T11:00:00Z'}))

    def test_calendar_identity_conflict_is_not_hidden_by_archive(self):
        self.prepare();wrong=deepcopy(self.cal)
        wrong['data']['response'][0]['teams']['home']['id']=999
        wrong['receipt']['payload_hash']=digest(wrong['data'])
        r=self.report(calendar=wrong)
        item=next(f for f in r['fixtures'] if f['provider_fixture_id']==20)
        self.assertIn('FIXTURE_IDENTITY_CONFLICT',item['blockers'])
        self.assertFalse(item['roles']['TRAIN']['qualified'])

    def test_archive_selector_mismatch_cannot_qualify_history(self):
        self.prepare();wrong=deepcopy(self.ft)
        wrong['receipt']['parameters']={'id':999};wrong['data']['parameters']={'id':'999'}
        wrong['receipt']['payload_hash']=digest(wrong['data'])
        archive_packets([wrong],self.archive,'2026-10-17T10:00:00Z')
        r=self.report();item=next(f for f in r['fixtures'] if f['provider_fixture_id']==10)
        self.assertIn('QUERY_RESPONSE_MISMATCH',item['blockers'])
        target=next(f for f in r['fixtures'] if f['provider_fixture_id']==20)
        self.assertEqual(target['pre_kickoff_history_fixture_ids'],[])

    def test_no_network_or_fit_api_called(self):
        self.prepare()
        with patch('urllib.request.urlopen',side_effect=AssertionError('NO_NETWORK')):
            r=self.report()
        self.assertFalse(r['model_fit_allowed']);self.assertEqual(r['network_requests'],0)
        self.assertTrue(all(not v['model_fit_allowed'] for f in r['fixtures'] for v in f['roles'].values()))


if __name__=='__main__':unittest.main()
