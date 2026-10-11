"""Private, crash-resistant daily report archive. Never modifies CORE or a wager ledger.

This is a *report finalization* tool, not a chat-event listener. Integrations
must invoke it after every final daily report and check its exit status.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

SCHEMA = "sefirot-daily-report-v1"
MAX_BYTES = 512_000
DEFAULT_STORE = Path.home() / ".sefirot" / "private-daily-reports"


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def check_report(report: object) -> dict:
    if not isinstance(report, dict) or set(report) != {
        "schema", "day", "timezone", "origin", "status", "source_refs", "report"
    }:
        raise ValueError("INVALID_DAILY_REPORT_KEYS")
    if report["schema"] != SCHEMA or report["timezone"] != "Europe/Kyiv":
        raise ValueError("INVALID_DAILY_REPORT_SCHEMA_OR_ZONE")
    day = report["day"]
    if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
        raise ValueError("INVALID_DAILY_REPORT_DAY")
    if report["origin"] not in ("CHAT_DAILY", "TICKET_AUDIT"):
        raise ValueError("INVALID_DAILY_REPORT_ORIGIN")
    if report["status"] != "REPORTED_UNVERIFIED":
        raise ValueError("REPORT_CANNOT_CLAIM_MODEL_OR_MONEY_CERTIFICATION")
    refs = report["source_refs"]
    if not isinstance(refs, list) or len(refs) > 100 or any(
        not isinstance(ref, str) or not 0 < len(ref) <= 300 for ref in refs
    ):
        raise ValueError("INVALID_SOURCE_REFS")
    body = report["report"]
    if report["origin"] == "CHAT_DAILY":
        if not isinstance(body, str) or not body.strip():
            raise ValueError("EMPTY_CHAT_REPORT")
    else:
        if (not isinstance(body, dict) or body.get("schema") != "ticket-audit-v1"
                or body.get("status") != "REPORTED_UNVERIFIED"
                or body.get("monetary_permission") is not False
                or [d.get("day") for d in body.get("days", [])] != [day]):
            raise ValueError("INVALID_TICKET_AUDIT_OR_DAY")
    payload = canonical(report)
    if len(payload) > MAX_BYTES:
        raise ValueError("REPORT_TOO_LARGE")
    return report


def _atomic_new(path: Path, payload: bytes) -> bool:
    """Write a complete immutable snapshot; caller holds the store lock."""
    if path.exists():
        if path.read_bytes() != payload:
            raise ValueError("EXISTING_ARCHIVE_HASH_COLLISION_OR_CORRUPTION")
        return False
    fd, temp_name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        if path.exists():
            if path.read_bytes() != payload:
                raise ValueError("ARCHIVE_RACE_OR_CORRUPTION")
            return False
        os.replace(temp_name, path)
        return True
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _atomic_pointer(path: Path, data: bytes) -> None:
    fd, temp_name = tempfile.mkstemp(prefix=".latest-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


@contextmanager
def _store_lock(store: Path):
    """Advisory OS lock, automatically released if the process crashes."""
    lock = store / ".save.lock"
    with open(lock, "a+b") as handle:
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise ValueError("ARCHIVE_BUSY_RETRY_AFTER_CHECK") from None
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def save(report: object, store: Path = DEFAULT_STORE) -> dict:
    report = check_report(report)
    store = Path(store)
    day = report["day"]
    payload = canonical(report)
    digest = hashlib.sha256(payload).hexdigest()
    destination = store / day / (digest + ".json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with _store_lock(store):
        added = _atomic_new(destination, payload)
        if added:
            pointer = {"schema": "sefirot-daily-latest-v1", "day": day,
                       "sha256": digest, "saved_at_utc": datetime.now(timezone.utc).isoformat()}
            _atomic_pointer(store / "latest.json", canonical(pointer))
        return {"saved": True, "new_version": added, "day": day,
                "sha256": digest, "path": str(destination),
                "versions_for_day": len(list(destination.parent.glob("*.json")))}


def verify(store: Path = DEFAULT_STORE) -> dict:
    store = Path(store)
    files = sorted(store.glob("????-??-??/*.json"))
    for path in files:
        payload = path.read_bytes()
        if hashlib.sha256(payload).hexdigest() != path.stem:
            raise ValueError("ARCHIVE_HASH_MISMATCH: " + str(path))
        data = json.loads(payload)
        check_report(data)
        if data["day"] != path.parent.name or canonical(data) != payload:
            raise ValueError("ARCHIVE_CANONICAL_MISMATCH: " + str(path))
    pointer = store / "latest.json"
    latest = None
    if pointer.exists():
        latest = json.loads(pointer.read_text(encoding="utf-8"))
        if not isinstance(latest, dict) or set(latest) != {
            "schema", "day", "sha256", "saved_at_utc"
        } or latest["schema"] != "sefirot-daily-latest-v1":
            raise ValueError("INVALID_LATEST_POINTER")
        selected = store / latest["day"] / (latest["sha256"] + ".json")
        if selected not in files:
            raise ValueError("LATEST_ARCHIVE_NOT_FOUND")
        datetime.fromisoformat(latest["saved_at_utc"])
    if files and latest is None:
        raise ValueError("MISSING_LATEST_POINTER")
    return {"verified": True, "snapshots": len(files), "latest": latest}


def _load(path: str) -> object:
    with open(path, "rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("REPORT_TOO_LARGE")
    return json.loads(raw)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Private, versioned SEFIROT daily report autosave")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--report", help="final daily report envelope JSON")
    mode.add_argument("--ticket-input", help="single-day original ticket-audit input JSON")
    mode.add_argument("--verify", action="store_true", help="verify all saved reports and latest pointer")
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    args = parser.parse_args(argv)
    try:
        if args.verify:
            result = verify(args.store)
        else:
            if args.report:
                report = _load(args.report)
            else:
                # Import only for the dedicated daily-ticket audit path; no CORE mutation.
                sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
                from sefirot.ticket_audit import audit_tickets
                from sefirot.contracts import Policy
                audit = audit_tickets(_load(args.ticket_input), policy=Policy())
                days = audit["days"]
                if len(days) != 1:
                    raise ValueError("DAILY_AUTOSAVE_REQUIRES_ONE_REPORT_DAY")
                report = {"schema": SCHEMA, "day": days[0]["day"],
                          "timezone": audit["timezone"], "origin": "TICKET_AUDIT",
                          "status": "REPORTED_UNVERIFIED", "source_refs": [audit["dataset_hash"]],
                          "report": audit}
            result = save(report, args.store)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (ValueError, OSError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print("DAILY_AUTOSAVE_FAILED: " + str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
