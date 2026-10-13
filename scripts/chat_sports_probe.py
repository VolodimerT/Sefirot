"""Read-only, bounded API-Football research for fixture and small-market evidence.

The key is resolved inside the existing protected Render -> Supabase gateway,
never through chat jobs. Source observations are not a calibrated market model.
"""
from __future__ import annotations

import re
from sefirot.football_gateway import get_sports, transport_status
from sefirot.football_provider import FootballRequestError, status_summary

MAX_QUERIES = 8
STAT_TYPES = {
    "Total Shots", "Shots on Goal", "Shots off Goal", "Blocked Shots",
    "Shots insidebox", "Shots outsidebox", "Corner Kicks", "Yellow Cards",
    "Red Cards", "Fouls", "Offsides", "Ball Possession", "Expected Goals",
    "Total passes", "Passes accurate", "Passes %", "Goalkeeper Saves",
}
ENDPOINTS = {"status", "fixtures", "fixtures/statistics", "fixtures/lineups"}
IDENTIFIER = re.compile(r"^[1-9][0-9]{0,9}$")
DATE = re.compile(r"^20[0-9]{2}-[01][0-9]-[0-3][0-9]$")


def _positive(value):
    return type(value) is int and 1 <= value <= 2_147_483_647


def _query(q):
    if not isinstance(q, dict) or set(q) != {"endpoint", "params"}:
        raise ValueError("PROBE_QUERY_SHAPE")
    endpoint, params = q["endpoint"], q["params"]
    if endpoint not in ENDPOINTS or not isinstance(params, dict):
        raise ValueError("PROBE_ENDPOINT_NOT_ALLOWED")
    if endpoint == "status":
        if params:
            raise ValueError("PROBE_STATUS_PARAMS")
        return endpoint, {}
    if endpoint == "fixtures":
        keys = set(params)
        allowed = ({"id"}, {"date", "league", "season"}, {"team", "last"},
                   {"league", "season"})
        if keys not in allowed:
            raise ValueError("PROBE_FIXTURES_FILTERS")
        if "date" in params and (not isinstance(params["date"], str) or
                                 not DATE.fullmatch(params["date"])):
            raise ValueError("PROBE_DATE")
        for k in keys - {"date"}:
            if not _positive(params[k]):
                raise ValueError("PROBE_IDENTIFIER")
        if params.get("last", 0) > 10 or params.get("season", 2026) < 2024:
            raise ValueError("PROBE_UNBOUNDED_HISTORY")
    else:
        keys = set(params)
        if endpoint == "fixtures/statistics":
            if keys not in ({"fixture"}, {"fixture", "half"}):
                raise ValueError("PROBE_FIXTURE_FILTERS")
            if "half" in params and (type(params["half"]) is not int or params["half"] not in (1, 2)):
                raise ValueError("PROBE_HALF_REQUIRED")
        elif keys != {"fixture"}:
            raise ValueError("PROBE_FIXTURE_FILTERS")
        if not _positive(params["fixture"]):
            raise ValueError("PROBE_FIXTURE_REQUIRED")
    return endpoint, params


def _compact_row(row):
    fixture, league, teams = row.get("fixture") or {}, row.get("league") or {}, row.get("teams") or {}
    if not isinstance(fixture, dict) or not isinstance(teams, dict):
        raise ValueError("PROBE_MALFORMED_FIXTURE")
    return {
        "id": fixture.get("id"), "kickoff": fixture.get("date"),
        "status": (fixture.get("status") or {}).get("short"),
        "league": {key: league.get(key) for key in ("id", "name", "season")},
        "home": {key: (teams.get("home") or {}).get(key) for key in ("id", "name")},
        "away": {key: (teams.get("away") or {}).get(key) for key in ("id", "name")},
        "fulltime": (row.get("score") or {}).get("fulltime"),
    }


def _compact_stats(row):
    team = row.get("team") or {}
    records = row.get("statistics") or []
    if not isinstance(team, dict) or not isinstance(records, list):
        raise ValueError("PROBE_MALFORMED_STATISTICS")
    return {
        "team": {key: team.get(key) for key in ("id", "name")},
        "statistics": {r["type"]: r.get("value") for r in records
                       if isinstance(r, dict) and r.get("type") in STAT_TYPES},
    }


def _compact_lineup(row):
    team = row.get("team") or {}
    return {
        "team": {key: team.get(key) for key in ("id", "name")},
        "formation": row.get("formation"),
        "coach": (row.get("coach") or {}).get("name"),
        "starting_xi_count": len(row.get("startXI") or []),
        "substitutes_count": len(row.get("substitutes") or []),
    }


def collect(payload):
    if not isinstance(payload, dict) or set(payload) != {"queries"}:
        raise ValueError("PROBE_REQUEST_SHAPE")
    queries = payload["queries"]
    if not isinstance(queries, list) or not 1 <= len(queries) <= MAX_QUERIES:
        raise ValueError("PROBE_QUERY_LIMIT")
    validated = [_query(q) for q in queries]  # reject whole batch before network
    output = []
    for endpoint, params in validated:
        try:
            packet = get_sports(endpoint, params)
        except (ValueError, OSError, FootballRequestError) as exc:
            reason = getattr(exc, "code", "PROVIDER_TRANSPORT_OR_AUTH_UNAVAILABLE")
            output.append({"endpoint": endpoint, "params": params,
                           "status": "ERROR", "reason": reason})
            # Do not waste daily API quota or repeatedly hit rejected auth.
            break
        receipt = packet["receipt"]
        if endpoint == "status":
            result = status_summary(packet)
            rows = result
            count = 1
        else:
            response = packet["data"]["response"]
            if not isinstance(response, list) or len(response) > 100:
                raise ValueError("PROBE_RESPONSE_TOO_LARGE")
            mapper = {
                "fixtures": _compact_row,
                "fixtures/statistics": _compact_stats,
                "fixtures/lineups": _compact_lineup,
            }[endpoint]
            rows = [mapper(row) for row in response]
            count = len(rows)
        output.append({
            "endpoint": endpoint, "params": params, "status": "DONE",
            "count": count, "rows": rows,
            "receipt": {
                key: receipt.get(key) for key in (
                    "provider", "provider_host", "endpoint", "parameters",
                    "received_at", "payload_hash", "http_status", "transport", "quota"
                ) if key in receipt
            },
        })
    return {
        "stage": "SPORTS_API_PROBE", "provider": "API_FOOTBALL_V3",
        "mode": "RESEARCH_ONLY", "transport_status": transport_status(),
        "queries": output, "monetary_permission": False,
        "automatic_execution": False, "execution_enabled": False,
        "model_calibrated": False,
    }
