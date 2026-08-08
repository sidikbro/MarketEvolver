# Paper runtime

MarketEvolver v0.17 is simulation-only. It has no broker adapter, live-order type, credential
path, leverage, shorting, or derivative support. Runtime work occurs only when an operator invokes
an explicit step; there is no daemon.

The boundary is `SignalIntent → RiskEvaluation → PaperOrderCandidate → ExecutionDecision →
PaperFill`. A signal must reference either a validated experiment or an explicit operator approval.
Raw hypotheses and provider/model output cannot create orders. Evidence and market observations
must already be visible, causally ordered, and fresh at decision time.

Portfolio configuration is versioned and becomes immutable after activation. Account snapshots,
signals, risk decisions (including rejection), execution decisions, fills, and operator actions are
append-only. Each snapshot enforces `cash + marked positions = NAV`, non-negative cash and
non-negative holdings. Fill reconciliation fails closed.

Historical replay and forward-paper modes share the same explicit clock. Forward mode may advance
only to newly observed timestamps and cannot rewrite earlier decisions. v0.16 next-session and cost
semantics are reused. PostgreSQL is the accounting authority; immutable Parquet NAV exports support
larger DuckDB analyses without becoming a second ledger.

CLI controls are `paper create/start/step/status/positions/risk/pause/resume/stop`. Every mutating
control writes an operator audit record. `step` without admitted signals records a no-fill step.

Current limitations: no order-book simulation, intraday scheduling, corporate-action automation,
tax jurisdiction engine, optimizer, or background process. Benchmark values must be supplied from
point-in-time market data by the caller.
# Expert boundary

Expert agents cannot call the paper package or construct order candidates. An assessment must first
become a reviewed hypothesis and validated experiment signal before the deterministic governor can
consider it.
