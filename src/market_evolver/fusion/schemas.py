from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from market_evolver.errors import ValidationError
from market_evolver.provenance import content_id
from market_evolver.time import require_aware_utc


class UnifiedClaimType(str, Enum):
    FACTUAL_EVENT = "factual_event"
    POLICY_ACTION = "policy_action"
    COMPANY_DISCLOSURE = "company_disclosure"
    MACRO_RELEASE = "macro_release"
    GEOPOLITICAL_EVENT = "geopolitical_event"
    RUMOR = "rumor"
    NARRATIVE = "narrative"
    FORECAST = "forecast"
    INTERPRETATION = "interpretation"


class ClaimStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    CORRECTED = "corrected"
    EXPIRED = "expired"


class LineageType(str, Enum):
    ORIGINATED_FROM = "originated_from"
    COPIED_FROM = "copied_from"
    FORWARDED_FROM = "forwarded_from"
    DERIVED_FROM = "derived_from"
    CORROBORATED_BY = "corroborated_by"
    CONTRADICTED_BY = "contradicted_by"
    SUPERSEDED_BY = "superseded_by"
    CORRECTED_BY = "corrected_by"


class IndependenceClass(str, Enum):
    INDEPENDENT = "independent"
    LIKELY_SYNDICATED = "likely_syndicated"
    COPIED = "copied"
    FORWARDED = "forwarded"
    SAME_PRIMARY_SOURCE = "same_primary_source"
    UNKNOWN = "unknown"


class CorroborationState(str, Enum):
    UNCORROBORATED = "uncorroborated"
    WEAKLY_CORROBORATED = "weakly_corroborated"
    INDEPENDENTLY_CORROBORATED = "independently_corroborated"
    OFFICIALLY_CONFIRMED = "officially_confirmed"
    DISPUTED = "disputed"
    CONTRADICTED = "contradicted"
    RESOLVED = "resolved"


class ResolutionOutcome(str, Enum):
    CONFIRMED = "confirmed"
    PARTIALLY_CONFIRMED = "partially_confirmed"
    CONTRADICTED = "contradicted"
    UNRESOLVED = "unresolved"
    EXPIRED = "expired"


DOMAINS = frozenset(
    {
        "technology",
        "real_estate",
        "banking",
        "defense",
        "energy",
        "tourism",
        "macro",
        "policy",
        "geopolitics",
        "company_specific",
    }
)


@dataclass(frozen=True, slots=True)
class UnifiedClaim:
    proposition: str
    claim_type: UnifiedClaimType
    entities: tuple[str, ...]
    geography: tuple[str, ...]
    domain: str
    source_evidence_ids: tuple[str, ...]
    originating_source_id: str
    first_observed_at: datetime
    valid_from: datetime
    valid_until: datetime | None
    status: ClaimStatus
    confidence: float
    provenance: tuple[str, ...]
    version: int = 1
    revision_of: str | None = None
    claim_id: str = field(init=False)

    def __post_init__(self) -> None:
        observed = require_aware_utc(self.first_observed_at, "first_observed_at")
        valid_from = require_aware_utc(self.valid_from, "valid_from")
        valid_until = (
            None if self.valid_until is None else require_aware_utc(self.valid_until, "valid_until")
        )
        object.__setattr__(self, "first_observed_at", observed)
        object.__setattr__(self, "valid_from", valid_from)
        object.__setattr__(self, "valid_until", valid_until)
        if not self.proposition or not self.originating_source_id or not self.provenance:
            raise ValidationError("claim identity and provenance are required")
        if not self.source_evidence_ids or self.domain not in DOMAINS:
            raise ValidationError("claim requires evidence and a supported domain")
        if valid_until is not None and valid_until <= valid_from:
            raise ValidationError("claim validity interval is invalid")
        if not 0 <= self.confidence <= 1 or self.version < 1:
            raise ValidationError("claim confidence/version is invalid")
        if (self.version == 1) != (self.revision_of is None):
            raise ValidationError("claim revision lineage is invalid")
        object.__setattr__(self, "claim_id", content_id("unified-claim", self))


@dataclass(frozen=True, slots=True)
class ClaimLineage:
    source_claim_id: str
    target_claim_id: str
    relationship: LineageType
    observed_at: datetime
    evidence_ids: tuple[str, ...]
    rationale: str
    lineage_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", require_aware_utc(self.observed_at, "observed_at"))
        if self.source_claim_id == self.target_claim_id or not self.rationale:
            raise ValidationError("invalid claim lineage")
        object.__setattr__(self, "lineage_id", content_id("claim-lineage", self))


