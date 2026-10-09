# SEFIROT chat bridge (research-only)

This optional separate Render Free web service calls **the canonical Python SEFIROT Service**, not an approximate ChatGPT probability estimator. Core source and policies remain untouched. It exists only on branch feature/chat-sefirot-bridge-20261010.

## Deploy
- Python runtime; branch feature/chat-sefirot-bridge-20261010
- Build: python -m pip install .
- Start: python scripts/chat_gateway.py
- Free plan, Frankfurt, manual deployment
- Required environment: SEFIROT_BRIDGE_TOKEN, 32-256 characters random and secret.
- Bind Render-provided PORT automatically.
- Authenticated requests use Authorization: Bearer <secret> and JSON Content-Type.

## API

GET /health is public and leaks no model input. Others require bearer auth.

- GET /v1/status — version hashes and basic integrity counts
- GET /v1/demo — actual engine's **synthetic** lifecycle with replay and integrity
- POST /v1/capture — JSON {"sports": <real sports-only contract>, "markets": <optional initial market list>}; canonical price-blind initial seal
- POST /v1/decide — {"prediction_id": <capture-id>, "quotes": [...], "recheck": {...}, "portfolio": {"bankroll": 1000.0, "peak": 1000.0}}; canonical EV/risk gates
- GET /v1/decision/<64-char id> — read recorded decision
- POST /v1/result — original canonical result payload
- GET /v1/report — original audited performance, including missing/blocked predictions

All returns are JSON. Post-capture quote revisions must remain new decisions, not altered old evidence. This bridge explicitly sets money_authorized=false even if a synthetic or research service returns BET. Never treat it as placement permission. No betting execution, LIVE, dogon or auto-selection.

## Crucial limitations

1. **Render Free filesystem is ephemeral.** The SQLite file can disappear after a restart or deploy. Never count it as the durable ledger and do not treat its report as a complete historical audit. Do not send real-world betting instructions relying on this storage without a durable, separately approved backend.
2. A connection to ChatGPT from within a chat **is not automatically created** by deploying an HTTPS service. One must explicitly connect a custom compatible tool / MCP integration or run the API in ChatGPT Work/cloud browser. This branch supplies a native REST API only, not a registered ChatGPT connector.
3. Supabase's original 22-table ledger is separate and empty until an intentionally authorized, verified append-only sync. No automatic remote writes or migration occur here.
4. API-Football provider reported ACCOUNT_SUSPENDED on October 6. The bridge accepts point-in-time sports JSON but cannot independently verify the provider or collect real future sports data. An independent source-backed collection + verified bookmaker receipts is required.
5. DC_DYNAMIC_V1 / SOS_LITE_V1 from PR #21 are **SHADOW** and not activated. There are zero new real independent holdout cases. The canonical core and underlying policy remain untouched.
6. The bridge intentionally refuses unauthenticated access, expired prematch capture and malformed requests. Authentication secret must never be put in Git or user-provided public screenshots.
