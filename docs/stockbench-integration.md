# StockBench integration

The v0.27 inspection targets clean sibling commit
`ce8b2b3483590646ad3b650ac8221f43f76fd091`, remote
`https://github.com/ChenYXxxx/stockbench.git`, under Apache-2.0. The inspected
configuration uses USD 100,000, twenty U.S. equities, adjusted daily bars, a
seven-trading-day price feature window, two-day news lookback, fifteen-day
warmup, and a configurable SPY or per-symbol buy-and-hold benchmark. It exposes
cumulative-return, drawdown, Sharpe, and Sortino analysis. Transaction costs and
the exact evaluation interval are not established by that configuration and
must be declared per comparison.

The observed conceptual pipeline is portfolio state and market/news/fundamental
inputs, fundamental filtering, decision generation, structured action, then
simulated portfolio accounting. The MarketEvolver bridge instead converts each
observation to a bounded `ResearchContext`, labels every imported field
`external_unproven_input`, routes only to an approved Generalist or specialist,
optionally applies the skeptical reviewer, and maps the governed proposal to
StockBench's action shape. A reviewer rejection becomes `HOLD`; the bridge does
not grant tools or permissions.

Supported comparison manifests cover the native/reference agent, Generalist,
Specialist, Specialist plus Skeptical Reviewer, anonymized MarketEvolver, fixed
topology, and governed evolved topology. These are definitions, not completed
runs. MarketEvolver-native evidence provenance cannot be manufactured for
StockBench inputs, and historical company names and news can overlap model
pretraining. Offline cache mode reduces network variability but does not prove
historical visibility or eliminate contamination.

The adapter is inspected and schema-testable, but the benchmark is not marked
runnable until its dataset/provider environment and a complete fair-comparison
manifest are operator-approved.

The inspected checkout contains local cache files, but v0.28 does not accept
their presence as proof of coverage or historical visibility. A reviewed
dataset manifest with hashes, asset/date coverage, preprocessing, adjustment,
and information-cutoff semantics is required. The native command is
`python -m stockbench.apps.run_backtest` with pinned config, date range, and
DeepSeek profile. Expected outputs are reports and logs under `storage/`.

In v0.29 an isolated Python 3.12 environment successfully installed the
unchanged requirements and passed package/data-hub/backtest-module imports. The
native CLI help then failed inside Typer/Click option construction, so the
environment is `BLOCKED_DEPENDENCY`. No external file or dependency pin was
changed. The 6,583-file cache is `PARTIALLY_REPRODUCIBLE`, not point-in-time
proven; see [the audit](external-data-audit.md).

Version 0.30 resolved only the CLI environment incompatibility: Click 8.1.8
with the declared Typer 0.12.5 makes native help pass, with a clean `pip check`.
This is recorded as `ENVIRONMENT_COMPATIBILITY`; no source or dependency file
was changed. Dataset causality and the native legacy model profile remain
separate blockers, so successful CLI startup is not benchmark readiness.
