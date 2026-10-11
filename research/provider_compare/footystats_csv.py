"""Read-only FootyStats Premium/free-sample Match CSV validation (no network).

Csv data downloaded *after* a past match is retrospective, not a contemporaneous
prematch snapshot. Never promote to canonical SEFIROT model inputs automatically.
"""
from __future__ import annotations

import csv
from datetime import datetime, timezone
from hashlib import sha256
from io import StringIO
import json
from .footystats import _asof

SCHEMA = "sefirot-footystats-csv-probe-v1"
MAX_CSV_BYTES = 8 * 1024 * 1024
MAX_ROWS = 10000
REQUIRED = (
    "timestamp", "status", "home_team_name", "away_team_name",
    "home_team_goal_count", "away_team_goal_count",
    "home_team_corner_count", "away_team_corner_count"
)
ALLOWED_STATUSES = {"complete", "incomplete", "postponed", "canceled", "cancelled", "suspended"}


def _nonnegative_int(row, key, *, upper=1000):
    value = row.get(key)
    if value is None or value == "":
        return None
    if not value.isascii() or not value.isdecimal() or len(value) > 16:
        raise ValueError("invalid integer in " + key)
    n = int(value)
    if n > upper:
        raise ValueError("oversized count in " + key)
    return n


def _name(value):
    if not isinstance(value, str):
        raise ValueError("missing club name")
    s = value.strip()
    if not s or len(s) > 128 or any(ord(c) < 32 for c in s):
        raise ValueError("invalid club name")
    return s


def inspect_csv(raw, *, season, received_at, expected_matches=None):
    """Validate one CSV without creating trusted match IDs or point-in-time data."""
    if not isinstance(raw, bytes) or len(raw) > MAX_CSV_BYTES or not raw:
        raise ValueError("missing or oversized CSV")
    try:
        as_of = _asof(received_at)
        text = raw.decode("utf-8-sig")
    except UnicodeError as exc:
        raise ValueError("CSV must be UTF-8") from exc
    if "\x00" in text:
        raise ValueError("NUL in CSV")
    if not isinstance(season, str) or len(season) > 32 or not season.strip():
        raise ValueError("explicit season label required")
    if expected_matches is not None and (type(expected_matches) is not int or not 1 <= expected_matches <= MAX_ROWS):
        raise ValueError("invalid expected match count")
    reader = csv.DictReader(StringIO(text, newline=""), restkey="_CSV_EXTRA", restval=None, strict=True)
    header = reader.fieldnames
    if not isinstance(header, list) or any(not x for x in header) or len(header) > 500 or len(set(header)) != len(header):
        raise ValueError("missing, duplicated or oversized CSV header")
    if not set(REQUIRED).issubset(header):
        raise ValueError("not FootyStats Match CSV; required columns missing")
    seen = set()
    complete = incomplete = goals_n = corners_n = 0
    records = []
    for row in reader:
        if len(records) >= MAX_ROWS:
            raise ValueError("CSV exceeds fixture limit")
        if "_CSV_EXTRA" in row or any(v is None for v in row.values()):
            raise ValueError("CSV column count mismatch")
        status = row["status"].strip()
        if status not in ALLOWED_STATUSES:
            raise ValueError("unknown match status")
        ts = _nonnegative_int(row, "timestamp", upper=253402300799)
        if ts is None or ts <= 0:
            raise ValueError("missing or invalid kickoff timestamp")
        try:
            kickoff = datetime.fromtimestamp(ts, tz=timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:
            raise ValueError("invalid kickoff") from exc
        home = _name(row["home_team_name"])
        away = _name(row["away_team_name"])
        if home.casefold() == away.casefold():
            raise ValueError("teams must differ")
        key = json.dumps([season, ts, home, away], ensure_ascii=False, separators=(",", ":"))
        if key in seen:
            raise ValueError("duplicate team-time match; no source fixture IDs")
        seen.add(key)
        goals = (_nonnegative_int(row, "home_team_goal_count"), _nonnegative_int(row, "away_team_goal_count"))
        corners = (_nonnegative_int(row, "home_team_corner_count"), _nonnegative_int(row, "away_team_corner_count"))
        if any(v is None for v in goals) and any(v is not None for v in goals):
            raise ValueError("partial goal result")
        if any(v is None for v in corners) and any(v is not None for v in corners):
            raise ValueError("partial corner result")
        if status == "complete":
            complete += 1
            if kickoff >= as_of:
                raise ValueError("finished match at or after file observation")
        else:
            incomplete += 1
            if any(v is not None for v in goals + corners):
                raise ValueError("unfinished match contains unverified results")
        if all(v is not None for v in goals):
            goals_n += 1
            if max(goals) > 50:
                raise ValueError("impossible score")
            total = _nonnegative_int(row, "total_goal_count") if "total_goal_count" in row else None
            if total is not None and sum(goals) != total:
                raise ValueError("goal total contradicts team scores")
        if all(v is not None for v in corners):
            corners_n += 1
            if max(corners) > 100:
                raise ValueError("implausible corner count")
        local_id = "footystats-csv:unmatched:" + sha256(key.encode("utf-8")).hexdigest()
        records.append({
            "local_candidate_id": local_id,
            "kickoff_utc": kickoff.isoformat(),
            "status": status,
            "observed_at": as_of.isoformat(),
            "goals": list(goals) if all(v is not None for v in goals) else None,
            "corners": list(corners) if all(v is not None for v in corners) else None,
            "original_fixture_id": None,
            "original_team_ids": None,
            "prematch_feature_availability": "UNVERIFIED",
            "provider_authentication": "UNVERIFIED_CSV_ORIGIN",
            "training_allowed": False,
            "holdout_allowed": False
        })
    if not records:
        raise ValueError("empty CSV dataset")
    if expected_matches is not None and len(records) != expected_matches:
        raise ValueError("declared fixture count mismatch")
    return {
        "schema": SCHEMA,
        "status": "KEEP_SHADOW",
        "source_type": "FOOTYSTATS_PREMIUM_MATCH_CSV",
        "season_operator_asserted": season,
        "first_observed_at_operator_asserted": as_of.isoformat(),
        "raw_csv_sha256": sha256(raw).hexdigest(),
        "count": len(records),
        "coverage": {
            "complete": complete, "other_statuses": incomplete,
            "complete_goal_scores": goals_n,
            "complete_corner_scores": corners_n
        },
        "has_prematch_columns": any(("Pre-Match" in k or "_pre_match" in k.lower() or k.startswith("pre_match")) for k in header),
        "has_1x2_odds_columns": all(k in header for k in ("odds_ft_home_team_win", "odds_ft_draw", "odds_ft_away_team_win")),
        "records": records,
        "source_certified": False,
        "training_allowed": False,
        "holdout_allowed": False,
        "monetary_permission": False,
        "blockers": [
            "CSV exporter not authenticated or contemporaneously sealed",
            "No original fixture/team IDs; candidate IDs are local hashes only",
            "No proof of historical prematch feature availability",
            "No verified external league/season coverage receipt",
            "CSV odds have no original bookmaker identity or quote timestamp"
        ]
    }
