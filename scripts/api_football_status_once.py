"""One-shot API-Football credential probe. No key, account ID or raw payload output.

Never run automatically at worker startup. Network access requires an explicit
--confirm-single-request argument; max 1 GET /status, zero retries.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from sefirot.credentials import credential
from sefirot.football_provider import FootballRequestError, get, status_summary


def probe_once(*, confirm=False, fetch=None, credential_reader=None):
    base = {"request_attempted": False, "endpoint": "/status",
            "monetary_permission": False, "execution_enabled": False}
    if not confirm:
        return {**base, "status": "NOT_EXECUTED", "reason": "EXPLICIT_CONSENT_REQUIRED"}
    credential_reader = credential if credential_reader is None else credential_reader
    try:
        credential_reader("API_FOOTBALL_KEY")
    except (ValueError, OSError, KeyError, TypeError):
        return {**base, "status": "CREDENTIAL_UNAVAILABLE", "reason": "MISSING_OR_INVALID_CREDENTIAL"}
    fetch = get if fetch is None else fetch
    # Exactly one provider call. This script NEVER calls the odds catalogue or /fixtures.
    try:
        packet = fetch("status")
        summary = status_summary(packet)
    except FootballRequestError as exc:
        return {**base, "request_attempted": True,
                "status": "PROVIDER_REJECTED", "reason": exc.code}
    except (ValueError, OSError, KeyError, TypeError):
        return {**base, "request_attempted": True,
                "status": "PROBE_FAILED", "reason": "NETWORK_OR_RESPONSE_ERROR"}
    active = summary.get("subscription_active") is True
    def safe_counter(x):
        return x if isinstance(x, int) and not isinstance(x, bool) and x >= 0 else None
    return {**base, "request_attempted": True,
            "status": "SUBSCRIPTION_ACTIVE" if active else "SUBSCRIPTION_INACTIVE",
            "subscription_active": active,
            "requests_current": safe_counter(summary.get("requests_current")),
            "requests_limit_day": safe_counter(summary.get("requests_limit_day")),
            "scope": "ONE_STATUS_CHECK_ONLY"}


def main(argv=None):
    parser = argparse.ArgumentParser(description="Explicit one-call provider status only")
    parser.add_argument("--confirm-single-request", action="store_true",
                        help="consume up to one API-Football /status request; never retry")
    args = parser.parse_args(argv)
    result = probe_once(confirm=args.confirm_single_request)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, allow_nan=False))
    return 0 if result["status"] == "SUBSCRIPTION_ACTIVE" else 2


if __name__ == "__main__":
    sys.exit(main())
