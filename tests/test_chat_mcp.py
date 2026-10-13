"""Protocol sanity checks for the research-only SEFIROT MCP adapter."""
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT / "scripts")]
spec = importlib.util.spec_from_file_location("chat_mcp", ROOT / "scripts" / "chat_mcp.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class MCPTests(unittest.TestCase):
    def request(self, method, params=None):
        return module.process_rpc({"jsonrpc": "2.0", "id": 13, "method": method, "params": params or {}})

    def test_initialize_and_discovery(self):
        handshake = self.request("initialize")["result"]
        self.assertEqual(handshake["protocolVersion"], "2025-03-26")
        tools = self.request("tools/list")["result"]["tools"]
        names = {tool["name"] for tool in tools}
        self.assertEqual(names, {"sefirot_status", "sefirot_demo", "sefirot_capture",
                                 "sefirot_decide", "sefirot_result", "sefirot_report"})
        self.assertNotIn("sefirot_execute", names)

    def test_protocol_errors_and_notification(self):
        self.assertEqual(self.request("garbage")["error"]["code"], -32601)
        self.assertIsNone(self.request("notifications/initialized"))
        self.assertEqual(module.process_rpc({"jsonrpc": "1.0", "id": 1,
                                             "method": "tools/list"})["error"]["code"], -32600)

    def test_demo_is_research_only(self):
        result = self.request("tools/call", {"name": "sefirot_demo", "arguments": {}})["result"]
        self.assertFalse(result["isError"])
        self.assertIn('"money_authorized": false', result["content"][0]["text"])

    def test_unknown_tool_is_error(self):
        result = self.request("tools/call", {"name": "place_bet", "arguments": {}})["result"]
        self.assertTrue(result["isError"])

    def test_nonobject_params_and_arguments_refuse_before_dispatch(self):
        for value in (None, False, True, 0, 2, '', 'invalid', [], [1]):
            for field in ('params', 'arguments'):
                with self.subTest(field=field, kind=type(value).__name__), \
                     patch.object(module, 'execute') as backend:
                    params = value if field == 'params' else {'name': 'sefirot_status', 'arguments': value}
                    response = module.process_rpc({'jsonrpc': '2.0', 'id': 13,
                                                   'method': 'tools/call', 'params': params})
                    self.assertEqual(response['id'], 13)
                    self.assertEqual(response['error']['code'], -32602)
                    backend.assert_not_called()

    def test_missing_arguments_remain_supported(self):
        with patch.object(module, 'execute', return_value={'ok': True}) as backend:
            response = self.request('tools/call', {'name': 'sefirot_status'})
        backend.assert_called_once_with('status', {})
        self.assertFalse(response['result']['isError'])

    def test_bad_tool_name_refuses_before_dispatch(self):
        for name in (None, [], 1, True):
            with self.subTest(name=name), patch.object(module, 'execute') as backend:
                response = self.request('tools/call', {'name': name, 'arguments': {}})
                self.assertEqual(response['error']['code'], -32602)
                backend.assert_not_called()

    def test_malformed_http_request_gets_protocol_error(self):
        handler = module.MCPHandler.__new__(module.MCPHandler)
        handler.path = '/mcp'
        body = json.dumps({'jsonrpc': '2.0', 'id': 13, 'method': 'tools/call', 'params': [1]}).encode()
        handler.headers = {'Content-Type': 'application/json', 'Content-Length': str(len(body))}
        handler.rfile = io.BytesIO(body)
        handler.authorized = Mock(return_value=True)
        handler.respond = Mock()
        with patch.object(module, 'execute') as backend:
            handler.do_POST()
        backend.assert_not_called()
        status, payload = handler.respond.call_args.args
        self.assertEqual(status, 200)
        self.assertEqual(payload['id'], 13)
        self.assertEqual(payload['error']['code'], -32602)

    def test_nonobject_rpc_root_is_invalid_request(self):
        for value in (None, [], True, 1):
            with self.subTest(value=value):
                self.assertEqual(module.process_rpc(value)['error']['code'], -32600)


if __name__ == "__main__":
    unittest.main()
