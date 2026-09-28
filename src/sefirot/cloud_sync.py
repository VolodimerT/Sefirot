"""Optional, one-way SQLite -> private Postgres ledger mirror.

The local ledger remains authoritative. A conflicting cloud row aborts the
entire transaction. This module neither executes bets nor changes policy.
"""
from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import sqlite3

from .contracts import canonical, digest, time
from .repository import TABLES


# Every name is a constant, never assembled from input. Parents precede children.
COLUMNS = {
    'teams': ('id', 'payload'),
    'markets': ('id', 'payload'),
    'model_versions': ('id', 'at', 'payload'),
    'matches': ('id', 'home', 'away', 'kickoff', 'league', 'payload'),
    'predictions': ('id', 'match_id', 'model_id', 'at', 'payload'),
    'decisions': ('id', 'prediction_id', 'at', 'payload'),
    'odds_snapshots': ('id', 'prediction_id', 'market_id', 'at', 'payload'),
    'bets': ('id', 'decision_id', 'at', 'payload'),
    'results': ('id', 'at', 'payload'),
    'closing_odds': ('id', 'match_id', 'market_id', 'at', 'payload'),
    'calibration_history': ('id', 'prediction_id', 'market_id', 'at', 'payload'),
    'postmatch_reports': ('id', 'decision_id', 'at', 'payload'),
    'postmortems': ('id', 'decision_id', 'at', 'payload'),
    'health_events': ('id', 'at', 'payload'),
    'calibrators': ('id', 'at', 'payload'),
    'validation_runs': ('id', 'at', 'payload'),
    'split_assignments': ('id', 'at', 'payload'),
    'overrides': ('id', 'at', 'payload'),
    'model_routes': ('id', 'at', 'payload'),
    'policy_approvals': ('id', 'at', 'payload'),
    'jobs': ('id', 'at', 'payload'),
    'audit_logs': ('id', 'at', 'event', 'payload', 'previous_hash', 'hash'),
}
CLOUD_COLUMNS = {**COLUMNS, 'audit_logs':
                 ('id', 'at', 'at_source', 'event', 'payload', 'payload_source', 'previous_hash', 'hash')}
MAX_ROWS = 100_000  # Bounded snapshot: larger ledgers need a streaming protocol.


def snapshot(path: str | Path) -> dict[str, list[dict]]:
    """Read one consistent, immutable SQLite snapshot and verify its audit chain."""
    path = Path(path).resolve()
    if not path.is_file():
        raise ValueError('local SQLite ledger does not exist')
    uri = path.as_uri() + '?mode=ro'
    db = sqlite3.connect(uri, uri=True, isolation_level=None, timeout=10)
    db.row_factory = sqlite3.Row
    try:
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        if db.execute('PRAGMA user_version').fetchone()[0] != 2:
            raise ValueError('unsupported SQLite ledger version')
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('SQLite integrity check failed')
        if db.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('SQLite foreign key check failed')
        if set(COLUMNS) != set(TABLES):
            raise ValueError('SQLite/Postgres table mapping is incomplete')
        rows: dict[str, list[dict]] = {}
        count = 0
        for table, columns in COLUMNS.items():
            batch = [dict(row) for row in db.execute(
                f"SELECT {','.join(columns)} FROM {table} ORDER BY id")]
            count += len(batch)
            if count > MAX_ROWS:
                raise ValueError('ledger exceeds bounded sync limit')
            for row in batch:
                try:
                    obj = json.loads(row['payload'])
                    if not isinstance(obj, dict) or canonical(obj) != row['payload']:
                        raise ValueError('noncanonical or nonobject payload')
                    for name in ('at', 'kickoff'):
                        if name in row:
                            time(row[name])
                except (TypeError, ValueError) as exc:
                    raise ValueError(f'invalid {table} ledger row') from exc
            rows[table] = batch
        _verify_chain(rows)
        db.execute('ROLLBACK')
        return rows
    finally:
        db.close()


def _verify_chain(rows: dict[str, list[dict]]) -> None:
    by_id = {t: {r['id']: r for r in group} for t, group in rows.items() if t != 'audit_logs'}
    referenced = set()
    previous = '0' * 64
    for sequence, row in enumerate(rows['audit_logs'], 1):
        if (row['id'] != sequence or row['previous_hash'] != previous or
                row['hash'] != digest([previous, row['at'], row['event'], row['payload']])):
            raise ValueError('local audit chain is broken')
        previous = row['hash']
        payload = json.loads(row['payload'])
        if 'record_table' in payload:
            table = payload['record_table']
            identifier = payload.get('record_id')
            if not isinstance(table, str) or not isinstance(identifier, (str, int)):
                raise ValueError('invalid local audit reference')
            record = by_id.get(table, {}).get(identifier)
            if record is None or digest(json.loads(record['payload'])) != payload.get('record_hash'):
                raise ValueError('local audit references a missing or changed record')
            referenced.add((table, identifier))
    for table in ('predictions', 'decisions', 'results', 'calibrators',
                  'validation_runs', 'bets'):
        if any((table, row['id']) not in referenced for row in rows[table]):
            raise ValueError('local decision or probability has no audit witness')


