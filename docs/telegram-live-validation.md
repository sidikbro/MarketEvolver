# Bounded live Telegram validation

Version 0.24 provides an operator-controlled check of the existing public
Telegram connector and social pipeline. It is a validation run, not a crawler,
source-discovery mechanism, or ingestion schedule. Deterministic tests and CI
never contact Telegram.

## Operator setup

Keep credentials, the session string, and the reviewed allowlist outside the
repository. A session may be supplied directly with
`MARKET_EVOLVER_TELEGRAM_SESSION` or through a protected text file named by
`MARKET_EVOLVER_TELEGRAM_SESSION_LOCATION`, but never both. Configure API ID,
API hash, and the allowlist path as shown in `.env.test.example`.

The allowlist is a local JSON array containing one to eight entries; three to
eight across distinct source classes is recommended. Each entry contains
`source_id`, public `public_identifier`, `source_class`, `languages`,
`domain_tags`, and `max_messages`. The maximum is 50. Private invite links,
phone-like identifiers, channel discovery, and linked-channel expansion are
rejected. Example shape:

```json
[{"source_id":"tg.reviewed.news","public_identifier":"public_username","source_class":"established_news","languages":["he"],"domain_tags":["public-affairs"],"max_messages":20}]
```

Run the deterministic system validation first, then make the separate explicit
live request:

```bash
make postgres-up
make validate
export MARKET_EVOLVER_TELEGRAM_LIVE_VALIDATION=YES
make validate-telegram-live TELEGRAM_LIVE=YES
```

Both the environment switch and CLI confirmation are required. Missing auth or
session material is reported as `SKIPPED_BY_OPERATOR`; an unreachable or
non-public allowlisted source fails that source. Reports and immutable raw
artifacts are written beneath
`data/live_validation/telegram/<run-id>/`, which Git ignores. Session files are
also ignored. Reports redact common credential fields and phone-like strings.

## Semantics and safety

At most 20–50 recent messages are requested per source. The connector records
native ID, Telegram publication/edit metadata, local observation time,
reply/forward metadata, engagement counters, links, mentions, hashtags,
language, text and artifact hashes, and source provenance. Media type, ID, and
caption are metadata only; no media bytes are downloaded. Missing messages are
not deletions. An edit is reported only when naturally observed against an
earlier retained version; otherwise the report says `NO_EDIT_CASE_OBSERVED`.

Known, hidden-origin, copied, and original messages are counted separately.
Forwards and copies never become independent confirmation. Narrow keyword and
metadata rules can append unreviewed `NarrativeCandidate` and unverified
`RumorClaim` records plus propagation edges. They cannot create canonical
events, promote claims, mutate graph facts or risk policy, create orders, or
interpret command-like text as instructions. Reputation remains
`insufficient_history` for this small observational sample. Cross-source fusion
is reported only if a natural governed match exists; otherwise it is explicitly
`no fusion candidate`.

Rate-limit handling is capped at three attempts with Telegram-requested delays
capped at 60 seconds. There is no circumvention. JSON and Markdown reports give
per-source counts, bytes/message, and text/metadata projections for 10, 100,
and 1,000 sources over 30 and 365 days. Media projections are clearly labeled
hypothetical and are not measurements.

## Privacy and legal limits

Every source requires operator review for public accessibility, retention,
jurisdiction, platform terms, and legitimate research purpose. The system does
not join or bypass private chats/groups, build contact graphs, infer identity,
enrich users, send messages, or recover deleted content that it did not already
observe. Public availability does not itself settle copyright, privacy, or
retention rights. Operators must minimize retention and remove a run with the
guarded cleanup option when its reviewed purpose ends.
