# Research replay benchmark

The original benchmark remains synthetic and deterministic. The v0.25
real-case catalog is separate, retrospectively selected, and must not be pooled
with synthetic metrics or called a protected evaluation set. Provider-dependent
comparison metrics remain inconclusive without validated provider traces.

Version 0.16 adds seven non-research baselines plus a false-rumor safety fixture
comparing first social observation, independent corroboration, official
confirmation, and no trade. Reports expose delay cost, false-positive exposure,
return, and drawdown separately; they do not label a simulation as profit or an
investment recommendation.

## Versioned cases

`ReplayCase` fixes the entity/assets, cutoff, horizon, evidence-manifest ID,
benchmark, expected output schema, evaluation protocol, and dataset version.
The initial `curated-replay-cases/1` suite contains seven cases:

1. USD/ILS movement;
2. Bank of Israel policy event;
3. company filing;
4. news event;
5. conflicting evidence;
6. revised evidence;
7. quiet/no-event control.

These are format and replay fixtures, not a statistically representative market
sample. No large historical dataset is downloaded into the repository.

## Research modes

Every case supports no-information, momentum, mean-reversion, deterministic
event rules, deterministic fundamentals, LLM research, and LLM plus skeptical
review. Deterministic modes describe observations or test hypotheses; they do
not emit BUY/SELL instructions. LLM modes require the v0.9 validated provider
and reviewer traces before meaningful evaluation.

Each mode can run with named and anonymized identities. Paired run records bind
the two results. The mapping remains outside model-visible context. A measured
gap is diagnostic and cannot establish that pretraining leakage was eliminated.

## Metrics

The report schema includes hypothesis-validity, reviewer-rejection,
unsupported-claim, provenance-failure, temporal-leakage, calibration,
directional-accuracy, benchmark-relative outcome, and named/anonymized-gap
metrics. Rates use persisted runs as their denominator and must be interpreted
with case counts and missing evaluations.

```bash
market-evolver benchmark run
market-evolver benchmark report
```

`benchmark run` creates immutable commitments and named/anonymized run pairs.
Outcome evaluation requires market observations through each matured horizon.

## Known limitations

- Seven curated cases cannot support general performance conclusions.
- Dataset version 1 does not reconstruct index constituents or delisted peers.
- Directional accuracy is absent unless explicitly requested and labeled.
- Calibration requires enough matured hypotheses; the empty report is not a
  model-quality result.
- LLM and reviewed-LLM placeholders are not silently substituted with rules.
