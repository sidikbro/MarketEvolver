# Historical research replay

Backtest replay consumes the same cutoff-correct market catalog and persists a
manifest of every Parquet hash, source version, parameter hash, code version,
and seed. Experiment signals must carry their own observation time and
provenance. Test results never rewrite the committed experiment specification.

Fusion replay exposes only claim versions, lineage, corroboration, resolutions,
contradictions, and reputation snapshots observed by the cutoff. Later official
confirmation and later source-performance knowledge never alter the historical
bundle. Full history remains available outside the selected recency window.

Telegram post versions use local `first_observed_at` for replay eligibility.
Later edits and observed deletions cannot leak backward; the original immutable
version remains queryable at earlier cutoffs. Hidden forward origins remain
unknown rather than being reconstructed.

## Deterministic clock and visibility

The replay clock advances daily, through an explicit event timestamp sequence,
or through a caller-supplied configured sequence. At timestamp `T`, a snapshot
contains only canonical events, policy actions, news, fundamentals, graph
relationships, market observations, macro-release vintages, deterministic
trends, and curated structural candidates whose local visibility time is no
later than `T`. Publisher dates and reconstructed market or macro periods cannot
grant earlier visibility. A later macro revision replaces current query output
but never changes an earlier replay snapshot.

Geopolitical snapshots similarly retain the confirmation state, candidate
mechanism paths, and contradictions known at `T`. A rumor visible at `T1` remains
a rumor in that replay even if an official confirmation or contradiction arrives
at `T2`. Reopenings, ceasefire violations, sanctions amendments, and resolutions
append versions rather than overwriting the earlier state.

Social replay selects only posts and edit/delete observations visible at `T`,
rumor status known at `T`, reviewed narrative objects, propagation edges, and
reputation snapshots computed from outcomes known by `T`. Raw social text is not
automatically added to model context.

Before advancing, the engine requires an immutable research commitment bound to
the current case and timestamp. It records the context manifest, hypothesis,
horizon, measurable outcome, falsification criterion, confidence, reviewer
decision, research mode, and commit time. PostgreSQL and ORM append-only controls
reject later modification.

## Outcomes

After the declared horizon matures, deterministic evaluation computes:

- forward return from the last price visible at commitment time;
- benchmark-relative return when a compatible benchmark series exists;
- maximum adverse and favorable excursion;
- realized volatility across visible horizon observations;
- path drawdown;
- direction only when the case explicitly requests it.

These are research outcome labels, not strategy profit, portfolio performance,
or executable trading results. Every evaluation retains the exact market
observation IDs used.

## Leakage audit

The snapshot audit explicitly checks the replay timestamp and cutoff gates for
prices, fundamentals, restatements, article revisions, and government
revisions. Dataset-level caveats remain visible:

- company aliases cannot remove outcomes memorized in model pretraining;
- benchmark composition is not historically reconstructed in v0.10;
- the small curated company universe has survivorship bias.

A passed timestamp audit does not clear those dataset caveats.

## CLI

```bash
market-evolver replay seed-cases
market-evolver replay run company_filing --mode event_rules
market-evolver replay run company_filing --mode llm_reviewed --anonymized
market-evolver replay inspect <run-id>
```

Version 0.10 commits replay research but does not schedule jobs, select assets,
allocate capital, or advance a clock autonomously.
