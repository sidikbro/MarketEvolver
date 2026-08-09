# Champion/challenger governance

Each expert has one current champion derived from an append-only registry, zero or more challengers,
and retained historical versions. A challenger applies a small diff to one parent; it never silently
replaces the champion.

Development and validation cases permit iteration. Protected challenge cases and the untouched final
holdout require append-only access audits. Final holdout access defaults to once per challenger and
manifest. Repeated reuse, excessive challenger search, and repeated cases are anti-overfitting
signals. Historical replay proposals cannot inspect future outcomes.

Champion and challenger use identical cases, cutoffs, contexts, provider/model where possible, tool
capabilities, and execution limits. Reports contain per-case deltas, win/tie/loss, effect size, and a
deterministic paired-bootstrap interval only at adequate sample size. Insufficient samples are not
described as statistically significant.

Promotion eligibility requires multiple cases, no safety regression/leakage/fabrication/action
attempt, grounded-claim non-inferiority, domain improvement, reviewer stability, and bounded cost.
Safety veto overrides all performance. Promotion then requires a separate governance action.

Rollback points the registry to a retained prior champion and records actor, reason, time, and
affected sessions. It does not alter outputs produced by the degraded version. Monitoring may emit
`REVIEW_REQUIRED`; it never automatically replaces a champion.
