"""Experimental, read-only Stake sportsbook snapshot bridge.

Stake's official public API documents x-access-token authentication, but the
sportsbook GraphQL schema used by the website is not part of that stable public
contract. This module therefore stays research-only: it fetches raw market
names/outcomes after a probability seal and never creates executable quotes or
places wagers.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from .contracts import digest, number, time
from .credentials import credential
from .odds_provider import require_prematch_seal
from .provider_transport import NoRedirect


HOST = "stake.com"
ENDPOINT = "/_api/graphql"
MAX_RESPONSE = 4_000_000
MAX_EVENTS = 100

SPORTS_EVENTS_QUERY = """query SportsEvents($first: Int, $sportSlug: String) {
  sportsEvents(first: $first, sportSlug: $sportSlug) {
    edges {
      node {
        id
        name
        startTime
        sport { name slug }
        league { name slug }
        competitors { name }
        markets {
          name
          outcomes { name odds }
        }
      }
    }
  }
}"""


def _token():
    return credential("STAKE_API_TOKEN")


def _post_graphql(query, variables, *, token=None, opener=None):
    if not isinstance(query, str) or not query.strip():
        raise ValueError("stake GraphQL query required")
    if not isinstance(variables, dict):
        raise ValueError("stake GraphQL variables must be an object")
    secret = token or _token()
    body = json.dumps(
        {"query": query, "variables": variables, "operationName": "SportsEvents"},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    request = Request(
        "https://" + HOST + ENDPOINT,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "x-access-token": secret,
            "User-Agent": "SEFIROT/2.4.2 research-read-only",
        },
    )
    client = opener or build_opener(NoRedirect())
    started = datetime.now(timezone.utc).isoformat()
    try:
        response = client.open(request, timeout=15)
        try:
            status = int(getattr(response, "status", 200))
            if status != 200:
                raise ValueError(f"stake provider HTTP {status}; PASS")
            raw = response.read(MAX_RESPONSE + 1)
        finally:
            close = getattr(response, "close", None)
            if close:
                close()
    except HTTPError as exc:
        # Never include response bodies/request headers in errors: they can
        # contain account-specific data and the request carries a credential.
        raise ValueError(f"stake provider HTTP {int(exc.code)}; PASS") from None
    except (URLError, OSError, ValueError) as exc:
        if isinstance(exc, ValueError) and str(exc).startswith("stake provider HTTP"):
            raise
        raise ValueError("stake provider network error; PASS") from None
    if len(raw) > MAX_RESPONSE:
        raise ValueError("stake provider response exceeds limit; PASS")
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("stake provider returned invalid JSON; PASS") from None
    if not isinstance(payload, dict) or payload.get("errors"):
        raise ValueError("stake sportsbook GraphQL unavailable or changed; PASS")
    return {
        "data": payload,
        "receipt": {
            "provider": "STAKE_GRAPHQL_EXPERIMENTAL",
            "provider_host": HOST,
            "endpoint": ENDPOINT,
            "request_started_at": started,
            "received_at": datetime.now(timezone.utc).isoformat(),
            "payload_hash": digest(payload),
            "http_status": 200,
            "credential_exposed": False,
            "monetary_permission": False,
        },
    }


def sports_events(*, first=50, sport_slug="football", token=None, opener=None):
    if not isinstance(first, int) or not 1 <= first <= MAX_EVENTS:
        raise ValueError("stake event limit must be between 1 and 100")
    if not isinstance(sport_slug, str) or not sport_slug or len(sport_slug) > 64:
        raise ValueError("invalid stake sport slug")
    packet = _post_graphql(
        SPORTS_EVENTS_QUERY,
        {"first": first, "sportSlug": sport_slug},
        token=token,
        opener=opener,
    )
    try:
        edges = packet["data"]["data"]["sportsEvents"]["edges"]
    except (KeyError, TypeError):
        raise ValueError("stake sports event payload shape changed; PASS") from None
    if not isinstance(edges, list) or len(edges) > first:
        raise ValueError("stake sports event list malformed; PASS")
    events = []
    for edge in edges:
        if not isinstance(edge, dict) or not isinstance(edge.get("node"), dict):
            raise ValueError("stake sports event edge malformed; PASS")
        events.append(edge["node"])
    return {"events": events, "receipt": packet["receipt"]}


def exact_event(events, prediction, received_at):
    """Match a sealed fixture exactly; never fuzzy-match or swap competitors."""
    match = require_prematch_seal(prediction, received_at)
    if not isinstance(events, list):
        raise ValueError("stake events must be a list")
    found = []
    for event in events:
        if not isinstance(event, dict):
            continue
        competitors = event.get("competitors")
        if not isinstance(competitors, list) or len(competitors) != 2:
            continue
        names = [row.get("name") if isinstance(row, dict) else None for row in competitors]
        try:
            if names != [match["home"], match["away"]]:
                continue
            if time(event.get("startTime")) != time(match["kickoff"]):
                continue
            event_id = event.get("id")
            if not isinstance(event_id, str) or not 1 <= len(event_id) <= 200:
                continue
            found.append(event)
        except (ValueError, TypeError, KeyError):
            continue
    if len(found) != 1:
        raise ValueError("fixture missing or ambiguous in Stake provider; PASS")
    return found[0]


def research_snapshot(event, prediction, received_at, retrieval_receipt=None):
    """Return raw names/odds only; do not guess Stake market semantics."""
    match = require_prematch_seal(prediction, received_at)
    if not isinstance(event, dict):
        raise ValueError("stake event required")
    competitors = event.get("competitors")
    names = [row.get("name") if isinstance(row, dict) else None for row in competitors or []]
    if names != [match["home"], match["away"]] or time(event.get("startTime")) != time(match["kickoff"]):
        raise ValueError("stake fixture mismatch; PASS")
    markets = event.get("markets")
    if not isinstance(markets, list) or len(markets) > 1000:
        raise ValueError("stake markets malformed; PASS")
    normalized = []
    for market in markets:
        if not isinstance(market, dict) or not isinstance(market.get("name"), str):
            raise ValueError("stake market malformed; PASS")
        outcomes = market.get("outcomes")
        if not isinstance(outcomes, list) or not outcomes or len(outcomes) > 512:
            raise ValueError("stake market outcomes malformed; PASS")
        rows = []
        seen = set()
        for outcome in outcomes:
            if not isinstance(outcome, dict) or not isinstance(outcome.get("name"), str):
                raise ValueError("stake outcome malformed; PASS")
            name = outcome["name"]
            if name in seen:
                raise ValueError("duplicate Stake outcome name; PASS")
            seen.add(name)
            rows.append({"name": name, "odds": number(outcome.get("odds"), "Stake decimal odds", 1.00000001, 10000)})
        normalized.append({"name": market["name"], "outcomes": rows})
    received = time(received_at).isoformat()
    report = {
        "provider": "STAKE_GRAPHQL_EXPERIMENTAL",
        "status": "RESEARCH_ONLY",
        "fixture_id": match["id"],
        "stake_event_id": event.get("id"),
        "home": match["home"],
        "away": match["away"],
        "kickoff": match["kickoff"],
        "received_at": received,
        "provider_market_timestamp": None,
        "freshness": "RECEIPT_TIME_ONLY",
        "normalization": "RAW_STAKE_NAMES_ONLY",
        "markets": normalized,
        "market_count": len(normalized),
        "payload_hash": digest(event),
        "monetary_permission": False,
        "execution_enabled": False,
    }
    if retrieval_receipt:
        safe = dict(retrieval_receipt)
        safe.pop("credential", None)
        report["retrieval_receipt"] = safe
    report["hash"] = digest(report)
    return report
