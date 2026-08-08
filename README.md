# MarketEvolver

MarketEvolver is a governed financial-market research laboratory. Version 0.11
adds immutable revision-aware macro observations, deterministic multi-horizon
trend intelligence, and point-in-time macro replay.

This repository intentionally contains **no trading bot**, broker integration,
order placement, leverage, options, or real-money execution capability.

## Development

```bash
python -m pip install -e '.[dev]'
pytest
```

Set `MARKET_EVOLVER_DATABASE_URL` to an explicit PostgreSQL URL before database
startup or migrations. TLS is added by default when absent. Set
`MARKET_EVOLVER_ARTIFACT_ROOT=/mnt/marketevolver` to relocate raw storage without
code changes.

```bash
market-evolver source list
market-evolver ingest boi --dataset representative-exchange-rates
market-evolver ingest-status
market-evolver storage-telemetry
market-evolver event list
market-evolver event show <event-id>
market-evolver event replay --at 2025-01-02T12:00:00+00:00
market-evolver event report
market-evolver entity seed
market-evolver entity list --at 2025-01-02T12:00:00+00:00
market-evolver entity resolve "בנק ישראל" --at 2025-01-02T12:00:00+00:00
market-evolver graph neighbors country.israel --at 2025-01-02T12:00:00+00:00
market-evolver graph trace-event <event-id> --at 2025-01-02T12:00:00+00:00
market-evolver news source-list
market-evolver news ingest bbc-business
market-evolver news replay --at 2025-01-02T12:00:00+00:00
market-evolver news candidates
market-evolver news quarantine
market-evolver policy source-list
market-evolver policy ingest boi-interest
market-evolver policy replay --at 2025-01-02T12:00:00+00:00
market-evolver policy candidates
market-evolver company seed
market-evolver company list
market-evolver company show nice --at 2025-01-02T12:00:00+00:00
market-evolver fundamentals show nice --at 2025-01-02T12:00:00+00:00
market-evolver filings list nice
market-evolver exposures show nice --at 2025-01-02T12:00:00+00:00
market-evolver research build-context nice --at 2025-01-02T12:00:00+00:00
market-evolver research hypothesize nice --at 2025-01-02T12:00:00+00:00
market-evolver research review <hypothesis-id>
market-evolver research trace <trace-id>
market-evolver market seed-assets
market-evolver market ingest observations.json --dataset-version internal/1
market-evolver replay seed-cases
market-evolver replay run company_filing --mode event_rules
market-evolver benchmark run
market-evolver benchmark report
market-evolver macro source-list
market-evolver macro series il.cpi.headline --at 2025-01-02T12:00:00+00:00
market-evolver trends calculate il.cpi.headline --at 2025-01-02T12:00:00+00:00
market-evolver trends replay --at 2025-01-02T12:00:00+00:00
```

External ingestion also requires `network_access = true` in trusted runtime
configuration. CBS and TASE/MAYA are registered but intentionally disabled.

See [Architecture](docs/architecture.md), [Threat model](docs/threat-model.md),
[Data sources](docs/data-sources.md), [Event Observatory](docs/event-observatory.md),
[Knowledge Graph](docs/knowledge-graph.md), [News Lab](docs/news-lab.md),
[Government Lab](docs/government-lab.md),
[Company fundamentals](docs/company-fundamentals.md),
[Research intelligence](docs/research-intelligence.md),
[Market data](docs/market-data.md), [Historical replay](docs/historical-replay.md), and
[Replay benchmark](docs/benchmark.md), [Macro Lab](docs/macro-lab.md), and
[Trends Lab](docs/trends-lab.md).
