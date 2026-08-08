# Threat model

## Backtest leakage and overfitting

Threats include same-bar execution, after-hours backdating, revised prices,
future corroboration/fundamentals/corporate actions, benchmark mismatch,
survivorship bias, silent missing-data interpolation, parameter changes after
test access, underestimated small-account costs, and repeated hypothesis search.
Typed timestamped signals, next-session rules, cutoff-aware Parquet reads,
explicit exclusions/costs, immutable specs/results, append-only test access, and
the hypothesis registry mitigate these risks. They do not eliminate selection
bias or prove deployability.

## Fusion and reputation poisoning

Attackers may amplify one claim through copied, forwarded, syndicated, or
cross-language posts to simulate consensus. Fusion requires deterministic
identity evidence and discounts dependent sources. Claims cannot self-resolve
unless they are reviewed primary authoritative statements. Exact contradiction
sides remain stored, and future outcomes or reputation cannot leak into an
earlier replay. Remaining risks include missing syndication disclosure,
identifier collisions, coordinated nominally independent sources, domain
misclassification, and sparse-sample reputation overinterpretation.

## Telegram public-source boundary

Telegram content is attacker-controlled untrusted data, including captions,
links, filenames, and prompt-like text. It cannot grant permissions, invoke
tools, promote canonical facts, or trigger execution. Collection is disabled by
default, restricted to explicit public usernames and bounded history, and
requires both network and secrets runtime permissions. Private chats, contacts,
join links, media downloads, and discovery are rejected.

