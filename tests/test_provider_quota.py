"""Direct transport keeps minute/daily quota distinct and private failures closed."""
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sefirot.football_provider import FootballRequestError, get


class DirectProviderQuotaTests(unittest.TestCase):
    def call(self, *, headers, errors=None):
        self.closed = False
        owner = self
        class Reply:
            status = 200
            def read(self, limit):
                return json.dumps({'errors': errors or [], 'response': {}}).encode()[:limit]
            def getheader(self, name):return headers.get(name)
        class Connection:
            def __init__(self, host, timeout):pass
            def request(self, method, path, headers):pass
            def getresponse(self):return Reply()
            def close(self):owner.closed = True
        return get('status', api_key='PRIVATE_AUTH_VALUE', connection_factory=Connection)

    def test_http_200_rate_limit_is_a_quota_failure_with_closed_transport(self):
        with self.assertRaises(FootballRequestError) as caught:
            self.call(headers={},errors={'rateLimit':'PRIVATE_ERROR_VALUE'})
        self.assertEqual(caught.exception.code,'PROVIDER_QUOTA_EXHAUSTED')
        self.assertEqual(caught.exception.receipt['http_status'],200)
        self.assertNotIn('PRIVATE_ERROR_VALUE',str(caught.exception))
        self.assertTrue(self.closed)

    def test_daily_and_minute_allowances_are_preserved_separately_without_auth(self):
        quota={'x-ratelimit-requests-remaining':'90','x-ratelimit-remaining':'0','x-ratelimit-limit':'10'}
        packet=self.call(headers=quota)
        self.assertEqual(packet['receipt']['quota'],quota)
        self.assertNotIn('PRIVATE_AUTH_VALUE',json.dumps(packet))
        self.assertTrue(self.closed)

    def test_malformed_numeric_headers_never_enter_receipts_or_error_text(self):
        for name in ('x-ratelimit-remaining','x-ratelimit-requests-remaining'):
            for value in ('PRIVATE_AUTH_VALUE',True,'-1','١','9'*13):
                with self.subTest(name=name,value=value),self.assertRaises(ValueError) as caught:
                    self.call(headers={name:value})
                self.assertNotIn('PRIVATE_AUTH_VALUE',str(caught.exception))
                self.assertTrue(self.closed)
