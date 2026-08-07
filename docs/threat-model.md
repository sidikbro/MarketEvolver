# Threat model

## Assets and security properties

The protected assets are research integrity, point-in-time correctness, raw
artifacts, the provenance graph, host secrets, and the boundary that prevents
research output from becoming financial execution.

## Trust boundaries

News, social posts, trends, feeds, documents, and model-generated text are
untrusted input. Government publications may be classified authoritative for
attribution, but their content still crosses the input boundary and is parsed as
data. Runtime permissions and policy originate only from trusted host
configuration.

## Threats and controls

| Threat | Initial control |
|---|---|
| Look-ahead bias or revised timestamps | UTC-aware causal timelines and decision cutoff validation |
| Claim laundering / lost attribution | Evidence requires source IDs; derived records retain parent IDs |
| Record tampering or nondeterminism | Frozen records and canonical SHA-256 content identities |
| Artifact overwrite or hash substitution | Content-addressed paths, atomic no-replace publication, and verification on write/read |
| Duplicate or concurrent ingestion | Primary-key content IDs and idempotent equality checks |
| Broken provenance chain | Repository insertion verifies every referenced parent |
| Parser acts on unretained content | Runner durably stores and hashes raw bytes before parsing |
| Retry changes historical visibility | Raw receipt reuses the original local first-observed timestamp |
| Source silently changes response type | Registry allowlists expected media types; mismatch fails |
| Historical API data mistaken for historical availability | Period/publication/effective times remain separate from local first observation |
| Partial or failed ingestion becomes invisible | Every run has a durable success/failure manifest and bounded error summary |
| Later revision rewrites historical belief | Revisions are new immutable event versions; replay filters versions and transitions by cutoff |
| Similar wording causes false event merge | Deduplication uses source-specific semantic keys and material fingerprints, never text similarity |
| Event appears before its evidence | Persistence rejects events, transitions, and mechanism links that predate supporting evidence |
| Causal link is mistaken for an investment instruction | Mechanism registry is direction-neutral and rejects BUY/SELL semantics |
| Lifecycle state changes without audit | Every explicit transition is an immutable, ordered record with rationale and evidence |
| Database downgrade or misdirection | Explicit PostgreSQL URL, mandatory configuration, TLS default, versioned Alembic migration |
| Mutation through ORM | Update/delete hooks fail; production roles should also deny UPDATE/DELETE |
| Prompt injection in news/social text | Content is data, not instructions; labs expose evidence only |
| Untrusted content causing a trade | No execution types or adapters; unsafe config fails closed |
| Model self-granting capabilities | Recommendations and `RuntimePermissions` are separate types/planes |
| Secret or host compromise | Network, filesystem, subprocess, secrets, and broker permissions default off |
| Correlation mistaken for confirmation | Explicit trust levels; corroboration is not inferred automatically |
| Digest collision/substitution | SHA-256 namespacing; future storage must verify bytes on read |
| Denial of service / oversized content | Future ingestion adapters must impose size, time, and rate limits |

## Explicit non-goals

This phase does not defend a broker or trading path because none exists. It does
not include portfolio optimization, order simulation, leverage, options,
credential storage, or real-money execution.

## Residual risks and next controls

Before adding any external lab, introduce content-size limits, parser sandboxing,
source-specific authentication, append-only audit storage, schema versioning,
and tests using revised/deleted documents. Any future action system must be a
separate service with human authorization and policy enforcement; research
objects must never be accepted as executable instructions.

PostgreSQL superusers and filesystem administrators remain able to tamper with
data. Deployment must restrict those roles, encrypt storage, back up both
metadata and artifacts consistently, monitor integrity failures, and periodically
reconcile stored bytes with database hashes. Local artifact writes do not provide
multi-host coordination; a future shared backend must preserve conditional
create/no-overwrite semantics.

The Bank of Israel endpoint is authoritative but remains external and untrusted
at the transport/parser boundary. TLS, expected media types, strict JSON fields,
timezone validation, and immutable raw retention limit silent corruption.
However, v0.3 does not yet enforce response-size limits, certificate pinning, or
semantic reconciliation against the SDMX series database. The current-rates API
also lacks an explicit revision history; its `lastUpdate` must not substitute
for MarketEvolver's local first-observed time.

The Event Observatory is rule-based and therefore only as complete as its
published rules and registries. It currently recognizes USD and EUR BOI rates;
unsupported currencies remain evidence but do not become canonical events.
The one-percent unusual-move threshold is an observatory classification, not a
prediction, risk limit, or recommendation. Mechanism links express plausible
transmission channels and carry confidence, horizon, evidence, and review state;
they do not assert asset-price direction.
