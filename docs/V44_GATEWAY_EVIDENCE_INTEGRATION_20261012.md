# V4.4: original gateway evidence and bounded offline integration

Task: issue #33 V4.4 / `SEFIROT_REASSESSMENT_V4_4_2026-10-12.md`.
Base: exact #41 `5a4b1d9a4ae95a1ab11f50f63a834a6d11a82991`.
Integrated source adapter: exact #38 `f547cc4f98d00313892322559e56b65d8082302e`.
Common ancestor: #37 `c4d2495086acf5f125d7f7ba8d8294ce90bdf84c`.
This candidate is a feature branch only, never a main merge or production deploy.

## Observable behavior

`scripts/gateway_evidence_archive.py` reads a saved original `/status` or exactly
one `/fixtures?id=...` response, checks the request/response identity and caller
receipt chronology, then exclusively creates a private whitelist-only receipt.
No networking, header token, secret retrieval, retry, mass scan, forecast,
training, activation, bookmaker quote or monetary permission is performed.

```bash
python scripts/gateway_evidence_archive.py --input /private/original-call.json --output /private/new-receipt.json
python scripts/calibration_fit_gate.py --db /private/original.sqlite --output /private/new-preflight.json
```

Do not use `--fit` without an independent source-backed population and separately
authorized fitting task. With no saved response, the archive command explicitly
returns `MISSING_ORIGINAL_RESPONSES`, with subscription/quota/fixture null.

## Original-call envelope

The caller supplies `schema=sefirot-gateway-call-v1`, positive
`gateway_version`, `request_started_at`, client `received_at`, `http_status`,
`request={endpoint,params}` and the exact gateway `response` object. All fields
are required. Header fields are prohibited; never include an API or runner key.
The gateway version and acquisition times are caller assertions, not a signed
server version or proof of provider origin. Do not invent them from HTTP logs,
file mtimes, an assistant summary or today's import time.

For status, parameters must be empty. For a single fixture, parameters must
contain exactly one positive numeric ID, and provider echo must match it.
Success requires the existing sports-only wrapper, provider/host identity,
HTTP 200, no application-level errors and consistent full single-page data.
The original `sports_archive.validate_packet` is reused for fixture validation.
Local import time is collected after reading; it cannot be backdated by CLI.

## Sanitization and gates

Output retains only hashes, bounded numeric quota counters, claimed gateway
version, receipt times, finite known plan names, boolean subscription active,
and numeric fixture/league/season identity, kickoff and finite status enum.
Account objects, names, headers and arbitrary error/plan strings are not echoed.
Raw file bytes remain in the caller's private archive, outside Git. Outputs use
exclusive creation and mode 0600 where supported; errors use one fixed message.

Inactive subscription, exhausted day/minute quota, missing minute counters,
unknown plan or conflicting counters block the provider gate. Minute limits are
never inferred from a plan name. Client receipt after kickoff cannot become a
prematch observation. Hashes bind supplied bytes/objects, not external identity.
All imports therefore remain `OFFLINE_CALLER_SUPPLIED`, with
`auth_verified_by_this_process=false`, `fit_allowed=false`, P/EV null and
`monetary_permission=false`. A structural receipt is not permission to collect
or bet and is not a source attestation.

## Integration and actual data boundary

#38 and #41 were integrated without conflicts in a candidate using a normal
merge. The #38 delta adds only its offline adapter/tests/documentation and
readiness report; the #41 risk audit stays intact. All `src/sefirot` bytes,
MODEL_MODULES, Policy and historical seals remain identical to #41. No legacy
generated report is rewritten or included in the new diff.

An authorized private checkpoint was checked using the original calibration
preflight in read-only mode. No eligible calibration records or planned cohort
exist there; no fit or activation occurred. This does not assess an external
bookmaker or assert that an API transport is broken. Previous chat descriptions
of Pro/quota and a fixture are not imported as fabricated original responses.
Actual private inputs and readback reports remain outside the public repository.

The next operational inputs are original status/single-fixture call envelopes
and an independently attested permitted league archive. Next P0-B then requires
a preregistered chronological TRAIN/CALIBRATION/HOLDOUT cohort, proper scoring,
and untouched future outcomes. Missing inputs remain missing. No fit on the
already-seen historical test or the eight-match sanity sample.

## Acceptance

Run the full `python test_sefirot.py`, synthetic lifecycle and
`python scripts/verify_release.py` on this integrated tree. Check all four
Ubuntu/Windows x Python 3.11/3.13 CI jobs on the exact published head, rather
than adding counts from unrelated branches. New tests are synthetic adversarial
engineering checks only. `MERGE_NOT_AUTHORIZED`, no cloud/key/runtime changes.
