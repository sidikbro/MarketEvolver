# Archive policy

The archive is a manually invoked scheduler interface, not a background daemon:

```bash
market-evolver archive run
market-evolver archive source il.boi
market-evolver archive status
market-evolver archive backfill-report
```

`archive run` and `archive source` record explicit skipped manifests until an
operator configures a reviewed adapter and credentials. They do not silently
perform network requests. Adapter families cover BOI, BBC/news, SEC, CBS,
government/policy, TASE/MAYA, geopolitical official feeds, and future
allowlisted Telegram text. Disabled contracts stay disabled.

Retention classes are:

- critical raw evidence: retain for replay reproducibility;
- normalized artifacts: retain, but independently rebuildable from raw;
- derived caches: rebuildable and not historical proof;
- media: separate legal/storage policy, never implicitly enabled.

Official archive discovery remains source-specific. SEC accessions may provide
primary release evidence when a compliant User-Agent and clear filing timestamp
exist. BOI current snapshots, historical statistical outcome series, and dated
publication archives remain distinct. Current CBS values are archived going
forward; they are not historical release vintages. Government and MAYA archive
contracts require review before enablement. News history is accepted only from
authorized operator-supplied archives with explicit provenance.

Coverage reports expose snapshots, bytes, revisions, gaps, last successful
observation, and retention policy by source. Storage estimates show
official-only, official plus news, official/news/Telegram text, and a separately
labeled hypothetical media scenario. Projections use observed bytes and an
explicit revision multiplier; they are planning estimates, not guarantees.
