"""Read-only server receipt resolution and status dispatcher; no provider fetch.

HMAC authenticates the enrolled collector, NOT the provider or event timestamp.
No real external-source attestation adapter exists in P1. Such inputs HOLD.
Synthetic routing is opt-in and visibly labelled on every response.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import sys
from time import perf_counter
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "src"), str(ROOT)]
from sefirot.contracts import Policy, canonical, digest, time
from sefirot.engine import code_hash, model_code_hash
from research.situation_contract import SituationRequest, SituationResponse, utc
from research.situational_v1 import route_fixture
import chat_store

MAX_SOURCE_BYTES = 65536


class SourceUnavailable(RuntimeError):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def strict_json(raw):
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError("duplicate JSON field")
            out[key] = value
        return out
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite JSON")))


def resolve_source(receipt_id):
    """No client path, packet, trust flag or signing key is accepted here."""
    if chat_store.configured():
        try:
            response = chat_store.request({"action": "situation_source", "receipt_id": receipt_id})
            if set(response) != {"receipt"}:
                raise SourceUnavailable("SOURCE_RESPONSE_INVALID")
            return response["receipt"]
        except RuntimeError as exc:
            if isinstance(exc, SourceUnavailable):
                raise
            raise SourceUnavailable("SOURCE_STORE_UNAVAILABLE") from exc
    root_value = os.environ.get("SEFIROT_SITUATION_RECEIPTS", "")
    if not root_value:
        raise SourceUnavailable("SOURCE_NOT_CONFIGURED")
    root = Path(root_value).absolute()
    path = root / (receipt_id + ".json")
    try:
        if any(p.is_symlink() for p in (path, root, *root.parents)):
            raise SourceUnavailable("SOURCE_PATH_UNSAFE")
        if not path.exists():
            return None
        with path.open("rb") as handle:
            raw = handle.read(MAX_SOURCE_BYTES + 1)
        if len(raw) > MAX_SOURCE_BYTES:
            raise SourceUnavailable("SOURCE_TOO_LARGE")
        return strict_json(raw)
    except (OSError, ValueError) as exc:
        raise SourceUnavailable("SOURCE_READ_FAILED") from exc


def authenticate_source(envelope, request):
    if envelope is None:
        raise SourceUnavailable("SOURCE_RECEIPT_NOT_FOUND")
    if not isinstance(envelope, dict) or set(envelope) != {"body", "collector_signature"}:
        raise SourceUnavailable("SOURCE_RESPONSE_INVALID")
    if len(canonical(envelope).encode("utf-8")) > MAX_SOURCE_BYTES:
        raise SourceUnavailable("SOURCE_TOO_LARGE")
    body = envelope["body"]
    fields = {"schema", "fixture_id", "source_id", "source_revision", "provider_status",
              "kickoff", "status_observed_at", "status_received_at", "origin"}
    if not isinstance(body, dict) or set(body) != fields or body["schema"] != "situation-source-receipt-v1":
        raise SourceUnavailable("SOURCE_RESPONSE_INVALID")
    if digest(body) != request.original_provider_receipt_id:
        raise SourceUnavailable("SOURCE_RECEIPT_HASH_MISMATCH")
    key = os.environ.get("SEFIROT_SITUATION_SOURCE_KEY", "")
    if not 48 <= len(key) <= 256 or not key.isascii():
        raise SourceUnavailable("SOURCE_AUTH_NOT_CONFIGURED")
    signature = envelope["collector_signature"]
    expected = hmac.new(key.encode(), canonical(body).encode(), hashlib.sha256).hexdigest()
    if not isinstance(signature, str) or not hmac.compare_digest(signature, expected):
        raise SourceUnavailable("SOURCE_COLLECTOR_AUTH_FAILED")
    if (body["fixture_id"] != request.fixture_id or body["source_id"] != request.identity.source_id
            or type(body["source_revision"]) is not int
            or body["source_revision"] != request.identity.source_revision
            or body["provider_status"] != request.provider_status
            or utc(body["kickoff"]) != request.kickoff
            or utc(body["status_observed_at"]) != request.status_observed_at):
        raise SourceUnavailable("SOURCE_ASSERTION_MISMATCH")
    if body["origin"] not in ("SYNTHETIC_TEST_ONLY", "UNATTESTED_ARCHIVE"):
        raise SourceUnavailable("SOURCE_ORIGIN_NOT_ATTESTED")
    # An authenticated collector receipt is not external provider attestation.
    return body


def short_summary(request, phase, depth, body, synthetic, age, action, reason):
    label = " | СИНТЕТИЧЕСКИЙ ТЕСТ" if synthetic else ""
    lines = [f"SEFIROT | {phase}{label}", f"Матч: {request.fixture_id}" + (f" | режим ответа: {depth}" if phase!="HOLD" else "")]
    if body:
        start = time(body["kickoff"])
        lines.append("Начало: " + start.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                     + " / " + start.astimezone(ZoneInfo("Europe/Kyiv")).strftime("%H:%M:%S Киев"))
        lag = f"{age:.0f} с" if age >= 0 else "противоречие времени"
        lines.append(f"Статус: {body['provider_status']} | давность: {lag} | источник: "
                     + ("тестовый" if synthetic else "внешнее происхождение не удостоверено"))
    lines.append("CORE: " + ("NO_SOURCE" if phase == "HOLD" else "NOT_EVALUABLE"))
    reasons={"SOURCE_REPORTS_NOT_STARTED":"источник сообщает NS; нужен отдельный спортивный расчёт",
        "FRESH_INPLAY_STATUS_NOT_A_LIVE_MODEL":"есть live-статус; проверенного live-прогноза нет",
        "RESULTS_NOT_FORECAST":"матч завершён; доступен отдельный аудит результата",
        "SOURCE_ORIGIN_NOT_ATTESTED":"происхождение спортивного статуса не удостоверено",
        "STALE_PREMATCH_STATUS":"прематчевый статус устарел", "STALE_LIVE_STATUS":"live-статус устарел",
        "KICKOFF_REACHED_NO_INPLAY_CONFIRMATION":"время начала наступило, live-статус не подтверждён",
        "STOPPED_OR_UNKNOWN_FIXTURE_STATUS":"статус неизвестен или матч остановлен",
        "SOURCE_POINT_IN_TIME_CONFLICT":"времена источника противоречат друг другу",
        "INPLAY_STATUS_CHRONOLOGY_CONFLICT":"live-статус противоречит времени начала",
        "FINISHED_STATUS_CHRONOLOGY_CONFLICT":"финальный статус противоречит времени начала",
        "REQUEST_PHASE_NOT_CONFIRMED":"запрошенный режим не соответствует статусу источника"}
    lines.append("Основание: " + reasons.get(reason,"нет допустимой свежей квитанции: "+reason) + ".")
    actions = {"REQUEST_SEPARATE_VERIFIED_PREMATCH_CAPTURE": "запросить отдельный прематчевый расчёт с проверенными спортивными данными",
               "WAIT_FOR_VALIDATED_LIVE_MODULE": "дождаться проверенного live-модуля",
               "REQUEST_SEPARATE_RESULT_AUDIT": "запросить отдельный аудит результата",
               "OBTAIN_AUTHENTICATED_CURRENT_STATUS_RECEIPT": "получить удостоверенную свежую квитанцию статуса"}
    lines.append("Следующее действие: " + actions[action] + ".")
    return "\n".join(lines)


def execute_situation(data, *, clock=None):
    started = perf_counter()
    request = SituationRequest.from_dict(data)
    now = (clock or (lambda: datetime.now(timezone.utc)))().astimezone(timezone.utc)
    phase, depth, reason, body = "HOLD", "NONE", "SOURCE_NOT_CONFIGURED", None
    authenticated, synthetic = False, False
    if request.identity.model_hash != model_code_hash():
        reason = "MODEL_IDENTITY_MISMATCH"
    elif time(request.request_at) > now:
        reason = "FUTURE_REQUEST_TIME"
    elif (now - time(request.request_at)).total_seconds() > 120:
        reason = "REQUEST_EXPIRED"
    else:
        try:
            body = authenticate_source(resolve_source(request.original_provider_receipt_id), request)
            authenticated = True
            synthetic = body["origin"] == "SYNTHETIC_TEST_ONLY"
            received = time(body["status_received_at"])
            observed = time(body["status_observed_at"])
            if observed > received or received > time(request.request_at):
                reason = "SOURCE_POINT_IN_TIME_CONFLICT"
            elif not synthetic:
                reason = "SOURCE_ORIGIN_NOT_ATTESTED"
            elif os.environ.get("SEFIROT_SITUATION_ALLOW_SYNTHETIC") != "1":
                reason = "SYNTHETIC_SOURCE_DISABLED"
            else:
                route = route_fixture({"fixture_id": body["fixture_id"], "source_id": body["source_id"],
                    "status": body["provider_status"], "kickoff": body["kickoff"],
                    "status_received_at": body["status_received_at"],
                    "status_observed_at": body["status_observed_at"]},
                    at=now.isoformat(), intent=request.intent.upper(), detail=request.depth.upper())
                phase = "POSTMATCH" if route["mode"] == "POSTMATCH_RECAP" else route["mode"]
                depth, reason = route["depth"], route["reason"]
        except SourceUnavailable as exc:
            reason = exc.reason
        except (ValueError, TypeError, KeyError):
            body, reason = None, "SOURCE_RESPONSE_INVALID"
    action = {"PREMATCH": "REQUEST_SEPARATE_VERIFIED_PREMATCH_CAPTURE",
              "LIVE_RESEARCH": "WAIT_FOR_VALIDATED_LIVE_MODULE",
              "POSTMATCH": "REQUEST_SEPARATE_RESULT_AUDIT",
              "HOLD": "OBTAIN_AUTHENTICATED_CURRENT_STATUS_RECEIPT"}[phase]
    age = (now-time(body["status_observed_at"])).total_seconds() if body else None
    response = SituationResponse(
        schema="sefirot-situation-status-v1", fixture_id=request.fixture_id, phase=phase, depth=depth,
        reasons=(reason,), next_action=action, request_at=request.request_at, evaluated_at=now.isoformat(),
        original_provider_receipt_id=request.original_provider_receipt_id, source_identity=request.identity,
        source_attestation="SYNTHETIC_TEST_ONLY" if synthetic else "NOT_ATTESTED",
        collector_authenticated=authenticated, external_origin_verified=False, synthetic=synthetic,
        provider_status=body["provider_status"] if body else None,
        kickoff=utc(body["kickoff"]) if body else None,
        status_observed_at=utc(body["status_observed_at"]) if body else None,
        status_received_at=utc(body["status_received_at"]) if body else None,
        source_age_seconds=age,
        core_verdict="NOT_EVALUABLE" if phase != "HOLD" else "NO_SOURCE", core_invoked=False,
        prematch_core_allowed=False, live_betting_allowed=False, monetary_permission=False,
        execution_enabled=False, model_hash=model_code_hash(), code_hash=code_hash(),
        policy_hash=Policy().fingerprint, request_key=request.request_key,
        measured_processing_ms=round((perf_counter()-started)*1000, 3),
        latency_scope="STATUS_DISPATCH_INCLUDING_SOURCE_LOOKUP_EXCLUDING_QUEUE_AND_HTTP",
        latency_target_validated=False,
        summary=short_summary(request,phase,depth,body,synthetic,age,action,reason))
    return response.to_dict()


def main():
    # CLI JSON is UTF-8 on every platform, including redirected Windows stdout.
    sys.stdout.reconfigure(encoding="utf-8", errors="strict")
    import argparse
    parser = argparse.ArgumentParser(description="Read an enrolled status receipt; never fetch sporting data")
    parser.add_argument("--request", type=Path, required=True)
    args = parser.parse_args()
    try:
        raw = args.request.read_bytes()
        if len(raw) > 16384:
            raise ValueError("request too large")
        output = execute_situation(strict_json(raw))
    except (ValueError, TypeError, KeyError, OSError):
        print(json.dumps({"error": "INVALID_SITUATION_REQUEST"}))
        return 2
    print(json.dumps(output, ensure_ascii=False, allow_nan=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
