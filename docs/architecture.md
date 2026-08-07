# Architecture

## Scope and boundary

MarketEvolver currently defines a research domain, not a trading system. The
package has no order, portfolio, broker, leverage, derivative, credential, or
real-money abstractions. A `ResearchDecision` is an epistemic record whose
strongest outcome is `accept_for_research`; it is not an execution command.

PostgreSQL is the authoritative metadata store; raw bytes live behind an
immutable artifact-store interface. Version 0.3 adds a registry of external
authorities and a deliberately narrow official-data ingestion path.

## Layers

1. **Configuration** loads explicit TOML policy and runtime capabilities with
   deny-by-default values. Unsafe governance flags fail closed. Database startup
   additionally requires an explicit PostgreSQL URL and TLS.
2. **Source records** identify what was published, when it became observable,
   when it was ingested, its trust class, and its content digest.
3. **Evidence** binds every claim to one or more immutable source identifiers.
4. **Events and hypotheses** preserve the evidence graph and distinguish when
   something occurred from when it became knowable.
5. **Research decisions** record a knowledge cutoff and validate every supplied
   input against that cutoff.
6. **Repositories** map each domain record to an immutable SQLAlchemy 2.x model.
   Duplicate content IDs are idempotent; mismatched records are rejected.
7. **Artifacts** are stored locally under
   `sha256/<first-2>/<next-2>/<full-digest>`. Atomic hard-link publication
   prevents replacement under concurrent ingestion, and reads reverify bytes.
   PostgreSQL stores hash, size, MIME type, relative path, and creation time.
8. **Labs** implement one small `ResearchLab` protocol. News, Social, Trends,
   Government, and Geopolitical labs can therefore arrive independently.
9. **Source registry** fixes stable authority IDs, expected media types,
   geography, timezone, ingestion method, enabled state, and revision caveats.
10. **Ingestion runners** enforce the sequence below and record every attempt in
    an operational manifest. Connectors cannot parse before raw persistence.

```text
fetch -> local first_observed_at + SHA-256 -> immutable raw artifact + receipt
      -> normalize -> parse -> Source + NormalizedObservation -> Evidence
                                                               |
                                                               no execution edge

raw bytes -> ArtifactStore (content addressed) <- artifact metadata -> PostgreSQL
host policy ---------> RuntimePermissions (separate capability plane)
```

## Point-in-time rules

- All timestamps must be timezone-aware and are compared in UTC.
- `published_at <= observed_at <= ingested_at`.
- `occurred_at <= known_at`.
- A decision may only consume records whose `available_at` is no later than its
  `knowledge_cutoff`, and its cutoff cannot follow its decision timestamp.
- `observed_at`, rather than a possibly revised publisher timestamp, determines
  when a source was available to the system.
- `EvidenceRepository.visible_at(T)` returns only evidence with an aware
  `observed_at <= T`. Ingestion rejects evidence dated before any referenced
  source and decisions containing post-cutoff evidence or hypotheses.
- Every normalized observation separately stores its described period,
  source-supplied publication time, local first-observed time, effective time,
  and optional supersession time. Historical visibility is determined only by
  local first observation, never by the period date or today's API availability.

## Provenance

Records are frozen dataclasses. Their identifiers are SHA-256 hashes over
canonical JSON with sorted keys, normalized enum values, and ISO timestamps.
Derived claims require parent identifiers. Content bodies remain outside these
records; `content_digest` and `excerpt_digest` bind them without duplicating
potentially hostile text.

Repository insertion checks every parent identifier before accepting a derived
record. SQLAlchemy hooks reject update and delete operations for artifacts and
all provenance records. This is application-level immutability; production
database roles should also receive INSERT/SELECT-only privileges.

## Persistence and migration

SQLAlchemy models are portable enough for isolated unit tests, but production
engine creation accepts PostgreSQL only. Alembic revision `0001` enables the
`vector` extension and creates the evidence graph. Evidence has a nullable
1,536-dimensional pgvector column; no embedding or prediction model is present.

The artifact root comes from configuration or
`MARKET_EVOLVER_ARTIFACT_ROOT`. Moving from a project-local `data` directory to
`/mnt/marketevolver` therefore changes deployment configuration, not application
code or database identifiers.

Alembic revision `0002` makes source publication time optional and adds raw
ingestion receipts, normalized observations, and run manifests. A raw receipt is
committed before parsing. Identical source/dataset/content hashes reuse that
receipt and its original first-observed timestamp. If parsing previously failed,
the same retained artifact may be retried; completed observations are skipped.

## Connectors and operations

The connector contract contains `fetch`, `persist_raw`, `normalize`, `parse`,
and `emit_evidence`. Only the Bank of Israel connector is enabled. It consumes
the official current representative-rates JSON endpoint and preserves the raw
payload, currency unit multiplier, rate timestamp, and local observation time.
CBS and TASE/MAYA implement disabled adapter skeletons pending stable, reviewed
API contracts.

Each run manifest records identity, timestamps, outcome, item and duplicate
counts, bytes, new artifacts, parser version, and a bounded error summary.
Telemetry exposes measured raw bytes, table counts, downloaded bytes per day,
and observation growth per day. It performs no forecasting.

## Governance

Recommendations are data in the research plane. `RuntimePermissions` are
host-supplied data in a separate capability plane. Neither a model nor a lab can
grant itself permissions, and the current configuration loader rejects any
execution or broker capability.
