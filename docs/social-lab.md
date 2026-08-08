# Social Lab

Version 0.13 defines an offline foundation for public social/community sources.
Private messages and private groups are rejected. No Telegram or other live
connector is enabled. Platform verification describes identity metadata, not
truthfulness.

Every post is immutable and defaults to `untrusted_unstructured`. Edits and
observable deletions append versions. Original text, normalized text, hashes,
artifact references, URLs, mentions, language, metrics, and provenance remain
separate. Social content cannot promote canonical events, mutate graph facts,
change permissions or policy, or trigger execution.

Research context includes reviewed narrative candidates and versioned rumor
status only. Raw post text is excluded by default. Replay uses local observation
time for posts, edits, deletions, claims, and reputation snapshots.

Only harmless synthetic fixtures are included: accurate and false rumors,
copies, edits, bilingual propagation, a coordination-looking cluster, and
independent corroboration.
