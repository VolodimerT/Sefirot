"""Read-only, bounded API-Football research for fixture and small-market evidence.

The key is resolved inside the existing protected Render -> Supabase gateway,
never through chat jobs. Source observations are not a calibrated market model.
"""
from __future__ import annotations

import re
import copy
from math import isfinite
from datetime import date
from hashlib import sha256
from pathlib import Path
from sefirot.contracts import canonical, digest, time
from sefirot.provider_transport import QUOTA_HEADERS
from sefirot.football_gateway import get_sports, transport_status
from sefirot.football_provider import FootballRequestError, status_summary

MAX_QUERIES = 8
MAX_ARCHIVE_BYTES = 128 * 1024  # Per job, inside the existing 850 KB queue cap.
SOURCE_SCHEMA = "guarded-probe-evidence-v1"
RECEIPT_FIELDS = ("provider", "provider_host", "endpoint", "parameters",
                  "request_started_at", "received_at", "upstream_received_at",
                  "payload_hash", "http_status", "transport", "quota")
STAT_TYPES = {
    "Total Shots", "Shots on Goal", "Shots off Goal", "Blocked Shots",
    "Shots insidebox", "Shots outsidebox", "Corner Kicks", "Yellow Cards",
    "Red Cards", "Fouls", "Offsides", "Ball Possession", "Expected Goals",
    "Total passes", "Passes accurate", "Passes %", "Goalkeeper Saves",
}
ENDPOINTS = {"status", "fixtures", "fixtures/statistics", "fixtures/lineups"}
IDENTIFIER = re.compile(r"^[1-9][0-9]{0,9}$")
DATE = re.compile(r"^20[0-9]{2}-[01][0-9]-[0-3][0-9]$")


class ProbeError(ValueError):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def _safe_receipt(receipt):
    result = {key: copy.deepcopy(receipt[key]) for key in RECEIPT_FIELDS if key in receipt}
    if "quota" in result:
        quota = result["quota"]
        result["quota"] = {key: value for key, value in quota.items()
                           if key in QUOTA_HEADERS and isinstance(value, str) and re.fullmatch(r"[0-9]{1,12}", value)} if isinstance(quota, dict) else {}
    return result


def _safe_source(data, endpoint):
    if not isinstance(data, dict) or set(data)-{"get", "parameters", "errors", "results", "paging", "response"}:
        return False
    if endpoint == "status":
        response = data.get("response")
        if not isinstance(response, dict) or set(response)-{"subscription", "requests"}: return False
    if endpoint == "fixtures/statistics":
        response = data.get("response")
        if not isinstance(response, list): return False
        for row in response:
            if not isinstance(row, dict) or not isinstance(row.get("statistics"), list): return False
            if any(not isinstance(r, dict) or r.get("type") not in STAT_TYPES for r in row["statistics"]):
                return False
    pending = [(data, 0)]
    while pending:
        value, depth = pending.pop()
        if depth > 24: return False
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str): return False
                label = re.sub(r"[^a-z0-9]", "", key.lower())
                if label in {"apikey", "authorization", "password", "headers"} or "secret" in label or "token" in label:
                    return False
                pending.append((item, depth+1))
        elif isinstance(value, list): pending.extend((v, depth+1) for v in value)
    return True


def verify_evidence(query):
    """Read-only content binding, never provider attestation or model promotion."""
    base = {"provider_origin_attested": False, "model_fit_eligible": False,
            "original_http_bytes_available": False, "monetary_permission": False}
    source = query.get("source_packet") if isinstance(query, dict) else None
    if not isinstance(source, dict): return {**base, "status": "ORIGINAL_PACKET_UNAVAILABLE"}
    try:
        if digest(query["rows"]) != query["projection_hash"] or source["projection_hash"] != query["projection_hash"]:
            return {**base, "status": "PROJECTION_HASH_MISMATCH"}
        receipt = source["receipt"]
        if (source["schema"] != SOURCE_SCHEMA or receipt["provider"] != "API_FOOTBALL_V3"
                or receipt["provider_host"] != "v3.football.api-sports.io"
                or receipt["endpoint"] != "/"+query["endpoint"] or receipt["parameters"] != query["params"]
                or receipt != query["receipt"] or receipt["transport"] != "SUPABASE_GATEWAY"
                or type(receipt["http_status"]) is not int or receipt["http_status"] != 200):
            return {**base, "status": "SOURCE_IDENTITY_MISMATCH"}
        time(receipt["received_at"])
        if digest(source["data"]) != receipt["payload_hash"] or digest(source) != query["source_packet_hash"]:
            return {**base, "status": "SOURCE_HASH_MISMATCH"}
        if not _safe_source(source["data"], query["endpoint"]):
            return {**base, "status": "UNSAFE_SOURCE_PACKET"}
        return {**base, "status": "CANONICAL_PACKET_ARCHIVED", "source_format": "CANONICAL_GATEWAY_JSON"}
    except (ValueError, TypeError, KeyError, RecursionError):
        return {**base, "status": "INVALID_SOURCE_EVIDENCE"}


