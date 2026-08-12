# Historical market-data quality

Validation flags uncertainty and never repairs values automatically. It detects
duplicate/out-of-order timestamps, impossible or negative OHLCV, missing
expected sessions, zero volume, extreme moves, split-like discontinuities, and
currency disagreement. Parquet and normalized-row hashes are verified.

Corporate actions are independent evidence-backed records. A discontinuity is
not silently treated as a split. Missing action metadata degrades the dataset.
Raw prices are never replaced by adjusted values; adjusted close is used only
when supplied under an explicit manifest policy.

Venue sessions must come from an explicit reviewed calendar. Price-row existence
does not prove session status, and shortened sessions require explicit times.
Current fixtures validate calendar alignment; production TASE and U.S. calendar
connectors remain a known gap.

DuckDB provides coverage, benchmark/FX joins, duplicate diagnostics, and scan
measurements. Cross-source comparison reports differences without synthesizing
a consensus. Telemetry separates raw, normalized, Parquet, and catalog bytes;
records compression and performance; and projects daily storage for 18, 100,
and 1,000 instruments over 5, 10, and 20 years. These are linear market-row
estimates, not news/social capacity forecasts.
