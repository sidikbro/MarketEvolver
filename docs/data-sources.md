# Data sources

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
