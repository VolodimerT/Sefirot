"""Authenticated HTTP transport for the canonical SEFIROT core.

Research-only. No wager placement and no certified model edge.
Render Free uses ephemeral storage; restart can lose local SQLite history.
"""
from __future__ import annotations

import hmac
import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock
from urllib.parse import urlsplit

from sefirot.contracts import Policy, VERSION
from sefirot.engine import code_hash, model_code_hash
from sefirot.fixtures import example
from sefirot.markets import DEFAULT_POOL
from sefirot.repository import Repository
from sefirot.service import Service

MAX_REQUEST_BYTES = 512 * 1024
GATE = Lock()


def configured_token() -> str:
    token = os.environ.get("SEFIROT_BRIDGE_TOKEN", "")
    if len(token) < 32 or len(token) > 256 or any(ord(c) < 33 or ord(c) > 126 for c in token):
        raise RuntimeError("SEFIROT_BRIDGE_TOKEN must be a 32-256 character high-entropy secret")
    return token


def ledger_path() -> Path:
    return Path(os.environ.get("SEFIROT_BRIDGE_DB", "/tmp/sefirot-chat.sqlite"))


def build_info() -> dict:
    return {"version": VERSION, "code_hash": code_hash(), "model_hash": model_code_hash(),
            "runtime": "SEFIROT_CANONICAL_CORE", "mode": "RESEARCH_ONLY",
            "money_authorized": False, "automatic_execution": False,
            "persistent_storage": False}


def run_demo() -> dict:
    """Real engine, synthetic evidence and controlled demonstration clock."""
    start = datetime.now(timezone.utc).replace(microsecond=0)
    case = example(start, "synthetic-chat-gateway")
    current = [start]
    with tempfile.TemporaryDirectory() as directory:
        repo = Repository(str(Path(directory) / "trial.sqlite"))
        try:
            engine = Service(repo, Policy(), clock=lambda: current[0])
            prediction = engine.capture(case["sports"], case["markets"])
            current[0] = start + timedelta(minutes=2)
            decision = engine.decide(prediction["id"], case["quotes"], case["recheck"],
                                     {"bankroll": 1000.0, "peak": 1000.0}, case["decision_at"])
            return {**build_info(), "synthetic": True, "prediction_id": prediction["id"],
                    "decision_id": decision["id"], "decision": decision["decision"],
                    "verdict": decision["verdict"], "class": decision["class"],
                    "limiting_factors": decision["limiting_factors"],
                    "replay_matches": engine.replay(decision["id"])["matches"],
                    "ledger_integrity": repo.verify()}
        finally:
            repo.close()


def execute(kind: str, data: dict) -> dict:
    """Invoke canonical Service exclusively: no invented probability formulas."""
    with GATE:
        location = ledger_path()
        location.parent.mkdir(parents=True, exist_ok=True)
        repo = Repository(str(location))
        try:
            if not repo.verify():
                raise ValueError("JOURNAL_INTEGRITY: closed")
            service = Service(repo, Policy())
            if kind == "capture":
                if set(data) - {"sports", "markets"} or "sports" not in data:
                    raise ValueError("capture requires sports and optionally markets")
                result = service.capture(data["sports"], data.get("markets", DEFAULT_POOL))
                return {**build_info(), "stage": "FORECAST_SEALED", "prediction_id": result["id"],
                        "sealed_at": result["sealed_at"], "fixture": result["sports"]["match"],
                        "synthetic": result["synthetic"], "candidates": result["candidates"],
                        "model_id": result["model_id"], "captured_prematch": result["captured_prematch"]}
            if kind == "decide":
                if set(data) != {"prediction_id", "quotes", "recheck", "portfolio"}:
                    raise ValueError("decide requires prediction_id, quotes, recheck and portfolio")
                result = service.decide(data["prediction_id"], data["quotes"],
                                        data["recheck"], data["portfolio"], service.now())
                return {**build_info(), "stage": "DECISION_RECORDED", "decision_id": result["id"],
                        "prediction_id": data["prediction_id"], "decision": result["decision"],
                        "verdict": result["verdict"], "class": result["class"],
                        "limiting_factors": result["limiting_factors"],
                        "candidates": result["candidates"],
                        "decision_card": result.get("decision_card"), "risk": result.get("risk")}
            if kind == "result":
                result = service.result(data)
                return {**build_info(), "stage": "RESULT_RECORDED", "result": result}
            if kind == "decision":
                result = repo.get("decisions", data["id"])
                return {**build_info(), "stage": "DECISION_READ", "decision": result}
            if kind == "report":
                return {**build_info(), "stage": "AUDIT_REPORT", "report": service.report()}
            if kind == "status":
                return {**build_info(), "stage": "READY", "ledger_integrity": True,
                        "stored_predictions": len(repo.all("predictions")),
                        "stored_decisions": len(repo.all("decisions"))}
            raise ValueError("unsupported operation")
        finally:
            repo.close()


