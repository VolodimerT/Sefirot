"""Original code/transport regressions; synthetic packets are not match evidence."""
import copy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts')]
import chat_sports_probe as probe
import chat_gateway
import chat_queue
from sefirot.contracts import digest
from sefirot.repository import Repository


def packet(endpoint='fixtures',params=None):
    params=params or {'id':123}
    row={'fixture':{'id':123,'date':'2026-10-13T19:00:00Z','status':{'short':'NS'}},
         'league':{'id':7,'name':'SYNTHETIC','season':2026},
         'teams':{'home':{'id':1,'name':'A'},'away':{'id':2,'name':'B'}},
         'score':{'fulltime':{'home':None,'away':None}},'venue':{'id':9}}
    if endpoint=='fixtures/statistics':
        row={'team':{'id':1,'name':'A'},'statistics':[{'type':'Corner Kicks','value':7}]}
    data={'get':endpoint,'parameters':params,'errors':{},'results':1,
          'paging':{'current':1,'total':1},'response':[row]}
    receipt={'provider':'API_FOOTBALL_V3','provider_host':'v3.football.api-sports.io',
             'endpoint':'/'+endpoint,'parameters':params,'received_at':'2026-10-13T10:00:00Z',
             'payload_hash':digest(data),'http_status':200,'sports_only':True,
             'request_started_at':'2026-10-13T09:59:59Z',
             'upstream_received_at':'2026-10-13T10:00:00Z','transport':'SUPABASE_GATEWAY',
             'quota':{'x-requests-remaining':'100'}}
    return {'data':data,'receipt':receipt}


def collect(packets,queries=None):
    queries=queries or [{'endpoint':'fixtures','params':{'id':123}}]
    with patch.object(probe,'get_sports',side_effect=packets), \
         patch.object(probe,'transport_status',return_value={'transport':'SUPABASE_GATEWAY'}):
        return probe.collect({'queries':queries})


