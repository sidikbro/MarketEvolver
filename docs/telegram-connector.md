# Telegram Public-Source Connector

Version 0.14 adds an optional Telegram client behind a narrow adapter. It is
disabled by default and accepts only explicitly allowlisted, publicly accessible
channels or public groups. Private chats, private groups, contacts, join links,
discovery, and unrestricted search are outside its contract.
It performs no contact-graph construction, identity inference, user profiling,
doxxing-style enrichment, message sending, or recovery of content MarketEvolver
did not previously observe.

## Configuration and credentials

Each allowlist entry has a stable internal ID, public username, source type,
languages, domain tags, collection bound, optional earliest date, and media
policy. An enabled entry must specify `since` or `max_messages`; a run can never
exceed 1,000 messages. Collection additionally requires trusted runtime network
and secrets permissions.

Telegram API ID, API hash, and StringSession are read only from the environment:

- `MARKET_EVOLVER_TELEGRAM_API_ID`
- `MARKET_EVOLVER_TELEGRAM_API_HASH`
- `MARKET_EVOLVER_TELEGRAM_SESSION`

They are never accepted in repository configuration, manifests, artifacts, or
logs. Operators must use a dedicated account, protect its session as a secret,
and review the current Telegram terms and client-library license before use.
Telethon was selected behind a replaceable adapter because it supports public
entity validation and bounded message iteration without coupling those APIs to
the governed domain model.

## Provenance and replay

The connector computes and stores the immutable raw message artifact before
normalization. Each resulting untrusted social post retains the channel,
Telegram message ID, local first-observation time, Telegram publication/edit
metadata, text hash, artifact hash, replies, URLs, mentions, available
engagement counters, and media metadata. Media bytes are not downloaded. Native
forwards preserve the reported origin message when visible; hidden origins
remain explicitly unknown.

Edits and observed deletions append new records. A replay before the local
observation of an edit or deletion sees the earlier version. Repeated fetches
are idempotent and checkpoints are append-only. Disappearance alone is not
treated as proof of deletion when a bounded API result could explain it;
current live deletion capture therefore requires an explicit Telegram update
or a later reviewed reconciliation contract.

Telegram text is always `untrusted_unstructured`. It cannot create a trusted
event, change policy or permissions, invoke tools, or trigger execution.
Embedded prompts remain inert quoted data. Narrative, rumor, coordination, and
reputation layers consume only their existing governed review paths.

## Operations

```bash
market-evolver telegram validate
market-evolver telegram ingest <allowlist-source-id> --limit 20
market-evolver telegram backfill <allowlist-source-id> --since 2025-01-01 --limit 100
market-evolver storage-telemetry
```

Run manifests record success, partial failure, or failure plus message, edit,
forward, deletion, byte, duplicate, and error counts. Rate limits receive at
most three bounded retries. Failures do not relax the allowlist or collection
limit. Raw artifacts use the configured content-addressed artifact root and
must remain outside Git.

Known limitations include API visibility changes, unavailable or mutable
engagement counters, hidden forward origins, ambiguous missing-message gaps,
and the absence of a configured production allowlist in the repository.

Version 0.24 adds a separate, doubly opted-in validation harness capped at 50
recent messages per reviewed source. It preserves hashtags, emits only
unreviewed deterministic narrative/rumor candidates, classifies native forward
lineage, and writes redacted reports outside Git. See
[telegram-live-validation.md](telegram-live-validation.md).
