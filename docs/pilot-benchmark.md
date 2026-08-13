# Bounded benchmark pilot

The proposed pilot is infrastructure validation, not a leaderboard. It uses
AAPL, 2025-04-01 through 2025-04-03, daily decisions, USD 100,000, whole-share
long-only behavior, and AAPL buy-and-hold as the benchmark. The controlled layer
uses next-open execution where supported and records any native timing mismatch.

MarketEvolver modes are deterministic baseline, General Market Researcher,
fixed relevant specialist, and specialist plus Skeptical Reviewer. Champion /
challenger learning and topology evolution are disabled. Three repeats use
seeds 3001, 3002, and 3003; all individual outcomes, mean, and spread must be
reported without choosing the best result.

The total pilot guard allows at most 12 model calls, 24,000 input tokens, 6,000
output tokens, USD 0.25 estimated cost, and 900 wall-clock seconds. Unpriced
usage fails closed. Missing financial, operational, research, or safety metrics
are `NOT_AVAILABLE`, never zero.

No pilot ran in v0.30 because `DEEPSEEK_API_KEY` was absent. Provider validation
reported `BLOCKED_PROVIDER`, with zero calls, tokens, latency, and cost. Running
StockBench or TradingAgents without the shared provider would not validate the
cross-system execution path. No observed return or winner exists.

The reproducibility package is
`config/external/v030-pilot-manifest.json`. It records repository pins,
environment/configuration hashes, proposed seeds and slice, limits, model
configuration, disabled learning features, and the blocked execution result.

## KTD-Fin follow-up

A [GitHub repository search](https://api.github.com/search/repositories?q=KTD-Fin)
on 2026-08-13 returned no repository identifiable as the financial benchmark
called KTD-Fin. The similarly named results were
unrelated student or game projects and did not carry a usable benchmark license.
KTD-Fin remains an unpinned methodology placeholder and is not integrated.
