"""HTTPS through the ordinary runtime proxy; no redirects or credential logs."""
import json
from http.client import HTTPException
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, Request, build_opener
from datetime import datetime, timezone
from .contracts import digest

HOSTS = ('api.the-odds-api.com', 'v3.football.api-sports.io')
MAX_RESPONSE = 4_000_000
QUOTA_HEADERS = ('x-requests-remaining', 'x-requests-used', 'x-requests-last',
                 'x-ratelimit-requests-remaining', 'x-ratelimit-requests-limit',
                 'x-ratelimit-remaining', 'x-ratelimit-limit')


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def read_response(response, limit):
    """Bound bytes and reject incomplete or ambiguous HTTP body framing."""
    getheader = getattr(response, 'getheader', None)
    if getheader is None and hasattr(response, 'headers'):
        getheader = response.headers.get
    declared = None
    if getheader is not None:
        length = getheader('Content-Length')
        encoding = getheader('Transfer-Encoding')
        if encoding is not None and (length is not None or not isinstance(encoding, str)
                                     or encoding.strip().lower() != 'chunked'):
            raise HTTPException('invalid provider response framing')
        if length is not None:
            if not isinstance(length, str) or not re.fullmatch(r'[0-9]{1,20}', length.strip()):
                raise HTTPException('invalid provider response framing')
            declared = int(length.strip())
    raw = response.read(limit + 1)
    # Leave over-limit bytes to each provider's existing public size error.
    if len(raw) <= limit and declared is not None and len(raw) != declared:
        raise HTTPException('incomplete provider response')
    return raw


def close_transport(transport):
    """Cleanup must not replace a primary refusal with private network text."""
    close = getattr(transport, 'close', None)
    if close is not None:
        try:
            close()
        except (OSError, HTTPException):
            pass


class ProviderConnection:
    """http.client-compatible subset, preserving injectable offline transports."""
    def __init__(self, host, timeout=15):
        if host not in HOSTS:
            raise ValueError('unsupported provider host')
        self.host, self.timeout, self.response = host, timeout, None

    def request(self, method, path, headers):
        if method != 'GET' or not path.startswith('/') or path.startswith('//'):
            raise ValueError('unsupported provider request')
        request = Request('https://' + self.host + path, headers=headers, method='GET')
        try:
            # Default ProxyHandler uses the environment's normal network route;
            # HTTPS certificate verification remains enabled.
            self.response = build_opener(NoRedirect()).open(request, timeout=self.timeout)
        except HTTPError as exc:
            self.response = exc
        except (URLError, OSError, ValueError, HTTPException):
            raise OSError('provider network unavailable') from None

    def getresponse(self):
        return self.response

    def close(self):
        if self.response is not None:
            close_transport(self.response)


def request_json(host, path, params, headers, *, query_credential=None,
                 connection_factory=ProviderConnection):
    """Return data and a receipt that excludes authentication headers and query."""
    sent = dict(params)
    if query_credential:
        sent['apiKey'] = query_credential
    connection = connection_factory(host, timeout=15)
    started = datetime.now(timezone.utc).isoformat()
    try:
        query = urlencode(sent)
        connection.request('GET', path + ('?' + query if query else ''),
                           headers={'Accept': 'application/json', **headers})
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError(f'provider HTTP {int(response.status)}')
        raw = read_response(response, MAX_RESPONSE)
        if len(raw) > MAX_RESPONSE:
            raise ValueError('provider response exceeds limit')
        try:
            value = json.loads(raw.decode('utf-8'))
        except (UnicodeError, json.JSONDecodeError):
            raise ValueError('provider returned invalid JSON') from None
        receipt = {'provider_host': host, 'endpoint': path, 'parameters': dict(params),
                   'request_started_at': started,
                   'received_at': datetime.now(timezone.utc).isoformat(),
                   'payload_hash': digest(value), 'http_status': 200}
        getheader = getattr(response, 'getheader', None)
        if getheader is None and hasattr(response, 'headers'):
            getheader = response.headers.get
        if getheader:
            quota = {key: getheader(key) for key in QUOTA_HEADERS if getheader(key) is not None}
            if any(not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,12}', value)
                   for value in quota.values()):
                raise ValueError('provider quota header malformed')
            receipt['quota'] = quota
        return {'data': value, 'receipt': receipt}
    except (OSError, HTTPException):
        raise ValueError('provider network unavailable') from None
    finally:
        close_transport(connection)
