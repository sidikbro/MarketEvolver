# Historical Backtesting

The v0.16 engine is a research simulator, not a trading system. It supports only
long-only positions, cash, daily or event-driven decisions, and single-position,
fixed-notional, or simple equal-weight policies. There is no broker, order API,
margin, shorting, leverage, derivatives, portfolio optimizer, or live execution.

## Point-in-time execution

Market observations come from the immutable v0.10 Parquet catalog and are read
through DuckDB. Asset identity, benchmark, calendar sessions, corporate-action
review, dataset hashes, and observation cutoff are checked before simulation.
An after-close signal cannot use that session's close or open. `next_open`,
`next_close`, and `next_valid_session` select a strictly legal execution point.
Missing prices, unknown execution semantics, unreviewed survivorship, incomplete
corporate actions, benchmark mismatch, and future signals fail closed.

Exit choices are fixed holding period, end of window, observed event
invalidation, simulation-only stop loss, or simulation-only take profit. Path
records retain entry/exit, quantity, prices, realized return, benchmark-relative
return, maximum favorable/adverse excursion, holding period, and each cost.

Results retain gross/net/benchmark/excess return, volatility, drawdown, Sharpe,
Sortino, hit rate, turnover, costs, signal/trade/skip counts, rejection reasons,
NAV and position histories. Reproducibility metadata includes Parquet hashes,
dataset/source versions, experiment and parameter hashes, code version, seed,
rows, bytes, and provenance.

Baselines are cash, benchmark buy-and-hold, equal-weight universe, momentum,
mean reversion, deterministic event, and deterministic macro rules. The
false-rumor safety fixture compares first-social, independent-corroboration,
official-confirmation, and no-trade gates. Its synthetic values test governance,
not expected returns.

Known limitations: v0.16 uses daily OHLCV rather than an order book, stop/take
levels are checked on available bars, multi-position allocation is deliberately
simple, walk-forward output is a deterministic window schedule, and exchange
calendars are only as complete as the ingested session dataset.
# Paper continuation

Validated v0.16 experiments may emit admitted signals into v0.17 paper portfolios. The paper clock
uses the same next-session, commission, spread, slippage, FX, and share-fraction semantics, while
persisting each pre-execution risk decision. Historical replay and forward paper runs therefore use
one causal boundary; neither may revise an earlier decision.
