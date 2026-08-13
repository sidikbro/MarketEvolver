# External benchmark v0.28 results

Run assessment date: 2026-08-13. This is a blocker report, not a performance
leaderboard. No synthetic outcome replaces a blocked execution.

## Immutable setup

| Component | Version/profile | Status |
|---|---|---|
| MarketEvolver | v0.28 execution framework `61aff73` | deterministic validation only |
| StockBench | `ce8b2b3483590646ad3b650ac8221f43f76fd091`, Apache-2.0 | `BLOCKED_PROVIDER` and unverified dataset manifest |
| TradingAgents | `a33fd4c0f134485a43553a2c23a63cb14adbd88f`, Apache-2.0 | `BLOCKED_PROVIDER` and `BLOCKED_DATASET` |
| DeepSeek | `deepseek-v4-flash`, temperature 0, 512 maximum output tokens, 30-second timeout, three bounded retries | `BLOCKED_PROVIDER` |

`DEEPSEEK_API_KEY`, `POLYGON_API_KEY`, and `FINNHUB_API_KEY` were absent. No
credential value was read or persisted. The DeepSeek validation command made no
network request and returned `BLOCKED_PROVIDER`, with zero calls, tokens,
latency, and cost.

## Runnable preparation

StockBench has 6,583 local cache files, but no reviewed dataset manifest proving
that AAPL and the proposed dates are complete, point-in-time safe, or derived
under the same information cutoff. It requires adjusted Polygon daily bars,
point-in-time Finnhub news/fundamentals when those inputs are enabled, provider
configuration, and its Python dependencies. Its application import smoke test
was blocked because `typer` is not installed in the MarketEvolver environment.
The pinned StockBench config names a `deepseek-v3.1` profile; DeepSeek's current
official API has retired legacy aliases and exposes V4 models, so provider
compatibility must be supplied explicitly and recorded as a comparison mismatch.

TradingAgents requires historical OHLCV plus historical news/fundamentals whose
visibility is proven at the analysis cutoff, DeepSeek access, and its Python
dependencies. Two read-only native test collection attempts were blocked by
missing `langchain_core` and `pandas`. No sibling checkout was modified.

No compatibility patch was created. Both baselines remain unpatched; therefore
`PATCHED_BASELINE` does not apply.

## Proposed common case

The versioned proposed case uses AAPL from 2025-04-01 through 2025-04-03, USD
100,000, one decision after the prior close with next-open execution, zero-basis
point provisional costs, whole shares, DeepSeek V4 Flash at temperature zero, and a
same-fill AAPL buy-and-hold benchmark. News and fundamentals are excluded to
reduce information-set mismatch. This case was not executed because provider
and dataset proof are unavailable.

Planned MarketEvolver modes are Generalist, fixed relevant specialist, specialist
plus skeptical reviewer, and a named/anonymized pair. Topology evolution is
disabled. Mode/agent-call differences make the native and MarketEvolver plans at
best `PARTIALLY_COMPARABLE`; actual external input and execution contracts may
further downgrade them to `NON_EQUIVALENT` after execution-time audit.

## Results and accounting

| System | Repeats | Return/variance | Tokens | Provider cost | Result |
|---|---:|---|---:|---:|---|
| StockBench | 0/3 | not computed | 0 | 0 | `BLOCKED_PROVIDER`; dataset proof unresolved |
| TradingAgents | 0/3 | not computed | 0 | 0 | `BLOCKED_PROVIDER`, `BLOCKED_DATASET` |
| MarketEvolver Generalist | 0/3 | not computed | 0 | 0 | `BLOCKED_PROVIDER` |
| MarketEvolver specialist | 0/3 | not computed | 0 | 0 | `BLOCKED_PROVIDER` |
| Specialist + reviewer | 0/3 | not computed | 0 | 0 | `BLOCKED_PROVIDER` |

There are no cumulative return, excess return, drawdown, volatility, Sharpe,
Sortino, turnover, trade, safety, grounding, or reviewer metrics because no run
occurred. A zero shown for usage means no call, not a zero-cost successful run.
The profile records the 2026-08-13 official V4-Flash cache-miss input price of
USD 0.14/million tokens and output price of USD 0.28/million tokens. Cache-hit
discounts are not assumed by the estimator.

## Contamination and fairness limits

The proposed dates postdate many possible model training cutoffs, but the model
release date and documented cutoff were not independently established. AAPL is
named and may be memorized. Identifier masking and anonymization have not been
run. StockBench cache vintage provenance is not established. TradingAgents
memory must be disabled/reset and recorded before comparison. Price/news data,
execution timing, cost application, prompts, and agent call counts must be
audited from completed manifests before any winner claim.

## v0.29 bring-up addendum

On 2026-08-13, `DEEPSEEK_API_KEY`, `POLYGON_API_KEY`, and `FINNHUB_API_KEY`
remained absent. DeepSeek status is `BLOCKED_PROVIDER`; zero requests, tokens,
latency, and estimated cost were incurred. The preflight limit is two calls,
1,024 input tokens, 512 output tokens, and USD 0.01, and fails closed when usage
cannot be priced.

StockBench installation/imports passed but native CLI construction failed, so
its remaining state is `BLOCKED_DEPENDENCY`; its cache is only
`PARTIALLY_REPRODUCIBLE`, and its legacy model profile is a mismatch.
TradingAgents installation, imports, CLI help, and 14 selected native tests
passed, but comparison remains `BLOCKED_DATASET`. With the credential absent,
the primary decision for both comparisons is `BLOCKED_PROVIDER`. No minimal
performance run was attempted and no winner claim is made.
