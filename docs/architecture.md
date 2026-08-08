# Architecture

## Scope and boundary

MarketEvolver currently defines a research domain, not a trading system. The
package has no order, portfolio, broker, leverage, derivative, credential, or
real-money abstractions. A `ResearchDecision` is an epistemic record whose
strongest outcome is `accept_for_research`; it is not an execution command.

PostgreSQL is the authoritative metadata store; raw bytes live behind an
immutable artifact-store interface. Version 0.5 adds a deliberately compact
Israel market ontology on top of the evidence and event layers.

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
11. **Event Observatory** applies deterministic rules to trusted normalized
    observations. Canonical event versions, support links, lifecycle transitions,
    and causal-mechanism links are all append-only.
12. **Knowledge Graph** stores versioned entities, aliases, taxonomy edges,
    relationships, and exposures. Traversal is deterministic, cutoff-aware, and
    returns candidate mechanisms with provenance rather than forecasts.
13. **News Lab** stores raw feeds before parsing, classifies evidence security
    independently from publisher trust, extracts only exact entities, and emits
    reviewable candidates rather than canonical events.
14. **Government Lab** records versioned official actions and append-only,
    evidence-backed lifecycle transitions without converting policy text into
    canonical market events automatically.
15. **Company fundamentals** versions company identity and listings, retains
    immutable filing artifacts, and stores reported facts, restatements,
    evidence-backed exposures, and deterministic derived metrics.
16. **Research intelligence** assembles immutable cutoff contexts, commits a
    canonical manifest before every provider call, validates structured model
    claims against supplied provenance, and records separate skeptical review.
17. **Market data and replay** catalogs immutable market observations in
    PostgreSQL, stores bulk rows in content-addressed Parquet, queries through
    DuckDB, and binds every historical evaluation to a pre-advance commitment.
18. **Macro and trends** stores source-release vintages separately from
    deterministic trend calculations, preserves disagreement, and injects only
    cutoff-visible macro state into research and replay.
19. **Geopolitical intelligence** separates extracted candidates, governed
    promotion, immutable event versions, timed corroboration, and independently
    provenanced multi-horizon economic-transmission paths.
20. **Social and narrative foundation** stores public untrusted posts, immutable
    edits, copy-aware propagation, reviewed narratives, rumor versions,
    coordination candidates, and historical domain reputation.

