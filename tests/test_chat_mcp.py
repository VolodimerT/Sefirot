"""Protocol sanity checks for the research-only SEFIROT MCP adapter."""
import importlib.util
from pathlib import Path
import sys
import unittest

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


if __name__ == "__main__":
    unittest.main()
