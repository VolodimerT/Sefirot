"""Offline whitelist-only gateway evidence; bytes/structure are not attestation."""
from hashlib import sha256
import json
from sefirot.contracts import digest, integer, strict, time
from sefirot.provider_transport import QUOTA_HEADERS
from sefirot.sports_archive import validate_packet

SCHEMA = 'sefirot-gateway-call-v1'
PLANS = {'Free', 'Pro', 'Ultra', 'Mega'}
STATUSES = {'NS', 'TBD', '1H', 'HT', '2H', 'ET', 'BT', 'P', 'SUSP',
            'INT', 'FT', 'AET', 'PEN', 'PST', 'CANC', 'ABD', 'AWD', 'WO', 'LIVE'}


def decode(raw):
    if not isinstance(raw, bytes) or len(raw) > 2_000_000:
        raise ValueError('EVIDENCE_SIZE_REJECTED')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('DUPLICATE_JSON_KEY')
            result[key] = value
        return result
    def constant(_):
        raise ValueError('NONFINITE_JSON')
    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=constant)
    except (UnicodeError, ValueError, RecursionError):
        raise ValueError('EVIDENCE_JSON_REJECTED') from None


def inspect(raw, *, imported_at):
    call = decode(raw)
    strict(call, ('schema', 'gateway_version', 'request_started_at', 'received_at',
                  'http_status', 'request', 'response'))
    if call['schema'] != SCHEMA or type(call['http_status']) is not int or call['http_status'] != 200:
        raise ValueError('SUCCESSFUL_CALL_ENVELOPE_REQUIRED')
    integer(call['gateway_version'], 'gateway version', 1, 100000)
    request = call['request']
    strict(request, ('endpoint', 'params'))  # Header/token fields are prohibited.
    endpoint = request['endpoint']
    if endpoint == 'status':
        if request['params'] != {}:
            raise ValueError('STATUS_PARAMETERS_REJECTED')
    elif endpoint == 'fixtures':
        strict(request['params'], ('id',))
        integer(request['params']['id'], 'fixture id', 1, 2147483647)
    else:
        raise ValueError('ONLY_STATUS_OR_SINGLE_FIXTURE')
    wrapper = call['response']
    if (not isinstance(wrapper, dict) or wrapper.get('ok') is not True
            or wrapper.get('provider') != 'API_FOOTBALL_V3'
            or wrapper.get('provider_host') != 'v3.football.api-sports.io'
            or wrapper.get('endpoint') != '/' + endpoint
            or digest(wrapper.get('params')) != digest(request['params'])
            or wrapper.get('sports_only') is not True
            or wrapper.get('monetary_permission') is not False
            or wrapper.get('execution_enabled') is not False):
        raise ValueError('GATEWAY_IDENTITY_REJECTED')
    started, upstream, received, imported = map(time, (
        call['request_started_at'], wrapper['received_at'], call['received_at'], imported_at))
    if not started <= upstream <= received <= imported:
        raise ValueError('EVIDENCE_CHRONOLOGY_REJECTED')
    data = wrapper['data']
    if not isinstance(data, dict) or data.get('errors') not in ({}, []):
        raise ValueError('PROVIDER_RESPONSE_REJECTED')
    if data.get('get') != endpoint:
        raise ValueError('PROVIDER_ENDPOINT_REJECTED')
    quota = wrapper.get('quota', {})
    if (not isinstance(quota, dict) or set(quota) - set(QUOTA_HEADERS)
            or any(not isinstance(v, str) or not v.isascii() or not v.isdigit()
                   or not 1 <= len(v) <= 12 for v in quota.values())):
        raise ValueError('QUOTA_REJECTED')
    quota = {k: int(v) for k, v in quota.items()}
    for remaining, limit in (
        ('x-ratelimit-requests-remaining', 'x-ratelimit-requests-limit'),
        ('x-ratelimit-remaining', 'x-ratelimit-limit')):
        if remaining in quota and limit in quota and quota[remaining] > quota[limit]:
            raise ValueError('QUOTA_COUNTER_CONFLICT')
    out = {'schema': 'gateway-evidence-receipt-v44', 'endpoint': '/' + endpoint,
           'gateway_version_claimed': call['gateway_version'],
           'request_started_at': started.isoformat(), 'upstream_received_at': upstream.isoformat(),
           'received_at': received.isoformat(), 'imported_at': imported.isoformat(),
           'raw_sha256': sha256(raw).hexdigest(), 'response_digest': digest(wrapper),
           'quota': quota, 'source_attestation': 'OFFLINE_CALLER_SUPPLIED',
           'auth_verified_by_this_process': False, 'monetary_permission': False,
           'fit_allowed': False, 'probability': None, 'ev': None}
    if endpoint == 'status':
        if data.get('parameters') not in ({}, []):
            raise ValueError('STATUS_PROVIDER_PARAMETERS_REJECTED')
        body = data['response']
        if not isinstance(body, dict):
            raise ValueError('STATUS_RESPONSE_REJECTED')
        subscription, requests = body['subscription'], body['requests']
        if type(subscription['active']) is not bool:
            raise ValueError('SUBSCRIPTION_ACTIVE_REJECTED')
        used = integer(requests['current'], 'day used', 0, 10**12)
        limit = integer(requests['limit_day'], 'day limit', 1, 10**12)
        if used > limit:
            raise ValueError('DAY_COUNTER_CONFLICT')
        if 'x-ratelimit-requests-limit' in quota and quota['x-ratelimit-requests-limit'] != limit:
            raise ValueError('DAY_LIMIT_CONFLICT')
        plan = subscription.get('plan')
        plan = plan if isinstance(plan, str) and plan in PLANS else 'UNKNOWN'
        out['subscription'] = {'active': subscription['active'], 'plan': plan}
        out['requests'] = {'used': used, 'limit_day': limit, 'remaining_day': limit - used,
                           'limit_minute': quota.get('x-ratelimit-limit'),
                           'remaining_minute': quota.get('x-ratelimit-remaining')}
        blockers = []
        if not subscription['active']:
            blockers.append('SUBSCRIPTION_INACTIVE')
        if used == limit or quota.get('x-ratelimit-requests-remaining') == 0:
            blockers.append('DAY_QUOTA_EXHAUSTED')
        if plan == 'UNKNOWN':
            blockers.append('PLAN_UNKNOWN')
        if quota.get('x-ratelimit-limit') is None or quota.get('x-ratelimit-remaining') is None:
            blockers.append('MINUTE_QUOTA_UNKNOWN')
        elif quota['x-ratelimit-limit'] == 0 or quota['x-ratelimit-remaining'] == 0:
            blockers.append('MINUTE_QUOTA_EXHAUSTED')
        out['blockers'] = blockers
        out['status'] = 'PROVIDER_GATE_BLOCKED' if blockers else 'STRUCTURALLY_VALID_UNATTESTED'
    else:
        if data.get('parameters') != {'id': str(request['params']['id'])}:
            raise ValueError('FIXTURE_PROVIDER_PARAMETERS_REJECTED')
        receipt = {'provider': wrapper['provider'], 'provider_host': wrapper['provider_host'],
                   'endpoint': wrapper['endpoint'], 'parameters': request['params'],
                   'request_started_at': started.isoformat(), 'received_at': received.isoformat(),
                   'payload_hash': digest(data), 'http_status': 200, 'sports_only': True,
                   'transport': 'SUPABASE_GATEWAY', 'upstream_received_at': upstream.isoformat()}
        validate_packet({'data': data, 'receipt': receipt}, imported.isoformat())
        if len(data['response']) != 1:
            raise ValueError('EXACTLY_ONE_FIXTURE_REQUIRED')
        if data['paging']['total'] != 1:
            raise ValueError('FIXTURE_PAGINATION_CONFLICT')
        row = data['response'][0]
        if row['fixture']['id'] != request['params']['id']:
            raise ValueError('FIXTURE_ID_CONFLICT')
        status = row['fixture']['status']['short']
        if status not in STATUSES:
            raise ValueError('FIXTURE_STATUS_REJECTED')
        out['fixture'] = {'id': row['fixture']['id'], 'league_id': row['league']['id'],
                          'season': row['league']['season'],
                          'kickoff': time(row['fixture']['date']).isoformat(), 'status': status}
        out['prematch_observed'] = status in ('NS', 'TBD') and time(row['fixture']['date']) > received
        out['status'] = 'STRUCTURALLY_VALID_UNATTESTED'
    out['hash'] = digest(out)
    return out


def missing(imported_at):
    return {'schema': 'gateway-evidence-receipt-v44', 'status': 'MISSING_ORIGINAL_RESPONSES',
            'imported_at': time(imported_at).isoformat(), 'api_calls': 0,
            'subscription': None, 'requests': None, 'fixture': None,
            'source_attestation': 'NOT_ESTABLISHED', 'monetary_permission': False,
            'fit_allowed': False, 'probability': None, 'ev': None}
