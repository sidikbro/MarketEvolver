# Israel Market Knowledge Graph

## Purpose and boundary

The v0.5 graph connects immutable market events to canonical entities and
plausible causal mechanisms. It supports historical research questions such as
"what relationships were known when this event was first observed?" It does not
predict prices, rank investments, or encode BUY/SELL conclusions.

PostgreSQL is authoritative. A separate graph database is intentionally deferred:
the initial graph is small, traversal depth is bounded, and relational storage
keeps point-in-time filtering, provenance, migrations, and operational controls
in one place.

## Ontology

Entities have a stable `entity_id` and immutable numbered versions. Supported
types include countries, currencies and pairs, central banks, government bodies,
regulators, exchanges, companies, sectors, industries, indices, ETFs,
commodities, economic indicators, and mechanisms.

The seed covers:

- Israel, Bank of Israel, ILS, USD, EUR, USD/ILS, and TASE;
- major Israeli market sectors and selected sub-sectors;
- direction-neutral mechanisms such as currency translation, import cost,
  financing cost, risk premium, defense procurement, and tourism demand.

Taxonomy uses explicit `child_of` relationships. Other typed relationships
include `belongs_to`, `regulated_by`, `listed_on`, `operates_in`, `contains`,
`affects`, and `leads_to`. Edges are never inferred merely from similar names.

## Aliases and resolution

Aliases are first-class, versioned records. The seed includes English, Hebrew,
common abbreviations, currency-pair spellings, and selected official identifiers
such as TASE's MIC. Matching uses deterministic Unicode normalization and an
aware cutoff. If a normalized alias identifies multiple visible entities, the
resolver reports ambiguity and all candidates; it never guesses.

## Exposures

An exposure states that one entity is qualitatively or quantitatively exposed to
another entity or mechanism. It records direction, strength, confidence,
validity, observation time, and provenance. Quantitative records require both a
value and unit. The initial seed uses only broad qualitative relationships and
does not invent numeric sensitivities.

## Point-in-time and revision semantics

Every graph record separates:

- the stable logical ID;
- its immutable version number;
- `valid_from` and optional `valid_to`;
- local `observed_at`;
- status (`active`, `superseded`, or `retracted`);
- provenance.

A query at cutoff `T` sees only records with `observed_at <= T` whose validity
interval contains `T`. Among those, it selects the highest visible version for
each logical object. Corrections append a version; they never alter an earlier
record. A version learned tomorrow cannot appear in yesterday's replay even if
its declared validity begins in the past.

## Event propagation

`graph trace-event` loads the exact canonical event visible at the cutoff,
verifies its supporting evidence, includes reviewed event-to-mechanism links,
and follows visible relationships to a maximum depth of three. Results include:

- entity and edge IDs with exact version numbers;
- evidence and seed provenance;
- the validated cutoff;
- a deterministic combined confidence.

These paths are auditable candidate transmission channels. They are not claims
of price direction, forecasts, or recommendations. Exposure records are
available from `graph neighbors`; v0.5 event tracing follows typed relationships
and does not yet traverse exposure records.

## Immutability and deployment

SQLAlchemy rejects updates and deletes for graph and provenance models. Alembic
revision `0004` installs PostgreSQL triggers that independently reject
`UPDATE`/`DELETE` on append-only tables. The application role should not own
tables and should receive only necessary `SELECT` and `INSERT` privileges.

There is no runtime bypass. If exceptional maintenance is unavoidable, the
migration owner must use a reviewed transaction, explicitly disable only the
target table's immutability trigger, make and audit the repair, re-enable the
trigger, and verify it before commit. Normal corrections must always append a
new version.

## CLI

```bash
market-evolver entity seed
market-evolver entity list --at 2025-01-02T12:00:00+00:00
market-evolver entity show country.israel --at 2025-01-02T12:00:00+00:00
market-evolver entity resolve "בנק ישראל" --at 2025-01-02T12:00:00+00:00
market-evolver graph neighbors country.israel --at 2025-01-02T12:00:00+00:00
market-evolver graph trace-event <event-id> --at 2025-01-02T12:00:00+00:00
```

All commands require the same explicit PostgreSQL configuration as the existing
storage and observatory commands.

## Known limitations

- The seed is intentionally small and includes no real company universe.
- Curated seed provenance identifies the MarketEvolver release, not a full set
  of external legal citations.
- Alias matching is deterministic and exact after normalization; fuzzy entity
  resolution is absent.
- Event traversal is relationship-based and bounded; exposure traversal and
  richer query planning are future work.
- PostgreSQL trigger SQL is validated offline by default. Deployment should run
  migration integration tests against its actual PostgreSQL/pgvector versions.
