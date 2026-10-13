"""One frozen synthetic integration, using original archive, worker and verifier."""
from contextlib import closing
from copy import deepcopy
from pathlib import Path
import json
import os
import tempfile
from unittest.mock import patch

from sefirot.contracts import digest, time
from sefirot import football_gateway
from sefirot.markets import validate_quote
from sefirot.repository import Repository
from sefirot.service import Service
from sefirot.sports_archive import archive_packets, export_sports
from sefirot.stake_provider import exact_event, research_snapshot
from sefirot.stake_mapper import normalize_snapshot
from sefirot.worker import process_inbox
from research.source_adapter_v3 import adapt_sources
from research.chat_answer_contract import build_answer, validate_answer, render_answer
from research.prematch_readiness import operator_report
from scripts import chat_sports_probe as probe

FIXTURES = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "prematch_issue59_source_v2"


def _frozen(path, schema):
    value = json.loads(path.read_text(encoding="utf-8"))
    body = dict(value); signature = body.pop("hash", None)
    if value.get("schema") != schema or value.get("synthetic") is not True or signature != digest(body):
        raise ValueError("FROZEN_SYNTHETIC_FIXTURE_REQUIRED")
    return value


def _offline_packet(packet, gateway_contract):
    # Actual SDK and probe, injected offline transport + synthetic credential.
    # This never looks up credentials or calls the default opener.
    wrapper = {**gateway_contract, "provider": "API_FOOTBALL_V3",
               "provider_host": packet["receipt"]["provider_host"], "endpoint": "/fixtures",
               "params": packet["receipt"]["parameters"], "sports_only": True,
               "monetary_permission": False, "execution_enabled": False,
               "received_at": packet["receipt"]["received_at"], "data": packet["data"]}
    class Reply:
        status = 200
        def read(self, size): return json.dumps(wrapper).encode()[:size]
        def close(self): pass
    stamps = iter([time(packet["receipt"]["request_started_at"]), time(packet["receipt"]["received_at"])])
    with patch.dict(os.environ, {"SEFIROT_SPORTS_GATEWAY_URL":
            "https://" + "a"*20 + ".supabase.co/functions/v1/sefirot-sports-gateway"}), \
         patch.object(football_gateway, "credential", return_value="SYNTHETIC_TEST_ONLY"):
        collected = football_gateway.get_sports("fixtures", packet["receipt"]["parameters"],
            opener=lambda *args, **kwargs: Reply(), clock=lambda: next(stamps), require_shared_budget=True)
    with patch.object(probe, "get_sports", return_value=collected), \
         patch.object(probe, "transport_status", return_value={"transport": "SYNTHETIC_OFFLINE"}):
        result = probe.collect({"queries": [{"endpoint": "fixtures", "params": packet["receipt"]["parameters"]}]})
    query = result["queries"][0]
    if probe.verify_evidence(query)["status"] != "CANONICAL_PACKET_ARCHIVED":
        raise ValueError("SYNTHETIC_PROBE_PACKET_NOT_ARCHIVED")
    # The probe envelope also has schema/projection_hash. Preserve the exact
    # canonical data and COMPLETE receipt required by the original importer.
    return {key: query["source_packet"][key] for key in ("data", "receipt")}


