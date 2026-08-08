# Source Reputation

Reputation is historical, domain-specific, and point-in-time. MarketEvolver does
not produce a single global trust score. Supported domains are technology, real
estate, banking, defense, energy, tourism, macro, policy, geopolitics, and
company-specific claims.

For a source/domain/window snapshot the engine records claims originated,
confirmed, contradicted, unresolved, precision among resolved claims,
confirmation lead time, contradiction rate, copy/forward rate, original-content
rate, sample size, and an explicit uncertainty label. Full claim and outcome
history remains immutable even when a recency window is selected.

Only resolutions visible at cutoff `T` affect a snapshot at `T`. A confirmation
or contradiction learned later cannot improve or damage historical reputation.
Copied and forwarded claims do not receive origination credit. Sparse samples
are labeled `insufficient_sample`; consumers must inspect sample size and
components rather than treating precision as certainty.

Lead-time metadata separately preserves the first known social, news, official,
and filing observations plus confirmation and contradiction times. It supports
descriptive questions about historical earliness without implying truth,
causality, or an investment recommendation.
