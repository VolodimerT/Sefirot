"""Research-only Stake quotes through a pre-existing canonical prematch seal.

No wager placement, no unsealed pre-price scan, no secret fields in output.
"""
from __future__ import annotations

from datetime import datetime, timezone
from sefirot.odds_provider import require_prematch_seal
from sefirot.stake_provider import (
    exact_event, fixture_markets, research_snapshot, sports_events,
)
from sefirot.stake_mapper import normalize_snapshot


def collect(repo, payload: dict) -> dict:
    if not isinstance(payload, dict) or set(payload) != {"prediction_id"}:
        raise ValueError("stake_snapshot requires only a prediction_id")
    identifier = payload["prediction_id"]
    if not isinstance(identifier, str) or len(identifier) != 64 or any(c not in "0123456789abcdef" for c in identifier):
        raise ValueError("invalid prediction_id")
    if not repo.verify():
        raise ValueError("journal integrity failure; PASS")
    prediction = repo.get("predictions", identifier)
    if not isinstance(prediction, dict) or prediction.get("synthetic") is not False:
        raise ValueError("actual original sealed prematch prediction required; PASS")
    received = datetime.now(timezone.utc)
    # This validation happens BEFORE any price, line or Stake provider access.
    require_prematch_seal(prediction, received)

    catalogue = sports_events(first=200, sport_slug="soccer", match_type="active")
    event = exact_event(catalogue["events"], prediction, received)
    packet = fixture_markets(event["slug"])
    report = research_snapshot(event, prediction, received, packet["markets"],
                               [catalogue["receipt"]] + packet.get("receipts", []))
    normalized = normalize_snapshot(report)
    main = normalized["main_quotes"]
    small = normalized["small_quotes"]
    # Keep the private Supabase job response small; publish complete counts and hashes.
    return {
        "stage": "STAKE_SNAPSHOT_RESEARCH",
        "provider": "STAKE_GRAPHQL_EXPERIMENTAL",
        "status": "RESEARCH_ONLY",
        "prediction_id": identifier,
        "fixture_id": report["fixture_id"],
        "home": report["home"], "away": report["away"], "kickoff": report["kickoff"],
        "received_at": report["received_at"],
        "provider_market_timestamp": None,
        "freshness": "RECEIPT_TIME_ONLY",
        "settlement_rules": "UNVERIFIED_PROVIDER_WEB_CONTRACT",
        "stake_event_id": report["stake_event_id"],
        "raw_market_count": report["market_count"],
        "main_quote_count": normalized["main_quote_count"],
        "small_quote_count": normalized["small_quote_count"],
        "main_quotes": main[:120],
        "small_quotes": small[:120],
        "truncated": len(main) > 120 or len(small) > 120,
        "snapshot_hash": report["hash"],
        "normalized_hash": normalized["hash"],
        "retrieval_receipts": report.get("retrieval_receipts", []),
        "monetary_permission": False,
        "automatic_execution": False,
        "execution_enabled": False,
    }
