"""Bind SQLite lookup columns to their canonical payloads without changing rows."""
import json

from .contracts import canonical, digest, time
from .markets import market_of


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
