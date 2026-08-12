# Governed historical market data

Version 0.23 adds immutable manifests and deterministic Parquet partitions for
bounded daily history. PostgreSQL remains the replay catalog; raw downloads and
normalized snapshots are content-addressed; DuckDB performs local analytics.
This is data plumbing, not a strategy or recommendation system.

## Source policy

| Source | Class | Scope | Adjustment and replay policy |
|---|---|---|---|
| BOI SDMX `RER_USD_ILS` | authoritative/official | Daily representative USD/ILS | Raw rates; outcome measurement only because old responses do not prove publication vintages |
| Stooq daily CSV | convenience/experimental | Explicit bounded symbols only | Raw OHLCV only; no official TASE attribution; outcome measurement only |
| TASE/MAYA | official, disabled | None | Historical OHLCV contract and access semantics remain unresolved |

The reviewed BOI request uses
`.../EXR/1.0/RER_USD_ILS?startperiod=YYYY-MM-DD&endperiod=YYYY-MM-DD&format=csv`.
It fixes daily frequency, USD base, ILS counter, representative type `OF00`, and
retains all release metadata in the raw artifact. Non-business dates are absent,
not filled. BOI documents that series values can be revised shortly after
publication; retrieval time cannot reconstruct an uncaptured vintage.

Stooq is replaceable and explicitly experimental. It is never described as
official exchange data. It supplies raw daily OHLCV but no reviewed adjusted
close or complete split/dividend stream. Use therefore carries reduced
authority, current-universe survivorship, composition, and corporate-action
caveats.

## Immutable layout

```text
data/market/history/
  raw/sha256/aa/bb/<digest>
  parquet/source=<source>/venue=<venue>/frequency=1d/
    instrument=<asset-id>/year=<YYYY>/bars.parquet
  manifests/<dataset-id>.json
```

Rows are sorted before Zstandard Parquet output. Raw OHLC and volume remain
distinct from optional adjusted close and adjustment factor. Manifests record
request bounds, retrieval times, all hashes, contract fingerprint,
parser/schema versions, code commit, survivorship/composition state, and replay
eligibility. A differing existing partition or manifest fails closed.

## Commands

```bash
market-evolver market source-list
market-evolver market ingest-history boi asset.fx.usdils \
  --from 2021-01-01 --to 2025-12-31 --confirm-live
market-evolver market ingest-history stooq asset.arcx.spy \
  --symbol spy.us --venue ARCX --currency USD \
  --from 2021-01-01 --to 2025-12-31 --confirm-live
market-evolver market validate-dataset <dataset-id>
market-evolver market quality-report <dataset-id>
market-evolver market coverage
```

Requests are capped at ten years and five MB. The existing 18 seeded assets stay
the intended universe; unsupported instruments are not added for row count.
