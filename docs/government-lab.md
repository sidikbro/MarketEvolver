# Government and Regulation Lab

## Semantics and boundary

A `GovernmentAction` is an immutable, versioned record of an official-policy,
legislative, regulatory, fiscal, procurement, or monetary-policy development.
It preserves jurisdiction, issuing body, action type, explicit dates, local
first observation, evidence, affected entities, candidate mechanisms,
confidence, expectation status, and provenance.

Government text and deterministic candidates cannot automatically mutate a
canonical event or the knowledge graph. Promotion is a separate reviewed
operation. No action or mechanism implies asset-price direction or an investment
recommendation.

## Lifecycle

Lifecycle transitions are append-only, timestamped, evidence-backed, and
validated against an explicit state graph. Supported states include rumored,
proposed, consultation, submitted, committee, approved, published, effective,
enforced, challenged, amended, suspended, repealed, and expired. Not every
action passes through every state; only modeled transitions are accepted.

Proposal, approval, publication, and effectiveness are distinct. An effective
date may legally precede or follow publication, but a publication cannot be
treated as locally observed before it was published.

## Historical replay and revisions

Visibility is controlled by `first_observed_at`. Transition state at cutoff T
uses only transitions recorded by T. Corrections and amendments append a new
version with `supersedes_action_id`; earlier versions remain queryable.
Contradictions reuse the News Lab evidence-contradiction records and never
silently replace either claim.

## Extraction and mechanisms

Extraction is deterministic and limited to exact issuing bodies, dates,
percentages, named entities/sectors, action keywords, and lifecycle wording.
Curated candidate mappings include interest-rate actions to financing cost,
refinancing cost, credit demand, and interest margin; housing policy to
financing and construction channels; and procurement to government spending.
They are hypotheses about transmission channels, not impact predictions.

`expectation_status` is always `unknown` in v0.7. Consensus, implied rates,
guidance, and surprise scoring are intentionally not implemented.

## Sources and limitations

The enabled policy connector reads the official BOI `GetInterest` JSON endpoint.
Raw bytes are stored before parsing. The endpoint exposes the current rate and
next decision date but currently provides neither the release timestamp nor
revision history, so those values remain unknown.

Ministry of Finance, Israel Securities Authority, Knesset, Competition
Authority, and Tax Authority definitions are registered but disabled pending
stable contract review. No legal interpretation, policy-intent inference,
sentiment, translation, or surprise scoring is performed.
