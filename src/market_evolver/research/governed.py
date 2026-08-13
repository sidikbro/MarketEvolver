from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from market_evolver.archive.schemas import VintageClassification
from market_evolver.errors import GovernanceViolation, IntegrityViolation, ValidationError
from market_evolver.external.schemas import UsageAccounting
from market_evolver.provenance import content_id
from market_evolver.research.schemas import ResearchClaim
from market_evolver.time import require_aware_utc


class EvidenceGateStatus(str, Enum):
    PASS = "PASS"
    BLOCKED_EVIDENCE = "BLOCKED_EVIDENCE"


class GroundingStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    PARTIALLY_SUPPORTED = "PARTIALLY_SUPPORTED"
    UNSUPPORTED = "UNSUPPORTED"
    CONTRADICTED = "CONTRADICTED"


class GovernedRunStatus(str, Enum):
    PASS = "PASS"
    BLOCKED_EVIDENCE = "BLOCKED_EVIDENCE"
    MODEL_OUTPUT_EXHAUSTED = "MODEL_OUTPUT_EXHAUSTED"
    SEMANTIC_PARSE_FAILED = "SEMANTIC_PARSE_FAILED"


class ReviewerDisposition(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    INCONCLUSIVE = "INCONCLUSIVE"


@dataclass(frozen=True, slots=True)
class GovernedEvidence:
    evidence_id: str
    vintage_id: str
    source_id: str
    trust_class: str
    first_observed_at: datetime
    source_published_at: datetime | None
    classification: VintageClassification
    text: str
    contradiction_ids: tuple[str, ...] = ()
    mechanisms: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        observed = require_aware_utc(self.first_observed_at, "first_observed_at")
        object.__setattr__(self, "first_observed_at", observed)
        if self.source_published_at is not None:
            object.__setattr__(
                self,
                "source_published_at",
                require_aware_utc(self.source_published_at, "source_published_at"),
            )
        if not all((self.evidence_id, self.vintage_id, self.source_id, self.trust_class, self.text)):
            raise ValidationError("governed evidence metadata is incomplete")
        if self.classification is not VintageClassification.OBSERVED_LIVE_AT_TIME:
            raise GovernanceViolation("governed reference requires newly live-observed evidence")


@dataclass(frozen=True, slots=True)
class EvidenceSufficiency:
    status: EvidenceGateStatus
    independent_sources: int
    official_sources: int
    news_sources: int
    contradictory_records: int
    stale_records: int
    reasons: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ClaimGrounding:
    claim_id: str
    status: GroundingStatus
    accepted_evidence_ids: tuple[str, ...]
    rejected_evidence_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReviewerEvaluation:
    disposition: ReviewerDisposition
    claims_accepted: int
    claims_rejected: int
    unsupported_claims_caught: int
    contradictions_identified: int
    uncertainty_change: str
    hypothesis_change: str

    def __post_init__(self) -> None:
        if min(
            self.claims_accepted,
            self.claims_rejected,
            self.unsupported_claims_caught,
            self.contradictions_identified,
        ) < 0:
            raise ValidationError("reviewer metrics cannot be negative")


@dataclass(frozen=True, slots=True)
class SealedResearchCommitment:
    subject_id: str
    committed_at: datetime
    cutoff: datetime
    horizon: str
    hypothesis: str
    expected_mechanism: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    vintage_ids: tuple[str, ...]
    confidence: float
    uncertainty: str
    provider: str
    model: str
    expert_mode: str
    commitment_id: str = field(init=False)

    def __post_init__(self) -> None:
        committed = require_aware_utc(self.committed_at, "committed_at")
        cutoff = require_aware_utc(self.cutoff, "cutoff")
        object.__setattr__(self, "committed_at", committed)
        object.__setattr__(self, "cutoff", cutoff)
        if committed < cutoff or not self.evidence_ids or not self.vintage_ids:
            raise ValidationError("commitment requires prior evidence and a valid cutoff")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValidationError("commitment evidence IDs must be unique")
        if not 0 <= self.confidence <= 1 or not all(
            (self.subject_id, self.horizon, self.hypothesis, self.uncertainty, self.provider, self.model, self.expert_mode)
        ):
            raise ValidationError("sealed commitment metadata is incomplete")
        object.__setattr__(self, "commitment_id", content_id("sealed-research-commitment", self))


@dataclass(frozen=True, slots=True)
class AccountedResearchOutcome:
    status: GovernedRunStatus
    claims: tuple[ResearchClaim, ...]
    usage: UsageAccounting
    reasoning_tokens: int
    visible_output_tokens: int
    request_id: str | None
    response_hash: str
    finish_reason: str | None
    error_summary: str | None

    def __post_init__(self) -> None:
        if min(self.reasoning_tokens, self.visible_output_tokens) < 0:
            raise ValidationError("research token accounting cannot be negative")
        if not self.response_hash.startswith("sha256:"):
            raise ValidationError("research outcome requires a response hash")


def assess_evidence_sufficiency(
    evidence: tuple[GovernedEvidence, ...], cutoff: datetime, *, stale_days: int = 7
) -> EvidenceSufficiency:
    cutoff = require_aware_utc(cutoff, "cutoff")
    future = tuple(item for item in evidence if item.first_observed_at > cutoff)
    if future:
        raise IntegrityViolation("future evidence rejected before provider invocation")
    sources = {item.source_id for item in evidence}
    official = sum(item.trust_class == "authoritative_official" for item in evidence)
    news = sum(item.trust_class == "reviewed_news" for item in evidence)
    contradictory = sum(bool(item.contradiction_ids) for item in evidence)
    stale = sum((cutoff - item.first_observed_at).days > stale_days for item in evidence)
    reasons = []
    if len(sources) < 2:
        reasons.append("fewer than two independent sources")
    if official < 1:
        reasons.append("official source absent")
    if news < 1:
        reasons.append("reviewed news corroboration absent")
    if len(evidence) < 2:
        reasons.append("fewer than two evidence records")
    if stale == len(evidence) and evidence:
        reasons.append("all evidence is stale")
    return EvidenceSufficiency(
        EvidenceGateStatus.BLOCKED_EVIDENCE if reasons else EvidenceGateStatus.PASS,
        len(sources),
        official,
        news,
        contradictory,
        stale,
        tuple(reasons),
    )


def audit_claim_grounding(
    claims: tuple[ResearchClaim, ...],
    evidence: tuple[GovernedEvidence, ...],
    *,
    rejected_claim_ids: tuple[str, ...] = (),
) -> tuple[ClaimGrounding, ...]:
    accepted = {item.evidence_id for item in evidence}
    contradicted = {value for item in evidence for value in item.contradiction_ids}
    output = []
    for claim in claims:
        referenced = set(claim.supporting_evidence_ids) | set(claim.contradicting_evidence_ids)
        fabricated = tuple(sorted(referenced - accepted))
        if fabricated:
            raise IntegrityViolation("model claim contains fabricated evidence ID")
        supported = tuple(sorted(set(claim.supporting_evidence_ids) & accepted))
        if claim.claim_id in rejected_claim_ids or not referenced or not supported:
            status = GroundingStatus.UNSUPPORTED
        elif set(claim.supporting_evidence_ids) & contradicted or claim.contradicting_evidence_ids:
            status = GroundingStatus.CONTRADICTED
        elif set(claim.supporting_evidence_ids) == accepted:
            status = GroundingStatus.SUPPORTED
        else:
            status = GroundingStatus.PARTIALLY_SUPPORTED
        output.append(ClaimGrounding(claim.claim_id, status, supported, fabricated))
    return tuple(output)


def seal_commitment(
    *,
    subject_id: str,
    cutoff: datetime,
    committed_at: datetime,
    horizon: str,
    hypothesis: ResearchClaim,
    evidence: tuple[GovernedEvidence, ...],
    uncertainty: str,
    provider: str,
    model: str,
    expert_mode: str,
) -> SealedResearchCommitment:
    grounding = audit_claim_grounding((hypothesis,), evidence)[0]
    if grounding.status not in {GroundingStatus.SUPPORTED, GroundingStatus.PARTIALLY_SUPPORTED}:
        raise GovernanceViolation("unsupported hypothesis cannot be sealed")
    referenced = set(hypothesis.supporting_evidence_ids)
    vintages = tuple(sorted(item.vintage_id for item in evidence if item.evidence_id in referenced))
    return SealedResearchCommitment(
        subject_id,
        committed_at,
        cutoff,
        horizon,
        hypothesis.text,
        hypothesis.mechanisms,
        tuple(sorted(referenced)),
        vintages,
        hypothesis.confidence,
        uncertainty,
        provider,
        model,
        expert_mode,
    )
