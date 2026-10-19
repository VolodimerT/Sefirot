# V4.0 P0: branch and CI inventory, 11.10.2026

Issue #33, full three attachments V4.0, repository audits 9 October,
forensic/model-check/ticket-ledger materials 10 October and corners shadow
11 October reviewed. Private source audits and receipts are not copied here.
Read-only original durable snapshot integrity checked; original 13/13 decisions
10 October are PASS class D, stake 0. This verifies archived journal content,
not accuracy, independent data provenance or new executions.

Inventory below was captured before changes. All listed HEAD objects fetched;
merge-base and diff paths computed. Full 52 exact-head job logs inspected.
An exact SHA push run can have another branch name containing the same commit:
checkout SHA was verified; branch label alone was not used as evidence.

| PR | HEAD | Declared BASE (= merge-base) | Merge-base with #22 | CI | Tests/job | Exact-head push run |
|---|---|---|---|---|---|---|
| #11 | `7d2356ca8d31` | `8e6a3ab81b93` | `053ad5a07c47` | 4/4 | 611 | [run 38090272868](https://github.com/VolodimerT/Sefirot/actions/runs/38090272868) |
| #15 | `ec98f41dd0cc` | `053ad5a07c47` | `ec98f41dd0cc` | 4/4 | 608 | [run 37782924973](https://github.com/VolodimerT/Sefirot/actions/runs/37782924973) |
| #16 | `503793b87e0e` | `ec98f41dd0cc` | `503793b87e0e` | 4/4 | 617 | [run 37785479004](https://github.com/VolodimerT/Sefirot/actions/runs/37785479004) |
| #17 | `167a5b703606` | `503793b87e0e` | `167a5b703606` | 4/4 | 632 | [run 37789734405](https://github.com/VolodimerT/Sefirot/actions/runs/37789734405) |
| #18 | `921307134a1e` | `167a5b703606` | `921307134a1e` | 3/4 | 648 | [run 37884311872](https://github.com/VolodimerT/Sefirot/actions/runs/37884311872) |
| #19 | `8a8e64ced208` | `921307134a1e` | `8a8e64ced208` | 4/4 | 654 | [run 37923336431](https://github.com/VolodimerT/Sefirot/actions/runs/37923336431) |
| #21 | `121a580143e8` | `8a8e64ced208` | `121a580143e8` | 4/4 | 716 | [run 37992654173](https://github.com/VolodimerT/Sefirot/actions/runs/37992654173) |
| #22 | `9b88d130e69e` | `121a580143e8` | `9b88d130e69e` | 4/4 | 730 | [run 38124172471](https://github.com/VolodimerT/Sefirot/actions/runs/38124172471) |
| #23 | `67e10930257b` | `121a580143e8` | `121a580143e8` | 4/4 | 768 | [run 38025971938](https://github.com/VolodimerT/Sefirot/actions/runs/38025971938) |
| #24 | `3707cbf2f2fc` | `67e10930257b` | `121a580143e8` | 4/4 | 801 | [run 38113246121](https://github.com/VolodimerT/Sefirot/actions/runs/38113246121) |
| #25 | `eb4f8f1c1ee2` | `7d2356ca8d31` | `053ad5a07c47` | 4/4 | 632 | [run 38091526334](https://github.com/VolodimerT/Sefirot/actions/runs/38091526334) |
| #26 | `c99351ca7902` | `ee433953e643` | `053ad5a07c47` | 4/4 | 687 | [run 38093906745](https://github.com/VolodimerT/Sefirot/actions/runs/38093906745) |
| #30 | `b7266fd60fdc` | `9b88d130e69e` | `9b88d130e69e` | 4/4 | 757 | [run 38124347645](https://github.com/VolodimerT/Sefirot/actions/runs/38124347645) |

#18 is 3/4, not green: Windows/Python3.11 PanelHttpTests
`test_only_valid_origin_and_session_token_can_process_jobs` raised
ConnectionAbortedError/WinError10053 before reading the HTTP response. This is
an observed archived CI failure, not proof of a gambling-model error or a
verified explanation of platform behaviour. Newer #19/#22 exact-head jobs
are green; this PR does not rewrite #18 or substitute an older green run.

## Isolated integration sequence

1. First P0 contract targets exact #22, not main, to read the original ledger
   and reuse its runtime infrastructure. New code is outside src/sefirot.
2. #11 -> #25 is a different corners branch. #15--#19--#21--#22 stack begins
   at the older #11 ancestor, not the current #11 HEAD. Reconcile overlapping
   source and identity changes explicitly in a later isolated integration PR;
   do not silently replace old forecasts or code hashes.
3. #23 -> #24 branches from #21, alongside #22. It adds provider evidence/QC,
   not automatic attestation for JSON in this P0. Full small-observation-v2
   and complete eligible-league denominator are the next task.
4. #26 uses a separate ARENA base. Keep diagnostic/referee/correlation rules
   research-only and assess their incremental errors on independent samples.
5. #30 and previous #32 are siblings above #22. The current P0 does not merge
   them. A later gateway integration must invoke this verifier, bind trusted
   fixture scope, attest current status and quote revisions and measure full
   transport latency before claiming all-chat deployment or LIVE capability.

Frozen code/model identities for every inventoried head were computed directly
from its git blobs with the canonical identity algorithm. The public report
lists only build/CI aggregates; raw journal exports stay private.
Selected P0 baseline identities:

- CORE 2.4.2; code_hash `5bde1cbf96efab4bfd3890c4802f86a14f193564bdd047e4db78e1fc4f6fe95f`.
- model_hash `46f1c991a2ee93a2d68a0ae9c1b091b866660501980f52c2456a83bf96ba6617`.
- policy_hash `5d92a9c98c13df0d313b8ef9f59605e93482b2eeb7f31f91f5031969871becd9`.
- All 46 Python source files unchanged; manifest SHA256
  `d2db17abcc47c7498d59af6e9bc935b9ca5da65055c276141105b8b3a71ab66b`.

## Findings and unimplemented dependencies

The immediate failure is outside CORE: free-form chat research was being
presented as a replacement for original PASS. A versioned structure alone
cannot authenticate itself; the verifier must read trusted original records.
The pre-change reproduction of the new regression suite failed at the absent
verifier module. This demonstrates a missing verification boundary, not a
claim that Service.decide had returned BET in those 13 archived cases.

Source-backed current phase, exact bookmaker quotes, combined Builder prices,
full-league count history/referee rules and independent holdout are absent.
Seen eight-match goal symptoms and correlated tickets are not independent new
evaluation data. Never use them to change baseline lambdas or claim edge.
Cashout/PENDING/source proposals stay distinct from settled model outcomes.

First PR stops at the requested P0 checkpoint. Next: observation-v2/full-league
QC; then corners; cards/referee; SHOTS/SOT; fouls; exact odds >=2 and same-match
Builder quotes; market-specific chronology/calibration/independent holdout.
Prospective denominators and error-rate/latency gates must be fixed before
outcomes. No provider request, subscription, production deploy or main merge.
