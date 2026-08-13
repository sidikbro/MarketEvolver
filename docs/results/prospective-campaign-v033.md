# Prospective governed research campaign v0.33

The campaign definition was sealed on 2026-08-13 before any v0.33 outcome
evaluation. This release adds experiment governance, not another agent
architecture, and creates no trading or paper-runtime action.

## Sealed definition and sampling

Campaign `v033-prospective-2026q3` is sealed as
`prospective-campaign:sha256:bd64e9b5f8ed3b91d09f559089538de7dce36a7062152b11af171fe8aa03a045`.
Its controlled universe is only `pair.usdils`, its horizon is seven days, and
its model is the already discovered `deepseek-v4-flash`. Mondays are quiet
controls; Tuesdays and Thursdays are scheduled observations. Eligible official
events and corroborated-news cases may enter only under the sealed policy.

Seven cases are scheduled from 2026-08-13 through 2026-08-27: five ordinary
scheduled observations and two quiet controls. At this initial report, one
existing case is eligible, six have not reached their observation date, and
zero are silently omitted. Evidence-gate failures will remain in the ledger as
`BLOCKED_EVIDENCE` and count in campaign totals.

## Research and control policy

Every newly eligible context uses identical evidence and cutoff for the
generalist, fixed specialist, and specialist plus skeptical reviewer. A
deterministic structured-evidence baseline is predeclared. Each mode may create
at most one hypothesis per case. Negative controls are expected to produce no
hypothesis or `INCONCLUSIVE`; they are not scored for always predicting.

The v0.32 sufficiency gate remains unchanged. The deterministic entity registry
binds `il.boi` to Bank of Israel and rejects claims expanding it to Bank of
Ireland before acceptance, independent of reviewer judgment.

## Initial commitment ledger

The v0.32 commitment
`sealed-research-commitment:sha256:36da4d76d82175263822f4220b47884c82a15e58b159287c90e14d0a6d5c14e3`
is registered first with its original creation provenance and unchanged content.
It remains `AWAITING_OUTCOME` until 2026-09-01. It is marked
`LEGACY_REGISTERED_NOT_V033_EVALUABLE`: v0.32 did not predeclare numeric outcome
thresholds and its BOI wording retains the entity ambiguity exposed by the
audit. Adding thresholds now would be retrospective reinterpretation, so its
eventual outcome cannot enter v0.33 hypothesis-performance metrics.

No future price, later evidence, outcome annotation, or interim trading
performance is present in the ledger.

## Pre-outcome quality and efficiency

The inherited paired v0.32 context had 5 `SUPPORTED`, 6
`PARTIALLY_SUPPORTED`, 2 `UNSUPPORTED`, and 0 `CONTRADICTED` claims. Both
unsupported claims were BOI-to-Bank-of-Ireland expansions. The model reviewer
caught 0 and missed 2; deterministic entity validation catches both. With no
reviewer rejections, reviewer precision is undefined and recall is 0%. No
supported claim was incorrectly rejected and no contradiction was available to
catch.

Inherited provider accounting is 4 calls, 3,110 input tokens, 16,443 output
tokens, 13,813 reasoning tokens, 2,630 visible tokens, 148,157 ms, and
$0.005039 estimated cost. Thirteen claims were emitted, but accepted-claim
efficiency is not recomputed from the legacy run because its mode-level
post-entity-gate acceptance was not recorded prospectively.

No new live evidence or model call is represented in this initial sealed
campaign record. Archive growth therefore remains the v0.32 baseline: 76,364
raw bytes downloaded, 33,760 normalized bytes, four live vintages, five unique
content-addressed artifacts, and zero revisions. Raw third-party content is not
committed.
