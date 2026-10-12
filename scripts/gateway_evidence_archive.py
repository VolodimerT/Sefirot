"""Explicit offline importer. No networking, credentials, fit or ledger writes."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
from research.gateway_evidence_v44 import inspect, missing


def main(argv=None):
    parser = argparse.ArgumentParser(description='Private sanitized status/single-fixture evidence archive')
    parser.add_argument('--input', type=Path, help='Saved original gateway call envelope; no headers')
    parser.add_argument('--output', type=Path, required=True, help='New private receipt file; overwrite rejected')
    args = parser.parse_args(argv)
    try:
        raw = None
        if args.input:
            with args.input.open('rb') as handle:
                raw = handle.read(2_000_001)
        # Actual local import clock, never a caller-supplied historical time.
        now = datetime.now(timezone.utc).isoformat()
        report = inspect(raw, imported_at=now) if raw is not None else missing(now)
        rendered = json.dumps(report, ensure_ascii=True, sort_keys=True, indent=2, allow_nan=False) + '\n'
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            handle.write(rendered)
        print(json.dumps({'status': report['status'], 'api_calls': 0, 'monetary_permission': False}))
        return 0
    except (OSError, ValueError, KeyError, TypeError, OverflowError):
        print('GATEWAY_EVIDENCE_REJECTED', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