def _archive(query, packet, remaining):
    unavailable = {"status": "SOURCE_NOT_ARCHIVED", "provider_origin_attested": False,
                   "model_fit_eligible": False, "original_http_bytes_available": False,
                   "monetary_permission": False}
    data = packet.get("data")
    if not _safe_source(data, query["endpoint"]):
        query["source_evidence"] = {**unavailable, "reason": "SOURCE_SAFETY"}; return 0
    source = {"schema": SOURCE_SCHEMA, "data": data, "receipt": query["receipt"],
              "projection_hash": query["projection_hash"]}
    try:
        size = len(canonical(source).encode("utf-8"))
        if size > remaining:
            query["source_evidence"] = {**unavailable, "reason": "SOURCE_BYTE_BUDGET"}; return 0
        query["source_packet"] = copy.deepcopy(source)
        query["source_packet_hash"] = digest(source)
        verified = verify_evidence(query)
    except (ValueError, TypeError, RecursionError):
        verified = {"status": "INVALID_SOURCE_EVIDENCE"}
    if verified["status"] != "CANONICAL_PACKET_ARCHIVED":
        query.pop("source_packet", None); query.pop("source_packet_hash", None)
        query["source_evidence"] = {**unavailable, "reason": verified["status"]}; return 0
    query["source_evidence"] = verified
    return size


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
        if "date" in params:
            try: date.fromisoformat(params["date"])
            except ValueError: raise ValueError("PROBE_DATE") from None
        for k in keys - {"date"}:
            if not _positive(params[k]):
                raise ValueError("PROBE_IDENTIFIER")
        if params.get("last", 0) > 10 or params.get("season", 2026) < 2024:
            raise ValueError("PROBE_UNBOUNDED_HISTORY")
    else:
        if set(params) != {"fixture"} or not _positive(params["fixture"]):
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
    statistics = {}
    for record in records:
        if not isinstance(record, dict) or record.get("type") not in STAT_TYPES: continue
        kind, value = record["type"], record.get("value")
        if kind in statistics:
            raise ProbeError("PROBE_DUPLICATE_STATISTIC")
        if (value is not None and (type(value) not in (int, float, str)
                or isinstance(value, (int, float)) and not isfinite(value)
                or isinstance(value, str) and len(value) > 100)):
            raise ProbeError("PROBE_INVALID_STATISTIC_VALUE")
        statistics[kind] = value
    return {
        "team": {key: team.get(key) for key in ("id", "name")},
        "statistics": statistics,
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
    remaining = MAX_ARCHIVE_BYTES
    for endpoint, params in validated:
        try:
            packet = get_sports(endpoint, params, require_shared_budget=True)
            receipt = packet["receipt"]
            if endpoint == "status":
                rows = status_summary(packet)
                rows["receipt"] = _safe_receipt(receipt)
                count = 1
            else:
                response = packet["data"]["response"]
                if not isinstance(response, list) or len(response) > 100:
                    raise ProbeError("PROBE_RESPONSE_TOO_LARGE")
                mapper = {"fixtures": _compact_row, "fixtures/statistics": _compact_stats,
                          "fixtures/lineups": _compact_lineup}[endpoint]
                rows = [mapper(row) for row in response]
                count = len(rows)
                if endpoint == "fixtures" and "id" in params and rows and (len(rows) != 1 or rows[0]["id"] != params["id"]):
                    raise ProbeError("PROBE_FIXTURE_IDENTITY_MISMATCH")
        except (ValueError, OSError, FootballRequestError, TypeError, KeyError, AttributeError) as exc:
            reason = getattr(exc, "code", "PROVIDER_TRANSPORT_OR_AUTH_UNAVAILABLE")
            output.append({"endpoint": endpoint, "params": params,
                           "status": "ERROR", "reason": reason})
            # Do not waste daily API quota or repeatedly hit rejected auth.
            break
        item = {
            "endpoint": endpoint, "params": copy.deepcopy(params), "status": "DONE",
            "count": count, "rows": copy.deepcopy(rows),
            "receipt": _safe_receipt(receipt),
            "projection_hash": digest(rows),
        }
        remaining -= _archive(item, packet, remaining)
        output.append(item)
    return {
        "stage": "SPORTS_API_PROBE", "provider": "API_FOOTBALL_V3",
        "mode": "RESEARCH_ONLY", "transport_status": transport_status(),
        "queries": output, "monetary_permission": False,
        "automatic_execution": False, "execution_enabled": False,
        "model_calibrated": False,
        "probe_version": SOURCE_SCHEMA,
        "probe_code_hash": sha256(Path(__file__).read_bytes()).hexdigest(),
        "shared_budget_required": True,
        "source_archive_bytes": MAX_ARCHIVE_BYTES-remaining,
    }

