# Explicit SHADOW target scope, 19 October 2026

## Confirmed defect and repair

Baseline PR #56 `2bef3110c9be20c1cf4a1f8af28a463ef0eafc45` has an
existing offline chain from original source packets to `engine.prepare`:
`football_pipeline.ingest` -> `model_inputs` -> `shadow_model.preview`.
An explicit EPL target with its own complete EPL calendar was nevertheless
blocked by a missing French, Italian or Spanish calendar. The preview loops
over four supported leagues and previously applied every calendar gate before
filtering the explicit fixture IDs.

The minimal repair in `research/shadow_model.py` requires complete calendars
for the selected fixture's own league. It retains the existing whole-source
pending/rejected QC stop. With no explicit target selector the former strict
all-league calendar behavior is unchanged. It does not admit a selected
fixture whose own calendar is incomplete or bypass any source QC.

## Reproduction and validation

`tests/test_shadow_target_scope.py` uses an owned temporary source Repository,
original-shaped packets, eight prior FT matches for each team and one future
NS fixture. No real provider or model is mocked in the positive route. Before
the repair that test returns `SHADOW_SOURCE_QC_STOP` at the unrelated league;
after the repair it returns one `UNVALIDATED_SHADOW` preview using the existing
CORE and finite, normalized market probabilities. Negative tests retain the
own-calendar and rejected-source gates.

The same tests exercise the existing `Service.capture` with those source
inputs in a separate owned prediction Repository. The test explicitly marks
the sports input synthetic. A prematch seal is created once and an exact retry
returns the same seal; there are no cohort assignments, calibrators, decisions
or bets. This demonstrates an existing callable seal route, not a live run,
historical prediction reconstruction, model training or independent validation.

Reproduce offline:

```sh
python -m unittest discover -s tests -p 'test_shadow*' -v
python -m unittest discover -s tests -p 'test_football_pipeline.py' -v
python -m unittest discover -s tests -p 'test_chat_source_sync.py' -v
python scripts/verify_release.py
```

The source Pipeline adapter bytes and all `src/sefirot`, MODEL_MODULES and
Policy bytes are unchanged. Existing original sources, QC records, receipts,
historical seals and fit permissions are not rewritten. The preview remains
read-only: no new forecasts/seals, calibrated P, EV, monetary permission or
execution. This patch is a candidate change and does not deploy a worker.

## Remaining integration gates

The existing source CLI can materialize sports inputs, but it does not invoke
`Service.capture`, reserve a cohort or append a durable prospective observation
plan. The current worker bootstrap invokes the preview only through its explicit
opt-in flag and only logs research output. A preview is not an immutable
prediction seal.

An honest prospective capture must use fresh, known-before-kickoff source
inputs and the current build's original `Service.capture` in a dedicated
authorized prediction ledger. If calibration/holdout evaluation is intended,
the selection/roles, market pool, model and evaluation protocol must be frozen
before new forecasts/outcomes are inspected. Existing viewed historical matches
cannot become an independent holdout simply by importing them or changing a
`model_fit_allowed` flag. Unknown data, missing histories and absent bookmaker
quotes remain explicit PASS/SHADOW blockers.
