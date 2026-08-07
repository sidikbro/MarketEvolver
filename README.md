# MarketEvolver

MarketEvolver is a governed financial-market research laboratory. Version 0.7
adds a Government and Regulation Lab with immutable policy actions, explicit
lifecycle transitions, and point-in-time replay.

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
```

External ingestion also requires `network_access = true` in trusted runtime
configuration. CBS and TASE/MAYA are registered but intentionally disabled.

See [Architecture](docs/architecture.md), [Threat model](docs/threat-model.md),
[Data sources](docs/data-sources.md), [Event Observatory](docs/event-observatory.md),
[Knowledge Graph](docs/knowledge-graph.md), [News Lab](docs/news-lab.md), and
[Government Lab](docs/government-lab.md).
