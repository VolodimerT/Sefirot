"""Streamable HTTP MCP adapter for the SEFIROT research bridge.

No independent model: every operation dispatches to chat_gateway.execute().
"""
import json
import os
from http.server import ThreadingHTTPServer
from urllib.parse import urlsplit

from chat_gateway import Handler, MAX_REQUEST_BYTES, configured_token, execute, run_demo

PROTOCOL = "2025-03-26"
TOOLS = [
    {"name": "sefirot_status",
     "description": "Check canonical SEFIROT model hashes, journal integrity and available research records.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
     "annotations": {"readOnlyHint": True}},
    {"name": "sefirot_demo",
     "description": "Run original canonical CORE end-to-end on clearly SYNTHETIC data, never a real betting signal.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
     "annotations": {"readOnlyHint": True}},
    {"name": "sefirot_capture",
     "description": "Seal an ORIGINAL sports-only prematch forecast BEFORE receiving odds. Requires source-backed complete sports JSON; no betting execution.",
     "inputSchema": {"type": "object", "properties": {
         "sports": {"type": "object", "description": "SEFIROT INPUT_CONTRACT original sports-only JSON"},
         "markets": {"type": "array", "items": {"type": "object"}, "description": "Optional frozen initial market pool"}},
         "required": ["sports"], "additionalProperties": False}},
    {"name": "sefirot_decide",
     "description": "Using an already sealed prediction, compare verified current bookmaker quotes and independent recheck through canonical EV, value, risk and death-test gates.",
     "inputSchema": {"type": "object", "properties": {
         "prediction_id": {"type": "string"},
         "quotes": {"type": "array", "items": {"type": "object"}},
         "recheck": {"type": "object"},
         "portfolio": {"type": "object", "properties": {
             "bankroll": {"type": "number"}, "peak": {"type": "number"}},
             "required": ["bankroll", "peak"]}},
         "required": ["prediction_id", "quotes", "recheck", "portfolio"], "additionalProperties": False}},
    {"name": "sefirot_result",
     "description": "Append original final result to the research ledger for a previously captured fixture. Never edits previous predictions.",
     "inputSchema": {"type": "object", "properties": {"result": {"type": "object"}},
                     "required": ["result"], "additionalProperties": False}},
    {"name": "sefirot_report",
     "description": "Read research ledger report including all PASS decisions and calibration; ephemeral ledger must not be called historical truth.",
     "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
     "annotations": {"readOnlyHint": True}}
]


def call_tool(name, arguments):
    if name == "sefirot_status": return execute("status", {})
    if name == "sefirot_demo": return run_demo()
    if name == "sefirot_capture": return execute("capture", arguments)
    if name == "sefirot_decide": return execute("decide", arguments)
    if name == "sefirot_result":
        if set(arguments) != {"result"}: raise ValueError("result object required")
        return execute("result", arguments["result"])
    if name == "sefirot_report": return execute("report", {})
    raise ValueError("unknown tool")


def process_rpc(request):
    if request.get("jsonrpc") != "2.0":
        return {"jsonrpc": "2.0", "id": request.get("id"),
                "error": {"code": -32600, "message": "Invalid JSON-RPC request"}}
    method = request.get("method")
    ident = request.get("id")
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        result = {"protocolVersion": PROTOCOL, "capabilities": {"tools": {"listChanged": False}},
                  "serverInfo": {"name": "sefirot-canonical-research", "version": "0.1.0"},
                  "instructions": "Research-only. Call capture before decide; no monetary permission, LIVE or execution. Empty history must PASS."}
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": TOOLS}
    elif method == "tools/call":
        params = request.get("params") or {}
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return {"jsonrpc": "2.0", "id": ident,
                    "error": {"code": -32602, "message": "Tool arguments must be object"}}
        try:
            outcome = call_tool(name, arguments)
            result = {"content": [{"type": "text", "text": json.dumps(outcome, ensure_ascii=False, allow_nan=False)}],
                      "isError": False}
        except (ValueError, KeyError, TypeError) as exc:
            result = {"content": [{"type": "text", "text": json.dumps({"error": "VALIDATION_FAILED",
                       "detail": str(exc)[:200]}, ensure_ascii=False)}], "isError": True}
        except Exception:
            result = {"content": [{"type": "text", "text": '{"error":"INTERNAL_ERROR"}'}], "isError": True}
    else:
        return {"jsonrpc": "2.0", "id": ident,
                "error": {"code": -32601, "message": "Method not found"}}
    return {"jsonrpc": "2.0", "id": ident, "result": result}


class MCPHandler(Handler):
    def do_POST(self):
        if urlsplit(self.path).path != "/mcp":
            return super().do_POST()
        if not self.authorized():
            return
        try:
            if self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower() != "application/json":
                self.respond(415, {"error": "JSON_REQUIRED"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= MAX_REQUEST_BYTES:
                self.respond(413, {"error": "INVALID_REQUEST_SIZE"})
                return
            request = json.loads(self.rfile.read(length))
            if not isinstance(request, dict):
                raise ValueError("MCP requires JSON-RPC object")
            response = process_rpc(request)
            if response is None:
                self.send_response(202)
                self.send_header("Content-Length", "0")
                self.end_headers()
            else:
                self.respond(200, response)
        except (ValueError, KeyError, TypeError):
            self.respond(400, {"jsonrpc": "2.0", "id": None,
                               "error": {"code": -32700, "message": "Parse error"}})


def main():
    configured_token()
    smoke = run_demo()
    if not (smoke.get("synthetic") is True and smoke.get("replay_matches") is True
            and smoke.get("ledger_integrity") is True and smoke.get("money_authorized") is False):
        raise RuntimeError("SEFIROT_CANONICAL_STARTUP_SMOKE_FAILED")
    print("SEFIROT_CORE_STARTUP_SMOKE_OK synthetic replay integrity research_only", flush=True)
    port = int(os.environ.get("PORT", "10000"))
    if not 0 < port < 65536: raise ValueError("invalid PORT")
    ThreadingHTTPServer(("0.0.0.0", port), MCPHandler).serve_forever()


if __name__ == "__main__":
    main()
