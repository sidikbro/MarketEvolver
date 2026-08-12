# Data sources

## Historical market data

BOI SDMX `RER_USD_ILS` is the official bounded USD/ILS historical source. Stooq
CSV is optional convenience/experimental data and never official TASE or U.S.
exchange data. TASE/MAYA historical OHLCV remains disabled. See
[historical-market-data.md](historical-market-data.md) and
[market-data-quality.md](market-data-quality.md).

## v0.22 live-validation status

BOI representative rates and policy interest, SEC submissions/companyfacts,
BBC Business RSS, and CBS series 3763 have bounded reviewed contracts. Exact
endpoints, request caps, access headers, storage policy, and replay classes are
in [live-validation.md](live-validation.md). BOI snapshots and BBC RSS are
forward-observation-only. SEC companyfacts and CBS series 3763 are temporally
ambiguous because today's response does not prove past visibility. Historical
BOI SDMX stays disabled pending a fixed series and vintage review.

## Bank of Israel policy interest

- **Registry ID:** `il.boi`
- **Authority:** official primary
- **Endpoint:** official `PublicApi/GetInterest` JSON
- **Cadence:** current snapshot; publisher-controlled
- **Timestamp semantics:** next-decision date is explicit; local observation
  controls visibility; missing release/effective timestamps remain unknown
- **Revision behavior:** no explicit revision history is exposed
- **Limitations:** not a historical decision or announcement archive

## Disabled government sources

Ministry of Finance (`il.mof`), Israel Securities Authority (`il.isa`), Knesset
(`il.knesset`), Competition Authority (`il.competition`), and Tax Authority
(`il.tax`) are registered but disabled pending source-specific contract review.

## BBC Business

- **Registry ID:** `uk.bbc.business`
- **Authority/trust:** established news; this does not imply factual correctness
- **Endpoint:** public BBC Business RSS feed
- **Cadence:** publisher-controlled, typically multiple updates per day
- **Timestamp semantics:** RSS `pubDate` is publisher-supplied;
  `first_observed_at` is generated locally and controls historical visibility
- **Revision behavior:** entries can be edited or removed; changed content at
  the same URI is retained as a new immutable revision
- **Access/storage:** feed payloads retained for internal provenance only; linked
  pages are not scraped or redistributed
- **Limitations:** feed summaries may omit article detail, and no explicit
  revision history is supplied

The source registry is the allowlist and metadata catalog for external
authorities. Registry inclusion does not grant runtime network access, and a
disabled source cannot be ingested.

## Bank of Israel (`il.boi`)

