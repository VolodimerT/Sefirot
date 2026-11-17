# SEFIROT 4.5 — xG chronology and first prospective seal readiness

Base: PR #83, `7d8bb1e3a7f8dd76d9c3863f891932a55efaa342`.
No Work acceptance report was published in PR #83 comments, reviews, or
review threads; no local Work artifact was found. The defects below were
reproduced independently. Production and paid API endpoints were not called.

## Reproduced boundary failures

Two red regressions against the base candidate:

1. A source fixture with an earlier FT observation followed by a newer NS
   observation still supplied a historical label and xG to a later target.
   The qualifier now marks `SOURCE_STATUS_REVISED_AFTER_FT` and withholds its
   label/history. A new plan must await a trustworthy final observation.
2. A statistics packet containing only the prior match's *other* team still
   counted as xG/statistics for the target team. Historical metric references
   now require a matching target team and report only that team's metric types.
   A packet with both teams but xG only on the opponent also cannot claim xG
   for the target. Foreign team IDs remain excluded.

The existing and extended regression also excludes a statistic received
before its source kickoff, a live statistic received after kickoff but before
the first trustworthy FT receipt, one first imported after scan cutoff, and
one received after scan cutoff. Original source packets remain unchanged. The
field `expected_goals` stays an observed but unvalidated research field;
its unit, methodology and permitted use were not proven by the archived JSON.

## Read-only real source check: one upcoming EPL fixture

On 17 November, archive fixture `1557474` was saved as `NS` with kickoff
`2026-11-21T12:30:00Z`, EPL league 39/season 2026. Its **only** saved
fixture observation and first import are dated 18 October, roughly 30 days
old. The current CORE policy permits a target observation age of at most
1440 minutes. A saved NS status does not confirm today's status or kickoff.

The original packet is a full season response with 380 rows, including 280
future EPL members. `forward.create_plan` reserves every future NS fixture in
the declared league; slicing this packet into a one-fixture “original” would
falsify provenance. No original single-fixture packet exists in the archive
for the chosen target. The single-fixture forward path was therefore checked
on isolated synthetic data: `create_plan` reserved exactly one member, and
`capture_plan` returned `STALE_TARGET_OBSERVATION` with zero predictions and
zero bets when the original observation was stale.

Read-only archive joins find at most seven saved FT history fixtures for each
target team in the same league (all archived seasons), below the CORE minimum
of eight per team even before additional QC exclusions. Saved postmatch xG is
present for four home-team and one away-team FT fixtures; its semantics and
independent calibration remain unverified. These counts were computed from
the latest fixture receipt per ID, matching team IDs, FT status, local import,
source kickoff and pre-target availability. They are an upper bound, not
model-ready observations.

## Admission outcome

`NO_PROSPECTIVE_SEAL`: a fresh exact-match NS packet and at least one more
eligible FT history fixture for each team are absent. The source packet must
be obtained through the protected gateway in a separately authorized budget
window, archived with original receipt/hash and locally imported before the
one-match plan and before kickoff. The forward capture must then independently
pass identity, freshness and history gates. xG is optional for the current
goal baseline and may not be admitted without a documented definition and
separate validation. A raw CALIBRATION seal does not prove calibration or
value; HOLDOUT additionally requires a frozen non-synthetic fit. The archived
fixture cannot be turned into a forecast by editing its packet or backdating
the journal. PASS / stake=0 remains.

No live query, hosted write, production deployment, real bet, or main merge
was performed. Exact test/CI results are recorded in the draft PR after push.
