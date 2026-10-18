"""Owned sealed examples and local HTTP only. No authentic prices/fit claimed."""
from copy import deepcopy
from datetime import datetime,timedelta,timezone
import http.client
import json
from pathlib import Path
import sys
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT),str(ROOT/'src'),str(ROOT/'scripts')]
from sefirot.repository import Repository
from sefirot.service import Service
from sefirot.fixtures import example
from research.manual_quote import preview
from scripts.operator_cockpit import make_server

class ManualQuoteTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)/'original.sqlite'
        self.now=datetime.now(timezone.utc)-timedelta(seconds=2);case=example(self.now,'owned-manual-example')
        self.repo=Repository(self.path);self.addCleanup(self.repo.close)
        self.pred=Service(self.repo,clock=lambda:self.now).capture(case['sports'],case['markets'])
        self.at=(self.now+timedelta(seconds=1)).isoformat()
        q=case['quotes'][0]
        self.payload={'prediction_id':self.pred['id'],'fixture_id':self.pred['sports']['match']['id'],
            'market':q['market'],'period':'FT_REGULATION_90','bookmaker':'MANUAL_OPERATOR',
            'odds':q['odds'],'observed_at':self.at,'rules_confirmed':True}
    def test_valid_manual_price_never_admits_synthetic_probability_or_writes(self):
        before=self.path.read_bytes();out=preview(self.repo,self.payload,self.at)
        self.assertEqual(out['decision'],'PASS');self.assertIsNone(out['probability']);self.assertIsNone(out['ev'])
        self.assertFalse(out['decision_created']);self.assertEqual(self.path.read_bytes(),before)
    def test_market_fixture_period_freshness_and_exact_rules_are_required(self):
        for key,value in [('fixture_id','other'),('period','FIRST_HALF'),('rules_confirmed',1),
                          ('observed_at',(self.now-timedelta(minutes=5)).isoformat()),('odds',True)]:
            with self.subTest(key=key),self.assertRaises((ValueError,KeyError)):
                preview(self.repo,{**self.payload,key:value},self.at)
    def test_http_manual_preview_is_optin_authenticated_same_origin_and_read_only(self):
        server=make_server(database=self.path,token='x'*40,manual_quotes=True)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            origin='http://127.0.0.1:'+str(server.server_port)
            self.payload['observed_at']=datetime.now(timezone.utc).isoformat()
            before=self.path.read_bytes()
            for auth,site,expected in [(False,origin,401),(True,'http://hostile.invalid',403),(True,origin,200)]:
                c=http.client.HTTPConnection('127.0.0.1',server.server_port,timeout=5)
                headers={'Content-Type':'application/json','Origin':site}
                if auth:headers['Authorization']='Bearer '+'x'*40
                c.request('POST','/api/manual-quote',json.dumps(self.payload),headers)
                r=c.getresponse();data=json.loads(r.read());c.close();self.assertEqual(r.status,expected,data)
                if expected==200:self.assertEqual(data['data']['decision'],'PASS')
            self.assertEqual(self.path.read_bytes(),before)
        finally:server.shutdown();server.server_close();thread.join(5)