class Handler(BaseHTTPRequestHandler):
    server_version = "SEFIROTBridge/0.1"

    def log_message(self, format, *args):
        # Do not log URLs, request bodies, tokens or private sporting data.
        pass

    def respond(self, status: int, payload: dict) -> None:
        contents = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Length", str(len(contents)))
        self.end_headers()
        self.wfile.write(contents)

    def authorized(self) -> bool:
        expected = configured_token()
        provided = self.headers.get("Authorization", "")
        if not provided.startswith("Bearer ") or not hmac.compare_digest(provided[7:], expected):
            self.respond(401, {"ok": False, "error": "UNAUTHORIZED"})
            return False
        return True

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == "/health":
            self.respond(200, {"ok": True, "service": "sefirot-chat-bridge", "mode": "RESEARCH_ONLY"})
            return
        if not self.authorized():
            return
        try:
            if path == "/v1/status":
                data = execute("status", {})
            elif path == "/v1/report":
                data = execute("report", {})
            elif path == "/v1/demo":
                data = run_demo()
            elif path.startswith("/v1/decision/"):
                identifier = path[len("/v1/decision/"):]
                if not (len(identifier) == 64 and all(c in "0123456789abcdef" for c in identifier)):
                    raise ValueError("invalid decision identifier")
                data = execute("decision", {"id": identifier})
            else:
                self.respond(404, {"ok": False, "error": "NOT_FOUND"})
                return
            self.respond(200, {"ok": True, "data": data})
        except (ValueError, KeyError, TypeError) as exc:
            self.respond(422, {"ok": False, "error": "VALIDATION_FAILED", "detail": str(exc)[:200]})
        except Exception:
            self.respond(500, {"ok": False, "error": "INTERNAL_ERROR"})

    def do_POST(self):
        path = urlsplit(self.path).path
        if not self.authorized():
            return
        operations = {"/v1/capture": "capture", "/v1/decide": "decide", "/v1/result": "result"}
        if path not in operations:
            self.respond(404, {"ok": False, "error": "NOT_FOUND"})
            return
        try:
            content_type = self.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
            if content_type != "application/json":
                self.respond(415, {"ok": False, "error": "JSON_REQUIRED"})
                return
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_REQUEST_BYTES:
                self.respond(413, {"ok": False, "error": "INVALID_REQUEST_SIZE"})
                return
            payload = json.loads(self.rfile.read(length))
            if not isinstance(payload, dict):
                raise ValueError("request must be a JSON object")
            self.respond(200, {"ok": True, "data": execute(operations[path], payload)})
        except (ValueError, KeyError, TypeError) as exc:
            self.respond(422, {"ok": False, "error": "VALIDATION_FAILED", "detail": str(exc)[:200]})
        except Exception:
            self.respond(500, {"ok": False, "error": "INTERNAL_ERROR"})


def main():
    configured_token()  # Fail closed unless operator provisioned token.
    port = int(os.environ.get("PORT", "10000"))
    if not 0 < port < 65536:
        raise ValueError("invalid PORT")
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()


if __name__ == "__main__":
    main()
