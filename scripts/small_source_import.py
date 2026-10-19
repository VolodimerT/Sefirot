"""Explicit offline saved-packet import; never queries API or changes CORE."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.small_source_adapter import import_api_archive, MAX_PACKET_BYTES, MAX_ARCHIVE_BYTES
from scripts.small_market_qc import strict_json


def read_packet(path):
    with path.open('rb') as handle:
        raw = handle.read(MAX_PACKET_BYTES + 1)
    if len(raw) > MAX_PACKET_BYTES:
        raise ValueError('PACKET_BYTES_LIMIT')
    return raw


def main(argv=None):
    parser = argparse.ArgumentParser(description='Offline API-Football FT archive import (research only)')
    parser.add_argument('--manifest', required=True, type=Path)
    parser.add_argument('--schedule', required=True, type=Path)
    parser.add_argument('--statistics', action='append', default=[], type=Path)
    parser.add_argument('--output', required=True, type=Path, help='New private JSON bundle; overwrite rejected')
    args = parser.parse_args(argv)
    try:
        # No user flag can backdate when these bytes became available locally.
        manifest = strict_json(args.manifest)
        schedule = read_packet(args.schedule)
        statistics = []
        size = len(schedule)
        for path in args.statistics:
            raw = read_packet(path)
            size += len(raw)
            if size > MAX_ARCHIVE_BYTES:
                raise ValueError('ARCHIVE_BYTES_LIMIT')
            statistics.append(raw)
        now = datetime.now(timezone.utc).isoformat()
        report = import_api_archive(manifest, schedule, statistics, now, now)
        rendered = json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + '\n'
        with args.output.open('x', encoding='utf-8') as handle:
            handle.write(rendered)
        print('RETROSPECTIVE_RESEARCH_ONLY: saved packet binding and QC complete; fit disabled.')
        return 0
    except (ValueError, OSError, KeyError, TypeError, AttributeError, RecursionError) as error:
        # Raw packets may contain provider messages/credentials: never echo them.
        reason = (str(error) if isinstance(error, ValueError)
                  and re.fullmatch('[A-Z][A-Z0-9_]{2,100}', str(error))
                  else 'OUTPUT_ALREADY_EXISTS' if isinstance(error, FileExistsError)
                  else 'INVALID_LOCAL_ARCHIVE_OR_OUTPUT')
        print('SOURCE_IMPORT_REJECTED: ' + reason, file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
