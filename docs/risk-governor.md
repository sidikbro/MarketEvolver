# Deterministic risk governor

The risk governor is ordinary typed Python with immutable policy inputs. It imports no LLM or
provider package. Models can propose research, but cannot set permissions, alter limits, recover a
portfolio, or execute a paper fill.

The built-in NIS 2,000 experimental policy is conservative, configurable by replacement with a new
immutable policy, and is not claimed to be financially optimal:

- maximum position 25%, single order NIS 400, gross exposure 70%
- sector exposure 35%, foreign-currency exposure 50%, daily turnover 40%
- at most three trades and three concurrent positions; retain 30% cash
- daily loss 3%; new-entry restriction at 6% drawdown; rolling 8%; full halt 12%
- two corroborating evidence records; market data no older than 24 hours
- equities and ETFs only on XTAE, XNYS, XNAS, or ARCX
- maximum strategy allocation 40%
- expected cost/order at most 3%; expected cost/NAV at most 1%

Risk outcomes are approved, resized, rejected, or portfolio-halted. Every non-approved result has
reason codes and can carry current/requested/allowed exposure attribution. Limits cover position,
sector, currency, cash reserve, gross exposure, turnover, trades, evidence, freshness, allowlists,
strategy validity, costs, and drawdown.

The kill-state order is NORMAL, ENTRY_RESTRICTED, PAUSED, HALTED. State may tighten automatically;
it never relaxes automatically. Recovery requires an explicit audited operator action. Corrupt
accounting, causal/provenance failures, impossible prices, or excessive rejection floods fail closed.
Missing sessions, benchmark data, and corporate-action interruptions must be rejected by the
execution adapter before a fill.
