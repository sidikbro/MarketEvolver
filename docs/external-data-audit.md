# External data audit

## StockBench cache

The inspected cache contains 6,583 files for 20 symbols: AAPL, AMGN, AMZN, AXP,
BA, CAT, CRM, GS, HD, HON, IBM, JNJ, JPM, MCD, MSFT, PG, SHW, TRV, UNH, and V.
Filename-derived indicator coverage is 2025-01-02 through 2025-07-31. Groups
are `corporate_actions`, `financials`, `news`, `news_by_day`, and
`stock_indicators`; metadata includes `api_source`, `cached_at`, `data_source`,
`start_date`, `end_date`, and `published_utc`.

Classification: `PARTIALLY_REPRODUCIBLE`.

The cache has no immutable retrieval/content-hash manifest, first-observed
timestamps, historical API visibility proof, raw bars behind adjusted
indicators, or complete filing/restatement availability. Publication timestamps
alone do not prove what was knowable at a cutoff. It is not accepted as causal
MarketEvolver evidence or as an exact-comparison dataset.

`market-evolver external data-audit` regenerates the structural audit without
ingesting or copying external data.

## TradingAgents requirements

The native default retrieves prices, indicators, fundamentals, and news through
Yahoo Finance; optional macro data through FRED; prediction-market context
through Polymarket; and sentiment through Reddit and StockTwits. Alpha Vantage
is an explicit alternative. Historical ticker/date input does not prove vintage
safety. Persistent memory is a contamination risk unless reset and declared.

Classification: `BLOCKED_DATASET` for a point-in-time comparison. No bounded
run was attempted because dataset proof and provider readiness must both pass.

## Fairness decision

The shared AAPL case remains unexecuted. StockBench also pins a retired
`deepseek-v3.1` profile; TradingAgents can select `deepseek-v4-flash`. Model,
information-set, and execution-timing differences are recorded, never silently
normalized.