@dataclass(frozen=True, slots=True)
class CorroborationRecord:
    claim_id: str
    evidence_id: str
    source_id: str
    independence: IndependenceClass
    state: CorroborationState
    observed_at: datetime
    rationale: str
    record_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", require_aware_utc(self.observed_at, "observed_at"))
        if not self.evidence_id or not self.source_id or not self.rationale:
            raise ValidationError("corroboration provenance is required")
        object.__setattr__(self, "record_id", content_id("claim-corroboration", self))


@dataclass(frozen=True, slots=True)
class ClaimResolution:
    claim_id: str
    outcome: ResolutionOutcome
    state: CorroborationState
    supporting_evidence_ids: tuple[str, ...]
    resolving_source_ids: tuple[str, ...]
    resolved_at: datetime
    rationale: str
    resolution_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "resolved_at", require_aware_utc(self.resolved_at, "resolved_at"))
        if not self.rationale:
            raise ValidationError("resolution rationale is required")
        if self.outcome is not ResolutionOutcome.UNRESOLVED and not self.supporting_evidence_ids:
            raise ValidationError("resolved claims require supporting evidence")
        object.__setattr__(self, "resolution_id", content_id("claim-resolution", self))


@dataclass(frozen=True, slots=True)
class ClaimContradiction:
    claim_id: str
    proposition_a: str
    proposition_b: str
    evidence_a: tuple[str, ...]
    evidence_b: tuple[str, ...]
    observed_at: datetime
    resolution_status: str
    ambiguity: str
    contradiction_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", require_aware_utc(self.observed_at, "observed_at"))
        if (
            not self.proposition_a
            or not self.proposition_b
            or not self.evidence_a
            or not self.evidence_b
        ):
            raise ValidationError("both contradiction sides require exact evidence")
        object.__setattr__(self, "contradiction_id", content_id("claim-contradiction", self))


@dataclass(frozen=True, slots=True)
class FusionScore:
    claim_id: str
    source_authority: float
    independence: float
    corroboration_count: float
    provenance_completeness: float
    contradiction_burden: float
    temporal_consistency: float
    historical_reputation: float
    calculated_at: datetime
    score_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "calculated_at", require_aware_utc(self.calculated_at, "calculated_at")
        )
        components = (
            self.source_authority,
            self.independence,
            self.corroboration_count,
            self.provenance_completeness,
            self.contradiction_burden,
            self.temporal_consistency,
            self.historical_reputation,
        )
        if any(not 0 <= value <= 1 for value in components):
            raise ValidationError("fusion components must be normalized")
        object.__setattr__(self, "score_id", content_id("fusion-score", self))

    @property
    def total(self) -> float:
        positive = (
            self.source_authority
            + self.independence
            + self.corroboration_count
            + self.provenance_completeness
            + self.temporal_consistency
            + self.historical_reputation
        ) / 6
        return round(max(0.0, positive * (1 - self.contradiction_burden)), 6)


@dataclass(frozen=True, slots=True)
class ReputationSnapshot:
    source_id: str
    domain: str
    window_start: datetime
    cutoff: datetime
    claims_originated: int
    confirmed: int
    contradicted: int
    unresolved: int
    precision_resolved: float
    median_confirmation_lead_seconds: int | None
    contradiction_rate: float
    copy_forward_rate: float
    original_content_rate: float
    sample_size: int
    uncertainty: str
    snapshot_id: str = field(init=False)

    def __post_init__(self) -> None:
        start = require_aware_utc(self.window_start, "window_start")
        cutoff = require_aware_utc(self.cutoff, "cutoff")
        object.__setattr__(self, "window_start", start)
        object.__setattr__(self, "cutoff", cutoff)
        if self.domain not in DOMAINS or start > cutoff or self.sample_size < 0:
            raise ValidationError("invalid reputation window")
        for value in (
            self.precision_resolved,
            self.contradiction_rate,
            self.copy_forward_rate,
            self.original_content_rate,
        ):
            if not 0 <= value <= 1:
                raise ValidationError("invalid reputation rate")
        object.__setattr__(self, "snapshot_id", content_id("fusion-reputation", self))


@dataclass(frozen=True, slots=True)
class LeadTime:
    claim_id: str
    first_social: datetime | None
    first_news: datetime | None
    first_official: datetime | None
    first_filing: datetime | None
    confirmation_time: datetime | None
    contradiction_time: datetime | None
