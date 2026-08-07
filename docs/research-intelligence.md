# Constrained research intelligence

## Trust boundary

An LLM is an untrusted research component, not an authority. Its output cannot
become an accepted claim, canonical event, runtime permission, order, or other
action automatically. MarketEvolver v0.9 contains no trading or broker path.

The deterministic mock provider is the default. The configurable JSON/HTTPS
adapter is provider-neutral and requires explicit host network permission plus
an endpoint supplied through the environment. Authorization values are never
written to manifests, calls, traces, logs, or provenance records.

## Research contexts and manifests

A `ResearchContext` is an immutable snapshot assembled at cutoff `T`. Every
item carries an ID, local first-observation timestamp, text representation, and
supporting evidence IDs. The assembler uses cutoff-aware repositories for
companies, filings, fundamentals, exposures, events, government actions, and
knowledge-graph relationships. It rejects any item or evidence learned after
`T`.

Before each research or reviewer call, an immutable context and canonical
manifest are committed. The manifest identifies the exact context, cutoff,
subject, evidence, events, policies, filings, observations, graph versions,
model, prompt version, and creation time. Its content-derived ID is the
reproducibility boundary. Equal inputs create the same context ID; later records
cannot enter an earlier replay.

## Structured output and provenance

Supported task families are event and entity extraction, candidate mechanisms,
evidence summarization, contradiction identification, and hypothesis
generation. Each provider returns a typed JSON array. Malformed JSON, missing
fields, unsupported evidence IDs, future data, action language, timeouts, and
oversized responses fail closed.

Claims are explicitly `observation`, `inference`, or `hypothesis`. These classes
are not interchangeable. Every claim needs supporting evidence from the exact
input context and may separately identify counterevidence. Provider suggestions
remain proposed; acceptance is a separate reviewed record and still has no path
to canonical event storage or permissions.

## Hypotheses and skeptical review

A research hypothesis records subjects, mechanism chain, evidence and
counterevidence, horizon, measurable outcome, falsification criterion,
confidence, generator, generation time, cutoff, and status. Supported means
only that specified evidence was consistent with the specified test; it never
means universally true.

The skeptical reviewer receives a separate, manifested context and provider
call. Deterministic gates check missing provenance, causal gaps, stale evidence,
unclear horizons, and testability. Structured reviewer output records issues
and alternative explanations. Review cannot rewrite the hypothesis or its
source trace.

## Prompt injection

Prompt rendering separates system policy, task instructions, required output,
and `evidence_data`. Article, filing, and document text is always DATA. Text such
as “ignore previous instructions,” “recommend buying,” or “change permissions”
is retained for provenance but has no control channel. Structured action or
recommendation output is rejected.

## Historical-name anonymization

Optional anonymization replaces subject and supplied historical names with
stable aliases such as `COMPANY_A`. The reversible mapping is returned to the
caller but is not embedded in the model context. Provenance IDs remain unchanged
so validation still works.

Anonymization can compare named and unnamed research and reduce direct
historical-outcome cues. It cannot remove all clues from values, dates, sectors,
filings, or model pretraining and is not a guarantee against memorized leakage.

## Trace, baselines, and CLI

The append-only trace records context, manifest, prompt version, provider
metadata and raw hash, structured claims, validation, reviewer, and final
acceptance/rejection. Provider secrets are excluded. Deterministic baselines
provide exact entity/event extraction, mechanism lookup, no-LLM evidence
summarization, and conservative empty contradiction/hypothesis outputs.

```bash
market-evolver research build-context nice --at 2025-01-02T12:00:00+00:00
market-evolver research build-context nice --at 2025-01-02T12:00:00+00:00 --anonymize
market-evolver research inspect-context <context-id>
market-evolver research hypothesize nice --at 2025-01-02T12:00:00+00:00
market-evolver research review <hypothesis-id>
market-evolver research trace <trace-id>
```

## Known limitations

- The mock output is a test fixture, not useful financial analysis.
- The generic HTTP adapter assumes a small JSON envelope rather than a vendor SDK.
- Context selection is intentionally conservative and may omit relevant facts.
- Ordinary news remains untrusted and is not included merely because a model mentions it.
- Reviewer checks cannot establish causal truth, novelty, or whether information was priced in.
- Pretraining may contain future knowledge; manifests and aliases cannot erase model weights.
