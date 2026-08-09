# Expert evaluation

Every specialist benchmark has a General Market Researcher baseline using the same cutoff and, where
possible, the same evidence universe. Scorecards expose grounded/unsupported claims, contradiction
handling, calibration, mechanism coverage, hypothesis testability, denials, latency, tokens/cost,
failures, leakage, fabricated provenance, action attempts, capability violations, and generalist
delta. Simulated return is not the primary score.

Six deterministic fixtures cover specialist value, no added value, a better generalist,
disagreement, capability denial, and anonymized/pretraining-memorization caveat. Default tests use no
network provider. External evaluation reuses the explicitly enabled provider abstraction.

Approval defaults require three cases, zero critical violations, non-negative generalist delta, and
mechanism coverage of 0.5. Fabricated evidence, repeated leakage/action attempts, corrupted output,
or severe capability violations make an expert eligible for suspension from future routing.
Historical records remain unchanged.

Limitations include small synthetic benchmarks, no causal proof of specialist value, and provider
memorization that anonymization cannot fully eliminate. Review and experiment validation remain
mandatory.

Champion/challenger evaluation separates development, validation, protected challenge, and final
holdout data. Comparisons use paired cases and component metrics; safety vetoes dominate quality
gains. Repeated adaptive holdout use is rejected and automatic promotion remains disabled.
