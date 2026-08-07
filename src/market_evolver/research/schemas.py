"""Immutable schemas for constrained model-assisted research."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from re import search

from market_evolver.errors import ValidationError
from market_evolver.provenance import content_id
from market_evolver.time import require_aware_utc


class ResearchTask(str, Enum):
    EVENT_EXTRACTION = "event_extraction"
    ENTITY_EXTRACTION = "entity_extraction"
    MECHANISM_EXTRACTION = "mechanism_extraction"
    EVIDENCE_SUMMARIZATION = "evidence_summarization"
    CONTRADICTION_IDENTIFICATION = "contradiction_identification"
    HYPOTHESIS_GENERATION = "hypothesis_generation"


class ClaimType(str, Enum):
    OBSERVATION = "observation"
    INFERENCE = "inference"
    HYPOTHESIS = "hypothesis"


class ReviewState(str, Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"
    REJECTED = "rejected"


class HypothesisStatus(str, Enum):
    PROPOSED = "proposed"
    UNDER_REVIEW = "under_review"
    ACCEPTED_FOR_TEST = "accepted_for_test"
    REJECTED = "rejected"
    FALSIFIED = "falsified"
    SUPPORTED = "supported"
    INCONCLUSIVE = "inconclusive"


@dataclass(frozen=True, slots=True)
class ContextItem:
    kind: str
    provenance_id: str
    first_observed_at: datetime
    text: str
    evidence_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "first_observed_at",
            require_aware_utc(self.first_observed_at, "first_observed_at"),
        )
        if not self.kind or not self.provenance_id or not self.text:
            raise ValidationError("context item identity and text are required")


@dataclass(frozen=True, slots=True)
class ResearchContext:
    cutoff: datetime
    subject_id: str
    items: tuple[ContextItem, ...]
    anonymized: bool = False
    research_context_id: str = field(init=False)

    def __post_init__(self) -> None:
        cutoff = require_aware_utc(self.cutoff, "cutoff")
        object.__setattr__(self, "cutoff", cutoff)
        if not self.subject_id:
            raise ValidationError("research context subject is required")
        if any(item.first_observed_at > cutoff for item in self.items):
            raise ValidationError("research context contains future information")
        ids = [item.provenance_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValidationError("research context provenance IDs must be unique")
        object.__setattr__(self, "research_context_id", content_id("research-context", self))

    @property
    def allowed_provenance_ids(self) -> frozenset[str]:
        return frozenset(
            item_id for item in self.items for item_id in (item.provenance_id, *item.evidence_ids)
        )


@dataclass(frozen=True, slots=True)
class AnonymizationMapping:
    research_context_id: str
    values: tuple[tuple[str, str], ...]
    created_at: datetime
    mapping_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", require_aware_utc(self.created_at, "created_at"))
        if not self.research_context_id or not self.values:
            raise ValidationError("anonymization mapping requires a context and values")
        if len({alias for _, alias in self.values}) != len(self.values):
            raise ValidationError("anonymization aliases must be unique")
        object.__setattr__(self, "mapping_id", content_id("anonymization-mapping", self))


@dataclass(frozen=True, slots=True)
class ContextManifest:
    research_context_id: str
    cutoff: datetime
    subject_id: str
    evidence_ids: tuple[str, ...]
    event_ids: tuple[str, ...]
    policy_ids: tuple[str, ...]
    filing_ids: tuple[str, ...]
    fundamental_ids: tuple[str, ...]
    graph_versions: tuple[str, ...]
    model_id: str
    prompt_version: str
    created_at: datetime
    manifest_id: str = field(init=False)

    def __post_init__(self) -> None:
        cutoff = require_aware_utc(self.cutoff, "cutoff")
        created = require_aware_utc(self.created_at, "created_at")
        object.__setattr__(self, "cutoff", cutoff)
        object.__setattr__(self, "created_at", created)
        if created < cutoff:
            raise ValidationError("context manifest cannot predate cutoff")
        object.__setattr__(self, "manifest_id", content_id("context-manifest", self))


@dataclass(frozen=True, slots=True)
class ResearchClaim:
    claim_type: ClaimType
    text: str
    supporting_evidence_ids: tuple[str, ...]
    contradicting_evidence_ids: tuple[str, ...]
    entities: tuple[str, ...]
    mechanisms: tuple[str, ...]
    horizon: str
    confidence: float
    model_id: str
    prompt_version: str
    created_at: datetime
    review_state: ReviewState = ReviewState.PROPOSED
    claim_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", require_aware_utc(self.created_at, "created_at"))
        if not self.text or not self.supporting_evidence_ids:
            raise ValidationError("model claims require text and supporting evidence")
        if not 0 <= self.confidence <= 1:
            raise ValidationError("claim confidence must be between zero and one")
        if search(
            r"\b(buy|buying|sell|selling|allocate|allocation|order|trade|recommend)\b",
            self.text.casefold(),
        ):
            raise ValidationError("research claim contains forbidden action language")
        object.__setattr__(self, "claim_id", content_id("research-claim", self))


@dataclass(frozen=True, slots=True)
class ResearchHypothesis:
    subject_entities: tuple[str, ...]
    mechanism_chain: tuple[str, ...]
    evidence_basis: tuple[str, ...]
    counterevidence: tuple[str, ...]
    expected_horizon: str
    measurable_outcome: str
    falsification_criterion: str
    confidence: float
    generated_by: str
    generated_at: datetime
    cutoff: datetime
    status: HypothesisStatus = HypothesisStatus.PROPOSED
    hypothesis_id: str = field(init=False)

    def __post_init__(self) -> None:
        generated = require_aware_utc(self.generated_at, "generated_at")
        cutoff = require_aware_utc(self.cutoff, "cutoff")
        object.__setattr__(self, "generated_at", generated)
        object.__setattr__(self, "cutoff", cutoff)
        if cutoff > generated:
            raise ValidationError("hypothesis cutoff cannot follow generation")
        if not self.subject_entities or not self.evidence_basis:
            raise ValidationError("hypothesis requires subjects and evidence")
        if (
            not self.expected_horizon
            or not self.measurable_outcome
            or not self.falsification_criterion
        ):
            raise ValidationError("hypothesis must be time-bounded and falsifiable")
        if not 0 <= self.confidence <= 1:
            raise ValidationError("hypothesis confidence must be between zero and one")
        object.__setattr__(self, "hypothesis_id", content_id("research-hypothesis", self))


@dataclass(frozen=True, slots=True)
class ReviewerResult:
    hypothesis_id: str
    accepted: bool
    issues: tuple[str, ...]
    alternative_explanations: tuple[str, ...]
    stale_evidence_ids: tuple[str, ...]
    reviewed_at: datetime
    model_id: str
    prompt_version: str
    reviewer_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "reviewed_at", require_aware_utc(self.reviewed_at, "reviewed_at"))
        if self.accepted and self.issues:
            raise ValidationError("review with unresolved issues cannot be accepted")
        object.__setattr__(self, "reviewer_id", content_id("research-review", self))


@dataclass(frozen=True, slots=True)
class ProviderCall:
    provider_id: str
    model_id: str
    requested_at: datetime
    responded_at: datetime
    settings: tuple[tuple[str, str], ...]
    prompt_version: str
    token_usage: tuple[tuple[str, int], ...]
    raw_response_hash: str
    structured_result: tuple[ResearchClaim, ...]
    call_id: str = field(init=False)

    def __post_init__(self) -> None:
        requested = require_aware_utc(self.requested_at, "requested_at")
        responded = require_aware_utc(self.responded_at, "responded_at")
        object.__setattr__(self, "requested_at", requested)
        object.__setattr__(self, "responded_at", responded)
        if responded < requested or not self.raw_response_hash.startswith("sha256:"):
            raise ValidationError("invalid provider call timeline or response hash")
        object.__setattr__(self, "call_id", content_id("provider-call", self))


@dataclass(frozen=True, slots=True)
class ResearchTrace:
    manifest_id: str
    provider_call_id: str
    claim_ids: tuple[str, ...]
    hypothesis_id: str | None
    reviewer_id: str | None
    validation_state: str
    accepted: bool
    created_at: datetime
    trace_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", require_aware_utc(self.created_at, "created_at"))
        if self.accepted and self.validation_state != "validated":
            raise ValidationError("unvalidated trace cannot be accepted")
        object.__setattr__(self, "trace_id", content_id("research-trace", self))
