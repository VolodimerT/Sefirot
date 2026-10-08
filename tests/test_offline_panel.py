"""Real local UI requests preserve manual processing, seals and read-only views."""
from contextlib import closing,redirect_stdout,redirect_stderr
from datetime import datetime,timedelta,timezone
import copy
import http.client
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.parse import urlencode

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from sefirot.cli import main
from sefirot.fixtures import example
from sefirot.offline_panel import Panel,make_server,render_panel
from sefirot.repository import Repository

NOW=datetime(2030,1,1,12,tzinfo=timezone.utc)


class PanelFixture:
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.database=self.root/'data'/'ledger.sqlite'
        self.inbox=self.root/'inbox';self.clock=[NOW];self.case=example(NOW)
        self.panel=Panel(self.database,self.inbox,clock=lambda:self.clock[0])

    def job(self,name,kind,payload):
        self.inbox.mkdir(exist_ok=True)
        (self.inbox/(name+'.json')).write_text(json.dumps({'id':name,'type':kind,'payload':payload}),encoding='utf-8')

    def capture(self):
        self.job('01-capture','CAPTURE',{'sports':self.case['sports']});self.panel.run()
        self.assertEqual(self.panel.last_run[0]['status'],'DONE')

    def decide(self):
        self.clock[0]=NOW+timedelta(minutes=2)
        self.job('02-decide','DECIDE',{'prediction_job_id':'01-capture','quotes':self.case['quotes'],
            'recheck':self.case['recheck'],'portfolio':{'bankroll':1000.,'peak':1000.}})
        self.panel.run();self.assertEqual(self.panel.last_run[1]['status'],'DONE')


class PanelViewTests(PanelFixture,unittest.TestCase):
    def test_empty_view_and_empty_run_create_neither_folder_nor_ledger(self):
        self.assertEqual(self.panel.snapshot()['status'],'NO_LEDGER')
        self.panel.run();html=render_panel(self.panel.snapshot(),self.panel.token)
        self.assertIn('Начните с прогноза',html);self.assertIn('disabled',html)
        self.assertFalse(self.database.parent.exists());self.assertFalse(self.inbox.exists())

    def test_preview_lists_quote_filename_without_reading_pending_jobs(self):
        self.job('02-decide','DECIDE',{'quotes':'not opened'})
        with patch.object(Path,'read_text',side_effect=AssertionError('pending job opened')):
            view=self.panel.snapshot();html=render_panel(view,self.panel.token)
        self.assertEqual(view['files'],['02-decide.json']);self.assertIn('02-decide.json',html)
        self.assertFalse(self.database.exists())

    def test_existing_cards_are_read_only_and_unchanged_not_new_admission(self):
        self.capture();self.decide();before=self.database.read_bytes()
        view=self.panel.snapshot();html=render_panel(view,self.panel.token)
        self.assertEqual(self.database.read_bytes(),before);self.assertEqual(view['recorded_jobs'],2)
        self.assertEqual(view['records'][0]['decision_card'],self.panel.last_run[1]['decision_card'])
        self.assertIn('Сохранённое решение',html);self.assertIn('Для нового входа нужна новая перепроверка',html)
        self.assertIn('Киев',html);self.assertEqual(view['records'][0]['decision_card']['decision'],'PASS')

    def test_future_receipts_are_not_backfilled_into_an_earlier_view(self):
        self.capture();self.decide();self.clock[0]=NOW
        view=self.panel.snapshot();self.assertEqual(view['recorded_jobs'],1)
        self.assertEqual(view['records'][0]['job_type'],'CAPTURE')

    def test_quotes_open_only_after_capture_is_durable_in_same_manual_run(self):
        self.job('01-capture','CAPTURE',{'sports':self.case['sports']})
        self.job('02-decide','DECIDE',{'prediction_job_id':'01-capture','quotes':self.case['quotes'],
            'recheck':self.case['recheck'],'portfolio':{'bankroll':1000.,'peak':1000.}})
        original=Path.read_text
        def read(path,*args,**kwargs):
            if path==self.inbox/'02-decide.json':
                with closing(Repository(self.database,read_only=True)) as repo:
                    self.assertEqual(len(repo.all('predictions')),1)
                    self.assertEqual(len(repo.all('jobs')),1)
                self.clock[0]=NOW+timedelta(minutes=2)
            return original(path,*args,**kwargs)
        with patch.object(Path,'read_text',read):self.panel.run()
        self.assertEqual([r['status'] for r in self.panel.last_run],['DONE','DONE'])

    def test_tampered_receipt_disables_view_and_processing_without_rewriting_ledger(self):
        self.capture()
        with closing(Repository(self.database)) as repo:
            repo.db.execute('DROP TRIGGER jobs_no_update');repo.db.execute("UPDATE jobs SET payload='{}'")
        before=self.database.read_bytes();view=self.panel.snapshot();self.panel.run()
        self.assertEqual(view['status'],'ERROR');self.assertEqual(view['records'],[])
        self.assertEqual(self.panel.last_run[0]['status'],'ERROR');self.assertEqual(self.database.read_bytes(),before)

    def test_user_text_is_escaped_in_filenames_cards_and_errors(self):
        self.capture();self.decide();view=copy.deepcopy(self.panel.snapshot())
        attack='<script>alert(1)</script>'
        view['files']=[attack];view['records'][0]['decision_card']['match']['home']=attack
        view['last_run']=[{'status':'ERROR','error':attack}]
        html=render_panel(view,self.panel.token)
        self.assertNotIn(attack,html);self.assertIn('&lt;script&gt;',html)

    def test_failed_job_is_error_and_safe_retry_remains_idempotent(self):
        self.capture();(self.inbox/'bad.json').write_text('{',encoding='utf-8')
        self.panel.run();self.assertEqual(self.panel.last_run[1]['status'],'ERROR')
        self.assertIn('ошибок 1',render_panel(self.panel.snapshot(),self.panel.token))
        (self.inbox/'bad.json').unlink();self.panel.run()
        self.assertEqual(self.panel.last_run[0]['status'],'ALREADY_PROCESSED')
        with closing(Repository(self.database,read_only=True)) as repo:
            self.assertEqual(len(repo.all('predictions')),1);self.assertTrue(repo.verify())


