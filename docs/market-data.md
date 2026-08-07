# Historical market data

## Boundary and model

The v0.10 market layer stores observations for research replay. It is not a
broker feed, execution service, portfolio system, or source of recommendations.

An immutable observation identifies the asset, venue, observation type, market
timestamp, local first-observation timestamp, source, adjustment status,
currency, parser version, and provenance. OHLCV records retain their raw open,
high, low, close, and volume. Index and FX records retain a level/rate value.
Adjusted and raw records have distinct identities; adjusted data never replaces
the source observation.

Corporate actions cover dividends, splits, reverse splits, symbol changes,
mergers, and delistings. Announcement, local observation, and effective times
remain separate. Trading-session records distinguish calendar date, open/close,
non-trading days, source, parser version, and when the calendar record became
known.

## Asset universe

The curated seed contains 18 instruments:

- ten TASE equity listings linked to the v0.8 companies;
- four selected NYSE dual listings: NICE, Elbit Systems, Teva, and ICL;
- SPY and VT broad ETFs;
- the TA-35 benchmark index;
- USD/ILS as a contextual FX series.

Each asset version links to a stable knowledge-graph entity and may identify a
benchmark. The seed is a research fixture, not a complete exchange security
master or historically reconstructed index membership file.

## PostgreSQL, Parquet, and DuckDB

PostgreSQL is authoritative for asset versions, partition hashes, row catalogs,
provenance, corporate actions, and trading sessions. Bulk numerical rows are
written into Zstandard-compressed Parquet partitions. Partitions use SHA-256
content-addressed paths and hard-link publication, so existing files are never
overwritten. Every read revalidates the file hash.

DuckDB writes and queries Parquet locally without a separate analytical server.
No Elasticsearch or graph database is used. The root is configured by
`MARKET_EVOLVER_MARKET_ROOT`, allowing relocation to mounted storage without
application changes.

## Point-in-time queries and revisions

`get_market_data(asset, start, end, cutoff)` filters the PostgreSQL catalog by
both market time and local observation time, then reads only referenced Parquet
files. If the same market timestamp is later corrected, the latest version
visible by the requested cutoff is returned. Earlier replay still receives the
original immutable version.

`get_close_visible_at` returns an observation only when the exact market
timestamp and observation were visible by the cutoff. Benchmark queries resolve
the asset's benchmark as known at the cutoff. Corporate actions and asset symbol
versions use the same local-observation rule.

## Ingestion and sources

```bash
market-evolver market seed-assets
market-evolver market asset-list
market-evolver market ingest observations.json --dataset-version internal-test/1
```

The JSON import is a governed local import surface, not a network connector.
Version 0.10 enables no external price vendor because no reviewed licensing,
revision, adjustment, timestamp, and redistribution contract has been selected.
Imported rows must already identify their source and provenance.

## Limitations

- No official or commercial historical price connector is enabled.
- Parquet partitions are immutable, but shared multi-host publication and object
  storage conditional writes are not implemented.
- The catalog does not reconstruct historical benchmark constituents.
- Corporate-action adjustment factors are stored as observations/actions but no
  automatic adjustment engine is provided.
- Session calendars are supported but not populated by the curated seed.
