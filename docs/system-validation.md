# System validation

Controlled external validation is separate. `make validate` never contacts
external sources. After it passes, an operator may run
`make validate-live LIVE=YES`; see [live-validation.md](live-validation.md).
Missing required operator identification is a reported skip, not a false pass.

Run the complete deterministic validation with:

```bash
make postgres-up
market-evolver validate-system
```

The command emits a JSON report and returns nonzero if a critical suite fails or
is unavailable. It covers Ruff, strict mypy, offline tests with coverage,
PostgreSQL migrations/integration, DuckDB and Parquet, provenance and corruption
checks, historical replay, safety boundaries, topology replay, and NIS 2,000
paper-accounting invariants. A skipped PostgreSQL suite is reported as `FAIL`,
not `PASS`.

The deterministic end-to-end fixture records a content-addressed official raw
artifact and a provenance-linked checkpoint for each existing stage from source
through evidence, event, graph, company, macro/policy/news, fusion, research,
expert routing, hypothesis, experiment, backtest, signal, risk, simulated fill,
and portfolio snapshot. It is a validation scenario, not a recommendation or a
live execution path.

Cross-lab replay checks rumor, corroborating news, official confirmation,
company and macro context, geopolitical context, and a later correction at
multiple cutoffs. Separate fixtures reconstruct historical expert versions,
champions, routers, and topology; exercise governed challenger promotion and
rollback; and reject corrupted artifacts, Parquet hash mismatches, malformed
timestamps, missing provenance, invalid references, and inconsistent database
metadata.

Known limitations: the comprehensive scenario uses curated synthetic inputs;
it proves system contracts, not external API availability or economic validity.
Docker is required for the local PostgreSQL suite. SQLite tests provide fast
domain feedback but cannot substitute for the PostgreSQL migration and trigger
suite. Live APIs and external model providers remain intentionally disabled.