```text
fetch -> local first_observed_at + SHA-256 -> immutable raw artifact + receipt
      -> normalize -> parse -> Source + NormalizedObservation -> Evidence
                                      -> rule extraction -> CanonicalEvent version
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
all provenance records. Revision `0004` also installs PostgreSQL triggers that
reject `UPDATE` and `DELETE` on append-only provenance and graph tables.

The application role must not own these tables and should receive only the
minimum `SELECT`/`INSERT` privileges. Exceptional maintenance must run as the
migration owner in a reviewed transaction that explicitly disables the exact
table trigger, performs and audits the repair, and re-enables it before commit.
There is no application-session bypass flag.

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

## Event Observatory

Alembic revision `0003` adds canonical events, event support, ordered lifecycle
transitions, and direction-neutral mechanism links. A canonical event contains
its material fingerprint and a source-specific semantic deduplication key.
Exact material matches reuse the event and add provenance support; changed
material requires a new immutable version with an explicit supersession link.

Replay first filters event versions by local `first_observed_at`, then verifies
that every supporting evidence record was also visible at the cutoff.
Transitions are filtered by their own timestamps when deriving status. Thus an
original event can be confirmed at T1, superseded at T2, and still be queried as
the system believed it at T1.

The initial extractor supports BOI USD/EUR representative-rate updates,
rate-movement events, and unusual moves at a deterministic one-percent
threshold. `boi_policy_event` is reserved as a typed placeholder; it emits
nothing until an official policy dataset is ingested.

## Israel Market Knowledge Graph

Alembic revision `0004` adds versioned entity, alias, relationship, and exposure
tables. A logical object keeps a stable ID while every correction creates a new
version with its own validity interval, local observation time, and provenance.
Queries require an aware cutoff and select only versions both observed and valid
at that time. Future corrections therefore cannot alter past graph answers.

The deterministic seed includes Israel, the Bank of Israel, ILS, USD, EUR,
USD/ILS, TASE, major sector taxonomy nodes, and the causal-mechanism registry.
It deliberately contains no guessed company fundamentals or quantitative
exposures. Hebrew, English, abbreviations, and external identifiers are stored
as versioned aliases; ambiguous matches return candidates rather than silently
choosing one.

Event tracing begins with the immutable event version and its reviewed mechanism
links, then follows versioned relationships to a bounded depth. Every returned
path identifies the exact entity and relationship versions, evidence provenance,
combined confidence, and validated cutoff. It is a causal research candidate,
not a prediction or investment recommendation.

PostgreSQL remains the graph system of record. The current bounded traversals
fit relational joins and keep bitemporal enforcement close to the provenance
tables; a separate graph database would add synchronization and historical-view
risks without a demonstrated workload need.

## News Lab

Alembic revision `0005` adds immutable news items, extracted entity links,
event candidates, review actions, corroborations, and contradictions. Normal
news is always untrusted unstructured evidence. Raw RSS bytes are retained before
strict parsing, and malformed material becomes an auditable quarantine record.

News replay filters each item by local first observation and each review or
corroboration by its own creation time. Edited articles append a revision linked
to the earlier observation. Exact source/content reingestion is idempotent, while
normalized cross-publisher copies are marked syndicated rather than independent.
No News Lab object has an automatic edge to canonical events or runtime policy.

## Government and Regulation Lab

Alembic revision `0006` adds government actions, lifecycle transitions, and
deterministic action candidates. Replay independently filters action observation
and transition timestamps. Corrections append versions linked through
`supersedes_action_id`; expectation status is explicitly unknown.

The enabled BOI policy connector reuses raw-first ingestion for the official
current-interest JSON endpoint. Other Israeli government and regulator sources
remain disabled until stable contracts are reviewed. Candidate mechanism
mappings are direction-neutral and cannot modify knowledge-graph facts.

## Company universe and fundamentals

Alembic revision `0007` adds company versions, filings, fundamental
observations, derived fundamentals, and company exposures. All five tables are
append-only in both SQLAlchemy and PostgreSQL. Company, filing, fact, and
exposure queries filter on local observation time; company and exposure queries
also apply their declared validity intervals.

Restatements create a new filing and fact linked to the earlier immutable
records. A cutoff before the amendment returns the original fact. A cutoff
afterward returns the restatement as current-at-cutoff without deleting the
original. Deterministic derived metrics retain exact input observation IDs and a
formula version, and require compatible period, currency, and unit inputs.

The initial company seed links ten Israeli issuers to existing sector, exchange,
and geography entities. The narrow SEC EDGAR adapter supports four reviewed
dual-listed CIKs through official JSON endpoints. It does not grant network
permission or bypass the raw-before-parse ingestion boundary. TASE/MAYA remains
disabled pending contract review.

## Constrained research intelligence

Alembic revision `0008` adds append-only research contexts, manifests, provider
calls, claims, extended hypotheses, reviews, and traces. Provider output must
parse into typed records, pass temporal and provenance gates, and remains
proposed until separate review. It has no write path into canonical events,
runtime permissions, or execution.

The exact context manifest is committed before provider invocation. The trace
retains provider/model identity, settings, timestamps, token usage when
available, prompt version, raw-response hash, structured parse, validation, and
review. Credentials are excluded. The offline mock is default; the generic
HTTPS adapter additionally requires explicit host network permission. Prompts
isolate evidence as data, and optional historical-name mappings remain outside
the model-visible context.

## Historical market data and replay benchmark

Alembic revision `0009` adds asset versions, market partition catalogs,
observation metadata, corporate actions, trading sessions, replay cases,
commitments, runs, outcomes, and named/anonymized pairs. PostgreSQL is the
metadata/provenance system of record. Immutable compressed Parquet holds bulk
rows, and embedded DuckDB performs analytical reads; no search or graph service
is introduced.

Point-in-time queries first filter catalog rows by market timestamp and local
observation cutoff. Parquet hashes are verified before use, and later corrected
observations cannot replace historical replay. The replay clock refuses to
advance without a complete immutable research commitment. Matured outcome
labels retain every input observation ID and are explicitly research metrics,
not strategy profit or execution results.

The asset seed contains 18 linked instruments and the benchmark contains seven
versioned case types across seven research modes. Both are deliberately small.
No external historical-market source is enabled pending a reviewed data and
licensing contract.

## Macro and trend intelligence

Alembic revision `0010` adds macro-release vintages, deterministic trend
signals, explicit divergences, and curated structural candidates. Repository
queries group releases by observation period and seasonal-adjustment class,
then select only the latest version whose local first-observation time is at or
before the cutoff. Trend records retain every input observation ID and their
calculation version.

Research contexts and replay snapshots include cutoff-visible macro, trend, and
structural records. They do not rebuild historical state from the current value
of an external API. Direction-neutral mechanism mappings connect trend families
to the existing knowledge vocabulary without asserting asset direction.

## Geopolitical intelligence

Alembic revision `0011` adds geopolitical candidates, separate review records,
immutable canonical event versions, transmission paths, and corroboration.
Current queries hide an earlier version only after its revision becomes locally
visible; direct lookup retains the original. Conflicting event lineages are not
merged merely because their text or topic is similar.

Candidate extraction is phrase-based and intentionally narrow. Canonicalization
requires a governed promotion record. Transmission paths validate against the
direction-neutral mechanism registry and preserve horizon, confidence, cutoff
validity, rationale, and provenance. Research and replay expose uncertainty and
contradictions as data rather than selecting one narrative silently.

## Governance

Recommendations are data in the research plane. `RuntimePermissions` are
host-supplied data in a separate capability plane. Neither a model nor a lab can
grant itself permissions, and the current configuration loader rejects any
execution or broker capability.
