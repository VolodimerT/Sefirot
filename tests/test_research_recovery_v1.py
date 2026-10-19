"""Safety-stop regressions: isolated owned transports, never real API evidence."""
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'src'),str(ROOT/'scripts'),str(ROOT/'tests')]
import chat_sports_probe as probe
from sefirot import football_gateway as gateway
from test_guarded_probe_evidence import packet
from test_sports_budget_gateway_response import _Response

class ResearchRecoveryTests(unittest.TestCase):
    def unsafe(self):
        p=packet('fixtures/statistics',{'fixture':123})
        p['data']['response'][0]['statistics'].extend([
            {'type':'Expected Threat','value':'OWNED_PRIVATE_SENTINEL'},
            {'type':'S E C R E T','value':'ANOTHER_PRIVATE_SENTINEL'}])
        p['receipt']['payload_hash']=probe.digest(p['data']);return p
    def collect(self,packets,queries,sink=None):
        with patch.object(probe,'get_sports',side_effect=packets) as provider,patch.object(probe,'transport_status',return_value={'transport':'SUPABASE_GATEWAY'}):
            out=probe.collect({'queries':queries},packet_sink=sink)
        return out,provider.call_count
    def test_source_safety_stops_remaining_stats_and_exposes_labels_only(self):
        q={'endpoint':'fixtures/statistics','params':{'fixture':123}}
        r,n=self.collect([self.unsafe(),packet('fixtures/statistics')],[q,q])
        self.assertEqual(n,1);self.assertEqual(len(r['queries']),1)
        item=r['queries'][0];self.assertEqual(item['status'],'ERROR');self.assertEqual(item['reason'],'SOURCE_SAFETY')
        self.assertEqual(item['source_evidence']['unsupported_stat_labels'],['Expected Threat'])
        for key in ('rows','source_packet','projection_hash','count'):self.assertNotIn(key,item)
        for value in ('OWNED_PRIVATE_SENTINEL','ANOTHER_PRIVATE_SENTINEL','S E C R E T'):self.assertNotIn(value,json.dumps(r))
    def test_sink_is_never_invoked_for_unsafe_source(self):
        with patch('builtins.print'):
            calls=[];q={'endpoint':'fixtures/statistics','params':{'fixture':123}}
            r,n=self.collect([self.unsafe()],[q,q],sink=calls.append)
        self.assertEqual(n,1);self.assertEqual(calls,[]);self.assertEqual(r['queries'][0]['reason'],'SOURCE_SAFETY')
    def test_safety_stop_retains_prior_original_packet_and_never_refetches(self):
        original=packet();raw=probe.canonical(original);good={'endpoint':'fixtures','params':{'id':123}}
        bad={'endpoint':'fixtures/statistics','params':{'fixture':123}}
        r,n=self.collect([original,self.unsafe()],[good,bad,bad])
        self.assertEqual(n,2);self.assertEqual(len(r['queries']),2)
        self.assertEqual(probe.verify_evidence(r['queries'][0])['status'],'CANONICAL_PACKET_ARCHIVED')
        self.assertEqual(probe.canonical(original),raw);self.assertEqual(r['queries'][-1]['reason'],'SOURCE_SAFETY')
    def test_real_gateway_transport_classifies_safe_error_and_closes_response(self):
        response=_Response(502,{'ok':False,'error':'SOURCE_SAFETY','unsupported_stat_labels':[
            'Expected Threat','S E C R E T','API Token','Cookie','PRIVATE123',{'value':'PRIVATE'},None]})
        calls=[]
        def opener(req,timeout):calls.append(req);return response
        with patch.dict(os.environ,{'SEFIROT_SPORTS_GATEWAY_URL':'https://abcdefghijklmnopqrst.supabase.co/functions/v1/sefirot-sports-gateway'}),patch.object(gateway,'credential',return_value='OWNED_TOKEN'),self.assertRaises(gateway.SportsSourceSafetyError) as err:
            gateway.get_sports('fixtures/statistics',{'fixture':123},opener=opener,require_shared_budget=True)
        self.assertEqual(err.exception.code,'SOURCE_SAFETY');self.assertEqual(err.exception.unsupported_stat_labels,['Expected Threat'])
        self.assertTrue(response.closed);self.assertEqual(len(calls),1);self.assertNotIn('PRIVATE',str(err.exception))
    def test_gateway_safety_diagnostic_reaches_probe_without_disguised_auth_error(self):
        q={'endpoint':'fixtures/statistics','params':{'fixture':123}}
        r,n=self.collect([gateway.SportsSourceSafetyError(['Expected Threat','Secret Value'])],[q,q])
        self.assertEqual(n,1);self.assertEqual(r['queries'][0]['reason'],'SOURCE_SAFETY')
        self.assertEqual(r['queries'][0]['source_evidence']['unsupported_stat_labels'],['Expected Threat'])
    def test_real_snake_case_diagnostics_and_original_hashes_are_preserved(self):
        p=packet('fixtures/statistics',{'fixture':123});p['data']['response'][0]['statistics'] += [
            {'type':'expected_goals','value':'1.45'},{'type':'goals_prevented','value':None}]
        p['receipt']['payload_hash']=probe.digest(p['data'])
        r,n=self.collect([p],[{'endpoint':'fixtures/statistics','params':{'fixture':123}}])
        self.assertEqual(n,1);self.assertEqual(r['queries'][0]['status'],'DONE')
        self.assertEqual(r['queries'][0]['source_packet']['data'],p['data'])
        self.assertEqual(probe.verify_evidence(r['queries'][0])['status'],'CANONICAL_PACKET_ARCHIVED')
