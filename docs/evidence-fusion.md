# Evidence Fusion

Version 0.15 introduces a governed resolution layer above official evidence,
policy actions, filings, macro observations, geopolitical events, news, and
reviewed social narratives. A unified claim is an immutable, versioned
proposition with an explicit semantic class. Rumors, narratives, forecasts, and
interpretations are never silently converted into factual events.

## Deterministic identity and lineage

Claims fuse only when claim type and domain agree, entities overlap, observation
times are within the configured deterministic window, and either an explicit
evidence identifier or exact normalized proposition fingerprint agrees. Semantic
similarity alone is insufficient.

Lineage records `originated_from`, `copied_from`, `forwarded_from`,
`derived_from`, `corroborated_by`, `contradicted_by`, `superseded_by`, and
`corrected_by`. Each edge has its own observation time, evidence, and rationale.
Corroboration classifies independence as independent, likely syndicated, copied,
forwarded, same-primary-source, or unknown. Repetition of one primary report
therefore does not inflate the independent evidence count.

## Resolution and contradiction

Append-only resolution records support confirmed, partially confirmed,
contradicted, unresolved, and expired outcomes. Non-authoritative sources cannot
resolve their own claims without independent or official supporting evidence.
Contradictions preserve the exact proposition and evidence on both sides;
ambiguity remains explicit instead of forcing consensus.

The fusion score exposes authority, independence, corroboration count,
provenance completeness, contradiction burden, temporal consistency, and
historical domain reputation separately. Its deterministic total is a summary,
not an unexplained truth or investment score.

## Replay and research

All claims, lineage, corroboration, contradictions, resolutions, scores, and
reputation snapshots are cutoff-aware. Research context may consume a compact
fused bundle containing the proposition, provenance, corroboration state,
contradiction count, and historical domain precision. Raw untrusted social/news
text remains excluded by default.

The bundled seven-case synthetic benchmark covers an early true rumor, early
false rumor, syndicated false claim, official correction, copied true claim,
mixed Hebrew/English propagation, and unresolved claim. It is a deterministic
governance regression fixture, not a predictive performance claim.

Known limitations: exact fingerprints miss paraphrases by design; explicit
source-lineage metadata may be incomplete; temporal windows are coarse; and the
initial uncertainty label is sample-size based rather than a statistical
credible interval.
