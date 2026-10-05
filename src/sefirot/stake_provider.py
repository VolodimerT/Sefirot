"""Experimental, read-only Stake sportsbook snapshot bridge.

This provider uses the current Stake web GraphQL contract discovered from the
sportsbook frontend. The contract is not part of Stake's stable public API, so
all output remains research-only and fail-closed.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener

from .contracts import digest, number, time
from .credentials import credential
from .odds_provider import require_prematch_seal
from .provider_transport import NoRedirect


HOST = "stake.com"
ENDPOINT = "/_api/graphql"
MAX_RESPONSE = 8_000_000
MAX_EVENTS = 200

SPORT_TOURNAMENT_FIXTURE_LIST_QUERY = """query SportTournamentFixtureList(
  $sport: String!, $tournamentLimit: Int = 50,
  $fixtureCountLimit: Int = 50, $type: SportSearchEnum!
) {
  slugSport(sport: $sport) {
    id name slug
    tournamentList(type: $type, limit: $tournamentLimit) {
      id name slug
      category { id name slug sport { id name slug } }
      fixtureList(type: $type, limit: $fixtureCountLimit) {
        id status slug name provider extId
        data {
          __typename
          ... on SportFixtureDataMatch {
            startTime
            competitors { name defaultName extId countryCode abbreviation }
            teams { name qualifier }
          }
          ... on SportFixtureDataOutright { name startTime endTime }
        }
      }
    }
  }
}"""

FIXTURE_GROUPS_QUERY = """query FixtureIndexGroups($fixture: String!) {
  slugFixture(fixture: $fixture) {
    id
    groups { id name translation rank }
  }
}"""

FIXTURE_MARKETS_QUERY = """query FixtureGroupMarkets(
  $fixture: String!, $groups: [String!]!
) {
  slugFixture(fixture: $fixture) {
    id
    groups(groups: $groups) {
      id name translation rank
      templates(includeEmpty: false, limit: 50) {
        id extId rank name
        markets(limit: 50) {
          id name status extId specifiers customBetAvailable provider
          outcomes { id active odds name customBetAvailable }
        }
      }
    }
  }
}"""


def _token():
    return credential("STAKE_API_TOKEN")


def _post_graphql(query, variables, *, token=None, opener=None, operation_name):
    if not isinstance(query, str) or not query.strip():
        raise ValueError("stake GraphQL query required")
    if not isinstance(variables, dict):
        raise ValueError("stake GraphQL variables must be an object")
    if not isinstance(operation_name, str) or not operation_name:
        raise ValueError("stake GraphQL operation name required")
    secret = token or _token()
    body = json.dumps(
        {"query": query, "variables": variables, "operationName": operation_name},
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
            "x-apollo-operation-name": operation_name,
            "apollo-require-preflight": "true",
            "Origin": "https://stake.com",
            "Referer": "https://stake.com/sports",
            "User-Agent": "Mozilla/5.0 SEFIROT/2.4.2 research-read-only",
        },
    )
    client = opener or build_opener(NoRedirect())
    started = datetime.now(timezone.utc).isoformat()
    try:
        response = client.open(request, timeout=20)
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
        detail = ""
        if os.environ.get("SEFIROT_STAKE_DEBUG_ERRORS") == "1":
            try:
                raw_error = exc.read(8192).decode("utf-8", "replace").replace(secret, "[REDACTED]")
                parsed = json.loads(raw_error)
                messages = []
                if isinstance(parsed, dict):
                    for row in parsed.get("errors", [])[:8]:
                        if isinstance(row, dict) and isinstance(row.get("message"), str):
                            messages.append(row["message"][:500])
                if messages:
                    detail = " | " + " ; ".join(messages)
                elif raw_error:
                    detail = " | body=" + raw_error[:500].replace("\n", " ")
            except Exception:
                detail = ""
        raise ValueError(f"stake provider HTTP {int(exc.code)}; PASS{detail}") from None
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
    if not isinstance(payload, dict):
        raise ValueError("stake provider returned invalid object; PASS")
    if payload.get("errors"):
        detail = ""
        if os.environ.get("SEFIROT_STAKE_DEBUG_ERRORS") == "1":
            detail = " | " + " ; ".join(
                str(row.get("message", ""))[:500]
                for row in payload.get("errors", [])[:8] if isinstance(row, dict)
            )
        raise ValueError("stake sportsbook GraphQL unavailable or changed; PASS" + detail)
    return {
        "data": payload,
        "receipt": {
            "provider": "STAKE_GRAPHQL_EXPERIMENTAL",
            "provider_host": HOST,
            "endpoint": ENDPOINT,
            "operation_name": operation_name,
            "request_started_at": started,
            "received_at": datetime.now(timezone.utc).isoformat(),
            "payload_hash": digest(payload),
            "http_status": 200,
            "credential_exposed": False,
            "monetary_permission": False,
        },
    }


def _sport_slug(value):
    if not isinstance(value, str) or not value or len(value) > 64:
        raise ValueError("invalid stake sport slug")
    value = value.strip().lower()
    return "soccer" if value in {"football", "soccer"} else value


def sports_events(*, first=50, sport_slug="soccer", match_type="active", token=None, opener=None):
    if not isinstance(first, int) or not 1 <= first <= MAX_EVENTS:
        raise ValueError("stake event limit must be between 1 and 200")
    sport = _sport_slug(sport_slug)
    if match_type not in {"active", "live", "upcoming"}:
        raise ValueError("invalid Stake match type")
    # Split the global event cap across tournaments. This endpoint itself is
    # tournament-oriented; exact fixture matching happens after flattening.
    fixture_limit = min(50, max(10, first))
    tournament_limit = min(100, max(10, (first + fixture_limit - 1) // fixture_limit * 10))
    packet = _post_graphql(
        SPORT_TOURNAMENT_FIXTURE_LIST_QUERY,
        {
            "sport": sport,
            "type": match_type,
            "tournamentLimit": tournament_limit,
            "fixtureCountLimit": fixture_limit,
        },
        token=token,
        opener=opener,
        operation_name="SportTournamentFixtureList",
    )
    try:
        root = packet["data"]["data"]["slugSport"]
        tournaments = root["tournamentList"]
    except (KeyError, TypeError):
        raise ValueError("stake sport fixture payload shape changed; PASS") from None
    if not isinstance(root, dict) or not isinstance(tournaments, list):
        raise ValueError("stake sport fixture payload malformed; PASS")
    events = []
    for tournament in tournaments:
        if not isinstance(tournament, dict):
            continue
        category = tournament.get("category") or {}
        fixtures = tournament.get("fixtureList") or []
        if not isinstance(fixtures, list):
            raise ValueError("stake fixture list malformed; PASS")
        for fixture in fixtures:
            if not isinstance(fixture, dict):
                continue
            data = fixture.get("data") or {}
            competitors = data.get("competitors") or []
            if len(competitors) != 2:
                continue
            event = {
                "id": fixture.get("id"),
                "slug": fixture.get("slug"),
                "name": fixture.get("name"),
                "status": fixture.get("status"),
                "provider": fixture.get("provider"),
                "extId": fixture.get("extId"),
                "startTime": data.get("startTime"),
                "competitors": competitors,
                "teams": data.get("teams") or [],
                "sport": {"id": root.get("id"), "name": root.get("name"), "slug": root.get("slug")},
                "league": {
                    "id": tournament.get("id"),
                    "name": tournament.get("name"),
                    "slug": tournament.get("slug"),
                    "category": category,
                },
            }
            events.append(event)
            if len(events) >= first:
                return {"events": events, "receipt": packet["receipt"]}
    return {"events": events, "receipt": packet["receipt"]}


def fixture_groups(fixture_slug, *, token=None, opener=None):
    if not isinstance(fixture_slug, str) or not fixture_slug or len(fixture_slug) > 300:
        raise ValueError("invalid Stake fixture slug")
    packet = _post_graphql(
        FIXTURE_GROUPS_QUERY,
        {"fixture": fixture_slug},
        token=token,
        opener=opener,
        operation_name="FixtureIndexGroups",
    )
    try:
        fixture = packet["data"]["data"]["slugFixture"]
    except (KeyError, TypeError):
        raise ValueError("stake fixture group payload shape changed; PASS") from None
    if not isinstance(fixture, dict):
        raise ValueError("stake fixture missing; PASS")
    groups = fixture.get("groups") or []
    if not isinstance(groups, list) or len(groups) > 500:
        raise ValueError("stake fixture groups malformed; PASS")
    names = []
    meta = []
    seen = set()
    for row in groups:
        if not isinstance(row, dict) or not isinstance(row.get("name"), str):
            continue
        name = row["name"]
        if name in seen:
            continue
        seen.add(name)
        names.append(name)
        meta.append({
            "id": row.get("id"), "name": name,
            "translation": row.get("translation"), "rank": row.get("rank"),
        })
    return {
        "fixture_id": fixture.get("id"),
        "groups": meta,
        "group_names": names,
        "receipt": packet["receipt"],
    }


def fixture_markets(fixture_slug, *, groups=None, token=None, opener=None):
    if groups is None:
        group_packet = fixture_groups(fixture_slug, token=token, opener=opener)
        groups = group_packet["group_names"]
    if not isinstance(groups, list) or not all(isinstance(x, str) and x for x in groups):
        raise ValueError("invalid Stake market group list")
    if len(groups) > 500:
        raise ValueError("too many Stake market groups")
    markets = []
    receipts = []
    # Chunk to keep single-fixture GraphQL responses bounded.
    for offset in range(0, len(groups), 8):
        chunk = groups[offset:offset + 8]
        packet = _post_graphql(
            FIXTURE_MARKETS_QUERY,
            {"fixture": fixture_slug, "groups": chunk},
            token=token,
            opener=opener,
            operation_name="FixtureGroupMarkets",
        )
        receipts.append(packet["receipt"])
        try:
            fixture = packet["data"]["data"]["slugFixture"]
        except (KeyError, TypeError):
            raise ValueError("stake fixture market payload shape changed; PASS") from None
        if not isinstance(fixture, dict):
            raise ValueError("stake fixture market payload missing; PASS")
        returned_groups = fixture.get("groups") or []
        if not isinstance(returned_groups, list):
            raise ValueError("stake fixture market groups malformed; PASS")
        for group in returned_groups:
            if not isinstance(group, dict):
                continue
            templates = group.get("templates") or []
            if not isinstance(templates, list):
                raise ValueError("stake fixture templates malformed; PASS")
            for template in templates:
                if not isinstance(template, dict):
                    continue
                rows = template.get("markets") or []
                if not isinstance(rows, list):
                    raise ValueError("stake market list malformed; PASS")
                for market in rows:
                    if not isinstance(market, dict) or not isinstance(market.get("name"), str):
                        continue
                    outcomes = market.get("outcomes") or []
                    if not isinstance(outcomes, list) or not outcomes:
                        continue
                    parsed_outcomes = []
                    for outcome in outcomes:
                        if not isinstance(outcome, dict) or not isinstance(outcome.get("name"), str):
                            continue
                        parsed_outcomes.append({
                            "id": outcome.get("id"),
                            "name": outcome.get("name"),
                            "odds": number(outcome.get("odds"), "Stake decimal odds", 1.00000001, 10000),
                            "active": outcome.get("active"),
                            "customBetAvailable": outcome.get("customBetAvailable"),
                        })
                    if not parsed_outcomes:
                        continue
                    markets.append({
                        "id": market.get("id"),
                        "name": market["name"],
                        "status": market.get("status"),
                        "extId": market.get("extId"),
                        "specifiers": market.get("specifiers"),
                        "customBetAvailable": market.get("customBetAvailable"),
                        "provider": market.get("provider"),
                        "group": group.get("name"),
                        "group_translation": group.get("translation"),
                        "template": template.get("name"),
                        "template_ext_id": template.get("extId"),
                        "outcomes": parsed_outcomes,
                    })
    return {
        "fixture_slug": fixture_slug,
        "markets": markets,
        "market_count": len(markets),
        "receipts": receipts,
    }


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
            if not isinstance(event.get("id"), str) or not isinstance(event.get("slug"), str):
                continue
            found.append(event)
        except (ValueError, TypeError, KeyError):
            continue
    if len(found) != 1:
        raise ValueError("fixture missing or ambiguous in Stake provider; PASS")
    return found[0]


def research_snapshot(event, prediction, received_at, markets, retrieval_receipts=None):
    """Return raw Stake market names/odds only; never infer settlement semantics."""
    match = require_prematch_seal(prediction, received_at)
    if not isinstance(event, dict):
        raise ValueError("stake event required")
    competitors = event.get("competitors")
    names = [row.get("name") if isinstance(row, dict) else None for row in competitors or []]
    if names != [match["home"], match["away"]] or time(event.get("startTime")) != time(match["kickoff"]):
        raise ValueError("stake fixture mismatch; PASS")
    if not isinstance(markets, list) or len(markets) > 5000:
        raise ValueError("stake markets malformed; PASS")
    received = time(received_at).isoformat()
    report = {
        "provider": "STAKE_GRAPHQL_EXPERIMENTAL",
        "status": "RESEARCH_ONLY",
        "fixture_id": match["id"],
        "stake_event_id": event.get("id"),
        "stake_fixture_slug": event.get("slug"),
        "home": match["home"],
        "away": match["away"],
        "kickoff": match["kickoff"],
        "received_at": received,
        "provider_market_timestamp": None,
        "freshness": "RECEIPT_TIME_ONLY",
        "normalization": "RAW_STAKE_NAMES_ONLY",
        "markets": markets,
        "market_count": len(markets),
        "payload_hash": digest({"event": event, "markets": markets}),
        "monetary_permission": False,
        "execution_enabled": False,
    }
    if retrieval_receipts:
        report["retrieval_receipts"] = [
            {k: v for k, v in row.items() if k != "credential"}
            for row in retrieval_receipts
        ]
    report["hash"] = digest(report)
    return report


def _boot_probe_if_requested():
    if os.environ.get("SEFIROT_STAKE_BOOT_PROBE") != "1":
        return
    auth_ok = None
    try:
        auth = _post_graphql(
            "query UserIdentity { user { id } }", {},
            operation_name="UserIdentity",
        )
        auth_ok = bool(((auth.get("data") or {}).get("data") or {}).get("user"))
        packet = sports_events(first=200, sport_slug="soccer", match_type="active")
        targets = (
            "italy - turkiye", "france - belgium", "romania - sweden",
            "montenegro - armenia", "cyprus - latvia",
            "northern ireland - georgia", "ukraine - hungary", "bosnia and herzegovina - poland",
        )
        matches = []
        for event in packet["events"]:
            event_name = str(event.get("name", "")).lower()
            if not any(target in event_name for target in targets):
                continue
            row = {
                "id": event.get("id"), "slug": event.get("slug"),
                "name": event.get("name"), "startTime": event.get("startTime"),
                "league": (event.get("league") or {}).get("name"),
            }
            if event.get("slug"):
                groups = fixture_groups(event["slug"])
                mp = fixture_markets(event["slug"], groups=groups["group_names"])
                selected = []
                for market in mp["markets"]:
                    template = str(market.get("template", ""))
                    name = str(market.get("name", ""))
                    spec = str(market.get("specifiers", ""))
                    keep = False
                    if template in ("1x2", "Draw No Bet", "Both Teams to Score", "Double Chance"):
                        keep = True
                    elif template == "Asian Total" and spec in ("total=2.5","total=3","total=3.5"):
                        keep = True
                    elif template == "Asian Handicap" and spec in (
                        "hcp=-1.5","hcp=-1.25","hcp=-1","hcp=-0.75","hcp=-0.5",
                        "hcp=0","hcp=0.5","hcp=0.75","hcp=1","hcp=1.25","hcp=1.5"
                    ):
                        keep = True
                    elif template in ("Total Corners", "1st Half - Total Corners",
                                      "Total Cards", "1st Half - Total Cards"):
                        keep = True
                    elif "shots" in (template + " " + name).lower():
                        keep = True
                    elif "corner range" in (template + " " + name).lower():
                        keep = True
                    if keep:
                        selected.append({
                            "group": market.get("group"),
                            "template": template,
                            "name": name,
                            "specifiers": market.get("specifiers"),
                            "outcomes": [
                                {"name": o.get("name"), "odds": o.get("odds")}
                                for o in (market.get("outcomes") or [])
                            ],
                        })
                row["group_count"] = len(groups["group_names"])
                row["market_count"] = mp["market_count"]
                row["markets"] = selected[:180]
            matches.append(row)
        print("SEFIROT_STAKE_BOOT_PROBE=" + json.dumps({
            "status": "OK",
            "auth_user_present": auth_ok,
            "event_count": len(packet["events"]),
            "matches": matches,
            "receipt": packet["receipt"],
        }, ensure_ascii=True, separators=(",", ":")), flush=True)
    except Exception as exc:
        print("SEFIROT_STAKE_BOOT_PROBE=" + json.dumps({
            "status": "FAILED", "auth_user_present": auth_ok, "error": str(exc)
        }, ensure_ascii=True, separators=(",", ":")), flush=True)


_boot_probe_if_requested()
