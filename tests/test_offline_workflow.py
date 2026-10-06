"""Failure injection for atomic offline processing and safe read-only commands."""
from contextlib import closing, redirect_stdout, redirect_stderr
from datetime import datetime,timedelta,timezone
import copy
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from sefirot.cli import main
from sefirot.fixtures import example
from sefirot.repository import Repository
from sefirot.service import Service
from sefirot.worker import process_inbox,render_inbox
NOW=datetime(2030,1,1,12,tzinfo=timezone.utc)


class AtomicInboxTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.inbox=self.root/'inbox';self.inbox.mkdir()
        self.repo=Repository(self.root/'ledger.sqlite');self.addCleanup(self.repo.close)
        self.clock=[NOW];self.service=Service(self.repo,clock=lambda:self.clock[0]);self.case=example(NOW)
    def job(self,name,kind,payload):
        data={'id':name,'type':kind,'payload':payload}
        (self.inbox/(name+'.json')).write_text(json.dumps(data));return data
    def capture(self):
        self.job('01-capture','CAPTURE',{'sports':self.case['sports']})
        row=process_inbox(self.service,self.inbox)[0];self.assertEqual(row['status'],'DONE')
        return row
    def fail_receipt(self):
        insert=self.repo.insert
        def fail(table,*args,**kwargs):
            if table=='jobs':raise sqlite3.OperationalError('injected receipt failure')
            return insert(table,*args,**kwargs)
        return patch.object(self.repo,'insert',side_effect=fail)
    def decision(self):
        self.clock[0]=NOW+timedelta(minutes=2)
        return self.job('02-decide','DECIDE',{'prediction_job_id':'01-capture','quotes':self.case['quotes'],
            'recheck':self.case['recheck'],'portfolio':{'bankroll':1000.,'peak':1000.}})
    def test_capture_and_receipt_rollback_together_then_retry_once(self):
        self.job('01-capture','CAPTURE',{'sports':self.case['sports']})
        with self.fail_receipt():self.assertEqual(process_inbox(self.service,self.inbox)[0]['status'],'ERROR')
        for table in ('predictions','matches','teams','model_versions','jobs'):self.assertEqual(self.repo.all(table),[])
        self.assertEqual(self.repo.db.execute('SELECT count(*) FROM audit_logs').fetchone()[0],0)
        self.assertEqual(process_inbox(self.service,self.inbox)[0]['status'],'DONE')
        self.assertEqual(process_inbox(self.service,self.inbox)[0]['status'],'ALREADY_PROCESSED')
        self.assertEqual(len(self.repo.all('predictions')),1);self.assertTrue(self.repo.verify())
    def test_busy_commit_rolls_back_and_retry_does_not_reuse_pending_receipt(self):
        self.job('01-capture','CAPTURE',{'sports':self.case['sports']})
        self.repo.db.execute('PRAGMA busy_timeout=1')
        with closing(sqlite3.connect(self.root/'ledger.sqlite',isolation_level=None)) as reader:
            reader.execute('BEGIN');reader.execute('SELECT count(*) FROM audit_logs').fetchone()
            failed=process_inbox(self.service,self.inbox)
            self.assertEqual(failed[0]['status'],'ERROR')
            self.assertFalse(self.repo.db.in_transaction)
            for table in ('predictions','matches','teams','model_versions','jobs'):
                self.assertEqual(self.repo.all(table),[])
            self.assertEqual(self.repo.db.execute('SELECT count(*) FROM audit_logs').fetchone()[0],0)
            reader.execute('ROLLBACK')
        self.assertEqual(process_inbox(self.service,self.inbox)[0]['status'],'DONE')
        self.assertEqual(process_inbox(self.service,self.inbox)[0]['status'],'ALREADY_PROCESSED')
        self.assertFalse(self.repo.db.in_transaction);self.assertTrue(self.repo.verify())
    def test_decision_quotes_and_receipt_rollback_together(self):
        self.capture();self.decision();before=self.repo.db.execute('SELECT count(*) FROM audit_logs').fetchone()[0]
        with self.fail_receipt():self.assertEqual(process_inbox(self.service,self.inbox)[1]['status'],'ERROR')
        for table in ('decisions','odds_snapshots'):self.assertEqual(self.repo.all(table),[])
        self.assertEqual(self.repo.db.execute('SELECT count(*) FROM audit_logs').fetchone()[0],before)
        rows=process_inbox(self.service,self.inbox);self.assertEqual(rows[1]['status'],'DONE')
        self.assertEqual(len(self.repo.all('decisions')),1);self.assertTrue(self.repo.verify())
    def test_result_feedback_and_receipt_rollback_together(self):
        self.capture();self.clock[0]=NOW+timedelta(minutes=232)
        self.job('03-result','RESULT',self.case['result'])
        with self.fail_receipt():self.assertEqual(process_inbox(self.service,self.inbox)[1]['status'],'ERROR')
        for table in ('results','calibration_history','health_events'):self.assertEqual(self.repo.all(table),[])
        self.assertEqual(process_inbox(self.service,self.inbox)[1]['status'],'DONE')
        self.assertEqual(len(self.repo.all('calibration_history')),7);self.assertTrue(self.repo.verify())
    def test_closing_and_receipt_rollback_together(self):
        self.capture();self.clock[0]=NOW+timedelta(minutes=2)
        quote={**self.case['quotes'][0],'phase':'CLOSE'}
        self.job('03-closing','CLOSING',{'match_id':self.case['sports']['match']['id'],'quote':quote})
        with self.fail_receipt():self.assertEqual(process_inbox(self.service,self.inbox)[1]['status'],'ERROR')
        self.assertEqual(self.repo.all('closing_odds'),[])
        self.assertEqual(process_inbox(self.service,self.inbox)[1]['status'],'DONE')
        self.assertEqual(len(self.repo.all('closing_odds')),1);self.assertTrue(self.repo.verify())
    def test_quote_job_is_not_opened_until_capture_has_been_committed(self):
        self.job('01-capture','CAPTURE',{'sports':self.case['sports']});self.decision();self.clock[0]=NOW
        original=Path.read_text
        def read(path,*args,**kwargs):
            if path==self.inbox/'02-decide.json':
                self.assertEqual(len(self.repo.all('predictions')),1)
                self.assertFalse(self.repo.db.in_transaction)
                self.clock[0]=NOW+timedelta(minutes=2)
            return original(path,*args,**kwargs)
        with patch.object(Path,'read_text',read):rows=process_inbox(self.service,self.inbox)
        self.assertEqual([r['status'] for r in rows],['DONE','DONE'])
    def test_default_markets_named_reference_and_repeat_card_are_consistent(self):
        capture=self.capture();self.assertEqual(len(self.repo.get('predictions',capture['prediction_id'])['candidates']),7)
        self.decision();rows=process_inbox(self.service,self.inbox);card=rows[1]['decision_card']
        self.assertEqual(card['decision'],'PASS');self.assertIn('SYNTHETIC',json.dumps(card))
        again=process_inbox(self.service,self.inbox)
        self.assertEqual(again[1]['decision_card'],card);self.assertEqual(again[1]['status'],'ALREADY_PROCESSED')
        self.assertEqual(len(self.repo.all('decisions')),1);self.assertTrue(self.service.replay(rows[1]['result_id'])['matches'])
        self.assertIn('прогноз зафиксирован до цены',render_inbox(rows))
    def test_changed_job_id_is_rejected_before_action(self):
        self.capture();data=json.loads((self.inbox/'01-capture.json').read_text())
        data['payload']['sports']['match']['id']='different'
        (self.inbox/'01-capture.json').write_text(json.dumps(data))
        self.assertEqual(process_inbox(self.service,self.inbox)[0]['status'],'ERROR')
        self.assertEqual(len(self.repo.all('predictions')),1)
    def test_missing_ambiguous_and_non_capture_references_never_record_decisions(self):
        self.capture();self.decision();p=self.inbox/'02-decide.json';original=json.loads(p.read_text())
        for change in ({'prediction_job_id':'missing'}, {'prediction_id':'also-set'}, {'prediction_job_id':None}):
            data=copy.deepcopy(original);data['payload'].update(change);p.write_text(json.dumps(data))
            self.assertEqual(process_inbox(self.service,self.inbox)[1]['status'],'ERROR')
        self.clock[0]=NOW+timedelta(minutes=232)
        self.job('03-result','RESULT',self.case['result']);p.unlink();process_inbox(self.service,self.inbox)
        self.clock[0]=NOW+timedelta(minutes=2)
        original['payload']['prediction_job_id']='03-result';p.write_text(json.dumps(original))
        self.assertEqual(process_inbox(self.service,self.inbox)[1]['status'],'ERROR')
        self.assertEqual(self.repo.all('decisions'),[])
    def test_tampered_receipt_stops_all_jobs_before_action(self):
        self.capture();self.repo.db.execute('DROP TRIGGER jobs_no_update')
        self.repo.db.execute("UPDATE jobs SET payload='{}'")
        self.job('02-capture','CAPTURE',{'sports':example(NOW,'other')['sports']})
        rows=process_inbox(self.service,self.inbox)
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['error'],'journal integrity failed')
        self.assertEqual(len(self.repo.all('predictions')),1)
    def test_inner_failure_rolls_back_only_savepoint_and_outer_failure_all(self):
        with self.repo.transaction():
            self.repo.log('OUTER',NOW.isoformat(),{})
            try:
                with self.repo.transaction():
                    self.repo.log('INNER',NOW.isoformat(),{});raise RuntimeError('inner failure')
            except RuntimeError:pass
            self.repo.log('AFTER',NOW.isoformat(),{})
        self.assertEqual([r[0] for r in self.repo.db.execute('SELECT event FROM audit_logs ORDER BY id')],['OUTER','AFTER'])
        with self.assertRaises(RuntimeError),self.repo.transaction():
            with self.repo.transaction():self.repo.log('NESTED_SUCCESS',NOW.isoformat(),{})
            raise RuntimeError('outer failure')
        self.assertEqual(self.repo.db.execute('SELECT count(*) FROM audit_logs').fetchone()[0],2)
        self.assertTrue(self.repo.verify())


