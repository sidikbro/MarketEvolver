# Narrative Intelligence

Telegram ingestion in v0.14 does not bypass this layer. Allowlisted messages
remain untrusted observations; native forwards, likely copies, and originals
are distinguished before narrative or rumor aggregation. No message text can
promote itself to trusted evidence or alter reviewer policy.

A narrative is not a fact. Candidates retain supporting posts, topics, entities,
language, extraction method, confidence, corroboration, contradiction, lifecycle,
and review state. Rumor confirmation appends a new claim version and cannot leak
backward.

Propagation distinguishes replies, quotes, reposts, forwards, likely copies,
shared URLs, and shared text. Exact hashes, normalized text, URL overlap, and
deterministic token similarity prevent copied amplification from being counted
as independent evidence.

Metrics remain multidimensional: volume, unique sources, original/copy ratios,
concentration, velocity, diversity, language spread, edits/deletions,
corroboration lag, and contradiction rate. There is no single sentiment score.

Coordination records are candidates based on timing/content features, never bot
or malicious-actor accusations. Reputation is domain-specific, windowed,
sample-size-aware, immutable, and computed only from outcomes known at cutoff.
