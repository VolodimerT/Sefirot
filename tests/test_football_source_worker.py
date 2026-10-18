"""Source context, acknowledgements and pre-claim archive readiness, all offline."""
from copy import deepcopy
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'src'),str(ROOT/'scripts')]
from sefirot import football_gateway as gateway
from sefirot.contracts import digest
import chat_queue
from test_football_pipeline import packet
from test_sports_budget_gateway_response import _Response

UID='00000000-0000-0000-0000-000000000088'
URL='https://abcdefghijklmnopqrst.supabase.co/functions/v1/sefirot-sports-gateway'
class SourceWorkerTests(unittest.TestCase):
    def test_context_without_gateway_never_falls_back_to_direct(self):
        with gateway.source_job_context(UID,1),patch.dict(os.environ,{'SEFIROT_SPORTS_GATEWAY_URL':''}),patch.object(gateway,'get') as direct:
            with self.assertRaises(ValueError):gateway.get_sports('fixtures',{'league':39,'season':2026})
            direct.assert_not_called()
    def test_ack_is_bound_to_exact_packet_and_server_chronology(self):
        p=packet();r=p['receipt'];r['request_started_at']='2026-10-16T11:59:59+00:00'
        wrapper={'ok':True,'provider':r['provider'],'provider_host':r['provider_host'],'endpoint':r['endpoint'],
            'params':r['parameters'],'sports_only':True,'monetary_permission':False,'execution_enabled':False,
            'shared_budget_guard':'POSTGRES_RESERVATION_V1','received_at':r['received_at'],'data':p['data'],
            'source_archive_receipt':r,'source_archive':{'stored':True,'raw_sha256':digest(p)}}
        def run(w):
            response=_Response(200,w);seen=[]
            def opener(req,timeout):seen.append(req);return response
            clock=iter([datetime(2026,10,16,11,59,58,tzinfo=timezone.utc),datetime(2026,10,16,12,0,1,tzinfo=timezone.utc)])
            with gateway.source_job_context(UID,1),patch.dict(os.environ,{'SEFIROT_SPORTS_GATEWAY_URL':URL}),patch.object(gateway,'credential',return_value='SYNTHETIC_TOKEN'):
                out=gateway.get_sports('fixtures',{'league':39,'season':2026},opener=opener,clock=lambda:next(clock),require_shared_budget=True)
            self.assertTrue(response.closed);self.assertEqual(seen[0].get_header('X-sefirot-source-job-id'),UID)
            return out
        confirmed = run(wrapper)
        self.assertEqual({k:confirmed[k] for k in ('data','receipt')},p)
        self.assertEqual(confirmed['private_source_archive_hash'],digest(p))
        for mutate in (lambda w:w.pop('source_archive'),lambda w:w['source_archive'].update(raw_sha256='b'*64)):
            w=deepcopy(wrapper);mutate(w)
            with self.assertRaises(ValueError):run(w)
        self.assertIsNone(gateway._SOURCE_JOB.get())
    def test_archive_unavailable_blocks_before_claim_or_provider(self):
        env={'SEFIROT_CHAT_JOB_WORKER_MODE':'sports_probe','SEFIROT_SOURCE_ARCHIVE':'1'}
        with patch.dict(os.environ,env),patch.object(chat_queue,'read_only_mode',return_value=True),patch.object(chat_queue,'request',return_value={'schema':'football-source-store-v1','ready':False}) as request,patch('chat_sports_probe.collect') as collect:
            with self.assertRaisesRegex(RuntimeError,'SOURCE_ARCHIVE_NOT_READY'):chat_queue.process_one()
            request.assert_called_once_with({'action':'source_status'});collect.assert_not_called()
    def test_lease_context_reaches_existing_collector_without_core_writes(self):
        calls=[]
        job={'id':UID,'kind':'sports_probe','attempt':1,'request':{'queries':[]}}
        def request(p):
            calls.append(p['action'])
            if p['action']=='source_status':return {'schema':'football-source-store-v1','ready':True}
            if p['action']=='claim':return {'job':job}
            return {'completed':True,'id':UID,'attempts':1}
        def collect(p,packet_sink):
            self.assertEqual(gateway._SOURCE_JOB.get(),(UID,1));self.assertTrue(callable(packet_sink))
            return {'queries':[],'monetary_permission':False}
        with patch.dict(os.environ,{'SEFIROT_CHAT_JOB_WORKER_MODE':'sports_probe','SEFIROT_SOURCE_ARCHIVE':'1'}),patch.object(chat_queue,'read_only_mode',return_value=True),patch.object(chat_queue,'request',side_effect=request),patch('chat_sports_probe.collect',side_effect=collect):
            self.assertTrue(chat_queue.process_one())
        self.assertEqual(calls,['source_status','claim','probe_complete']);self.assertIsNone(gateway._SOURCE_JOB.get())