class GuardedProbeEvidenceTests(unittest.TestCase):
    def test_missing_gateway_never_falls_back_to_direct_provider(self):
        from sefirot import football_gateway
        with patch.dict(os.environ,{},clear=True), \
             patch.object(football_gateway,'get',return_value=packet()) as direct:
            result=probe.collect({'queries':[{'endpoint':'fixtures','params':{'id':123}}]})
        direct.assert_not_called()
        self.assertEqual(result['queries'][0]['status'],'ERROR')

    def test_probe_explicitly_requires_shared_budget_transport(self):
        with patch.object(probe,'get_sports',return_value=packet()) as network, \
             patch.object(probe,'transport_status',return_value={'transport':'SUPABASE_GATEWAY'}):
            probe.collect({'queries':[{'endpoint':'fixtures','params':{'id':123}}]})
        network.assert_called_once_with('fixtures',{'id':123},require_shared_budget=True)

    def test_safe_complete_packet_is_preserved_and_rehashable(self):
        original=packet();saved=copy.deepcopy(original)
        result=collect([original]);q=result['queries'][0]
        self.assertEqual(q['source_evidence']['status'],'CANONICAL_PACKET_ARCHIVED')
        self.assertEqual(q['source_packet']['data'],original['data'])
        self.assertEqual(digest(q['source_packet']['data']),q['receipt']['payload_hash'])
        self.assertEqual(digest(q['rows']),q['projection_hash'])
        self.assertEqual(original,saved)
        self.assertFalse(q['source_evidence']['provider_origin_attested'])
        self.assertFalse(result['model_calibrated'])
        self.assertFalse(result['monetary_permission'])

    def test_missing_data_cannot_be_reconstructed_from_an_old_hash(self):
        old={'endpoint':'fixtures','params':{'id':123},'rows':[{'id':123}],
             'receipt':{'payload_hash':'0'*64}}
        saved=copy.deepcopy(old)
        self.assertEqual(probe.verify_evidence(old)['status'],'ORIGINAL_PACKET_UNAVAILABLE')
        self.assertEqual(old,saved)

    def test_projection_mutation_is_detected_against_current_binding(self):
        q=collect([packet()])['queries'][0]
        q['rows'][0]['home']['name']='tampered'
        self.assertEqual(probe.verify_evidence(q)['status'],'PROJECTION_HASH_MISMATCH')

    def test_source_mutation_is_detected_without_refitting(self):
        q=collect([packet()])['queries'][0]
        q['source_packet']['data']['response'][0]['venue']['id']=77
        self.assertEqual(probe.verify_evidence(q)['status'],'SOURCE_HASH_MISMATCH')

    def test_receipt_request_binding_cannot_be_relabelled(self):
        q=collect([packet()])['queries'][0]
        q['params']={'id':999}
        self.assertEqual(probe.verify_evidence(q)['status'],'SOURCE_IDENTITY_MISMATCH')

    def test_wrong_exact_fixture_stops_batch_without_another_request(self):
        p=packet();p['data']['response'][0]['fixture']['id']=999;p['receipt']['payload_hash']=digest(p['data'])
        with patch.object(probe,'get_sports',side_effect=[p,packet()]) as network, \
             patch.object(probe,'transport_status',return_value={}):
            result=probe.collect({'queries':[{'endpoint':'fixtures','params':{'id':123}}]*2})
        self.assertEqual(network.call_count,1)
        self.assertEqual(result['queries'][0]['reason'],'PROBE_FIXTURE_IDENTITY_MISMATCH')

    def test_impossible_calendar_date_is_rejected_before_network(self):
        with patch.object(probe,'get_sports') as network:
            with self.assertRaises(ValueError):
                probe.collect({'queries':[{'endpoint':'fixtures','params':{'date':'2026-02-30','league':7,'season':2026}}]})
        network.assert_not_called()

    def test_sensitive_or_unknown_statistics_are_never_raw_archived(self):
        p=packet('fixtures/statistics',{'fixture':123})
        p['data']['response'][0]['statistics'].append({'type':'Secret Extra','value':'TOKEN_SENTINEL'})
        p['receipt']['payload_hash']=digest(p['data'])
        r=collect([p],[{'endpoint':'fixtures/statistics','params':{'fixture':123}}])
        self.assertNotIn('TOKEN_SENTINEL',json.dumps(r))
        self.assertNotIn('Secret Extra',json.dumps(r))
        self.assertNotIn('source_packet',r['queries'][0])
        self.assertEqual(r['queries'][0]['source_evidence']['status'],'SOURCE_NOT_ARCHIVED')

    def test_unrecognized_receipt_headers_cannot_enter_archive(self):
        p=packet();p['receipt']['authorization']='TOKEN_SENTINEL'
        q=collect([p])['queries'][0]
        self.assertNotIn('TOKEN_SENTINEL',json.dumps(q))
        self.assertNotIn('authorization',q['source_packet']['receipt'])

    def test_oversized_source_budget_leaves_explicit_unavailable_evidence(self):
        p=packet();p['data']['response'][0]['venue']['name']='x'*2000;p['receipt']['payload_hash']=digest(p['data'])
        with patch.object(probe,'MAX_ARCHIVE_BYTES',100):
            r=collect([p])
        q=r['queries'][0]
        self.assertNotIn('source_packet',q)
        self.assertEqual(q['source_evidence']['reason'],'SOURCE_BYTE_BUDGET')

    def test_capture_has_no_model_ledger_or_approval_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'canonical.sqlite'
            repo=Repository(path);repo.close()
            before=path.read_bytes()
            with patch.object(probe,'get_sports',return_value=packet()), \
                 patch.object(probe,'transport_status',return_value={}):
                result=chat_gateway._execute_at('sports_probe',{'queries':[{'endpoint':'fixtures','params':{'id':123}}]},path)
            self.assertEqual(path.read_bytes(),before)
            self.assertFalse(result['money_authorized'])
            self.assertFalse(result['monetary_permission'])

    def test_durable_probe_never_checkpoints_a_new_forecast(self):
        def restore(path):
            repo=Repository(path);repo.close();return 7
        with patch.object(chat_gateway.chat_store,'configured',return_value=True), \
             patch.object(chat_gateway.chat_store,'restore',side_effect=restore), \
             patch.object(chat_gateway.chat_store,'checkpoint') as checkpoint, \
             patch.object(probe,'get_sports',return_value=packet()), \
             patch.object(probe,'transport_status',return_value={}):
            result=chat_gateway.execute('sports_probe',{'queries':[{'endpoint':'fixtures','params':{'id':123}}]})
        checkpoint.assert_not_called();self.assertEqual(result['store_revision'],7)

    def test_missing_ledger_cannot_be_created_by_a_readonly_probe(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'missing'/'canonical.sqlite'
            with patch.object(probe,'get_sports') as network:
                with self.assertRaisesRegex(ValueError,'JOURNAL_REQUIRED_FOR_PROBE'):
                    chat_gateway._execute_at('sports_probe',{'queries':[{'endpoint':'status','params':{}}]},path)
            network.assert_not_called();self.assertFalse(path.parent.exists())

    def test_actual_sdk_stops_at_first_unmarked_gateway_reply(self):
        from sefirot import football_gateway
        calls=[]
        class Response:
            status=200
            def read(self,limit):
                wrapper={'ok':True,'provider':'API_FOOTBALL_V3','provider_host':'v3.football.api-sports.io',
                         'endpoint':'/fixtures','params':{'id':123},'sports_only':True,
                         'monetary_permission':False,'execution_enabled':False,
                         'received_at':datetime.now(timezone.utc).isoformat(),'data':packet()['data']}
                return json.dumps(wrapper).encode()
            def close(self): pass
        class Opener:
            def open(self,request,timeout): calls.append(request.full_url);return Response()
        with patch.dict(os.environ,{'SEFIROT_SPORTS_GATEWAY_URL':'https://abcdefghijklmnopqrst.supabase.co/functions/v1/sefirot-sports-gateway'},clear=True), \
             patch.object(football_gateway,'build_opener',return_value=Opener()), \
             patch.object(football_gateway,'credential',return_value='SYNTHETIC_TOKEN'):
            result=probe.collect({'queries':[{'endpoint':'fixtures','params':{'id':123}}]*2})
        self.assertEqual(len(calls),1)
        self.assertEqual(result['queries'][0]['status'],'ERROR')

    def test_raw_archive_budget_applies_across_whole_job(self):
        original=packet()
        size=collect([original])['source_archive_bytes']
        with patch.object(probe,'MAX_ARCHIVE_BYTES',size+1):
            result=collect([original,original],[{'endpoint':'fixtures','params':{'id':123}}]*2)
        self.assertIn('source_packet',result['queries'][0])
        self.assertNotIn('source_packet',result['queries'][1])
        self.assertLessEqual(result['source_archive_bytes'],size+1)

    def test_sensitive_fixture_field_cannot_leak_through_source_packet(self):
        p=packet();p['data']['response'][0]['api_key']='TOKEN_SENTINEL';p['receipt']['payload_hash']=digest(p['data'])
        result=collect([p])
        self.assertNotIn('TOKEN_SENTINEL',json.dumps(result))
        self.assertNotIn('source_packet',result['queries'][0])

    def test_bad_receipt_hash_is_not_recomputed_as_original_evidence(self):
        p=packet();p['receipt']['payload_hash']='0'*64
        result=collect([p]);q=result['queries'][0]
        self.assertEqual(q['receipt']['payload_hash'],'0'*64)
        self.assertNotIn('source_packet',q)
        self.assertEqual(q['source_evidence']['reason'],'SOURCE_HASH_MISMATCH')

    def test_corrupted_readonly_ledger_blocks_before_network(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'canonical.sqlite'
            repo=Repository(path)
            repo.db.execute("INSERT INTO audit_logs(at,event,payload,previous_hash,hash) VALUES(?,?,?,?,?)",
                            ('2026-10-13T10:00:00Z','BROKEN','{}','0'*64,'1'*64))
            repo.close();before=path.read_bytes()
            with patch.object(probe,'get_sports') as network:
                with self.assertRaisesRegex(ValueError,'JOURNAL_INTEGRITY'):
                    chat_gateway._execute_at('sports_probe',{'queries':[{'endpoint':'status','params':{}}]},path)
            network.assert_not_called();self.assertEqual(path.read_bytes(),before)

    def test_conflicting_duplicate_statistic_is_not_last_value_wins(self):
        p=packet('fixtures/statistics',{'fixture':123})
        p['data']['response'][0]['statistics'].append({'type':'Corner Kicks','value':99})
        p['receipt']['payload_hash']=digest(p['data'])
        result=collect([p],[{'endpoint':'fixtures/statistics','params':{'fixture':123}}])
        self.assertEqual(result['queries'][0]['status'],'ERROR')
        self.assertEqual(result['queries'][0]['reason'],'PROBE_DUPLICATE_STATISTIC')

    def test_object_statistic_cannot_smuggle_credentials_into_projection(self):
        p=packet('fixtures/statistics',{'fixture':123})
        p['data']['response'][0]['statistics'][0]['value']={'api_key':'TOKEN_SENTINEL'}
        p['receipt']['payload_hash']=digest(p['data'])
        result=collect([p],[{'endpoint':'fixtures/statistics','params':{'fixture':123}}])
        self.assertEqual(result['queries'][0]['reason'],'PROBE_INVALID_STATISTIC_VALUE')
        self.assertNotIn('TOKEN_SENTINEL',json.dumps(result))

    def test_editing_returned_projection_does_not_mutate_original_packet(self):
        p=packet();saved=copy.deepcopy(p)
        result=collect([p]);result['queries'][0]['rows'][0]['fulltime']['home']=99
        self.assertEqual(p,saved)

    def test_status_summary_cannot_copy_unknown_receipt_credentials(self):
        p=packet();p['data']['response']={'subscription':{'active':True,'plan':'SYNTHETIC'},
                                        'requests':{'current':1,'limit_day':100}}
        p['data']['get']='status';p['data']['parameters']={}
        p['receipt'].update(endpoint='/status',parameters={},authorization='TOKEN_SENTINEL')
        p['receipt']['payload_hash']=digest(p['data'])
        result=collect([p],[{'endpoint':'status','params':{}}])
        self.assertNotIn('TOKEN_SENTINEL',json.dumps(result))


if __name__=='__main__':unittest.main()
