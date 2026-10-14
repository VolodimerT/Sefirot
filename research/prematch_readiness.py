"""Read existing originals and source gaps; never fetch, write or make a forecast."""
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import sqlite3

from sefirot.contracts import Policy, VERSION, time
from sefirot.identity import code_hash, model_code_hash
from sefirot.repository import Repository
from sefirot.service import Service
from sefirot.readiness import inspect_readiness
from research.chat_answer_contract import build_answer, validate_answer, _record


def source_channels(at):
    # Historical Issue #29 is not a fresh status probe. No config/vault reads.
    return {name: {"status": "NOT_VERIFIED", "checked_at": None,
                   "report_at": at, "quota": None, "quota_verified": False,
                   "evidence": "NO_CURRENT_AUTHORIZED_RUNTIME_RECEIPT",
                   **({"last_documented_status": "ACCOUNT_SUSPENDED",
                       "last_documented_at": "2026-10-06T16:18:54+00:00",
                       "historical_reference": "https://github.com/VolodimerT/Sefirot/issues/29"}
                      if name == "API_FOOTBALL" else {})}
            for name in ("API_FOOTBALL", "STAKE", "GATEWAY", "SUPABASE_STORE")}


def operator_report(database=None, *, at=None, prediction_id=None, include_market_views=False):
    now = time(at) if at else datetime.now(timezone.utc)
    stamp = now.isoformat()
    report = {"schema": "prematch-operator-readiness-v1", "at": stamp,
              "build": {"version": VERSION, "code_hash": code_hash(),
                        "model_hash": model_code_hash(), "policy_hash": Policy().fingerprint},
              "sources": source_channels(stamp), "ledger_status": "NOT_SUPPLIED",
              "readiness": [], "original_decisions": [], "verified_market_views": [], "audit_events": 0,
              "network_requests": 0, "forecasts_created": 0, "quotes_fetched": False,
              "read_only": True, "monetary_permission": False, "execution_enabled": False,
              "stake": 0.0, "missing_evidence": ["CURRENT_SOURCE_STATUS_AND_QUOTA",
                    "INDEPENDENT_SOURCE_ORIGIN", "STAKE_SETTLEMENT_AND_FRESH_PRICE",
                    "INDEPENDENT_CALIBRATION_AND_HOLDOUT", "PRODUCTION_RUNTIME_NOT_CONNECTED"]}
    if database is None:
        return report
    if not Path(database).is_file():
        report["ledger_status"] = "ABSENT"
        return report
    try:
        with closing(Repository(str(database), read_only=True)) as repo:
            repo.db.execute("BEGIN")
            try:
                if not repo.verify():
                    report["ledger_status"] = "INTEGRITY_FAILED"
                    return report
                service = Service(repo, clock=lambda: now)
                predictions = repo.all("predictions", stamp)
                if prediction_id:
                    predictions = [p for p in predictions if p["id"] == prediction_id]
                    if not predictions:
                        raise ValueError("PREDICTION_NOT_AT_CUTOFF")
                report["readiness"] = [inspect_readiness(service, p["id"], stamp)
                                       for p in predictions[-100:]]
                mids = {p["sports"]["match"]["id"] for p in predictions}
                for d in repo.all("decisions", stamp):
                    if d["match_id"] not in mids:
                        continue
                    answer = build_answer(d["match_id"], [d["match_id"]], at=now, repo=repo,
                                          decision_id=d["id"], archive=True)
                    verified = validate_answer(answer, expected_fixtures=[d["match_id"]],
                                               at=now, repo=repo, archive=True)
                    report["original_decisions"].append(verified.to_dict())
                    if include_market_views:
                        original, sealed = _record(repo, d["id"])
                        card = original.get("decision_card", {})
                        fields = ("market", "status", "eligible", "odds", "implied_probability",
                            "model_probability", "ev", "ev_low", "calibration", "stress_class",
                            "tactical_fit", "public_trap", "death_test", "effective_blockers")
                        report["verified_market_views"].append({"decision_id": original["id"],
                            "fixture_id": original["match_id"], "match": sealed["sports"]["match"],
                            "at": original["at"], "core_decision": original["decision"],
                            "core_class": original["class"], "data_origin": verified["data_origin"],
                            "code_hash": sealed["code_hash"],
                            "archive_only": True, "fresh_quote_attested": False,
                            "build_matches": sealed["code_hash"] == report["build"]["code_hash"],
                            "source": "ORIGINAL_VERIFIED_DECISION_CARD",
                            "markets": [{k: row.get(k) for k in fields}
                                for row in card.get("alternatives", [])],
                            "research_candidate": {k: card.get("research_candidate", {}).get(k)
                                for k in ("market", "status", "model_probability", "ev", "ev_low")}
                                if card.get("research_candidate") else None})
                report["original_decisions"] = report["original_decisions"][-100:]
                report["verified_market_views"] = report["verified_market_views"][-100:]
                report["audit_events"] = sum(time(row["at"]) <= now for row in
                    repo.db.execute("SELECT at FROM audit_logs"))
                report["ledger_status"] = "VERIFIED_LOCAL_ORIGIN_NOT_ATTESTED"
            finally:
                repo.db.rollback()
    except (ValueError, KeyError, TypeError, OSError, sqlite3.Error):
        report.update(ledger_status="UNREADABLE_OR_UNVERIFIABLE", readiness=[],
                      original_decisions=[], verified_market_views=[], audit_events=0)
    return report
