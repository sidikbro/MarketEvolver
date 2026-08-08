# Macro Intelligence Lab

## Point-in-time release model

`MacroObservation` is an immutable source release, not current truth. It keeps
the described period separate from publisher time and the locally generated
first-observation time. A later correction points to its predecessor and never
updates it. Queries at cutoff `T` select the newest release for each period and
seasonal-adjustment class that was locally visible by `T`.

Supported categories cover inflation, rates, employment, activity, housing,
consumer demand, trade, tourism, industrial production, credit, government
spending, energy, FX context, and a technology-capex placeholder. Units use a
small validated vocabulary; raw provenance and parser version are mandatory.
Hebrew and English labels are stored independently.

## Expectations and surprises

Expected value, expectation source, and expectation observation time are an
atomic group. The expectation must have been visible by publication. When it is
absent, status is explicitly `unknown` and surprise is `null`; direction alone
is never treated as surprise. When valid, surprise is the deterministic
actual-minus-expected difference in the same declared unit.

## Sources

The existing reviewed Bank of Israel exchange-rate and policy paths remain
enabled and can supply macro context through governed transformations. CBS is
registered but disabled: v0.11 found no sufficiently fixed contract proving
release vintages and revision visibility for a narrow CPI ingestion path.
FRED, ECB, World Bank, OECD, and EIA are registered as disabled reviewed-source
candidates. Their current APIs must not be used to imply historical visibility.

The CLI accepts governed local JSON observation envelopes. This enables offline
testing and curated imports without claiming that an external connector is
production-ready.

## Limitations

- A locally unseen initial vintage cannot be reconstructed from a current API.
- Observation-period strings are preserved, not converted into inferred release
  dates.
- Cross-source units and seasonal-adjustment methodologies are not normalized.
- No macro series is converted into an investment recommendation.
