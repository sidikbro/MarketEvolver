# MarketEvolver

MarketEvolver is a governed financial-market research laboratory. Version 0.2
adds a persistent PostgreSQL evidence store, immutable raw-artifact storage, and
optional pgvector embeddings while preserving point-in-time correctness.

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

See [Architecture](docs/architecture.md) and [Threat model](docs/threat-model.md).