def _cloud_row(table: str, local: dict) -> dict:
    row = dict(local)
    row['payload'] = json.loads(row['payload'])
    for name in ('at', 'kickoff'):
        if name in row:
            if table == 'audit_logs':
                row['at_source'] = row['at']
            row[name] = time(row[name])
    if table == 'audit_logs':
        row['payload_source'] = local['payload']
    return row


def _same(table: str, expected: dict, actual: dict) -> bool:
    if set(actual) != set(CLOUD_COLUMNS[table]):
        return False
    for name in CLOUD_COLUMNS[table]:
        value = actual[name]
        if name == 'payload':
            if not isinstance(value, dict) or canonical(value) != canonical(expected[name]):
                return False
        elif name in ('at', 'kickoff'):
            if not isinstance(value, datetime) or value.tzinfo is None or value != expected[name]:
                return False
        elif value != expected[name]:
            return False
    return True


def mirror(rows: dict[str, list[dict]], connection) -> dict:
    """Upload and verify a full snapshot atomically using a DB-API connection.

    Only the dedicated sefirot_ingest Postgres role may run this operation.
    Caller owns transaction/commit; an exception must roll it back.
    """
    if set(rows) != set(COLUMNS):
        raise ValueError('incomplete local snapshot')
    counts = {}
    with connection.cursor() as cursor:
        cursor.execute('SELECT current_user')
        if cursor.fetchone()[0] != 'sefirot_ingest':
            raise ValueError('cloud sync requires dedicated sefirot_ingest role')
        cursor.execute('SELECT pg_advisory_xact_lock(27182, 212)')
        for table, local in rows.items():
            columns = CLOUD_COLUMNS[table]
            cursor.execute(f"SELECT {','.join(columns)} FROM sefirot.{table} ORDER BY id")
            found = [dict(zip(columns, record)) for record in cursor.fetchall()]
            expected = {r['id']: _cloud_row(table, r) for r in local}
            if len(expected) != len(local):
                raise ValueError(f'duplicate local id in {table}')
            for cloud in found:
                candidate = expected.get(cloud['id'])
                if candidate is None or not _same(table, candidate, cloud):
                    raise ValueError(f'cloud conflict in {table}: {cloud["id"]}')
            existing = {r['id'] for r in found}
            for row in local:
                if row['id'] in existing:
                    continue
                values = _cloud_row(table, row)
                cursor.execute(
                    f"INSERT INTO sefirot.{table}({','.join(columns)}) VALUES ({','.join('%s::jsonb' if c == 'payload' else '%s' for c in columns)})",
                    tuple(canonical(values[c]) if c == 'payload' else values[c] for c in columns))
            cursor.execute(f'SELECT {",".join(columns)} FROM sefirot.{table} ORDER BY id')
            verified = [dict(zip(columns, record)) for record in cursor.fetchall()]
            if len(verified) != len(expected) or any(
                r['id'] not in expected or not _same(table, expected[r['id']], r)
                for r in verified
            ):
                raise ValueError(f'cloud post-write verification failed: {table}')
            counts[table] = len(verified)
    return {'status': 'MIRRORED', 'rows': counts, 'audit_head':
            rows['audit_logs'][-1]['hash'] if rows['audit_logs'] else '0' * 64,
            'snapshot_hash': digest(rows), 'authority': 'local SQLite',
            'monetary_permission': False}


def check_local(path: str | Path) -> dict:
    rows = snapshot(path)
    return {'status': 'LOCAL_VERIFIED', 'rows': {t: len(batch) for t, batch in rows.items()},
            'audit_head': rows['audit_logs'][-1]['hash'] if rows['audit_logs'] else '0' * 64,
            'snapshot_hash': digest(rows), 'cloud_written': False,
            'monetary_permission': False}


def sync(path: str | Path, dsn: str | None = None, ca: str | None = None) -> dict:
    """Explicit opt-in cloud write; SSL certificate and credentials stay local."""
    rows = snapshot(path)
    dsn = dsn or os.environ.get('SEFIROT_SUPABASE_DB_DSN')
    ca = ca or os.environ.get('SEFIROT_SUPABASE_CA')
    if not dsn or not ca or not Path(ca).is_file():
        raise ValueError('sync requires SEFIROT_SUPABASE_DB_DSN and an existing SEFIROT_SUPABASE_CA file')
    try:
        import psycopg
    except ImportError as exc:
        raise ValueError('install the optional dependency: pip install .[sync]') from exc
    # psycopg keyword arguments override any weaker sslmode embedded in DSN.
    try:
        with psycopg.connect(dsn, sslmode='verify-full', sslrootcert=ca, connect_timeout=10) as connection:
            with connection.transaction():
                connection.execute('SET TRANSACTION ISOLATION LEVEL SERIALIZABLE')
                return mirror(rows, connection)
    except psycopg.Error as exc:
        # Never echo DSN or a server-provided error which might contain secrets.
        raise ValueError('cloud sync failed; transaction rolled back; check connectivity, role and schema') from exc
