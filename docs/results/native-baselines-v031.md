# Native external baselines v0.31

These runs are operational and architectural observations under different
information regimes. They are not a leaderboard and do not establish causal or
information-set equivalence.

## A. StockBench native

Classification: `NATIVE_ONLY`. Controlled comparison classification:
`NON_EQUIVALENT`.

The pinned checkout is
`ce8b2b3483590646ad3b650ac8221f43f76fd091`. The only permitted compatibility
change is the documented Typer 0.12.5 / Click 8.1.8 environment resolution; no
source patch is permitted. Its checked-in native model is
`deepseek-v3.1-250821`. A v4-flash profile may be supplied only through the
framework's supported runtime configuration interface and remains a model
configuration difference.

The cache manifest is retrospective. Every file observed as consumed is hashed,
but `historical_vintage_proof` remains false.

One AAPL decision-day infrastructure run completed for 2025-04-03. StockBench
ignored the requested single-agent mode and used its dual-agent path. It made
three DeepSeek calls: 6,362 input tokens, 8,109 output tokens, 84,360 ms summed
provider latency, and USD 0.003160 estimated cost. The decision-agent call used
its full 4,096-token allowance but returned no visible content; StockBench
filtered that malformed result and recorded `HOLD`. It also made a report call
despite the no-summary request. The result is
`SINGLE_RUN_INFRASTRUCTURE_VALIDATION`, not a stability result.

The syscall-derived retrospective manifest contains 1,802 successfully opened
cache files. StockBench scanned the 1,797-file news cache while selecting five
AAPL news items; the manifest records all files it opened. Native financial
outputs were zero cumulative return, zero drawdown, zero trades, zero turnover,
and zero transaction cost for the one-day HOLD path. Benchmark return,
volatility, and excess return are `NOT_AVAILABLE`.

## B. TradingAgents native

Classification: `NATIVE_ONLY`. Controlled comparison classification:
`NON_EQUIVALENT`.

The pinned checkout is
`a33fd4c0f134485a43553a2c23a63cb14adbd88f`. Dynamic market, fundamentals,
news, and sentiment inputs require request-time metadata and response hashes.
Those observations do not prove the response was historically visible at the
analysis date.

One AAPL/2025-04-03 run was attempted with only the market analyst selected and
the native researcher, trader, risk, and portfolio-manager graph unchanged. It
created and hashed an AAPL Yahoo Finance cache snapshot and recorded ten
DeepSeek response hashes, but ended before producing a decision envelope.
TradingAgents did not expose token usage through this path. Because usage and
cost could not be priced, the cost guard failed closed: no retry and no repeats
were run. Status: `FAILED_EXTERNAL`.

## C. MarketEvolver governed reference

Classification: `GOVERNED_REFERENCE`. Generalist, specialist, and specialist
plus skeptical-reviewer modes retain MarketEvolver's normal point-in-time and
provenance requirements. They are not forced onto an external information set.

No governed reference was executed. The retained real-replay catalog has no
eligible point-in-time evidence set for these three modes; substituting
retrospective external data would weaken MarketEvolver's normal provenance
rules. Status: `BLOCKED`; zero provider calls.

## D. Operational comparison

No winner field is defined. Native systems retain their intended protocols and
all results are described as observed under different information regimes.

StockBench completed one infrastructure run. TradingAgents failed before a
decision. MarketEvolver remained blocked at its evidence gate. No cross-system
financial ranking or winner can be calculated.

## E. Cost comparison

Each system fails closed above 100 provider calls, 250,000 input tokens, 100,000
output tokens, USD 0.25 estimated provider cost, or 900 seconds. Missing or
unpriced usage cannot pass the guard.

StockBench used USD 0.003160. TradingAgents made ten observed provider calls,
but native token and cost accounting was unavailable; its total is therefore
`NOT_AVAILABLE`, not zero. The governed reference made zero calls.

## F. Architecture complexity

Run envelopes record active agents, LLM calls, tool/data calls, calls per
decision, tokens per decision, latency per decision, and provider cost per
decision. Unobservable values are `NOT_AVAILABLE`.

StockBench effectively used three active LLM roles/calls for one decision
(filter, decision, report), 14,471 tokens per decision, and USD 0.003160 per
decision. TradingAgents recorded ten LLM responses before failure; exact active
node count, tokens per decision, and cost per decision are `NOT_AVAILABLE`.

## G. Data/provenance limitations

StockBench cache hashes establish reproducibility of consumed bytes, not causal
vintage. TradingAgents runtime response hashes establish what the run observed,
not when a vendor first made the data available. External native runs remain
`NATIVE_ONLY`; controlled comparisons remain `NON_EQUIVALENT` even after a
successful execution.

Immutable artifacts are under `config/external/v031-runs/`. External checkouts
were verified clean at their pins after execution. Runtime outputs remain in
isolated `/tmp` workspaces and are represented in committed manifests by hashes,
sizes, configuration, timing, and observed failures.
