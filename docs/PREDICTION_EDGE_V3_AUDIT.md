# PREDICTION EDGE V3 — P0 audit, 2026-10-09

## Verified starting point

Base: draft PR #19, `feature/calibration-multiseason-collector-20261008`,
`8a8e64ced20800f64454089c65b48ff501523cc6` (tree
`df207db40751240330dd36c216d2e4e2682081a5`). Local baseline: 654 unittest tests PASS.
`main` is `96dd95861be6c11bbc450432ca280f9a4d2efd3f`; it is not #19.
GitHub REST open-PR inspection confirmed #11–#20 are draft, not merged (no #10).
#19 depends on #18 → #17 → #16 → #15 → #11. ARENA #12 → #13 → #14 is separate.
#20 vector-first audit branches from #18, not #19; it adds an independent script,
not a new trained football model. None of those parallel branches were merged here.

## Findings: defects, limitations and hypotheses distinguished

| ID / severity | Evidence and reproduction | Impact / disposition |
|---|---|---|
| D1 HIGH — cross-contract calibration inconsistency | `src/sefirot/probability.py:122–179`: buckets and posterior updates are separate per exact contract. Construct HOME and AWAY 1X2 bins with 20 wins each and raw win=.4: each becomes 20.8/22=.94545, although mutually exclusive. This can occur when bucket training subsets differ; it is not a claim that this occurred in real forecasts. | Mathematical counterexample, not measured field frequency. CORE preserved; research score-temperature calibration changes one distribution and projects all markets from it. Existing v4 posterior is not copied into candidate models. |
| L1 HIGH — independent goals / no fitted team effects | `probability.py:28,84–120`: product Poisson, arithmetic averages of own attack/opponent defense, pooled venue history. `schedule_trace` explicitly not used in probability. | Hypothesis: ridge team effects and low-score dependence may help. DC_DYNAMIC_V1 implements this in shadow; no observed accuracy gain. |
| L2 HIGH — sparse reliability | `probability.py:122–179`: profile × exact line × five WIN buckets; minimum 20. No league in bucket identity. | Pooling leagues within a profile may hide segment errors. New benchmark separates league/profile; classwise bins and ECE retain n. Temperature is a separate small-grid hypothesis. No claim of reliable per-fixture confidence from 20 observations. |
| B1 BLOCKER — real prospective evidence absent locally | No user archive/ledger supplied to this checkout; credential resolver reports missing provider keys. Historical `docs/FORWARD_SCORECARD.md` says 0/17 scored; `reports/FROZEN_EFFECTIVENESS_AUDIT_20261006.json` is already-viewed history. | Data availability, not software defect. No sporting network call, no claim of fresh suspension or restored API. Report fields are 0 or null. |
| L3 HIGH — no unseen reuse of 380-match TEST | `reports/FROZEN_EFFECTIVENESS_AUDIT_20261006.json`; prior SOS won some contracts and lost others. | Do not refit or select on this set. Manifest rejects ID overlap with viewed TEST. New holdout has not yet been registered. |
| L4 MEDIUM — first-observed history limits | `sports_archive.py:146–182` binds first FT receipt and rejects conflicting final scores. `goal_model.py:35–43` requires prior receipt before historical kickoff. | Correct anti-leak behavior: downloading old seasons today cannot reconstruct what was known then. SOS frozen-opponent features often shrink to priors without old receipts. V3 retains this limitation. |
| L5 MEDIUM — Builder score domain coupling | `builder_research.py:64–85` accepts only scores 0..35. V3 candidates use 0..50 with explicit tail bound. | Existing Builder cannot silently consume new distributions. Research builder uses shared cells across its validated domain; production module unchanged. |
| B2 BLOCKER — joint price absent | `builder_research.py:139+` compares singles, does not supply a verified combined quote. | Correct existing behavior. V3 keeps builder_ev=null / UNPRICED, even when joint probability exists. |
| L6 HIGH — ARENA provenance and selection bias | PR #14 `scripts/arena_control_forward.py:1–125` has original/naive/arena hypothetical arms and self-attested plan fallback; PR #13 retains missing captures. | Number of reviewers is not independent evidence. Added separate eight-role veto ablation, phi overlap and CORE/candidate ± ARENA coverage. No integration with parallel PR, no proven benefit. Top-class errors are not a proxy for betting profitability. |
| L7 HIGH — research records are self-attested | V3 seals/checksums validate internal integrity, not authorship or real first-observed time. | All outputs remain KEEP_SHADOW. Binding fitted candidates/calibration to original repository/packet receipts is an explicit remaining integration task. |
| L8 MEDIUM — inference uncertainty unavailable | Rate stress in `probability.py:106–117` is sensitivity, not interval coverage. | Paired date-cluster bootstrap quantifies cohort metric uncertainty, not a model probability interval. Comparator does not manufacture lower bounds; without supplied bounds it returns NO_DATA. |

## What was checked and left intact

- `evidence.eligible_history` validates result chronology, duplicate IDs, exact league/profile,
  receipt cutoff and source eligibility. These are real safeguards, not missing features.
- `_payoffs.py:49–89` settles DNB/integer lines with PUSH and EV = win*(odds−1)−loss.
- `markets.py:41+` requires complete partitions for no-vig comparisons; one price is explicitly
  a break-even proxy. New comparator additionally requires fixture ID and explicit verification.
- `data_session.py:191–207` declares the seasonal query universe before collection.
- `sports_archive.py` retains first receipt; `forward.py` separates cohort/capture/result jobs.
- `calibration_fit_gate.py` checks original ledger and API receipts before fitting. New candidate
  records are NOT yet routed through that production provenance gate.
- No `src/sefirot` module, Policy, identity list, ledger, seal or money cap was edited.
  The old CLI does not import research. Baseline wrapper is bit-for-bit output-equal to `estimate`.

## Reproduction

`python -m unittest discover -s tests -p test_prediction_edge_v3.py`

Full regression and final commit CI are recorded in the draft PR. Synthetic tests establish
implementation properties only. No fresh sporting forecast superiority is established.
