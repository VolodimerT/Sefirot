"""Owned queue/HTTP recovery checks; no credentials or provider calls."""
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import os
from pathlib import Path
import runpy
import sys
from threading import Event, Thread
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'src'), str(ROOT/'scripts')]
import chat_queue as queue
import chat_mcp as mcp
import chat_sports_probe as probe

MODE = {'SEFIROT_BRIDGE_READ_ONLY': '1', 'SEFIROT_CHAT_JOB_WORKER_MODE': 'sports_probe'}
UID = 'c38eb7dd-822f-4f94-8fba-cc6b0ec44009'
JOB = {'job': {'id': UID, 'kind': 'sports_probe', 'request': {
    'queries': [{'endpoint': 'status', 'params': {}}]}, 'attempt': 1}}
ACK = {'completed': True, 'id': UID, 'attempts': 1}


class ProbeWorkerRecoveryTests(unittest.TestCase):
    def setUp(self):
        # The circuit stop is process-local by design; isolate synthetic jobs.
        queue._provider_stop = None
        self.addCleanup(setattr, queue, '_provider_stop', None)

    def test_read_only_core_can_run_explicit_sports_only_worker(self):
        result = {'queries': [{'endpoint': 'status', 'status': 'ERROR',
                              'reason': 'SHARED_BUDGET_STALE_BUDGET'}]}
        with patch.dict(os.environ, MODE), patch.object(queue, 'request', side_effect=[JOB, ACK]) as store, \
                patch.object(probe, 'collect', return_value=result) as collect, \
                patch.object(queue, 'execute') as core:
            self.assertTrue(queue.process_one())
        collect.assert_called_once_with(JOB['job']['request'])
        core.assert_not_called()
        self.assertEqual(store.call_args.args[0]['action'], 'probe_complete')
        self.assertEqual(store.call_args.args[0]['response'], result)
        self.assertEqual(store.call_args.args[0]['attempt'], 1)
        self.assertTrue(queue.worker_status()['provider_paused'])

    def test_sports_only_mode_never_dispatches_core_mutations(self):
        for kind in ('capture', 'decide', 'result', 'stake_snapshot', 'demo', 'situation'):
            job = {'job': {**JOB['job'], 'kind': kind}}
            with self.subTest(kind=kind), patch.dict(os.environ, MODE), \
                    patch.object(queue, 'request', side_effect=[job, ACK]) as store, \
                    patch.object(queue, 'execute') as core, patch.object(queue, 'run_demo') as demo, \
                    patch.object(probe, 'collect') as collect:
                self.assertTrue(queue.process_one())
                self.assertFalse(store.call_args.args[0]['success'])
                self.assertEqual(store.call_args.args[0]['error'], 'INPUT_VALIDATION_OR_PREMATCH_GATE')
                core.assert_not_called(); demo.assert_not_called(); collect.assert_not_called()
                self.assertFalse(queue.worker_status()['provider_paused'])

    def test_expired_budget_is_reported_without_direct_provider_fallback(self):
        from sefirot.football_gateway import SportsBudgetGateError
        with patch.dict(os.environ, MODE), patch.object(queue, 'request', side_effect=[JOB, ACK]) as store, \
                patch.object(probe, 'get_sports', side_effect=SportsBudgetGateError('STALE_BUDGET')) as gateway:
            self.assertTrue(queue.process_one())
        gateway.assert_called_once_with('status', {}, require_shared_budget=True)
        result = store.call_args.args[0]['response']
        self.assertEqual(result['queries'][0]['reason'], 'SHARED_BUDGET_STALE_BUDGET')
        self.assertFalse(result['monetary_permission'])
        self.assertTrue(queue.worker_status()['provider_paused'])

    def test_reclaimed_probe_does_not_repeat_provider_in_sports_only_mode(self):
        for attempt in (2, 3):
            with self.subTest(attempt=attempt), patch.dict(os.environ, MODE), \
                    patch.object(queue, 'request', side_effect=[{'job': {**JOB['job'], 'attempt': attempt}},
                        {**ACK, 'attempts': attempt}]) as store, patch.object(probe, 'collect') as collect:
                self.assertTrue(queue.process_one())
                collect.assert_not_called()
                self.assertEqual(store.call_args.args[0]['error'], 'PROVIDER_FETCH_RETRY_REQUIRES_REVIEW')

    def test_unknown_mode_fails_before_claim_or_thread(self):
        for value in ('', 'true', 'all', 'SPORTS_PROBE', ' sports_probe'):
            with self.subTest(value=value), patch.dict(os.environ, {**MODE, 'SEFIROT_CHAT_JOB_WORKER_MODE': value}), \
                    patch.object(queue, 'request') as store, patch.object(queue, 'Thread') as thread:
                with self.assertRaisesRegex(RuntimeError, 'INVALID_CHAT_JOB_WORKER_MODE'):
                    queue.process_one()
                with self.assertRaisesRegex(RuntimeError, 'INVALID_CHAT_JOB_WORKER_MODE'):
                    queue.start()
                store.assert_not_called(); thread.assert_not_called()

    def test_concurrent_process_one_does_not_claim_twice(self):
        entered, release = Event(), Event()
        errors = []
        def claim(_):
            entered.set()
            if not release.wait(5): raise RuntimeError('SYNTHETIC_WAIT_TIMEOUT')
            return {'job': None}
        def first():
            try: queue.process_one()
            except BaseException as exc: errors.append(exc)
        with patch.dict(os.environ, MODE), patch.object(queue, 'request', side_effect=claim) as store:
            thread = Thread(target=first); thread.start()
            try:
                self.assertTrue(entered.wait(3))
                self.assertFalse(queue.process_one())
                self.assertEqual(store.call_count, 1)
            finally: release.set(); thread.join(5)
        self.assertFalse(errors)

    def test_repeated_start_has_one_worker_and_stop_is_interruptible(self):
        with patch.dict(os.environ, MODE), patch.object(queue, 'process_one', return_value=False) as process:
            try:
                self.assertTrue(queue.start())
                first = queue.worker_status()
                self.assertTrue(queue.start())
                self.assertTrue(first['running'])
            finally: queue.stop(timeout=3)
            self.assertFalse(queue.worker_status()['running'])
            self.assertLessEqual(process.call_count, 1)

    def test_authenticated_status_is_local_and_never_fetches_provider(self):
        handler = mcp.MCPHandler.__new__(mcp.MCPHandler)
        handler.path = '/status'
        handler.authorized = Mock(return_value=True)
        handler.respond = Mock()
        with patch.dict(os.environ, MODE), patch.object(queue, 'request') as store, \
                patch.object(probe, 'get_sports') as gateway:
            handler.do_GET()
        store.assert_not_called(); gateway.assert_not_called()
        status, payload = handler.respond.call_args.args
        self.assertEqual(status, 200)
        self.assertEqual(payload['data']['mode'], 'sports_probe')
        self.assertFalse(payload['data']['monetary_permission'])
        self.assertNotIn('token', str(payload).lower())

    def test_status_requires_auth(self):
        handler = mcp.MCPHandler.__new__(mcp.MCPHandler)
        handler.path = '/status'; handler.authorized = Mock(return_value=False); handler.respond = Mock()
        with patch.object(queue, 'worker_status') as status:
            handler.do_GET()
        status.assert_not_called(); handler.respond.assert_not_called()

    def test_actual_http_status_auth_and_health_never_spend_quota(self):
        token = 'synthetic-test-only-bridge-credential-000000000'
        with patch.dict(os.environ, {**MODE, 'SEFIROT_BRIDGE_TOKEN': token,
                'RENDER_GIT_COMMIT': 'a'*40}), patch.object(queue, 'request') as store, \
                patch.object(probe, 'get_sports') as provider:
            server = ThreadingHTTPServer(('127.0.0.1', 0), mcp.MCPHandler)
            thread = Thread(target=server.serve_forever, daemon=True); thread.start()
            def get(path, headers=None):
                conn = HTTPConnection('127.0.0.1', server.server_port, timeout=3)
                try:
                    conn.request('GET', path, headers=headers or {})
                    response = conn.getresponse()
                    import json
                    return response.status, json.loads(response.read())
                finally: conn.close()
            try:
                self.assertEqual(get('/status')[0], 401)
                status, body = get('/status', {'Authorization': 'Bearer '+token})
                self.assertEqual(status, 200)
                self.assertEqual(body['data']['provider_quota'], 'NOT_VERIFIED')
                with patch.object(queue, 'worker_status', return_value={'running': True}):
                    status, body = get('/health')
                    self.assertEqual(status, 200)
                    self.assertEqual(body['commit'], 'a'*40)
                    self.assertTrue(body['core_read_only'])
            finally: server.shutdown(); thread.join(3); server.server_close()
            store.assert_not_called(); provider.assert_not_called()

    def test_bad_port_never_starts_worker_or_accesses_credentials(self):
        for port in ('0', '-1', '65536', 'abc'):
            with self.subTest(port=port), patch.dict(os.environ, {**MODE, 'PORT': port}), \
                    patch.object(queue, 'start') as start, patch.object(mcp, 'configured_token') as auth:
                with self.assertRaises(ValueError):mcp.main()
                start.assert_not_called(); auth.assert_not_called()

    def test_startup_sports_worker_preserves_read_only_store(self):
        status = {'ledger_integrity': True, 'persistent_storage': True, 'store_revision': 59}
        smoke = {'synthetic': True, 'replay_matches': True, 'ledger_integrity': True, 'money_authorized': False}
        with patch.dict(os.environ, {**MODE, 'SEFIROT_STORE_URL': 'synthetic-store', 'PORT': '10000'}), \
                patch.object(mcp, 'configured_token'), patch.object(mcp, 'run_demo', return_value=smoke), \
                patch.object(mcp, 'execute', return_value=status), patch.object(mcp, 'ThreadingHTTPServer'), \
                patch.object(queue, 'start') as start, patch.object(queue, 'stop'), \
                patch('chat_store.checkpoint') as save, patch('signal.signal'):
            mcp.main()
        start.assert_called_once(); save.assert_not_called()

    def test_existing_render_launcher_dispatches_before_importing_scanner(self):
        with patch.dict(os.environ, {'SEFIROT_BRIDGE_MODE': 'mcp'}), patch.object(mcp, 'main') as main, \
                self.assertRaises(SystemExit) as result:
            runpy.run_path(str(ROOT/'scripts/strict_double_20261006_v2.py'), run_name='__main__')
        self.assertEqual(result.exception.code, 0)
        main.assert_called_once()


if __name__ == '__main__': unittest.main()

