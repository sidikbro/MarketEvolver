# Controlled live validation

Version 0.22 validates reviewed public contracts without placing network access
in normal tests or CI. It is not a crawler or production ingestion schedule.

## Operator workflow

Run deterministic validation first, then explicitly opt in:

```bash
make postgres-up
make validate
export MARKET_EVOLVER_SEC_USER_AGENT="MarketEvolver Research contact@example.com"
export MARKET_EVOLVER_CBS_USER_AGENT="MarketEvolver Research contact@example.com"
make validate-live LIVE=YES
```

Do not commit operator contact strings. Both `LIVE=YES` and the CLI's
`--confirm-live` are opt-in barriers. JSON, Markdown, and raw artifacts go under
`data/live_validation/<run-id>/`. The CLI `--cleanup` option deletes only its
generated `live-*` directory beneath `live_validation`.

## Reviewed contracts

| Source | Endpoint | Bound | Temporal class |
|---|---|---:|---|
| BOI current FX | `https://www.boi.org.il/PublicApi/GetExchangeRates` | 1 MB, one request | forward observation only |
| BOI policy | `https://www.boi.org.il/PublicApi/GetInterest` | 100 KB, one request | forward observation only |
| BOI historical FX | BOI SDMX `RER_USD_ILS` | 5 MB, bounded to ten years | outcome measurement only |
| SEC submissions | `https://data.sec.gov/submissions/CIK{cik}.json` | 20 MB, one request/CIK | temporally ambiguous |
| SEC company facts | `https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json` | 20 MB, one request/CIK | temporally ambiguous |
| BBC Business | `https://feeds.bbci.co.uk/news/business/rss.xml` | 2 MB, one request | forward observation only |
| CBS series 3763 | `https://apis.cbs.gov.il/series/data/list?id=3763&last=3&format=json&download=false&lang=en` | 1 MB, one request | temporally ambiguous |

SEC validation is limited per run to Teva (`0000818686`) and Elbit Systems
(`0001027664`) and uses structured JSON, not filing HTML. CBS requires an
identifying User-Agent as documented by CBS.

Each successful response is content-addressed before parsing, re-read to verify
its hash, and written again to verify immutable idempotency. Reports record the
contract fingerprint, parser, volume, item count, hash, and provenance chain.
Media-type or required-field drift fails closed. HTTP errors, rate limits, and
malformed data are not aggressively retried.

Missing SEC or CBS identification produces `SKIPPED_BY_OPERATOR` and a degraded
report. Contacted broken sources produce `FAILED`. Reports redact email-like
contacts, URL passwords, and common secret fields. No article bodies, broad CBS
catalog, or historical bulk data are requested.

Thirty- and 365-day storage projections are linear estimates from the observed
bounded workload, not capacity forecasts. Snapshot APIs cannot reconstruct
uncaptured vintages. Fusion is reported as `no fusion candidate` unless live
claims naturally match, and ratios are not manufactured from incompatible SEC
facts.

Telegram validation is a separate command, configuration surface, and artifact
subtree. It is never included implicitly in `validate-live`; follow the bounded
workflow in [telegram-live-validation.md](telegram-live-validation.md).
