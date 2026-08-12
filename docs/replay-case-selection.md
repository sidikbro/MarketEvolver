# Replay case selection audit

Retrospective selection can produce a benchmark containing only memorable
events or favorable outcomes. Every real case records why it was selected, the
selector, selection time, whether the outcome was known, and
development/protected status. Missing fields invalidate the case.

The v0.25 catalog was selected by the versioned specification on 2026-08-12.
Outcomes were already known, so all seven cases are development cases. They must
not be relabeled as protected evaluation. Future protected cases require
selection and sealing before outcomes are inspected.

Selection rules are:

- include quiet, ambiguous, conflicting, and no-material-outcome controls;
- prefer official dated releases and locally retained immutable vintages;
- do not choose solely for dramatic market movement;
- classify market history separately as outcome-only;
- mark unavailable vintage, article snapshot, filing timestamp, or equity
  history as `UNUSABLE_FOR_CAUSAL_REPLAY`;
- never repair a gap using present-day summaries or inference;
- record failures without tuning prompts, thresholds, experts, or topology
  inside the benchmark.

The small catalog supports engineering validation only. Aggregate rates are
descriptive and are not statistically meaningful.
