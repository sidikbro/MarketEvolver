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
