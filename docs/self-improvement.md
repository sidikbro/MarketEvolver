# Governed self-improvement

MarketEvolver v0.19 lets approved experts propose bounded research-configuration changes. It does not
create/delete agents, mutate topology, activate production autonomously, generate executable code,
or modify paper-runtime authority.

Allowed proposal types cover prompts, reasoning checklists, retrieval/tool-selection policy within
existing capabilities, source ordering, context budget, routing metadata, and taxonomy hints. Each
proposal is immutable, attributable, and limited to three changes. Model suggestions remain
untrusted artifacts in `proposed` state.

Host-controlled risk, execution, broker, cutoff/leakage, provenance, append-only, evidence-trust, and
capability rules are immutable. A proposal touching them is rejected before challenger creation.
Tool changes may only reduce the parent allowlist. Source priority changes ordering, never authority
or truth status. Prompts may change domain reasoning, not host safety instructions.

Failure attribution separates quality failures from critical safety failures. Mature outcomes may
inform calibration, hypothesis validity, and benchmark-relative evaluation, but evolution does not
optimize solely for financial return. Cross-expert transfer is a new explicit proposal evaluated in
the recipient domain; it is never copied automatically.

Automatic promotion is designed as a policy field but is `false` in v0.19. No model/expert identity
can approve itself. Operator/governance promotion and rollback are immutable audit events.

v0.20 extends the proposal pattern to topology but does not let expert-version improvement expand
capabilities or create/activate specialists directly. Those changes require topology certification
and a separate governance activation event.
