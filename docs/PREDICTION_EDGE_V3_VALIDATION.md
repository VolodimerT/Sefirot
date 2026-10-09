# V3 validation, 2026-10-09

Base: `8a8e64ced20800f64454089c65b48ff501523cc6` (#19).

- Unchanged baseline regression: 654 tests passed before edits.
- Final full release: **716/716** tests, including **62** new numerical/anti-leakage cases.
- `python scripts/verify_release.py`: PASS; demo replay_matches=true, integrity=true.
- `python scripts/prediction_edge_v3.py --output-dir reports`: zero real fixtures; KEEP_SHADOW.
- `git diff --check`: PASS. Canonical `src/sefirot`, config, CI workflows byte-identical to base.
- CORE code hash: `5bde1cbf96efab4bfd3890c4802f86a14f193564bdd047e4db78e1fc4f6fe95f`.
- CORE model hash: `46f1c991a2ee93a2d68a0ae9c1b091b866660501980f52c2456a83bf96ba6617`.
- Reports from earlier releases were restored rather than rewritten; new evidence is in V3 files.
- Published commit SHA and all four GitHub CI jobs are recorded in the draft PR body.

Tests cover DC correction and conservation, zero/extreme rates, common market projections, PUSH/VOID, missing histories, fit convergence, receipt/season/profile/target leakage, viewed-TEST/HOLDOUT overlap, invalid simplexes and market universes, paired date clustering, coverage, calibration coherence, unverified quotes, CLV and correlated Builders, and ARENA false-veto diagnostics.

These are software tests. Real raw/calibrated model Brier/log loss, market EV/CLV and ARENA benefit remain unmeasured. Next: original archive/ledger binding, fixed future cohort enrollment, real quotes and prospective paired evaluation.
