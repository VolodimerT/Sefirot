"""Offline read-only FootyStats league-matches research adapter.

Never authenticates provider content or yields a trainable/prospective SEFIROT
packet. In particular, historical match results downloaded today must not
receive timestamps from their old kickoffs.
"""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json


SOURCE = "FOOTYSTATS_LEAGUE_MATCHES"
SCHEMA = "sefirot-provider-probe-v1"


def _int(value, label, *, lower=0):
    if type(value) is not int or value < lower:
        raise ValueError("invalid " + label)
    return value


def _asof(value):
    if not isinstance(value, str):
        raise ValueError("received_at must be ISO8601")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid received_at") from exc
    if result.tzinfo is None or result.utcoffset() is None:
        raise ValueError("received_at requires explicit timezone")
    return result.astimezone(timezone.utc)


def inspect(payload, *, season_id, received_at, expected_page=1):
    """Validate response shape and return RESEARCH_ONLY coverage statistics.

    A successful local parse is NOT proof of endpoint access, provider origin,
    fresh information, original published_at or machine-learning eligibility.
    Caller must secure a raw response/receipt separately.
    """
    season_id = _int(season_id, "season_id", lower=1)
    expected_page = _int(expected_page, "page", lower=1)
    as_of = _asof(received_at)
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise ValueError("FootyStats provider did not report success")
    data = payload.get("data")
    if not isinstance(data, list) or len(data) > 1000:
        raise ValueError("invalid or over-limit FootyStats match page")
    pager = payload.get("pager")
    if pager is not None:
        if not isinstance(pager, dict):
            raise ValueError("invalid pager")
        if "current_page" not in pager or _int(pager["current_page"], "current_page", lower=1) != expected_page:
            raise ValueError("unexpected page")
    elif expected_page != 1:
        raise ValueError("unverified noninitial page")
    ids = set()
    coverage = {k: 0 for k in ("finished", "nonfinished", "complete_goal_scores", "complete_corner_scores", "unverified_kickoff")}
    records = []
    for row in data:
        if not isinstance(row, dict):
            raise ValueError("malformed fixture")
        fid = _int(row.get("id"), "fixture_id", lower=1)
        home = _int(row.get("homeID"), "homeID", lower=1)
        away = _int(row.get("awayID"), "awayID", lower=1)
        if fid in ids or home == away:
            raise ValueError("duplicate fixture or same opponent")
        ids.add(fid)
        if row.get("competition_id") is not None and _int(row["competition_id"], "competition_id", lower=1) != season_id:
            raise ValueError("season identity mismatch")
        timestamp = _int(row.get("date_unix"), "date_unix", lower=1)
        try:
            kickoff = datetime.fromtimestamp(timestamp, timezone.utc)
        except (OverflowError, OSError, ValueError) as exc:
            raise ValueError("invalid kickoff timestamp") from exc
        if kickoff > as_of:
            coverage["unverified_kickoff"] += 1
        status = row.get("status")
        if status not in ("complete", "incomplete", "suspended", "canceled"):
            raise ValueError("unknown fixture status")
        goals = None
        corners = None
        if status == "complete":
            coverage["finished"] += 1
            if kickoff >= as_of:
                raise ValueError("completed match from the future")
            gh, ga = row.get("homeGoalCount"), row.get("awayGoalCount")
            if gh is not None or ga is not None:
                gh = _int(gh, "homeGoalCount")
                ga = _int(ga, "awayGoalCount")
                if gh > 50 or ga > 50:
                    raise ValueError("impossible goal count")
                goals = [gh, ga]
                coverage["complete_goal_scores"] += 1
            ch, ca = row.get("team_a_corners"), row.get("team_b_corners")
            if ch is not None or ca is not None:
                ch = _int(ch, "home_corners")
                ca = _int(ca, "away_corners")
                if ch > 100 or ca > 100:
                    raise ValueError("impossible corner count")
                corners = [ch, ca]
                coverage["complete_corner_scores"] += 1
        else:
            coverage["nonfinished"] += 1
        records.append({
            "source_match_id": "footystats:match:" + str(fid),
            "source_home_team_id": "footystats:team:" + str(home),
            "source_away_team_id": "footystats:team:" + str(away),
            "season_id": season_id,
            "kickoff_utc": kickoff.isoformat(),
            "status": status,
            "goals": goals,
            "corners": corners,
            "first_observed_at": as_of.isoformat(),
            "original_publication_time": None,
            "original_prematch_snapshot_verified": False,
            "source_authentication": "UNVERIFIED_EXTERNAL_ORIGIN",
            "training_allowed": False,
        })
    # Not enough information here to attest entire season or page coverage.
    # In particular missing/unknown pager metadata cannot be a completeness proof.
    return {
        "schema": SCHEMA,
        "provider": SOURCE,
        "status": "KEEP_SHADOW",
        "season_id": season_id,
        "received_at": as_of.isoformat(),
        "page": expected_page,
        "total_pages_verified": False,
        "raw_response_digest": sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest(),
        "fixture_count": len(records),
        "coverage": coverage,
        "records": records,
        "odds_verified": False,
        "source_authentication": "UNVERIFIED_EXTERNAL_ORIGIN",
        "training_allowed": False,
        "prospective_holdout_allowed": False,
        "monetary_permission": False,
        "blockers": [
            "Response is not externally authenticated",
            "No original first-observed provider receipt",
            "Pre-match snapshots and historical time-of-availability unverified",
            "Season pagination and full-fixture coverage unverified",
            "No independent provider fixture/team-ID crosswalk",
            "No verified contemporaneous bookmaker quotes",
        ],
    }
