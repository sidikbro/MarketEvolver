# News Lab

## Security boundary

Source trust class is provenance metadata, not a declaration that a claim is
true. The registry distinguishes `official`, `primary_corporate`,
`established_news`, `specialist_publication`, `social`, and
`anonymous_or_unknown`.

Evidence security is separate:

- official machine-readable data may be `trusted_structured`;
- official prose may be `trusted_unstructured`;
- ordinary publisher text is always `untrusted_unstructured`;
- malformed or provenance-deficient material is `quarantined`.

Untrusted and quarantined news cannot grant permissions, modify graph facts,
change policy, execute actions, or be promoted to a canonical event. There are
no execution interfaces in this repository.

## Ingestion and retention

The first reviewed connector reads the public BBC Business RSS feed. It is a
narrow connector with a fixed HTTPS endpoint, host contract, accepted media
types, two-megabyte response limit, strict UTF-8/XML parsing, and DTD/entity
rejection. It is not a general scraper.

The exact feed payload is SHA-256 hashed and durably written to the configured
content-addressed artifact store before parsing. Each item retains its source,
canonical URI, publication time, local first-observed time, optional update
times, parser version, raw artifact digest, normalized content digest, language,
trust/security classes, and provenance.

An unchanged source/URI/content tuple is idempotent. Changed content at the same
canonical URI becomes a new immutable revision linked to the prior item.
Normalized identical content from another publisher is marked syndicated and
does not count as independent corroboration.

## Extraction and candidates

Extraction is deterministic and limited to metadata, language, and exact
Hebrew/English aliases already present in the v0.5 entity registry. It recognizes
explicit currencies, Israel, Bank of Israel, and TASE names. Ambiguous aliases
are not resolved. There is no sentiment, surprise, causal-impact, price-direction,
translation, embedding, or LLM inference.

A `NewsEventCandidate` is not a canonical event. It records exact extracted
entities, a possible type, method, confidence, supporting spans, creation time,
and point-in-time review state. Reviews are append-only. Promotion is a separate
controlled action and fails closed for untrusted or quarantined news.

Corroboration records distinct evidence and publishers, explicit independence
assumptions, time ordering, confidence, and contradictions. Same-publisher and
normalized syndicated copies are not independent. Contradictions are retained;
the system does not silently choose a winner.

## Historical replay

News visibility is based on local `first_observed_at`, never today's feed
contents or the publisher's publication date alone. Revisions remain separate,
so an edit observed at T2 cannot appear at T1. Candidate review and
corroboration timestamps are filtered independently, preventing later review
knowledge from leaking backward.

## PostgreSQL integration tests

Default tests use SQLite and require no network. Optional PostgreSQL tests
exercise migrations through `0005`, database-trigger update/delete rejection,
transaction rollback, and point-in-time graph queries:

```bash
export MARKET_EVOLVER_TEST_POSTGRES_URL='postgresql+psycopg://.../marketevolver_test'
pytest -m postgres tests/test_postgres_integration.py
```

Use a dedicated disposable database whose name contains `_test`. Append-only
tests intentionally leave immutable test records behind. The database must have
pgvector available because migration `0001` enables it.

## Known limitations

- RSS contains summaries and links, not necessarily complete article bodies.
- BBC feed availability, retention, and terms remain external dependencies.
- Exact normalized fingerprints detect copied text but not sophisticated
  paraphrases.
- Entity matching is exact and does not translate or perform fuzzy matching.
- Corroboration is deliberately narrow and does not establish factual truth.
- No live endpoint is required or contacted by the default suite.