API credentials and sessions are environment-only secrets. Manifests and errors
record sanitized classes and counts, never credential values. Immutable raw
artifacts and database triggers limit evidence tampering; append-only edits and
deletions prevent historical rewriting. Remaining risks include account
compromise, source impersonation, hidden forward origin, ambiguous deletion
gaps, platform API changes, and jurisdiction-specific retention obligations.

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
| Future graph knowledge leaks into replay | Every entity, alias, edge, and exposure is filtered by local observation and validity interval |
| Alias collision silently links the wrong entity | Resolution returns all deterministic candidates and marks ambiguity |
| Guessed exposure becomes quantitative fact | Seed data is qualitative; numeric exposure requires an explicit value, unit, and provenance |
| Graph traversal obscures provenance | Paths retain exact object versions, event evidence, edge provenance, cutoff, and confidence |
| Graph cycles or path explosion | Traversal is deterministic, cycle-aware, and bounded to a small depth |
| Publisher reputation is mistaken for truth | Trust class describes provenance only; normal news remains untrusted unstructured evidence |
| Prompt or policy injection in article text | Raw text is data; deterministic parsing exposes no permission, policy, execution, or graph-mutation path |
| Edited article rewrites history | Every changed URI/content observation is an immutable revision with its own local observation time |
| Syndicated copies inflate corroboration | Normalized fingerprints and publisher identity prevent copies from counting as independent |
| Malformed XML or encoding reaches extraction | Size limit, strict decoding, DTD/entity rejection, source-contract checks, and quarantine |
| Later review leaks into replay | Candidate reviews and corroborations are append-only and independently cutoff-filtered |
| Contradictory evidence is silently discarded | Explicit contradiction records preserve both evidence IDs and unresolved status |
| Proposal is mistaken for enacted law | Proposal, approval, publication, and effectiveness are separate lifecycle states |
| Later policy status leaks backward | Action observation and transition timestamps are independently cutoff-filtered |
| Government correction overwrites history | Corrections append versions with explicit supersession provenance |
| Missing expectations imply surprise | Expectation status defaults to and remains `unknown` |
| Policy channel becomes market advice | Mechanism mappings are candidate, confidence-scored, and direction-neutral |
| Lifecycle state changes without audit | Every explicit transition is an immutable, ordered record with rationale and evidence |
| Future filing or restatement leaks backward | Filing and fact visibility use local first observation; amendments append explicit links |
| Ticker reuse or history loss | Company and listing versions have validity intervals and stable company IDs |
| Currency/unit mismatch corrupts ratios | Derived metrics require compatible period, currency, and units and retain every input ID |
| Vague prose becomes a quantitative exposure | Numeric exposures require explicit evidence, value, and unit; no prose estimation |
| Filing bytes are replaced after parsing | Filing records reference verified content-addressed, immutable raw artifacts |
| SEC identity or endpoint is abused | CIK allowlist, official HTTPS hosts, response-size bounds, and operator contact User-Agent |
| Model fabricates or launders provenance | Post-call gate restricts claim references to evidence in the committed context |
| Current information enters historical research | Pre-call gate checks every local observation against the aware cutoff |
| Prompt injection in filings or articles | Evidence is isolated as DATA; action language and malformed structured output fail closed |
| Model recommendation becomes authority | Provider output, accepted claim, canonical event, and runtime permission remain separate planes |
| Provider secret leaks through trace | Authorization comes from the environment and is excluded from persistence |
| Historical names reveal memorized outcomes | Optional stable aliases reduce cues without claiming complete leakage prevention |
| Future or reconstructed prices leak into replay | Catalog queries require market time and local observation time at or before cutoff |
| Adjusted data erases raw history | Raw and adjusted observations have separate immutable identities and partitions |
| Parquet file replacement changes outcomes | SHA-256 paths, no-overwrite publication, and verification on every analytical read |
| Replay hypothesis is changed after seeing outcome | Complete commitment is persisted before clock advance; ORM and database reject mutation |
| Benchmark constituents leak current membership | Dataset caveat is explicit; v0.10 does not claim historical constituent reconstruction |
| Delisted assets disappear from evaluation | Asset versions support delisting, while the initial curated benchmark flags survivorship bias |
| Revised macro release leaks backward | Initial and revised releases are append-only; cutoff queries use local first-observation time |
| Current API history is mistaken for historical visibility | Connectors remain disabled unless release-vintage semantics are reviewed and captured |
| Seasonal and raw series are mixed | Seasonal-adjustment class is part of revision identity and trend inputs cannot mix classes |
| Missing expectations become fabricated surprises | Missing expectation is explicitly unknown; value, source, and observed time are atomic |
| Trend direction becomes an investment instruction | Trend states and mechanism mappings are direction-neutral research observations |
| Rumor is silently promoted to geopolitical fact | Extraction creates a candidate; canonical promotion requires a separate auditable review |
| Later confirmation or outcome leaks backward | Confirmation, contradiction, resolution, and revision are append-only records gated by local observation time |
| Syndicated reports appear independent | Same publisher or normalized fingerprint is classified as syndication, not corroboration |
| Conflicting reports are collapsed | Official contradiction and unresolved conflict remain explicit timed records |
| Human harm is optimized as a market opportunity | Casualty/outcome forecasting, political-intent inference, trade direction, and allocation are excluded |
| Candidate mechanism becomes asserted causation | Paths retain candidate status, horizon, confidence, rationale, and provenance separately from events |
| Social prompt injection reaches research instructions | Raw social text remains untrusted data and is excluded from context by default |
| Copies amplify apparent support | Propagation and deterministic fingerprints separate copies/reposts from independent sources |
| Future reputation leaks backward | Reputation snapshots are immutable and selected by computation cutoff |
| Coordination candidate becomes accusation | Feature clusters remain uncertain candidates; no bot or malicious label is inferred |
| Private communication is collected | Only explicitly public sources are accepted; private accessibility is rejected |
| Database downgrade or misdirection | Explicit PostgreSQL URL, mandatory configuration, TLS default, versioned Alembic migration |
| Mutation through ORM or direct SQL | ORM hooks fail and PostgreSQL triggers reject updates/deletes; production roles remain least-privilege |
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

