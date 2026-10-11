"""Zero-network tests for the opt-in public example endpoint client."""
from datetime import datetime, timezone
from email.message import Message
import json
import unittest
from scripts.footystats_public_demo import fetch_example, MAX_BYTES


class Response:
    def __init__(self, payload, content_type="application/json"):
        self.status = 200
        self.data = payload
        self.headers = Message()
        self.headers["Content-Type"] = content_type

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def read(self, maximum):
        return self.data[:maximum]


class Opener:
    def __init__(self, resp):
        self.resp = resp
        self.count = 0
        self.requests = []

    def open(self, req, timeout):
        self.count += 1
        self.requests.append((req.full_url, timeout))
        return self.resp


def payload():
    return json.dumps({"success": True, "pager": {"current_page": 1}, "data": [
        {"id": 901, "homeID": 10, "awayID": 20, "competition_id": 1625,
         "date_unix": 1537056000, "status": "complete",
         "homeGoalCount": 1, "awayGoalCount": 2, "team_a_corners": 3, "team_b_corners": 4}
    ]}).encode()


class PublicDemoTests(unittest.TestCase):
    @staticmethod
    def clock():
        return datetime(2026, 10, 11, tzinfo=timezone.utc)

    def test_one_request_and_no_authorization(self):
        opener = Opener(Response(payload()))
        report = fetch_example(opener=opener, clock=self.clock)
        self.assertEqual(opener.count, 1)
        self.assertEqual(opener.requests[0][1], 10)
        self.assertIn("season_id=1625", opener.requests[0][0])
        self.assertIn("key=example", opener.requests[0][0])
        self.assertEqual(report["fixture_count"], 1)
        self.assertFalse(report["training_allowed"])
        self.assertFalse(report["monetary_permission"])
        self.assertNotIn("records", report)

    def test_reject_html(self):
        with self.assertRaises(ValueError):
            fetch_example(opener=Opener(Response(payload(), "text/html")), clock=self.clock)

    def test_reject_large(self):
        with self.assertRaises(ValueError):
            fetch_example(opener=Opener(Response(b"x" * (MAX_BYTES + 1))), clock=self.clock)

    def test_reject_malformed_json(self):
        with self.assertRaises(ValueError):
            fetch_example(opener=Opener(Response(b"not json")), clock=self.clock)


if __name__ == "__main__":
    unittest.main()
