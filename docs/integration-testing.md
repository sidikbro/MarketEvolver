# Integration testing

MarketEvolver v0.21 provides a disposable local PostgreSQL 16 environment with
pgvector. It binds only to `127.0.0.1:55432`, uses test-only credentials, and
stores database state in container tmpfs. It is never a production database.

## Local workflow

Install the development dependencies, then run:

```bash
make postgres-up
make test-postgres
make test-all
make validate
make postgres-down
```

`make postgres-up` waits for the health check. `tests/conftest.py` selects the
Compose URL only when that exact local port is reachable; an explicitly set
`MARKET_EVOLVER_TEST_POSTGRES_URL` always wins. `.env.test.example` documents
the disposable values but tests do not load or require a committed `.env`.

`make test-all` runs the offline suite and then the PostgreSQL suite. An absent
database is an error for this target, never a successful skip. The PostgreSQL
suite upgrades a clean database through Alembic `0022`, reruns `upgrade head`,
checks representative indexes and foreign keys, exercises transaction rollback,
and verifies database-level append-only triggers.

## Markers and network policy

- `unit`: small deterministic tests.
- `integration`: deterministic cross-module and storage tests.
- `postgres`: requires the dedicated PostgreSQL service.
- `slow`: deterministic but relatively expensive.
- `live` and `external_provider`: require network/provider access and are
  excluded from normal validation and CI.

CI runs all non-live offline tests plus the PostgreSQL suite against a pgvector
service. No official-source, social, model-provider, or other live request is
made.

## Coverage

Validation writes `coverage.xml` and reports missing lines. There is no global
percentage gate: provenance, cutoff replay, migrations, topology governance,
and paper-accounting boundaries are critical regardless of aggregate coverage.
New critical modules should receive direct behavioral tests rather than being
hidden by coverage in unrelated utility code.
