"""Optional existing private Supabase gateway; provider key stays server-side."""
from datetime import datetime, timezone
import json
import os
import re
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from .contracts import digest, time
from .credentials import credential
from .football_provider import HOST, PARAMETERS, FootballRequestError, get
from .provider_transport import MAX_RESPONSE, NoRedirect, QUOTA_HEADERS


def transport_status():
    configured = bool(os.environ.get('SEFIROT_SPORTS_GATEWAY_URL'))
    name = 'SEFIROT_SPORTS_GATEWAY_TOKEN' if configured else 'API_FOOTBALL_KEY'
    try:
        credential(name)
    except (ValueError, OSError):
        ready = False
    else:
        ready = True
    return {'transport': 'SUPABASE_GATEWAY' if configured else 'DIRECT',
            'credential_configured': ready, 'credential_name': name}


def get_sports(endpoint, params=None, *, opener=None, clock=None):
    url = os.environ.get('SEFIROT_SPORTS_GATEWAY_URL')
    if not url:
        return get(endpoint, params)
    parts = urlsplit(url)
    if (parts.scheme != 'https' or not re.fullmatch(r'[a-z0-9]{20}\.supabase\.co', parts.netloc)
            or parts.path != '/functions/v1/sefirot-sports-gateway' or parts.query or parts.fragment):
        raise ValueError('invalid private sports gateway URL')
    params = dict(params or {})
    if (endpoint not in PARAMETERS or set(params) - PARAMETERS[endpoint]
            or any(isinstance(v, bool) or not isinstance(v, (str, int)) for v in params.values())):
        raise ValueError('unsupported sports endpoint/parameters')
    token = credential('SEFIROT_SPORTS_GATEWAY_TOKEN')
    clock = clock or (lambda: datetime.now(timezone.utc))
    started = clock().isoformat()
    request = Request(url, method='POST', data=json.dumps({'endpoint': endpoint, 'params': params}).encode(),
                      headers={'Content-Type': 'application/json', 'Accept': 'application/json',
                               'x-sefirot-runner-token': token})
    try:
        response = (opener or build_opener(NoRedirect()).open)(request, timeout=15)
    except HTTPError as exc:
        response = exc
    except OSError:
        raise ValueError('sports gateway network unavailable') from None
    try:
        raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError('sports gateway response exceeds limit')
        try:
            wrapper = json.loads(raw.decode('utf-8'))
        except (UnicodeError, json.JSONDecodeError):
            raise ValueError('sports gateway returned invalid JSON') from None
        if not isinstance(wrapper, dict):
            raise ValueError('sports gateway response malformed')
        if response.status != 200 or wrapper.get('ok') is not True:
            if response.status == 422 and wrapper.get('error') == 'PROVIDER_REJECTED_REQUEST':
                raise FootballRequestError(wrapper.get('provider_errors', {}))
            if wrapper.get('error') == 'UPSTREAM_HTTP_ERROR':
                status = wrapper.get('upstream_http_status')
                if type(status) is int and 100 <= status <= 599:
                    raise ValueError('sports gateway upstream HTTP ' + str(status))
            if wrapper.get('error') in ('UPSTREAM_TIMEOUT', 'UPSTREAM_UNAVAILABLE'):
                raise ValueError('sports gateway network unavailable')
            raise ValueError('sports gateway HTTP ' + str(int(response.status)))
        received = clock().isoformat()
        if (wrapper.get('provider') != 'API_FOOTBALL_V3' or wrapper.get('provider_host') != HOST
                or wrapper.get('endpoint') != '/' + endpoint or wrapper.get('params') != params
                or wrapper.get('sports_only') is not True or wrapper.get('monetary_permission') is not False
                or wrapper.get('execution_enabled') is not False):
            raise ValueError('sports gateway response identity mismatch')
        observed = time(wrapper['received_at'])
        if not time(started) <= observed <= time(received):
            raise ValueError('sports gateway receipt chronology mismatch')
        data = wrapper['data']
        if not isinstance(data, dict) or data.get('errors') not in ({}, []):
            raise ValueError('sports gateway provider response malformed')
        if endpoint != 'status' and (not isinstance(data.get('response'), list)
                or data.get('results') != len(data['response']) or data.get('paging', {}).get('total', 1) > 1):
            raise ValueError('sports gateway incomplete provider response')
        receipt = {'provider': 'API_FOOTBALL_V3', 'provider_host': HOST,
            'endpoint': '/' + endpoint, 'parameters': params, 'request_started_at': started,
            'received_at': received, 'payload_hash': digest(data), 'http_status': 200, 'sports_only': True,
            'transport': 'SUPABASE_GATEWAY', 'upstream_received_at': wrapper['received_at']}
        if 'quota' in wrapper:
            quota = wrapper['quota']
            if (not isinstance(quota, dict) or set(quota) - set(QUOTA_HEADERS)
                    or any(not isinstance(v, str) or not re.fullmatch(r'[0-9]{1,12}', v)
                           for v in quota.values())):
                raise ValueError('sports gateway quota response malformed')
            receipt['quota'] = dict(quota)
        return {'data': data, 'receipt': receipt}
    finally:
        response.close()
