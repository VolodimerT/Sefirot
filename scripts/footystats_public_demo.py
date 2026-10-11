"""One-shot FootyStats public example-key smoke, opt-in, no account or paid plan.

Uses only season=1625 demo league-matches, first page, bounded response. Never
calls private SEFIROT services or credentials, never authenticates pregame time.
"""
from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import build_opener, HTTPRedirectHandler, Request

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.provider_compare.footystats import inspect

URL = "https://api.football-data-api.com/league-matches"
MAX_BYTES = 10 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("provider redirect blocked")


def fetch_example(*, opener=None, clock=None):
    """Perform exactly one public HTTPS request, without retries or private keys."""
    opener = opener or build_opener(NoRedirect())
    clock = clock or (lambda: datetime.now(timezone.utc))
    # Public documentation's published demo; not a private account credential.
    query = urlencode({"key": "example", "season_id": "1625", "page": "1"})
    request = Request(URL + "?" + query, headers={"Accept": "application/json", "User-Agent": "SEFIROT-Research-Demo/1"})
    try:
        with opener.open(request, timeout=10) as response:
            if response.status != 200:
                raise ValueError("unexpected provider HTTP status")
            if response.headers.get_content_type() != "application/json":
                raise ValueError("unexpected provider content type")
            body = response.read(MAX_BYTES + 1)
            received = clock().astimezone(timezone.utc).isoformat()
            if len(body) > MAX_BYTES:
                raise ValueError("provider payload too large")
    except HTTPError as exc:
        raise ValueError("provider HTTP " + str(exc.code)) from None
    except URLError:
        raise ValueError("provider connection unavailable") from None
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, ValueError):
        raise ValueError("provider JSON invalid") from None
    report = inspect(payload, season_id=1625, received_at=received, expected_page=1)
    # Exclude full raw data; do not leak accidental odds/player fields.
    return {k: v for k, v in report.items() if k != "records"}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True, help="new local JSON report; no overwrite")
    p.add_argument("--execute-public-demo-request", action="store_true",
                   help="explicit opt-in to one free public demo query")
    args = p.parse_args(argv)
    if not args.execute_public_demo_request:
        p.error("must explicitly opt in to public request")
    try:
        report = fetch_example()
        with args.output.open("x", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.write("\n")
        print(json.dumps({"status": report["status"], "count": report["fixture_count"],
                          "training_allowed": False}))
    except (ValueError, OSError, TypeError) as exc:
        p.exit(2, str(exc) + "\n")


if __name__ == "__main__":
    main()