- **Authority:** official primary; central bank.
- **Enabled dataset:** `representative-exchange-rates`.
- **Endpoint:** official
  [`PublicApi/GetExchangeRates`](https://www.boi.org.il/PublicApi/GetExchangeRates)
  JSON endpoint.
- **Expected cadence:** once per Israeli foreign-currency business day, normally
  during the afternoon; publication time is not guaranteed.
- **Timestamp semantics:** each payload item supplies `lastUpdate`. MarketEvolver
  preserves it as that observed payload's `published_at` and `effective_at`.
  `first_observed_at` is generated locally after response receipt. The described
  period is the calendar date of `lastUpdate`.
- **Revision behavior:** Bank documentation says the separate series database
  is updated roughly 15 minutes after initial publication and may contain
  revised values. Every distinct payload hash is retained; no current response
  is backdated to an earlier visibility time.
- **Known limitations:** the current endpoint has no historical visibility or
  explicit supersession field. `lastUpdate` combines date and update time, and
  the API does not document a formal version identifier. Rates are indicative,
  not legally binding. v0.3 does not reconcile values with SDMX.

Official references:

- [Exchange rates](https://www.boi.org.il/en/economic-roles/financial-markets/exchange-rates/)
- [API/SDMX extraction guide](https://www.boi.org.il/information/bank-paymnts/guide/api-guide/)
- [Representative-rate explanatory notes](https://www.boi.org.il/en/economic-roles/financial-markets/explanatory-notes-to-the-representative-exchange-rates/)

## Israel Central Bureau of Statistics (`il.cbs`)

- **Authority:** official primary; national statistical office.
- **Status:** registered, disabled connector skeleton.
- **Expected cadence:** dataset-specific, ranging from monthly releases to
  quarterly and annual publications.
- **Timestamp semantics:** future connectors must preserve the statistical
  period, release/publication timestamp, local first observation, effective
  timestamp if defined, and revision/supersession time independently.
- **Revision behavior:** releases may be preliminary, revised, benchmarked, or
  seasonally adjusted. Every release vintage must remain addressable.
- **Known limitations:** no production API contract or dataset is fixed in v0.3.
  The skeleton performs no network request.

## TASE/MAYA (`il.tase.maya`)

- **Authority:** official primary for exchange-hosted corporate disclosures.
- **Status:** registered, disabled connector skeleton.
- **Expected cadence:** event-driven during disclosure publication windows.
- **Timestamp semantics:** future ingestion will distinguish issuer reporting
  period, exchange publication time, local first observation, effective time,
  and correction/supersession time.
- **Revision behavior:** filings may be corrected, replaced, or supplemented.
  Raw versions and their relationships must remain immutable.
- **Known limitations:** v0.3 defines only adapter and disclosure metadata
  shapes. It does not download filings or historical archives.

## Planned registry families

The registry enums and validation also accommodate future official sources such
as the Israel Securities Authority, Ministry of Finance, Knesset, and
Competition Authority, plus separately tiered news providers and untrusted
social platforms. Adding metadata never authorizes ingestion or execution.

## SEC EDGAR (`us.sec.edgar`)

- **Authority:** official primary; U.S. Securities and Exchange Commission.
- **Status:** enabled narrow connector for NICE, Elbit Systems, Teva, and ICL.
- **Endpoints:** official submissions and XBRL company-facts JSON APIs.
- **Expected cadence:** event-driven as filings are accepted.
- **Timestamp semantics:** SEC `filingDate` is publisher metadata;
  MarketEvolver's local `first_observed_at` independently controls visibility.
  Report period dates describe the filing and never imply prior availability.
- **Revision behavior:** amended filings have distinct accession numbers/forms;
  filing and observation records link restatements without overwriting originals.
- **Access:** network permission and an operator-supplied SEC-compliant contact
  `User-Agent` are required. Responses are size-bounded and must enter immutable
  artifact storage before parsing in a production ingestion run.
- **Known limitations:** company facts may contain multiple contexts, dimensions,
  custom taxonomy extensions, and amended duplicates. Version 0.8 parses only a
  small `us-gaap` allowlist and does not perform full XBRL reconciliation.

## Macro source candidates (v0.11)

| Registry ID | Authority | Status | Expected cadence | Revision and timestamp limitation |
| --- | --- | --- | --- | --- |
| `il.cbs` | Israel CBS, official primary | Disabled | Dataset-specific monthly/quarterly | Current values do not prove release vintages; CPI contract remains under review |
| `us.fred` | Federal Reserve Bank of St. Louis, official secondary | Disabled | Series-specific | ALFRED realtime periods must be captured and validated before replay |
| `eu.ecb.data` | ECB, official primary | Disabled | Series-specific | SDMX revisions require locally retained vintages |
| `global.worldbank` | World Bank, official secondary | Disabled | Usually annual | Histories may be rebenchmarked without complete vintage guarantees |
| `global.oecd.sdmx` | OECD, official secondary | Disabled | Series-specific | Dataset structures and observations can be revised |
| `us.eia` | EIA, official primary | Disabled | Daily through annual | API-key, release, and revision semantics require series-level review |

Registry presence is not enablement. v0.11 made no live request to these
sources. The already reviewed BOI FX and policy endpoints remain enabled, but
their current responses are not treated as complete historical macro archives.

## Geopolitical source candidates (v0.12)

| Registry ID | Class | Status | Limitation |
| --- | --- | --- | --- |
| `il.pmo.statements` | Official Israeli government | Disabled | No reviewed immutable statement/revision feed |
| `il.idf.statements` | Official Israeli security statements | Disabled | Operational updates and corrections lack an approved machine contract |
| `us.state.statements` | Foreign-government statements | Disabled | Feed/page revision and retention semantics require review |
| `global.un.press` | International institution | Disabled | Correction and publication-time contract requires review |
| `global.icao` | Aviation authority | Disabled | No approved cancellation/capacity historical API |
| `global.imo` | Shipping authority | Disabled | No approved route-disruption historical API |
| `global.iea` | Energy institution | Disabled | Licensing and release-vintage semantics require review |
| `uk.bbc.business` | Established global news | Enabled | Untrusted content; RSS edits are locally versioned and require corroboration |

The disabled aviation, shipping, and energy interfaces perform no fetch. Source
registration never authorizes network access or canonical event promotion.

## Social sources (v0.13)

Version 0.13 enabled no live social connector; only synthetic, publicly harmless
fixtures exercised the schemas. Private-message ingestion remains absent.
Connectors must prove public accessibility, legal retention, edit/delete
semantics, stable source identity, rate limits, and raw-artifact provenance.

## Telegram public sources (v0.14)

No channel is enabled in repository defaults. Operators may configure only
reviewed public-channel or public-group usernames in the explicit allowlist.
Telegram publication/edit metadata is source-supplied; local
`first_observed_at` alone establishes historical visibility. Messages and raw
artifacts are immutable, while edits and observed deletions append versions.
Forwards retain visible native origins or an explicit unknown-origin marker.
Media collection is metadata-only. API access, retention legality, channel
identity, revision behavior, and deletion observability must be reviewed per
source before enablement.