def run_scenario(*, fixture_directory=FIXTURES, work_directory=None):
    if work_directory is None:
        with tempfile.TemporaryDirectory(prefix="sefirot-prematch-e2e-") as directory:
            return run_scenario(fixture_directory=fixture_directory, work_directory=directory)
    root = Path(work_directory)
    # Owned NEW directory only: never run a demo against a user's ledger.
    if root.exists() and any(root.iterdir()):
        raise ValueError("EMPTY_OWNED_SCENARIO_DIRECTORY_REQUIRED")
    root.mkdir(parents=True, exist_ok=True)
    source = _frozen(Path(fixture_directory) / "source.json", "prematch-synthetic-source-v1")
    archive = root / "archive"
    packets = [_offline_packet(packet, source["gateway_contract"]) for packet in source["packets"]]
    archive_packets(packets, archive, source["capture_at"])
    exported = export_sports(archive, source["fixture_id"], source["capture_at"],
                             profile=source["profile"], source_reliability=.95)
    adapter = adapt_sources(archive=archive, cutoff=source["capture_at"],
                            league_id=source["league_id"], season=source["season"],
                            profile=source["profile"])
    sports = deepcopy(exported["sports"]); sports["synthetic"] = True
    markets = [{"kind": "1X2", "side": "HOME"}]
    inbox = root / "inbox"; inbox.mkdir()
    capture_job = {"id": "synthetic-prematch-capture", "type": "CAPTURE",
                   "payload": {"sports": sports, "markets": markets}}
    (inbox / "01-capture.json").write_text(json.dumps(capture_job), encoding="utf-8")
    clock = [time(source["capture_at"])]
    database = root / "scenario.sqlite"
    with closing(Repository(str(database))) as repo:
        service = Service(repo, clock=lambda: clock[0])
        captured = process_inbox(service, inbox)
        if len(captured) != 1 or captured[0]["status"] != "DONE":
            raise ValueError("SCENARIO_CAPTURE_FAILED")
        prediction = repo.get("jobs", capture_job["id"])["result"]
        sealed_hash = digest(prediction)
        # Price bytes are first opened only AFTER the original probability seal.
        price = _frozen(Path(fixture_directory) / "price.json", "prematch-synthetic-price-v1")
        if price["rules_evidence"] != "SYNTHETIC_TEST_REGULATION_90_NOT_PROVIDER_ATTESTATION":
            raise ValueError("SYNTHETIC_RULES_ONLY")
        event = exact_event([price["event"]], prediction, source["quote_at"])
        snapshot = research_snapshot(event, prediction, source["quote_at"], price["markets"])
        mapped = normalize_snapshot(snapshot)
        quotes = [{"market": row["market"], "odds": row["odds"],
                   "bookmaker": "SYNTHETIC_STAKE_CONTRACT", "observed_at": source["quote_at"],
                   "received_at": source["quote_at"], "phase": "FINAL", "rules": "REGULATION_90",
                   "line_id": price["hash"]} for row in mapped["main_quotes"]]
        if {r["market"]["side"] for r in quotes} != {"HOME", "DRAW", "AWAY"}:
            raise ValueError("COMPLETE_SYNTHETIC_PARTITION_REQUIRED")
        for quote in quotes:
            validate_quote(quote, sports["match"]["kickoff"], source["decision_at"], prediction["sealed_at"])
        decision_job = {"id": "synthetic-prematch-decide", "type": "DECIDE",
                        "payload": {"prediction_job_id": capture_job["id"], "quotes": quotes,
                                    "recheck": {"checked_at": source["quote_at"], "evidence": sports["evidence"]},
                                    "portfolio": {"bankroll": 0., "peak": 0.}}}
        (inbox / "02-decide.json").write_text(json.dumps(decision_job), encoding="utf-8")
        clock[0] = time(source["decision_at"])
        completed = process_inbox(service, inbox)
        if [r["status"] for r in completed] != ["ALREADY_PROCESSED", "DONE"]:
            raise ValueError("SCENARIO_DECISION_FAILED")
        decision = repo.get("jobs", decision_job["id"])["result"]
        if decision["decision"] != "PASS" or decision["class"] != "D" or repo.all("bets"):
            raise ValueError("SYNTHETIC_PASS_INVARIANT_FAILED")
        audit_before = repo.db.execute("SELECT count(*) FROM audit_logs").fetchone()[0]
        duplicate = process_inbox(service, inbox)
        if any(r["status"] != "ALREADY_PROCESSED" for r in duplicate):
            raise ValueError("DUPLICATE_JOB_FAILED")
        if audit_before != repo.db.execute("SELECT count(*) FROM audit_logs").fetchone()[0]:
            raise ValueError("DUPLICATE_CHANGED_AUDIT")
        if digest(repo.get("predictions", prediction["id"])) != sealed_hash or not repo.verify():
            raise ValueError("ORIGINAL_SEAL_OR_JOURNAL_CHANGED")
        answer = build_answer(sports["match"]["id"], [sports["match"]["id"]], at=clock[0],
                              repo=repo, decision_id=decision["id"], archive=True)
        verified = validate_answer(answer, expected_fixtures=[sports["match"]["id"]], at=clock[0],
                                   repo=repo, archive=True)
        result = {"schema": "prematch-offline-e2e-v1", "synthetic": True,
                  "source_fixture_hash": source["hash"], "price_fixture_hash": price["hash"],
                  "prediction_id": prediction["id"], "decision_id": decision["id"],
                  "build": {k: prediction[k] for k in ("version", "code_hash", "model_hash", "policy_hash")},
                  "coverage": exported["coverage"], "source_adapter_training_rows": len(adapter["training_rows"]),
                  "source_origin": "SYNTHETIC_TEST_NOT_PROVIDER_ATTESTATION",
                  "gateway_probe_packets": len(packets),
                  "gateway_budget_scope": "MOCK_TRANSPORT_NOT_DEPLOYED_QUOTA_PROOF",
                  "real_quote_rules": mapped["settlement_rules"], "quote_count": len(quotes),
                  "truth_levels": {"CORE_BET": None, "CORE_PASS": verified.to_dict(),
                      "RESEARCH_ONLY": {"stake_mapping_hash": mapped["hash"], "synthetic": True},
                      "BOOKMAKER_QUOTE_OBSERVED": {"synthetic": True, "verified_real": False,
                                                   "quote_hash": digest(quotes)},
                      "OUR_TICKET": None},
                  "chat_text": render_answer(verified), "audit_events": audit_before,
                  "duplicate_status": [r["status"] for r in duplicate], "replay_matches": service.replay(decision["id"])["matches"],
                  "ledger_integrity": True, "network_requests": 0, "monetary_permission": False,
                  "execution_enabled": False, "stake": 0.0}
    result["operator"] = operator_report(database, at=source["decision_at"])
    result["hash"] = digest(result)
    return result
