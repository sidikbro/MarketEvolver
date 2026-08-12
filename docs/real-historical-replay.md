# Real historical replay

Version 0.25 adds a curated, immutable real-case catalog alongside the synthetic
benchmark. It validates temporal reconstruction and measurement; it is not
strategy optimization, financial advice, or evidence of a profitable process.

Every case separates research evidence, outcome-only market data, and
retrospective metadata. Research inputs must be `vintage_safe` and have a local
observation time and hash. BOI SDMX history is
`outcome_measurement_only`: it may be revealed after commitment but cannot enter
the historical research context. Current APIs and unretained pages are
`temporally_ambiguous` and never fill gaps.

The initial development catalog has seven cases and nine cutoffs:

| Case | Status | Reason |
|---|---|---|
| BOI January 2024 rate cut | Unusable | dated page was not locally observed/hashed in 2024 |
| BOI decision/later policy report | Unusable | later report is not a captured correction vintage |
| Quiet USD/ILS control week | Usable | no-event control and outcome-only FX measurement |
| October 2023 USD/ILS move | Unusable | no retained vintage-safe event/news input |
| Teva 2023 annual filing | Unusable | accession/fact vintage not captured locally |
| Israel December 2023 CPI | Unusable | CBS publication vintage not retained |
| October 2023 disruption | Unusable | article snapshot/edit history unavailable |

All are retrospective development cases and the selector already knew their
outcomes. No protected set is claimed. Cases were chosen for category/control
diversity, not return magnitude.

For each usable cutoff the harness seals six comparison manifests:
deterministic baseline, General Market Researcher, fixed specialist, specialist
plus skeptical reviewer, anonymized specialist, and named specialist. The same
context hash is used. Without a validated provider trace, provider-dependent
modes are `not_run:no_provider_trace`; output, latency, token cost, confidence
gaps, and reviewer effects are not invented.

```bash
make postgres-up
market-evolver market ingest-history boi asset.fx.usdils \
  --from 2023-10-01 --to 2024-02-15 --confirm-live
market-evolver replay real-report
```

Reports are ignored under `data/real_replay/`. Each report includes the
case/version, git commit, source and dataset references, context hashes,
expert/topology/prompt/provider versions, seeds, timeline, sealed hypotheses,
outcomes when verified runtime BOI data is present, and limitations. Raw source
payloads remain in ignored content-addressed storage.

The initial hypothesis is deliberately non-directional: measure USD/ILS without
claiming a tradable edge. Direction accuracy, specialist superiority, reviewer
improvement, named/anonymized leakage, and calibration therefore remain
inconclusive. Return is outcome measurement, not strategy profit.

The initial run therefore has one usable quiet control and six unusable event
cases. This is an evidence-capture gap, not a reason to backdate observation
timestamps. Future events become usable only after forward collection preserves
their original vintages.

Version 0.26 adds a backfill assessment for those six gaps. An eligible archive
proof may support a new case version, but never rewrites v0.25. At initial
release no historical vintage was recovered and no case was upgraded.