class PanelHttpTests(PanelFixture,unittest.TestCase):
    def setUp(self):
        super().setUp();self.server=make_server(self.panel,0)
        self.thread=threading.Thread(target=lambda:self.server.serve_forever(poll_interval=.01),daemon=True)
        self.thread.start();self.addCleanup(self.stop)
        self.origin=f'http://127.0.0.1:{self.server.server_port}'

    def stop(self):
        self.server.shutdown();self.thread.join(timeout=3);self.server.server_close()

    def request(self,method='GET',path='/',body=None,headers=None):
        with closing(http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)) as client:
            client.request(method,path,body=body,headers=headers or {})
            response=client.getresponse();return response.status,dict(response.getheaders()),response.read().decode('utf-8')

    def post(self,body=None,**headers):
        defaults={'Origin':self.origin,'Content-Type':'application/x-www-form-urlencoded'};defaults.update(headers)
        return self.request('POST','/run',urlencode({'token':self.panel.token}) if body is None else body,defaults)

    def test_get_is_read_only_no_remote_assets_and_no_script_or_auto_processing(self):
        self.job('01-capture','CAPTURE',{'sports':self.case['sports']})
        status,headers,html=self.request()
        self.assertEqual(status,200);self.assertEqual(self.server.server_address[0],'127.0.0.1')
        self.assertEqual(headers['Cache-Control'],'no-store');self.assertIn("default-src 'none'",headers['Content-Security-Policy'])
        self.assertEqual(headers['Referrer-Policy'],'same-origin')  # Keep Origin on local form POST.
        self.assertNotIn('<script',html);self.assertNotIn('src="http',html);self.assertFalse(self.database.exists())

    def test_only_valid_origin_and_session_token_can_process_jobs(self):
        self.job('01-capture','CAPTURE',{'sports':self.case['sports']})
        for origin in ('https://example.invalid','null',''):
            self.assertEqual(self.post(Origin=origin)[0],403)
        self.assertEqual(self.request('POST','/run',urlencode({'token':self.panel.token}),{'Content-Type':'application/x-www-form-urlencoded'})[0],403)
        self.assertEqual(self.post('token=wrong')[0],403);self.assertFalse(self.database.exists())
        self.assertEqual(self.post()[0],303);self.assertTrue(self.database.exists())

    def test_wrong_host_rebinding_and_duplicate_host_are_rejected(self):
        for host in ('localhost:'+str(self.server.server_port),'evil.invalid:'+str(self.server.server_port),''):
            self.assertEqual(self.request(headers={'Host':host})[0],403)
            self.assertEqual(self.post(Host=host)[0],403)
        with closing(http.client.HTTPConnection('127.0.0.1',self.server.server_port,timeout=5)) as c:
            c.putrequest('GET','/');c.putheader('Host','evil.invalid');c.endheaders()
            response=c.getresponse();self.assertEqual(response.status,403);response.read()
        self.assertFalse(self.database.exists())

    def test_body_contract_limits_duplicates_and_nonascii_tokens_do_not_run_actions(self):
        for body,expected in [('token=wrong&token=again',400),('token=%E6%B5%8B%E8%AF%95',403),('token',400),('x=wrong',403),('token='+'x'*600,413)]:
            self.assertEqual(self.post(body)[0],expected)
        self.assertFalse(self.database.exists())

    def test_incorrect_content_type_and_chunked_transport_are_rejected(self):
        self.assertEqual(self.post(**{'Content-Type':'application/json'})[0],415)
        self.assertEqual(self.post(**{'Transfer-Encoding':'chunked'})[0],400)
        self.assertFalse(self.database.exists())

    def test_manual_repeat_does_not_duplicate_capture_or_change_record(self):
        self.job('01-capture','CAPTURE',{'sports':self.case['sports']})
        self.assertEqual(self.post()[0],303)
        with closing(Repository(self.database,read_only=True)) as repo:
            before=(repo.all('predictions'),repo.all('jobs'),repo.db.execute('SELECT hash FROM audit_logs ORDER BY id').fetchall())
        self.assertEqual(self.post()[0],303)
        with closing(Repository(self.database,read_only=True)) as repo:
            after=(repo.all('predictions'),repo.all('jobs'),repo.db.execute('SELECT hash FROM audit_logs ORDER BY id').fetchall())
        self.assertEqual(after,before)
        self.assertEqual(self.panel.last_run[0]['status'],'ALREADY_PROCESSED')
        self.assertIn('Прогноз сохранён',self.request()[2])

    def test_other_paths_methods_and_get_run_never_process_the_queue(self):
        self.job('01-capture','CAPTURE',{'sports':self.case['sports']})
        for method,path,code in [('GET','/run',404),('GET','/../ledger.sqlite',404),('GET','/?token=x',404),('OPTIONS','/',405)]:
            self.assertEqual(self.request(method,path)[0],code)
        self.assertFalse(self.database.exists())


