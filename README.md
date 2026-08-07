# MarketEvolver

MarketEvolver is a governed financial-market research laboratory. Version 0.4
adds an Event Observatory that deterministically converts trusted observations
into immutable, point-in-time canonical market events.

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
```

External ingestion also requires `network_access = true` in trusted runtime
configuration. CBS and TASE/MAYA are registered but intentionally disabled.

See [Architecture](docs/architecture.md), [Threat model](docs/threat-model.md),
[Data sources](docs/data-sources.md), and
[Event Observatory](docs/event-observatory.md).
