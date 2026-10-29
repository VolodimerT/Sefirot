"""Optional existing private Supabase gateway; provider key stays server-side."""
from datetime import datetime, timezone
from contextlib import contextmanager
from contextvars import ContextVar
from http.client import HTTPException
import json
import os
import re
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import Request, build_opener

from .contracts import digest, time
from .credentials import credential
from .football_query import (QUERY_ERROR_CODES, FootballQueryError, validate_fixture_query,
                             validate_fixture_query_parameters)
from .football_provider import HOST, PARAMETERS, FootballRequestError, get, validate_enrichment_request, validate_provider_data
from .provider_transport import MAX_RESPONSE, NoRedirect, QUOTA_HEADERS, read_response, close_transport, strict_json_payload


_BUDGET_REASONS = frozenset({
    "PAUSED", "BUSY", "UNFINISHED_ATTEMPT", "STALE_BUDGET",
    "DAILY_LIMIT", "MINUTE_LIMIT",
})
_SOURCE_JOB = ContextVar('sefirot_source_job',default=None)


@contextmanager
def source_job_context(job_id,attempt):
    if (not isinstance(job_id,str) or not re.fullmatch(r'[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',job_id)
            or type(attempt) is not int or not 1<=attempt<=3):
        raise ValueError('source job lease required')
    token=_SOURCE_JOB.set((job_id,attempt))
    try:yield
    finally:_SOURCE_JOB.reset(token)


class SportsBudgetGateError(ValueError):
    """Fixed budget denials without provider credentials or raw response text."""

    def __init__(self, reason):
        if type(reason) is not str or reason not in _BUDGET_REASONS:
            raise ValueError("unknown sports budget denial")
        self.code = "SHARED_BUDGET_" + reason
        super().__init__("sports shared budget refused request")


class SportsGatewayTransportError(ValueError):
    """Fixed gateway failure code; never carry an upstream body or credential."""

    CODES = frozenset({"UPSTREAM_TIMEOUT", "UPSTREAM_UNAVAILABLE",
                       "UPSTREAM_HTTP_429", "UPSTREAM_HTTP_502",
                       "UPSTREAM_HTTP_503"})

    def __init__(self, code):
        if code not in self.CODES:
            raise ValueError("unknown sports gateway failure")
        self.code = code
        super().__init__("sports gateway transport failed")


def safe_stat_labels(labels):
    """Bounded schema hints only: never arbitrary provider strings/values."""
    if not isinstance(labels,list):return []
    return sorted({v for v in labels[:256] if isinstance(v,str) and 1<=len(v)<=40
        and re.fullmatch(r'[A-Za-z][A-Za-z /%_-]{0,39}',v)
        and not re.search(r'(?i)(secret|token|key|auth|password|account|user|session|cookie|bearer|credential|access|api)',re.sub(r'[^a-z0-9]','',v.lower()))})[:5]


class SportsSourceSafetyError(ValueError):
    code='SOURCE_SAFETY'
    def __init__(self,labels=None):
        self.unsupported_stat_labels=safe_stat_labels(labels)
        super().__init__('sports source rejected by safety guard')


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