class PanelCliTests(unittest.TestCase):
    def invoke(self,*args):
        with redirect_stdout(io.StringIO()),redirect_stderr(io.StringIO()):return main(list(args))

    def test_web_dispatches_before_database_creation_and_keeps_existing_core_command(self):
        with tempfile.TemporaryDirectory() as t:
            db=Path(t)/'missing'/'ledger.sqlite'
            with patch('sefirot.offline_panel.serve',return_value=0) as serve:
                self.assertEqual(self.invoke('--db',str(db),'work',str(Path(t)/'inbox'),'--web','--port','0'),0)
                self.assertEqual(serve.call_args.args[0],str(db));self.assertEqual(serve.call_args.args[3],0)
            self.assertFalse(db.parent.exists())

    def test_web_rejects_watch_text_and_port_without_web_before_io(self):
        with tempfile.TemporaryDirectory() as t:
            db=Path(t)/'missing'/'ledger.sqlite'
            for flags in (['--web','--watch'],['--web','--text'],['--port','8765'],['--web','--port','-1']):
                self.assertEqual(self.invoke('--db',str(db),'work',t,*flags),2)
            self.assertFalse(db.parent.exists())

    def test_invalid_ports_never_bind_a_socket(self):
        for port in (-1,65536,True,'8765'):
            with self.assertRaises(ValueError):make_server(Panel(':memory:','inbox'),port)
