"""Offline, read-only comparison of canonical SQLite and observed cloud metadata.

No network, mirror, restore, checkpoint or record insertion is performed.
Cloud metadata remains an observation supplied by the caller, not an attestation.
"""
from collections import Counter
import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sefirot.cloud_sync import snapshot
from sefirot.contracts import digest, time

MIRROR_TABLES = ('predictions', 'decisions', 'calibrators', 'validation_runs',
                 'odds_snapshots', 'closing_odds', 'results')
MAX_BYTES = 8_000_000


def _offline(path):
    if any(Path(str(path) + suffix).exists() for suffix in ('-wal', '-shm', '-journal')):
        raise ValueError('OFFLINE_SNAPSHOT_REQUIRED')


def _metadata(observation):
    if not isinstance(observation, dict) or set(observation) != {'observed_at', 'snapshot', 'mirror_counts'}:
        raise ValueError('INVALID_CLOUD_OBSERVATION')
    remote, counts = observation['snapshot'], observation['mirror_counts']
    if (not isinstance(remote, dict) or set(remote) != {'revision', 'checksum',
            'actual_compressed_sha256', 'updated_at'} or type(remote['revision']) is not int
            or remote['revision'] < 1 or not isinstance(counts, dict) or set(counts) != set(MIRROR_TABLES)
            or any(type(v) is not int or v < 0 for v in counts.values())):
        raise ValueError('INVALID_CLOUD_OBSERVATION')
    for key in ('checksum', 'actual_compressed_sha256'):
        if not isinstance(remote[key], str) or not re.fullmatch('[a-f0-9]{64}', remote[key]):
            raise ValueError('INVALID_CLOUD_OBSERVATION')
    try:
        if time(remote['updated_at']) > time(observation['observed_at']):
            raise ValueError('future observation')
    except (TypeError, ValueError):
        raise ValueError('INVALID_CLOUD_OBSERVATION_TIME') from None
    return remote, counts


def reconcile(path, observation):
    """Return public aggregates and a separate private per-prediction inventory."""
    remote, cloud_counts = _metadata(observation)
    path = Path(path).resolve()
    _offline(path)
    with path.open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('SNAPSHOT_TOO_LARGE')
    # Verify one owned, immutable copy through the original ledger validator.
    with tempfile.TemporaryDirectory(prefix='sefirot-reconcile-') as folder:
        owned = Path(folder) / 'snapshot.sqlite'
        owned.write_bytes(raw)
        rows = snapshot(owned)
    _offline(path)
    with path.open('rb') as stream:
        if stream.read(MAX_BYTES + 1) != raw:
            raise ValueError('SNAPSHOT_CHANGED_DURING_REVIEW')
    packed = bytearray(gzip.compress(raw, mtime=0))
    candidates = {hashlib.sha256(packed).hexdigest()}
    # Python/zlib versions differ only in gzip's OS metadata byte for this
    # deterministic encoding. Compare the portable header too, never raw data.
    packed[9] = 255
    candidates.add(hashlib.sha256(packed).hexdigest())
    intact = remote['checksum'] == remote['actual_compressed_sha256']
    matches = intact and remote['checksum'] in candidates
    inventory = []
    for row in rows['predictions']:
        p = json.loads(row['payload'])
        inventory.append({'prediction_id': row['id'], 'fixture_id': p['sports']['match']['id'],
            'sealed_at': p['sealed_at'], 'code_hash': p['code_hash'], 'model_hash': p['model_hash'],
            'policy_hash': p['policy_hash'], 'revision': p.get('revision'), 'parent': p.get('parent'),
            'history_rows': len(p['sports']['history']),
            'used_history_rows': len(p['model']['used_history']),
            'sources_hash': digest(p['sports']['sources']), 'ledger_witness_verified': True,
            'provider_origin_independently_verified': False})
    local_counts = {name: len(records) for name, records in rows.items()}
    report = {'schema': 'sefirot-storage-reconciliation-v1',
        'observed_at': observation['observed_at'],
        'cloud_metadata_authority': 'CALLER_SUPPLIED_OBSERVATION',
        'snapshot_revision': remote['revision'], 'snapshot_updated_at': remote['updated_at'],
        'raw_sqlite_sha256': hashlib.sha256(raw).hexdigest(),
        'compressed_snapshot_integrity': intact, 'canonical_snapshot_matches': matches,
        'journal_integrity': True, 'local_counts': local_counts, 'mirror_counts': cloud_counts,
        'mirror_comparison': 'COUNTS_ONLY_NOT_CONTENT_VERIFIED',
        'mirror_state': ('EMPTY_MATERIALIZED_LAYER' if all(v == 0 for v in cloud_counts.values())
                         else 'CONTENT_RECONCILIATION_REQUIRED'),
        'prediction_build_counts': dict(sorted(Counter(p['code_hash'] for p in inventory).items())),
        'distinct_prediction_ids': len({p['prediction_id'] for p in inventory}),
        'distinct_fixture_ids': len({p['fixture_id'] for p in inventory}),
        'historical_revisions_preserved': True,
        'status': 'CANONICAL_CONTENT_MATCH' if matches else 'CANONICAL_CONTENT_NOT_VERIFIED',
        'cloud_written': False, 'original_written': False,
        'monetary_permission': False, 'execution_enabled': False}
    report['hash'] = digest(report)
    return report, inventory


def _write_private(path, value):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', required=True)
    parser.add_argument('--cloud-observation', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--private-inventory')
    args = parser.parse_args(argv)
    try:
        with Path(args.cloud_observation).open('rb') as stream:
            data = stream.read(65537)
        if len(data) > 65536:
            raise ValueError('OBSERVATION_TOO_LARGE')
        observation = json.loads(data)
        report, inventory = reconcile(args.db, observation)
        if args.private_inventory:
            _write_private(args.private_inventory, inventory)
        _write_private(args.output, report)
    except (ValueError, OSError, KeyError, TypeError, sqlite3.Error):
        print(json.dumps({'status': 'STORAGE_RECONCILIATION_FAILED', 'original_written': False,
                          'cloud_written': False, 'monetary_permission': False}))
        return 2
    print(json.dumps({'status': report['status'], 'prediction_count': report['local_counts']['predictions'],
                      'snapshot_revision': report['snapshot_revision'], 'cloud_written': False}))
    return 0 if report['canonical_snapshot_matches'] else 2


if __name__ == '__main__':
    raise SystemExit(main())