The knowledge graph is a curated research ontology, not a complete map of the
Israeli market. Seed relationships and qualitative exposures carry explicit
seed provenance but have not been independently reconciled with every official
registry. No TASE companies or company-level fundamentals are seeded. Alias
resolution is exact after Unicode normalization, not fuzzy, and ambiguity
requires caller review.

Application and database immutability cannot stop a PostgreSQL superuser,
table owner, or storage administrator. Production deployment must separate the
application role from the migration owner, audit DDL and trigger changes, and
test restore procedures. The database-trigger behavior is validated by rendered
migration SQL and should also be exercised against the deployment's exact
PostgreSQL version before release.

News feed content remains adversarial even when delivered by an established
publisher. RSS summaries can be incomplete, edited, syndicated, incorrectly
timestamped, or legally restricted. v0.6 retains feed artifacts for internal
provenance but does not fetch linked article pages, translate text, or infer
sentiment. Exact deterministic duplicate detection will miss paraphrased
syndication. Operator review remains necessary for corroboration, contradiction
resolution, and any future canonical-event promotion.

Official government content remains untrusted at the parser boundary and may be
corrected, delayed, challenged, or partially implemented. The BOI interest API
is a current snapshot without explicit revision history or release timestamp.
Government portal contracts can change, and deterministic keyword extraction
does not provide legal interpretation.

LLM providers can hallucinate, follow adversarial content, retain submitted
data, expose pretrained future knowledge, or fail nondeterministically. Schema
validation and manifests make failures auditable but do not make claims true.
External deployment must review retention terms, restrict submitted content,
isolate credentials, and monitor size and rate limits. Historical-name aliases
cannot remove identifiers implicit in dates, values, sectors, or model weights.
Skeptical review can identify common defects but cannot prove causal validity or
that an effect was not already priced in.

Historical market datasets can contain vendor corrections, retroactive
adjustments, timezone mistakes, missing sessions, stale symbols, and licensing
constraints. Local observation time prevents known later versions from leaking
backward but cannot reconstruct a vintage never captured. Content addressing
detects replacement but not false source data. The curated universe and seven
cases are subject to selection and survivorship bias; benchmark composition is
not reconstructed. Outcome returns describe observed price paths and must not be
presented as realized strategy profit.

Macro data adds preliminary releases, revisions, rebenchmarks, seasonal-factor
changes, publication lags, and incompatible units. Point-in-time capture can
preserve only vintages actually observed. Deterministic slopes and anomaly
scores describe their inputs but do not establish causation or predict asset
returns. Curated structural themes are hypotheses subject to selection bias and
must not be presented as automatically detected facts.

Geopolitical reporting is incomplete, adversarial, rapidly revised, translated,
and sometimes intentionally deceptive. Official statements can also be partial
or corrected. Source authority does not establish complete truth. The lab can
preserve observed uncertainty and timing but cannot verify battlefield facts,
intent, casualties, or conflict outcomes. Its curated transmission registry is
an analytical vocabulary, not proof of causality or market impact.

Company seed data can become stale through ticker changes, delistings, mergers,
or classification changes. It is curated rather than a complete security master
and must be revised by appending versions. SEC company facts may contain
amendments, issuer extensions, dimensions, and multiple contexts that a narrow
allowlist cannot fully reconcile. TASE/MAYA remains disabled until its access,
publication-time, and correction semantics are reviewed. Derived values are
mechanical transformations of compatible observations, not assessments of
quality, comparability, valuation, or future performance.
# v0.17 paper-runtime threats

Raw model output, revoked strategies, stale or future observations, invalidated evidence, duplicated
signals, order floods, concentration, cash exhaustion, dominant fees, impossible prices, missing
sessions, corporate-action ambiguity, and corrupted NAV all fail closed. Long-only schemas and fill
reconciliation prohibit synthetic shorts and negative cash. Risk relaxation and kill-state recovery
require explicit audited operator action. The runtime contains no broker credentials or provider
imports, so a research-plane compromise cannot grant execution permission.
