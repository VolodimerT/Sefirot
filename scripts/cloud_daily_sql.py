"""Prepare a SAFE, copyable SQL write using the private Supabase SQL connector.

This module does not connect to Supabase. Invoker MUST send the generated SQL
through the authenticated connection and verify the returned saved=true receipt.
Never log or commit the generated SQL: it embeds the private report as hex.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from daily_autosave import check_report


def insert_sql(report: object) -> str:
    payload = check_report(report)
    # UTF-8 hex is safe in a SQL literal even if the report contains quotes,
    # shell characters, SQL-like text, CR/LF, emoji, or a dollar-quote marker.
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                            separators=(",", ":"), allow_nan=False).encode("utf-8")
    hex_payload = serialized.hex()
    return ("SELECT sefirot.save_daily_report("
            "convert_from(decode('" + hex_payload + "', 'hex'), 'UTF8')::jsonb"
            ") AS save_receipt;")


def latest_sql(day: str | None = None) -> str:
    if day is None:
        return ("SELECT report_day, sha256, saved_at FROM sefirot.daily_report_archive "
                "ORDER BY saved_at DESC, sha256 DESC LIMIT 10;")
    from datetime import date
    if not isinstance(day, str) or date.fromisoformat(day).isoformat() != day:
        raise ValueError("INVALID_REPORT_DAY")
    return ("SELECT report_day, sha256, saved_at, payload "
            "FROM sefirot.daily_report_archive WHERE report_day = '" + day +
            "' ORDER BY saved_at DESC, sha256 DESC;")


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare private SEFIROT cloud autosave SQL")
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    data = json.loads(args.report.read_text(encoding="utf-8"))
    print(insert_sql(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
