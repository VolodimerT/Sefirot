"""Read-only rollout counterexamples; owned SQLite/HTTP and synthetic auth only."""
from datetime import datetime, timezone
from hashlib import sha256
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import importlib
import json
from pathlib import Path
import sys
import tempfile
from threading import Thread
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'scripts')]
gateway = importlib.import_module('chat_gateway')
mcp = importlib.import_module('chat_mcp')
queue = importlib.import_module('chat_queue')
from sefirot.fixtures import example
from sefirot.repository import Repository

MODE = {'SEFIROT_BRIDGE_READ_ONLY': '1', 'SEFIROT_STORE_URL': ''}
SMOKE = {'synthetic': True, 'replay_matches': True,
         'ledger_integrity': True, 'money_authorized': False}


class ReadOnlyRolloutTests(unittest.TestCase):
    def test_original_status_and_report_leave_complete_sqlite_bytes_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'original.sqlite'
            Repository(db).close()
            before = db.read_bytes()
            with patch.dict('os.environ', {**MODE, 'SEFIROT_BRIDGE_DB': str(db)}):
                status = gateway.execute('status', {})
                report = gateway.execute('report', {})
            self.assertTrue(status['ledger_integrity'])
            self.assertEqual(status['stored_predictions'], 0)
            self.assertEqual(report['stage'], 'AUDIT_REPORT')
            self.assertEqual(db.read_bytes(), before)

    def test_missing_ledger_refuses_without_creating_database_or_parent(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'not-created' / 'original.sqlite'
            with patch.dict('os.environ', {**MODE, 'SEFIROT_BRIDGE_DB': str(db)}):
                with self.assertRaisesRegex(ValueError, 'READ_ONLY_LEDGER_REQUIRED'):
                    gateway.execute('status', {})
            self.assertFalse(db.parent.exists())

    def test_mutations_and_provider_operations_refuse_before_store_or_backend(self):
        with patch.dict('os.environ', MODE), \
                patch.object(gateway.chat_store, 'configured', return_value=True), \
                patch.object(gateway.chat_store, 'restore', return_value=1) as restore, \
                patch.object(gateway.chat_store, 'checkpoint', return_value=2) as checkpoint, \
                patch.object(gateway, '_execute_at', return_value={'ok': True}) as backend, \
                patch.object(gateway, 'execute_situation', return_value={'ok': True}) as situation:
            for kind in ('capture', 'decide', 'result', 'sports_probe', 'situation', 'demo', 'unknown'):
                with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'BRIDGE_READ_ONLY'):
                    gateway.execute(kind, {})
            restore.assert_not_called()
            checkpoint.assert_not_called()
            backend.assert_not_called()
            situation.assert_not_called()

    def test_mcp_discovery_and_direct_calls_do_not_offer_or_execute_mutations(self):
        with patch.dict('os.environ', MODE), \
                patch.object(mcp, 'execute', return_value={'ok': True}) as backend, \
                patch.object(mcp, 'run_demo', return_value=SMOKE) as demo:
            rpc = lambda method, params=None: mcp.process_rpc({'jsonrpc': '2.0', 'id': 7,
                'method': method, 'params': params or {}})
            names = {t['name'] for t in rpc('tools/list')['result']['tools']}
            self.assertEqual(names, {'sefirot_status', 'sefirot_report'})
            for name in ('sefirot_capture', 'sefirot_decide', 'sefirot_result', 'sefirot_demo', 'sefirot_situation'):
                with self.subTest(name=name):
                    result = rpc('tools/call', {'name': name, 'arguments': {'result': {}}})['result']
                    self.assertTrue(result['isError'])
                    self.assertIn('BRIDGE_READ_ONLY', result['content'][0]['text'])
            backend.assert_not_called()
            demo.assert_not_called()
            self.assertFalse(rpc('tools/call', {'name': 'sefirot_status'})['result']['isError'])
            backend.assert_called_once_with('status', {})

    def test_internal_probe_entry_cannot_bypass_read_only_operation_gate(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'not-created.sqlite'
            with patch.dict('os.environ', MODE), patch.object(gateway, 'Repository') as repository:
                for kind in ('sports_probe', 'capture', 'decide', 'result'):
                    with self.subTest(kind=kind), self.assertRaisesRegex(ValueError, 'BRIDGE_READ_ONLY'):
                        gateway._execute_at(kind, {}, path)
                repository.assert_not_called()
            self.assertFalse(path.exists())

    def test_queue_neither_claims_jobs_nor_starts_background_thread(self):
        with patch.dict('os.environ', MODE), \
                patch.object(queue, 'request', return_value={'job': None}) as store, \
                patch.object(queue, 'Thread') as worker:
            self.assertFalse(queue.process_one())
            self.assertFalse(queue.start())
            worker.assert_not_called()
            store.assert_not_called()
            queue.run()
            store.assert_not_called()
            worker.assert_not_called()

    def test_warm_store_startup_does_not_checkpoint_or_start_queue(self):
        status = {'ledger_integrity': True, 'persistent_storage': True, 'store_revision': 59}
        with patch.dict('os.environ', {**MODE, 'SEFIROT_STORE_URL': 'synthetic-managed-store', 'PORT': '10000'}), \
                patch.object(mcp, 'configured_token'), patch.object(mcp, 'run_demo', return_value=SMOKE), \
                patch.object(mcp, 'execute', return_value=status), \
                patch.object(mcp, 'ThreadingHTTPServer') as server, \
                patch.object(queue, 'start') as worker, \
                patch.object(gateway.chat_store, 'checkpoint') as checkpoint:
            mcp.main()
            worker.assert_not_called()
            checkpoint.assert_not_called()
            server.return_value.serve_forever.assert_called_once()

    def test_empty_store_startup_refuses_before_first_checkpoint_and_bind(self):
        status = {'ledger_integrity': True, 'persistent_storage': False, 'store_revision': 0}
        with patch.dict('os.environ', {**MODE, 'SEFIROT_STORE_URL': 'synthetic-managed-store'}), \
                patch.object(mcp, 'configured_token'), patch.object(mcp, 'run_demo', return_value=SMOKE), \
                patch.object(mcp, 'execute', return_value=status), \
                patch.object(mcp, 'ThreadingHTTPServer') as server, \
                patch.object(queue, 'start') as worker, \
                patch.object(gateway.chat_store, 'checkpoint') as checkpoint:
            with self.assertRaisesRegex(RuntimeError, 'READ_ONLY_EXISTING_STORE_REQUIRED'):
                mcp.main()
            checkpoint.assert_not_called()
            worker.assert_not_called()
            server.assert_not_called()

    def test_invalid_mode_refuses_before_credentials_smoke_store_and_bind(self):
        for value in ('', 'true', 'yes', 'false', ' 1', '01'):
            with self.subTest(value=value), patch.dict('os.environ', {**MODE, 'SEFIROT_BRIDGE_READ_ONLY': value}), \
                    patch.object(mcp, 'configured_token') as auth, \
                    patch.object(mcp, 'run_demo', return_value=SMOKE) as demo, \
                    patch.object(mcp, 'execute') as backend, \
                    patch.object(mcp, 'ThreadingHTTPServer') as server:
                with self.assertRaisesRegex(RuntimeError, 'INVALID_BRIDGE_READ_ONLY_MODE'):
                    mcp.main()
                auth.assert_not_called()
                demo.assert_not_called()
                backend.assert_not_called()
                server.assert_not_called()

    def test_real_http_inherited_routes_cannot_bypass_read_only_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / 'original.sqlite'
            Repository(db).close()
            before = sha256(db.read_bytes()).hexdigest()
            token = 'synthetic-readonly-http-' + 'x' * 48
            env = {**MODE, 'SEFIROT_BRIDGE_TOKEN': token, 'SEFIROT_BRIDGE_DB': str(db)}
            with patch.dict('os.environ', env):
                server = ThreadingHTTPServer(('127.0.0.1', 0), mcp.MCPHandler)
                worker = Thread(target=server.serve_forever, daemon=True)
                worker.start()
                def request(method, path, payload=None, authenticated=True):
                    client = HTTPConnection('127.0.0.1', server.server_port, timeout=10)
                    try:
                        headers = {'Content-Type': 'application/json'}
                        if authenticated:
                            headers['Authorization'] = 'Bearer ' + token
                        body = json.dumps(payload).encode() if payload is not None else None
                        client.request(method, path, body, headers)
                        response = client.getresponse()
                        return response.status, json.loads(response.read())
                    finally:
                        client.close()
                try:
                    self.assertEqual(request('GET', '/v1/status', authenticated=False)[0], 401)
                    status, body = request('GET', '/v1/status')
                    self.assertEqual(status, 200)
                    self.assertTrue(body['data']['ledger_integrity'])
                    self.assertEqual(request('GET', '/v1/demo')[0], 403)
                    sports = example(datetime.now(timezone.utc), 'synthetic-readonly-http')['sports']
                    status, body = request('POST', '/v1/capture', {'sports': sports})
                    self.assertEqual(status, 422)
                    self.assertEqual(body['detail'], 'BRIDGE_READ_ONLY')
                    status, body = request('POST', '/mcp', {'jsonrpc': '2.0', 'id': 7,
                        'method': 'tools/call', 'params': {'name': 'sefirot_demo', 'arguments': {}}})
                    self.assertEqual(status, 200)
                    self.assertTrue(body['result']['isError'])
                finally:
                    server.shutdown()
                    server.server_close()
                    worker.join(5)
            self.assertEqual(sha256(db.read_bytes()).hexdigest(), before)
            repo = Repository(db, read_only=True)
            try:
                self.assertTrue(repo.verify())
                self.assertEqual(repo.all('predictions'), [])
            finally:
                repo.close()


if __name__ == '__main__':
    unittest.main()
