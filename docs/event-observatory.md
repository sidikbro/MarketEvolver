# Event Observatory

## Purpose and boundary

The Event Observatory converts trusted, normalized evidence into canonical
market-event versions. It is deterministic and research-only. It produces no
forecasts, portfolio actions, BUY/SELL labels, orders, or execution requests.

## Event semantics

A canonical event records:

- a typed event classification and semantic deduplication key;
- source and evidence provenance;
- geography, canonical entities, sectors, and affected asset classes;
- source publication, local first-observation, and effective timestamps;
- status, confidence, novelty, and revision state;
- an optional superseded event version;
- direction-neutral causal mechanisms, tags, and sorted material attributes.

`event_id` is a SHA-256 content identity. `material_fingerprint` excludes
provenance arrival details and captures semantic facts used for exact
deduplication. Similar text is never a merge criterion.

## Historical truth and current truth

Historical truth means what MarketEvolver could legally support at cutoff T.
`get_events_visible_at(T)` returns only event versions locally observed by T and
checks that all of their required evidence was also visible by T.

Current truth is derived from the latest lifecycle transitions visible now. It
does not replace historical truth:

```text
T1: event A observed -> confirmed
T2: event B observed -> revised; B supersedes A
    event A confirmed -> superseded
```

A replay at T1 sees only A and its T1 status. A replay after T2 sees A, B, and
their revision relationship. A remains immutable and directly queryable.

## Lifecycle and revision policy

Supported states are `observed`, `proposed`, `confirmed`, `revised`,
`superseded`, and `retracted`. Transitions are explicit append-only records with
an event ID, ordered sequence, timestamp, before/after states, rationale,
evidence IDs, and reviewer status. Superseded and retracted states are terminal.

An exact semantic/material match reuses the canonical event and adds an
append-only support relationship for new official provenance. A changed value
under the same semantic key must create a new event with a non-original revision
state and `supersedes_event_id`. Changes are never silently merged into the old
row.

## Entity model

The initial registry contains Bank of Israel, ILS, USD, EUR, Israel, the
financial and real-estate sectors, exporters, and importers. Entity types are
extensible to companies, ministries, foreign governments, commodities, and
industries. Extractors may emit events only for registered entities.

## Causal mechanism model

Mechanisms are separate canonical concepts:

- currency translation;
- import cost;
- export competitiveness;
- financing cost;
- credit demand;
- interest margin;
- risk premium;
- consumer demand.

An event-to-mechanism link records confidence, expected horizon, rationale,
evidence provenance, reviewer status, and link time. A link identifies a
possible transmission channel, not a predicted sign or investment direction.

## Initial deterministic rules

For registered BOI USD/EUR representative rates:

1. Every supported observation produces a representative-rate update.
2. An observation with a prior supported rate produces a percentage movement.
3. An absolute movement of at least 1.0 percent also produces an unusual-FX-move
   event.
4. A materially changed observation for the same currency and period produces a
   revision that supersedes the prior version.

`boi_policy_event` exists only as a future typed placeholder. No policy event is
inferred from exchange-rate data.

## Observatory report

The deterministic report measures events by source and type, revision count,
referenced entities and mechanisms, and first-observed coverage range. It
contains no recommendation or capacity forecast.

## Known limitations

- Only USD and EUR BOI rates are entity-linked in v0.4.
- Rules do not infer intent, cause, surprise relative to expectations, or market
  impact.
- The unusual-move threshold is fixed and not volatility-adjusted.
- Event support is append-only, but the event's original source/evidence arrays
  remain the provenance that created its content ID; additional support lives in
  the support table.
- PostgreSQL application roles still need database-level UPDATE/DELETE denial to
  complement ORM immutability hooks.
