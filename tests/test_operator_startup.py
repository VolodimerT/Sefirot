"""Actual owned CLI/loopback startup; no provider credentials or real ledger."""
import json
import os
from pathlib import Path
import queue
import re
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "operator_cockpit.py"
TOKEN = "SYNTHETIC_LOCAL_OPERATOR_STARTUP_ONLY_" + "x" * 32


def environment(token=None):
    env = dict(os.environ)
    env.pop("SEFIROT_BRIDGE_TOKEN", None)
    env["PYTHONIOENCODING"] = "utf-8"
    if token is not None:
        env["SEFIROT_BRIDGE_TOKEN"] = token
    return env


class OperatorStartupTests(unittest.TestCase):
    def run_cli(self, *args, token=None):
        return subprocess.run([sys.executable, str(SCRIPT), *args], cwd=ROOT,
                              env=environment(token), capture_output=True,
                              encoding="utf-8", timeout=15)

    def test_missing_or_invalid_access_code_has_safe_exit_and_no_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "absent.sqlite"
            for token in (None, "short", "x" * 32 + "\n", "я" * 32):
                with self.subTest(token_kind=type(token).__name__):
                    result = self.run_cli("--db", str(missing), "--port", "0", token=token)
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(result.stdout, "")
                    self.assertIn("SEFIROT_BRIDGE_TOKEN", result.stderr)
                    self.assertNotIn("Traceback", result.stderr)
                    if token:
                        self.assertNotIn(token, result.stderr)
                    self.assertFalse(missing.exists())

    def test_port_outside_tcp_range_is_rejected_without_traceback(self):
        for port in ("-1", "65536"):
            with self.subTest(port=port):
                result = self.run_cli("--port", port, token=TOKEN)
                self.assertEqual(result.returncode, 2)
                self.assertIn("0..65535", result.stderr)
                self.assertNotIn("Traceback", result.stderr)
                self.assertNotIn(TOKEN, result.stdout + result.stderr)

    def test_busy_port_has_safe_failure_without_exposing_access_code(self):
        with socket.socket() as listener:
            if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
                listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind(("127.0.0.1", 0)); listener.listen()
            result = self.run_cli("--port", str(listener.getsockname()[1]), token=TOKEN)
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stdout, "")
        self.assertIn("SEFIROT", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertNotIn(TOKEN, result.stderr)

    def test_success_announces_actual_loopback_port_and_keeps_read_only_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "absent.sqlite"
            process = subprocess.Popen([sys.executable, str(SCRIPT), "--db", str(missing), "--port", "0"],
                cwd=ROOT, env=environment(TOKEN), stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, encoding="utf-8")
            lines = queue.Queue()
            reader = threading.Thread(target=lambda: lines.put(process.stdout.readline()), daemon=True)
            reader.start()
            try:
                try:
                    line = lines.get(timeout=8)
                except queue.Empty:
                    self.fail("CLI did not announce its loopback address")
                match = re.search(r"http://127\.0\.0\.1:(\d+)", line)
                self.assertIsNotNone(match, line)
                self.assertNotIn(TOKEN, line)
                base = match.group(0)
                self.assertGreater(int(match.group(1)), 0)
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                with opener.open(base, timeout=5) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIn("ТОЛЬКО ПРОСМОТР", response.read().decode("utf-8"))
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    opener.open(base + "/api/operator", timeout=5)
                self.assertEqual(denied.exception.code, 401)
                denied.exception.close()
                request = urllib.request.Request(base + "/api/operator",
                    headers={"Authorization": "Bearer " + TOKEN})
                with opener.open(request, timeout=5) as response:
                    report = json.load(response)["data"]
                self.assertEqual(report["ledger_status"], "ABSENT")
                self.assertTrue(report["read_only"])
                self.assertFalse(report["monetary_permission"])
                self.assertFalse(report["execution_enabled"])
                self.assertEqual(report["network_requests"], 0)
                request = urllib.request.Request(base + "/LIVE", data=b"{}",
                    headers={"Authorization": "Bearer " + TOKEN}, method="POST")
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    opener.open(request, timeout=5)
                self.assertEqual(denied.exception.code, 403)
                denied.exception.close()
                self.assertFalse(missing.exists())
            finally:
                process.terminate()
                process.communicate(timeout=10)
                reader.join(timeout=5)
                self.assertFalse(reader.is_alive())


if __name__ == "__main__":
    unittest.main()
