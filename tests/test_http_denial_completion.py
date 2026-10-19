"""Denied requests must finish bounded body transport without backend work."""
import http.client
import socket
import sys
from pathlib import Path
from threading import Thread
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'scripts'), str(ROOT / 'src')]
from chat_gateway import Handler, MAX_REQUEST_BYTES
from scripts.operator_cockpit import make_server


class HTTPDenialCompletionTests(unittest.TestCase):
    def delayed_body(self, method, path, authorization, expected):
        token = 'synthetic-denial-token-' + 'x' * 48
        server = make_server(database=None, token=token)
        worker = Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with socket.create_connection(('127.0.0.1', server.server_port), timeout=5) as conn:
                auth = ('Authorization: Bearer ' + token + '\r\n') if authorization else ''
                headers = (method + ' ' + path + ' HTTP/1.1\r\nHost: 127.0.0.1:'
                           + str(server.server_port) + '\r\n' + auth
                           + 'Content-Length: 2\r\nContent-Type: application/json\r\n\r\n')
                conn.sendall(headers.encode())
                response = http.client.HTTPResponse(conn)
                response.begin()
                self.assertEqual(response.status, expected)
                response.read()
                # Headers and body are deliberately separate writes. A denial
                # must already be visible while the transport awaits the body.
                conn.settimeout(.01)
                with self.assertRaises(socket.timeout):
                    conn.recv(1)
                conn.settimeout(5)
                conn.sendall(b'{}')
                self.assertEqual(conn.recv(1), b'', 'expected clean EOF, not TCP reset')
        finally:
            server.shutdown()
            server.server_close()
            worker.join(5)

    def test_forbidden_put_delivers_403_before_late_body_and_finishes_cleanly(self):
        self.delayed_body('PUT', '/session', True, 403)

    def test_unauthorized_post_delivers_401_before_late_body_and_finishes_cleanly(self):
        self.delayed_body('POST', '/v1/capture', False, 401)

    def test_finish_does_not_read_unbounded_ambiguous_or_consumed_body(self):
        for headers, consumed in (({'Content-Length': str(MAX_REQUEST_BYTES + 1)}, 0),
                                  ({'Content-Length': 'invalid'}, 0),
                                  ({'Content-Length': '2', 'Transfer-Encoding': 'chunked'}, 0),
                                  ({'Content-Length': '2'}, 2)):
            with self.subTest(headers=headers, consumed=consumed):
                handler = Handler.__new__(Handler)
                handler.headers = headers
                handler.rfile = Mock()
                handler.rfile.body_bytes_read = consumed
                handler.wfile = Mock(closed=False)
                handler.connection = Mock()
                handler.finish()
                handler.rfile.read.assert_not_called()
                handler.connection.settimeout.assert_not_called()
                handler.rfile.close.assert_called_once()
                handler.wfile.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