def get_sports(endpoint, params=None, *, opener=None, clock=None, require_shared_budget=False):
    url = os.environ.get('SEFIROT_SPORTS_GATEWAY_URL')
    if not url:
        if require_shared_budget or _SOURCE_JOB.get():
            raise ValueError('shared-budget sports gateway required')
        return get(endpoint, params)
    parts = urlsplit(url)
    if (parts.scheme != 'https' or not re.fullmatch(r'[a-z0-9]{20}\.supabase\.co', parts.netloc)
            or parts.path != '/functions/v1/sefirot-sports-gateway' or parts.query or parts.fragment):
        raise ValueError('invalid private sports gateway URL')
    params = dict(params or {})
    if (endpoint not in PARAMETERS or set(params) - PARAMETERS[endpoint]
            or any(isinstance(v, bool) or not isinstance(v, (str, int)) for v in params.values())):
        raise ValueError('unsupported sports endpoint/parameters')
    validate_enrichment_request(endpoint, params)
    if endpoint == 'fixtures':
        validate_fixture_query_parameters(params)
    token = credential('SEFIROT_SPORTS_GATEWAY_TOKEN')
    clock = clock or (lambda: datetime.now(timezone.utc))
    started = clock().isoformat()
    request = Request(url, method='POST', data=json.dumps({'endpoint': endpoint, 'params': params}).encode(),
                      headers={'Content-Type': 'application/json', 'Accept': 'application/json',
                               'x-sefirot-runner-token': token})
    context=_SOURCE_JOB.get()
    if context:
        request.add_header('x-sefirot-source-job-id',context[0])
        request.add_header('x-sefirot-source-attempt',str(context[1]))
    try:
        response = (opener or build_opener(NoRedirect()).open)(request, timeout=15)
    except HTTPError as exc:
        response = exc
    except (OSError, HTTPException):
        raise ValueError('sports gateway network unavailable') from None
    try:
        raw = read_response(response, MAX_RESPONSE)
        if len(raw) > MAX_RESPONSE:
            raise ValueError('sports gateway response exceeds limit')
        try:
            wrapper = strict_json_payload(raw)
        except ValueError:
            raise ValueError('sports gateway returned invalid JSON') from None
        if not isinstance(wrapper, dict):
            raise ValueError('sports gateway response malformed')
        if response.status != 200 or wrapper.get('ok') is not True:
            if (response.status == 429 and wrapper.get('ok') is False
                    and wrapper.get('error') == 'SHARED_BUDGET_STOP'):
                reason = wrapper.get('budget_reason')
                if type(reason) is str and reason in _BUDGET_REASONS:
                    raise SportsBudgetGateError(reason)
                raise ValueError('sports gateway budget response invalid')
            if response.status==502 and wrapper.get('ok') is False and wrapper.get('error')=='SOURCE_SAFETY':
                raise SportsSourceSafetyError(wrapper.get('unsupported_stat_labels'))
            if isinstance(wrapper.get('error'), str) and wrapper['error'] in QUERY_ERROR_CODES:
                raise FootballQueryError(wrapper['error'])
            if response.status == 422 and wrapper.get('error') == 'PROVIDER_REJECTED_REQUEST':
                raise FootballRequestError(wrapper.get('provider_errors', {}))
            if wrapper.get('error') == 'UPSTREAM_HTTP_ERROR':
                status = wrapper.get('upstream_http_status')
                if type(status) is int and 100 <= status <= 599:
                    if status in (429, 502, 503):
                        raise SportsGatewayTransportError('UPSTREAM_HTTP_' + str(status))
                    raise ValueError('sports gateway upstream HTTP ' + str(status))
            if wrapper.get('error') in ('UPSTREAM_TIMEOUT', 'UPSTREAM_UNAVAILABLE'):
                raise SportsGatewayTransportError(wrapper['error'])
            raise ValueError('sports gateway HTTP ' + str(int(response.status)))
        received = clock().isoformat()
        if (wrapper.get('provider') != 'API_FOOTBALL_V3' or wrapper.get('provider_host') != HOST
                or wrapper.get('endpoint') != '/' + endpoint or wrapper.get('params') != params
                or wrapper.get('sports_only') is not True or wrapper.get('monetary_permission') is not False
                or wrapper.get('execution_enabled') is not False):
            raise ValueError('sports gateway response identity mismatch')
        if require_shared_budget and wrapper.get('shared_budget_guard') != 'POSTGRES_RESERVATION_V1':
            raise ValueError('shared-budget sports gateway required')
        observed = time(wrapper['received_at'])
        if not time(started) <= observed <= time(received):
            raise ValueError('sports gateway receipt chronology mismatch')
        data = wrapper['data']
        if not isinstance(data, dict) or data.get('errors') not in ({}, []):
            raise ValueError('sports gateway provider response malformed')
        validate_provider_data(endpoint, data)
        if endpoint == 'fixtures':
            validate_fixture_query(data, params)
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
        if context:
            original=wrapper.get('source_archive_receipt')
            proof=wrapper.get('source_archive')
            if (not isinstance(original,dict) or set(original)!=set(receipt)
                    or not isinstance(proof,dict) or proof.get('stored') is not True
                    or any(original[k]!=v for k,v in receipt.items() if k not in ('request_started_at','received_at'))
                    or not time(started)<=time(original['request_started_at'])<=time(original['received_at'])<=time(received)
                    or original['received_at']!=receipt['upstream_received_at']
                    or proof.get('raw_sha256')!=digest({'data':data,'receipt':original})):
                raise ValueError('durable source archive acknowledgement required')
            receipt=original
        return {'data': data, 'receipt': receipt,
                **({'private_source_archive_hash': proof['raw_sha256']} if context else {})}
    except (OSError, HTTPException):
        raise ValueError('sports gateway network unavailable') from None
    finally:
        close_transport(response)

