# Expert agents

MarketEvolver uses a fixed, reviewed catalog of domain specialists. Experts are not created,
rewritten, promoted, or connected dynamically. Each immutable version identifies its domain,
geography, horizons, entity/source/tool/task/mechanism allowlists, prompt version, model policy, and
mandatory forbidden capabilities.

The catalog contains General Market Researcher, Technology/AI, Israeli Real Estate, Banking/Macro,
Defense/Geopolitics, and Energy experts. Seeds begin in `evaluation`, not `approved`.

An expert request is not a host grant. Every repository read goes through the read-only research
tool registry, which validates expert status, cutoff, entity type, source class, and tool allowlist,
then persists the grant or denial. Structured results retain provenance and cannot contain records
observed after cutoff. Raw social text is never treated as instructions.

Sessions record task, subject/domain, horizon, cutoff, context manifest, authorized/used tools,
provider/model/prompt version, timestamps, status, and anonymization. Assessments distinguish
observations, inferences, hypotheses, counterevidence, mechanisms, uncertainties, evidence, and
unresolved questions. “No conclusion” is valid. Recommendation and order language is rejected.

Routing is deterministic from tags, geography, event/mechanism, and entity sector. Suspended experts
are excluded. Panels preserve each output and skeptical review; conflicts are not averaged away.

Experts have no execution authority. The only allowed path is `ExpertAssessment → reviewed
ResearchHypothesis → validated ExperimentSpecification → validated signal → deterministic risk
governor → paper runtime`.

Expert evolution creates immutable versions from bounded proposals; it never mutates a definition in
place or expands its host-granted capabilities. Champion changes require governance approval.
