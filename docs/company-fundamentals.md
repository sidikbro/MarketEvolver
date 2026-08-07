# Company universe and fundamentals

## Scope

Version 0.8 adds a small, curated company universe and an immutable fundamentals
layer. It supports historical research; it does not rank securities, recommend
investments, value companies, or connect to trading systems.

The initial universe contains Bank Leumi, Bank Hapoalim, Azrieli Group,
Melisron, NICE, Elbit Systems, NewMed Energy, Shufersal, Teva, and ICL. NICE,
Elbit, Teva, and ICL carry reviewed SEC CIK identifiers and TASE/NYSE listings.
Seed provenance identifies the curated MarketEvolver release. It is not a
substitute for a current exchange security master, so ISINs are left unset until
an authoritative identifier feed is reviewed.

## Historical identity

A stable company ID can have multiple immutable versions. Each version records
legal, Hebrew, and English names; exact aliases; external identifiers; status;
classification; domicile; and listing intervals. `get_company_at(id, T)` requires
both local observation by `T` and validity at `T`. A ticker change, delisting, or
classification correction is appended rather than applied in place.

Company aliases are linked into the knowledge graph. Exact normalized matches
may resolve to zero, one, or multiple companies. Ambiguity is returned for human
review and never silently resolved.

## Filings and observations

A filing records its type, source URI, accession number, filed and first-observed
timestamps, fiscal period, parser version, evidence IDs, and immutable raw
artifact hash. Supported types are annual and quarterly reports, earnings
releases, investor presentations, and regulatory filings.

Each fundamental observation is an immutable fact tied to one filing and at
least one evidence record. It retains:

- fiscal start and end dates;
- source publication and local first-observation timestamps;
- exact decimal text, currency, and unit;
- parser version and structured dimensions;
- original/restated status and an explicit replaced observation ID.

Historical replay uses local first observation. When a restatement becomes
visible, current-at-cutoff fundamentals replace the superseded fact in the
result, while both immutable records remain directly addressable.

## Exposures and derived values

Company exposures are accepted only when supported by explicit evidence. A
qualitative exposure has no numeric value; a quantitative exposure must have
both a value and unit. Versions carry independent validity and observation
times.

The ratio layer is deterministic. Version 0.8 computes net debt, operating
margin, and free cash flow only when compatible source observations exist.
Every result stores the formula version and exact input observation IDs. It does
not estimate missing facts, convert currencies, or calculate market-price
valuation ratios.

## SEC EDGAR

The enabled `us.sec.edgar` adapter is deliberately narrow. It accepts only the
reviewed CIKs in the curated dual-listed universe, calls official submissions
and company-facts JSON endpoints, retains accession/form/filing metadata, and
extracts a small allowlist of `us-gaap` facts. Network use still requires
host-granted permission and an operator-supplied SEC-compliant `User-Agent`
containing contact information.

The connector parser is only one part of ingestion. A production caller must
store and register the raw JSON artifact before parsing, then persist filing and
fact records with evidence links. TASE/MAYA remains disabled: its timestamp,
revision, access, and stable download contracts are not yet sufficiently
reviewed for broad filing ingestion.

## CLI

```bash
market-evolver company seed
market-evolver company list
market-evolver company show nice --at 2025-01-02T12:00:00+00:00
market-evolver fundamentals show nice --at 2025-01-02T12:00:00+00:00
market-evolver filings list nice --at 2025-01-02T12:00:00+00:00
market-evolver exposures show nice --at 2025-01-02T12:00:00+00:00
```

These commands use the configured PostgreSQL database. Naive cutoff timestamps
are rejected.

## Known limitations

- The universe is intentionally incomplete and does not track index membership.
- Seeded names, tickers, and classifications require periodic official review.
- No live SEC filing is seeded automatically and no MAYA filing is downloaded.
- SEC company facts can contain issuer-specific tags, dimensions, duplicate
  contexts, and amended facts; the narrow parser does not attempt full XBRL
  reconciliation.
- Currencies and units must already match for a derived metric. No FX conversion
  or scaling inference is performed.
- Segment and geography dimensions are stored but not inferred from prose.
