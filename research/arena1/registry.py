"""Create-once research JSON records, separate from the read-only CORE ledger."""
import json
from pathlib import Path

from scripts.arena_control import check_hash, write_new
from sefirot.contracts import canonical

from .diagnostics import diagnose


def register(directory, prediction, quotes, at, **options):
    # Finish all validation before creating any registry output.
    report = diagnose(prediction, quotes, at, **options)
    root = Path(directory)
    if root.is_symlink() or any(p.is_symlink() for p in root.parents):
        raise ValueError('registry symlink aliases forbidden')
    if root.exists() and not root.is_dir():
        raise ValueError('separate registry directory required')
    root.mkdir(parents=True, exist_ok=True)
    target = root / (report['hash'] + '.json')
    write_new(target, report)
    return target, report


def read_bound(path, prediction, quotes, at, **options):
    target = Path(path)
    if target.is_symlink():
        raise ValueError('registry symlink record forbidden')
    if target.stat().st_size > 8 * 1024 * 1024:
        raise ValueError('bounded registry record required')
    report = json.loads(target.read_text(encoding='utf-8'))
    check_hash(report)
    expected = diagnose(prediction, quotes, at, **options)
    if canonical(report) != canonical(expected):
        raise ValueError('diagnostic record does not reproduce from original inputs')
    if target.name != report['hash'] + '.json':
        raise ValueError('registry content filename mismatch')
    return report
