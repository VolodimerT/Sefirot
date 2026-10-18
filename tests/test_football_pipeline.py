"""Isolated source/ledger/import/chronology tests. No provider calls."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'src')]
from sefirot.contracts import canonical,digest
from sefirot.repository import Repository
from sefirot.sports_archive import archive_packets,read_archive
from research import football_pipeline as pipe

NOW='2026-10-17T12:00:00+00:00'


def fixture(fid=10,status='FT'):
    return {'fixture':{'id':fid,'date':'2026-10-14T12:00:00+00:00' if status=='FT' else '2026-10-18T12:00:00+00:00',
                        'status':{'short':status,'elapsed':90 if status=='FT' else None}},
            'league':{'id':39,'season':2026,'type':'League'},
            'teams':{'home':{'id':1,'name':'Alpha'},'away':{'id':2,'name':'Beta'}},
            'score':{'fulltime':{'home':2 if status=='FT' else None,'away':1 if status=='FT' else None}}}


def packet(endpoint='fixtures',params=None,rows=None,at='2026-10-16T12:00:00+00:00'):
    params=params if params is not None else {'league':39,'season':2026}
    if rows is None:rows=[fixture(),fixture(20,'NS')]
    d={'get':endpoint,'parameters':{k:str(v) for k,v in params.items()},'errors':[],
       'results':len(rows),'paging':{'current':1,'total':1},'response':rows}
    return {'data':d,'receipt':{'provider':'API_FOOTBALL_V3','provider_host':'v3.football.api-sports.io',
        'endpoint':'/'+endpoint,'parameters':params,'request_started_at':at,'received_at':at,
        'upstream_received_at':at,'http_status':200,'sports_only':True,'transport':'SUPABASE_GATEWAY',
        'payload_hash':digest(d)}}


def stats(at='2026-10-16T13:00:00+00:00'):
    rows=[{'team':{'id':tid,'name':'Synthetic'},'statistics':[{'type':'Corner Kicks','value':0},
        {'type':'Total Shots','value':12},{'type':'Shots on Goal','value':None},
        {'type':'Yellow Cards','value':2},{'type':'Fouls','value':11}]} for tid in (1,2)]
    return packet('fixtures/statistics',{'fixture':10},rows,at)


class FootballPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'source.sqlite';self.repo=Repository(self.path)
        self.addCleanup(self.repo.close)
    def put(self,p,at=NOW):return pipe.ingest(self.repo,canonical(p).encode(),imported_at=at)

    def test_original_bytes_hash_and_provider_receipt_survive_dedup(self):
        p=packet();raw=json.dumps(p,indent=3).encode()
        first=pipe.ingest(self.repo,raw,imported_at=NOW)
        second=pipe.ingest(self.repo,raw,imported_at='2026-10-17T12:01:00+00:00')
        self.assertTrue(first['added_source']);self.assertFalse(second['added_source'])
        source=pipe._records(self.repo,pipe.SOURCE)[0]
        self.assertEqual(source['raw_utf8'].encode(),raw)
        self.assertEqual(source['source_packet']['receipt'],p['receipt'])
        self.assertEqual(source['at'],NOW);self.assertTrue(self.repo.verify())

    def test_archive_commits_before_qc_and_crash_replay_requires_no_refetch(self):
        with patch.object(pipe,'_qc',side_effect=RuntimeError('SYNTHETIC_CRASH')):
            with self.assertRaises(RuntimeError):self.put(packet())
        self.assertEqual(len(pipe._records(self.repo,pipe.SOURCE)),1)
        self.assertEqual(pipe.plan_day(self.repo,at=NOW)['queries'],[])
        self.assertFalse(self.put(packet())['added_source'])
        self.assertEqual(len(pipe._records(self.repo,pipe.QC)),1)

    def test_bad_hash_is_quarantined_not_lost_or_used(self):
        p=packet();p['receipt']['payload_hash']='a'*64
        r=self.put(p);self.assertFalse(r['accepted'])
        self.assertEqual(len(pipe._records(self.repo,pipe.SOURCE)),1)
        self.assertEqual(pipe.packets(self.repo,NOW),[])
        self.assertEqual(pipe.plan_day(self.repo,at=NOW)['queries'],[])

    def test_secrets_duplicate_json_and_nonfinite_reject_before_storage(self):
        p=packet();p['receipt']['parameters']['token']='SYNTHETIC_PRIVATE'
        with self.assertRaises(ValueError):self.put(p)
        for raw in (b'{"data":{},"data":{},"receipt":{}}',b'{"data":NaN,"receipt":{}}'):
            with self.assertRaises(ValueError):pipe.ingest(self.repo,raw,imported_at=NOW)
        self.assertEqual(pipe._records(self.repo,pipe.SOURCE),[])

    def test_full_calendar_denominator_and_partial_date_are_distinct(self):
        p=packet(params={'date':'2026-10-14','league':39,'season':2026},rows=[fixture()])
        self.put(p);v=pipe.league_view(self.repo,as_of=NOW)
        self.assertIsNone(v['expected_matches']);self.assertFalse(v['calendar_complete'])
        self.put(packet());v=pipe.league_view(self.repo,as_of=NOW)
        self.assertEqual(v['expected_matches'],2);self.assertEqual(v['observed_matches'],2)

    def test_null_zero_and_fouls_semantics_never_filled_or_promoted(self):
        self.put(packet());self.put(stats());v=pipe.league_view(self.repo,as_of=NOW)
        self.assertEqual(v['statistics_complete_counts']['CORNERS'],1)
        self.assertEqual(v['statistics_missing_counts']['SOT'],1)
        self.assertEqual(v['fouls_semantics'],'NOT_VERIFIED')
        out=pipe.model_inputs(self.repo,20,as_of=NOW,profile='MEN',source_reliability=.8)
        self.assertEqual(out['main']['sports']['history'][0]['home_goals'],2)
        self.assertEqual(out['small']['CORNERS:home']['observations'][0]['count'],0)
        self.assertIsNone(out['probability']);self.assertFalse(out['forecast_created'])

    def test_import_cutoff_cannot_create_a_retrospective_forecast(self):
        self.put(packet())
        with self.assertRaises(ValueError):pipe.model_inputs(self.repo,20,as_of='2026-10-16T13:00:00+00:00',profile='MEN',source_reliability=.8)
        self.assertEqual(self.repo.all('predictions'),[])
        self.assertEqual(self.repo.all('split_assignments'),[])

    def test_result_and_statistics_revisions_rejected_and_originals_retained(self):
        self.put(packet());self.put(stats())
        p=packet(at='2026-10-17T10:00:00+00:00');p['data']['response'][0]['score']['fulltime']['home']=3
        p['receipt']['payload_hash']=digest(p['data']);self.put(p)
        v=pipe.league_view(self.repo,as_of=NOW)
        self.assertEqual(v['reasons']['RESULT_REVISION_CONFLICT'],1)
        self.assertEqual(len(pipe._records(self.repo,pipe.SOURCE)),3)

    def test_wrong_fixture_statistics_remains_archived_but_not_joined(self):
        self.put(packet());p=stats();p['receipt']['parameters']['fixture']=999;p['data']['parameters']['fixture']='999'
        p['receipt']['payload_hash']=digest(p['data']);self.put(p)
        self.assertEqual(pipe.league_view(self.repo,as_of=NOW)['reasons']['STATISTICS_FIXTURE_UNBOUND'],1)

    def test_missing_stats_and_conflicting_calendars_are_visible(self):
        self.put(packet());v=pipe.league_view(self.repo,as_of=NOW)
        self.assertEqual(v['statistics_missing_counts']['CORNERS'],1)
        p=packet(rows=[fixture(30,'NS')]);self.put(p)
        v=pipe.league_view(self.repo,as_of=NOW)
        self.assertIsNone(v['expected_matches']);self.assertEqual(v['reasons']['SIMULTANEOUS_CALENDAR_CONFLICT'],1)

    def test_sync_rescans_hash_order_and_never_reimports_or_calls_provider(self):
        raw=canonical(packet()).encode();key=pipe.sha256(raw).hexdigest()
        row={'raw_source':raw.decode(),'raw_sha256':key,'next':key}
        def request(q):return row if q['after']=='' else {'next':None}
        with patch('scripts.chat_sports_probe.get_sports') as network:
            self.assertEqual(pipe.sync_archive(self.repo,request=request)['added_sources'],1)
            self.assertEqual(pipe.sync_archive(self.repo,request=request)['added_sources'],0)
            network.assert_not_called()
        self.assertEqual(len(pipe._records(self.repo,pipe.SOURCE)),1)
        with self.assertRaises(ValueError):pipe.sync_archive(self.repo,request=lambda q:{**row,'raw_sha256':'b'*64})

    def test_daily_collect_reuses_sources_and_continues_only_missing_ft_stats(self):
        now=[datetime.fromisoformat(NOW)];calls=[];waits=[]
        def clock():return now[0].isoformat()
        def wait(n):waits.append(n);now[0]+=timedelta(seconds=n)
        def collect(payload,packet_sink):
            q=payload['queries'][0];calls.append(q)
            p=packet(at=clock()) if q['endpoint']=='fixtures' else stats(at=clock())
            packet_sink(p);return {'queries':[{'status':'DONE'}]}
        out=pipe.collect_day(self.repo,execute=True,collector=collect,clock=clock,wait=wait)
        self.assertEqual([q['endpoint'] for q in calls],['fixtures','fixtures/statistics'])
        self.assertTrue(all(n>=61 for n in waits));self.assertEqual(out['plan']['queries'],[])
        pipe.collect_day(self.repo,execute=True,collector=collect,clock=clock,wait=wait)
        self.assertEqual(len(calls),2);self.assertEqual(len(pipe._records(self.repo,pipe.SOURCE)),2)

    def test_temporal_source_views_separate_actual_prematch_ft_and_late_import(self):
        self.put(packet());v=pipe.league_view(self.repo,as_of=NOW)
        self.assertEqual([r['fixture_id'] for r in v['temporal_source_views']['PREMATCH']],[20])
        self.assertEqual([r['fixture_id'] for r in v['temporal_source_views']['POST_FT']],[10])
        p=packet(rows=[fixture(30,'NS')]);p['data']['response'][0]['fixture']['date']='2026-10-17T11:00:00Z'
        p['receipt']['payload_hash']=digest(p['data']);self.put(p)
        v=pipe.league_view(self.repo,as_of=NOW)
        self.assertEqual([r['fixture_id'] for r in v['temporal_source_views']['HISTORICAL_NS']],[30])
        self.assertNotIn(30,[r['fixture_id'] for r in v['temporal_source_views']['PREMATCH']])
        self.assertEqual(self.repo.all('predictions'),[])

    def test_old_unbound_stat_does_not_poison_new_verified_post_ft_packet(self):
        self.put(packet());self.put(stats(at='2026-10-16T11:00:00+00:00'))
        self.assertEqual(pipe.league_view(self.repo,as_of=NOW)['statistics_qc_matches'],0)
        self.put(stats());v=pipe.league_view(self.repo,as_of=NOW)
        self.assertEqual(v['statistics_qc_matches'],1)
        self.assertEqual(v['statistics_complete_counts']['CORNERS'],1)
        self.assertEqual(v['reasons']['STATISTICS_BEFORE_FT_KNOWLEDGE'],1)
        self.assertEqual(len(pipe._records(self.repo,pipe.SOURCE)),3)
        self.assertNotIn({'endpoint':'fixtures/statistics','params':{'fixture':10}},pipe.plan_day(self.repo,at=NOW)['queries'])

    def test_dry_plan_no_provider_calls_and_five_requests_global_cap(self):
        with patch('scripts.chat_sports_probe.get_sports') as network:
            p=pipe.collect_day(self.repo,clock=lambda:NOW)
            network.assert_not_called()
        self.assertEqual(p['daily_limit'],5);self.assertEqual(p['queries'][0]['params'],{'league':39,'season':2026})
        for n in range(5):
            r={'schema':pipe.ATTEMPT,'id':'attempt:'+str(n),'at':NOW,'query':{'endpoint':'fixtures','params':{'id':n+1}}}
            with self.repo.transaction():pipe._append(self.repo,r)
        self.assertEqual(pipe.plan_day(self.repo,40,2026,at=NOW)['queries'],[])

    def test_uncertain_dispatch_intent_survives_next_day_without_retry(self):
        def crash(*a,**kw):raise OSError('SYNTHETIC_LOST_RESPONSE')
        with self.assertRaises(OSError):pipe.collect_day(self.repo,execute=True,collector=crash,clock=lambda:NOW)
        self.assertEqual(pipe.plan_day(self.repo,at='2026-10-18T12:00:00+00:00')['queries'],[])
        self.assertEqual(len(pipe._records(self.repo,pipe.ATTEMPT)),1)

    def test_invalid_period_statistics_archived_qc_rejected(self):
        p=stats();p['receipt']['parameters']['half']=True;p['data']['parameters']['half']='True'
        p['receipt']['payload_hash']=digest(p['data'])
        self.assertFalse(self.put(p)['accepted'])

    def test_atomic_archive_publication_failure_never_leaves_partial_json(self):
        d=Path(self.temp.name)/'archive'
        with patch('sefirot.sports_archive.os.link',side_effect=OSError('SYNTHETIC_IO')):
            with self.assertRaises(OSError):archive_packets([packet()],d,NOW)
        self.assertEqual(list(d.glob('*.json')),[]);self.assertEqual(read_archive(d),[])

    def test_concurrent_source_import_is_deduplicated_by_repository_transaction(self):
        raw=canonical(packet()).encode()
        def run(_):
            r=Repository(self.path)
            try:return pipe.ingest(r,raw,imported_at=NOW)
            finally:r.close()
        with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run,range(2)))
        self.assertEqual(len(pipe._records(self.repo,pipe.SOURCE)),1)
        self.assertTrue(self.repo.verify())

    def test_probe_sink_is_before_mapping_and_preserves_data_on_mapper_failure(self):
        from scripts import chat_sports_probe as probe
        p=stats()
        p['data']['response'][0]['statistics'].append({'type':'Corner Kicks','value':8})
        p['receipt']['payload_hash']=digest(p['data'])
        seen=[]
        with patch.object(probe,'get_sports',return_value=p):
            out=probe.collect({'queries':[{'endpoint':'fixtures/statistics','params':{'fixture':10}}]},packet_sink=lambda x:seen.append(deepcopy(x)))
        self.assertEqual(seen,[p]);self.assertEqual(out['queries'][0]['status'],'ERROR')


if __name__=='__main__':unittest.main()
