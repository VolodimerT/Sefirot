"""Bind SQLite lookup columns to their canonical payloads without changing rows."""
import json

from .contracts import canonical, digest, time
from .markets import market_of


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

TIME_FIELDS = {
    'model_versions': 'registered_at', 'predictions': 'sealed_at',
    'decisions': 'at', 'odds_snapshots': 'received_at', 'bets': 'at',
    'results': 'received_at', 'closing_odds': 'received_at',
    'calibration_history': 'received_at', 'postmatch_reports': 'at',
    'postmortems': 'at', 'health_events': 'at', 'calibrators': 'fit_at',
    'validation_runs': 'at', 'split_assignments': 'at', 'overrides': 'at',
    'model_routes': 'at', 'policy_approvals': 'at', 'jobs': 'at',
}


def validate_row(table, row, *, require_canonical=True):
    """Validate the stored ID, timestamp and foreign keys against the payload.

    Dates compare as UTC instants: equivalent ISO offsets are accepted.
    No database writes or schema migrations are needed for existing ledgers.
    """
    try:
        payload = json.loads(row['payload'])
        if not isinstance(payload, dict) or (require_canonical and canonical(payload) != row['payload']):
            raise ValueError('noncanonical payload')
        if table == 'audit_logs':
            time(row['at'])
            return payload

        expected = {}
        if table == 'teams':
            expected['id'] = payload['name']
        elif table == 'markets':
            expected['id'] = market_of(payload).key
        elif table == 'matches':
            expected = {name: payload[name] for name in ('id', 'home', 'away', 'league')}
            if time(row['kickoff']) != time(payload['kickoff']):
                raise ValueError('kickoff mismatch')
        elif table == 'predictions':
            expected = {'id': payload['id'], 'model_id': payload['model_id'],
                        'match_id': payload['sports']['match']['id']}
        elif table == 'decisions':
            expected = {'id': payload['id'], 'prediction_id': payload['prediction_id']}
        elif table == 'odds_snapshots':
            expected = {'id': digest([row['prediction_id'], payload]),
                        'market_id': market_of(payload['market']).key}
        elif table == 'bets':
            expected = {'id': payload['id'], 'decision_id': payload['decision_id']}
        elif table == 'results':
            expected['id'] = payload['match_id']
        elif table == 'closing_odds':
            expected = {'id': digest(payload), 'match_id': payload['match_id'],
                        'market_id': market_of(payload['market']).key}
        elif table == 'calibration_history':
            expected = {'id': digest(payload), 'prediction_id': payload['prediction_id'],
                        'market_id': payload['market']}
        elif table == 'postmatch_reports':
            expected = {'id': digest(payload), 'decision_id': payload['decision_id']}
        elif table == 'postmortems':
            expected = {'id': digest([payload['decision_id'], payload['market']]),
                        'decision_id': payload['decision_id']}
        elif table == 'calibrators':
            expected['id'] = payload['hash']
        elif table == 'split_assignments':
            expected['id'] = payload['match_id']
        elif table in ('overrides', 'policy_approvals'):
            expected['id'] = digest(payload)
        elif table in ('model_versions', 'health_events', 'validation_runs', 'model_routes', 'jobs'):
            expected['id'] = payload['id']
        else:
            raise ValueError('unknown ledger table')

        if any(row[name] != value for name, value in expected.items()):
            raise ValueError('identifier or reference mismatch')
        if table in TIME_FIELDS and time(row['at']) != time(payload[TIME_FIELDS[table]]):
            raise ValueError('timestamp mismatch')
        return payload
    except (KeyError, IndexError, TypeError, ValueError, OverflowError):
        raise ValueError(f'invalid {table} ledger row') from None


def validate_schema(db):
    """Check lookup columns and single-ID primary keys, even in empty tables.

    Read schema metadata afresh. This is a local structural check, not source
    authentication; no journal outcome or permission is cached.
    """
    for table, required in COLUMNS.items():
        columns = list(db.execute(f'PRAGMA table_info({table})'))
        names = {column[1].lower() for column in columns}
        primary = [column[1].lower() for column in columns if column[5]]
        if not set(required) <= names or primary != ['id']:
            raise ValueError('invalid SQLite ledger schema')
