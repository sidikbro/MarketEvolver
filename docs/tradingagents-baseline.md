# TradingAgents baseline

The v0.27 read-only inspection targets clean sibling commit
`a33fd4c0f134485a43553a2c23a63cb14adbd88f`, remote
`https://github.com/tauricresearch/tradingagents.git`, under Apache-2.0.

The inspected architecture has market, news, sentiment/social, and fundamental
analysts; bull and bear researchers; a research manager; trader; aggressive,
conservative, and neutral risk managers; and a portfolio manager. It includes a
provider abstraction plus persistent decision memory and later reflection. Its
input contract is centered on ticker and analysis date with provider-sourced
market, fundamental, news, and sentiment context. Output semantics culminate in
a structured buy/sell/hold-style decision. Exact capital, costs, execution
timing, data vintages, and backtest interval belong in each run manifest.

The external wrapper does not import or alter TradingAgents. It will execute
only after explicit operator approval, against the pinned clean sibling, without
a shell. An import boundary accepts only configuration and dataset hashes,
timestamps, decisions, portfolio-path hash, normalized reported metrics,
runtime, provider/model, legally retainable prompt hashes, seeds, environment,
and reproducibility-log hash.

Persistent memory can cross evaluation boundaries and therefore must be reset or
declared. A current provider snapshot is not evidence that data was visible on a
historical analysis date. Historical company names may leak through pretraining,
and claims about verified snapshots need independent provenance review.
TradingAgents is inspected but not runnable or evaluated in MarketEvolver v0.27.

In v0.28 the prepared native command is `tradingagents analyze --ticker <asset>
--date <date>`. Required artifacts are a cutoff-safe OHLCV snapshot,
news/fundamental snapshots, exact configuration, decision and portfolio paths,
and a reset/declared memory state. The local environment lacks its dependencies
and no verified dataset manifest or provider credential was available.

In v0.29 an isolated Python 3.12 installation passed imports, CLI help, and 14
selected native signal/date tests. The repository's `requirements.txt` is only
`.` and is working-directory dependent, so setup explicitly targeted the
sibling project and its development extra. DeepSeek V4 Flash is in the model
catalog, but the historical data paths do not prove an information-time
vintage. The comparison remains `BLOCKED_DATASET` after provider access returns.