class OfflineCliTests(unittest.TestCase):
    def invoke(self,*args):
        out=io.StringIO();err=io.StringIO()
        with redirect_stdout(out),redirect_stderr(err):code=main(list(args))
        return code,out.getvalue(),err.getvalue()
    def test_invalid_jobs_fail_both_json_and_text_exit_status(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);folder=root/'inbox';folder.mkdir();(folder/'bad.json').write_text('{')
            for text in (False,True):
                code,out,_=self.invoke('--db',str(root/'ledger.sqlite'),'work',str(folder),*(['--text'] if text else []))
                self.assertEqual(code,2);self.assertIn('ошибка' if text else 'ERROR',out)
    def test_read_commands_refuse_missing_ledger_without_creating_parent(self):
        with tempfile.TemporaryDirectory() as t:
            db=Path(t)/'missing'/'ledger.sqlite'
            for args in [('report',),('accounting',),('replay','missing'),('compare','old','new')]:
                self.assertEqual(self.invoke('--db',str(db),*args)[0],2)
                self.assertFalse(db.parent.exists())
    def test_read_commands_preserve_existing_ledger_bytes(self):
        with tempfile.TemporaryDirectory() as t:
            db=Path(t)/'ledger.sqlite';case=example(NOW)
            with closing(Repository(db)) as repo:
                clock=[NOW];s=Service(repo,clock=lambda:clock[0]);p=s.capture(case['sports'],case['markets'])
                clock[0]=NOW+timedelta(minutes=2)
                d=s.decide(p['id'],case['quotes'],case['recheck'],{'bankroll':1000.,'peak':1000.},clock[0].isoformat())
            before=db.read_bytes()
            for args in [('report',),('accounting',),('replay',d['id'])]:
                self.assertEqual(self.invoke('--db',str(db),*args)[0],0)
                self.assertEqual(db.read_bytes(),before)
    def test_backtest_is_standalone_and_does_not_create_ledger(self):
        with tempfile.TemporaryDirectory() as t:
            db=Path(t)/'missing'/'ledger.sqlite'
            code,out,_=self.invoke('--db',str(db),'backtest',str(ROOT/'examples/core2_backtest.json'))
            self.assertEqual(code,0);self.assertEqual(json.loads(out)['fixtures'],12);self.assertFalse(db.parent.exists())
    def test_capture_runs_without_network_and_empty_queue_has_instructions(self):
        with tempfile.TemporaryDirectory() as t:
            root=Path(t);folder=root/'inbox';folder.mkdir()
            (folder/'01-capture.json').write_text(json.dumps({'id':'capture','type':'CAPTURE','payload':{'sports':example()['sports']}}))
            with patch('socket.socket',side_effect=AssertionError('unexpected network')):
                code,out,_=self.invoke('--db',str(root/'ledger.sqlite'),'work',str(folder),'--text')
            self.assertEqual(code,0);self.assertIn('прогноз зафиксирован до цены',out)
            self.assertIn('Очередь пуста',render_inbox([]))
