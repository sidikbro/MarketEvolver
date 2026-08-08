# Hypothesis Testing

Version 0.16 separates three objects that must never be conflated:

1. A `ResearchHypothesis` describes an economic mechanism and falsifiable idea.
2. A typed `SignalDefinition` specifies exact observable fields, operators,
   values, and optional lookbacks.
3. A historical simulation applies validated execution and cost semantics.

Signal clauses cover event type, corroboration state, macro trend, fundamental
ratio, price momentum, claim reputation, and mechanism/exposure matches. They
are data structures, not executable Python; no `eval`, dynamic import, or
free-form model output enters the simulator. Each signal observation has a local
observation time and provenance, so future corroboration or fundamentals cannot
be backdated into an earlier decision.

Experiment specifications are content-addressed, immutable versions containing
the hypothesis/context, universe, benchmark, signal, entry/exit rules, holding
period, allocation policy, explicit costs, disjoint research/validation/test
windows, exclusions, parameters, code hash, and provenance. Validated specs
cannot be revised. Test-set access is append-only and blocks later parameter
changes.

The multiple-hypothesis registry records hypotheses generated, experiments
executed/rejected/reported, and preserves the denominator needed for later
data-snooping corrections. Current robustness helpers provide seeded bootstrap
intervals, sign-permutation baselines, sensitivity results, period splits, and
leave-one-period-out summaries. These diagnostics do not establish statistical
significance.
