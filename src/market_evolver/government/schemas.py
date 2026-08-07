"""Immutable government actions, candidates, and lifecycle audit records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from market_evolver.errors import ValidationError
from market_evolver.provenance import content_id
from market_evolver.time import require_aware_utc


class GovernmentActionType(str, Enum):
    MONETARY_POLICY = "monetary_policy"
    FISCAL_POLICY = "fiscal_policy"
    TAXATION = "taxation"
    REGULATION = "regulation"
    LEGISLATION = "legislation"
    GOVERNMENT_BUDGET = "government_budget"
    PROCUREMENT = "procurement"
    TENDER = "tender"
    SANCTIONS = "sanctions"
    EXPORT_CONTROL = "export_control"
    IMPORT_POLICY = "import_policy"
    COMPETITION_POLICY = "competition_policy"
    BANKING_REGULATION = "banking_regulation"
    HOUSING_POLICY = "housing_policy"
    INFRASTRUCTURE_POLICY = "infrastructure_policy"
    ENERGY_POLICY = "energy_policy"
    LABOR_POLICY = "labor_policy"
    SECURITIES_REGULATION = "securities_regulation"


class GovernmentActionStatus(str, Enum):
    RUMORED = "rumored"
    PROPOSED = "proposed"
    CONSULTATION = "consultation"
    SUBMITTED = "submitted"
    COMMITTEE = "committee"
    APPROVED = "approved"
    PUBLISHED = "published"
    EFFECTIVE = "effective"
    ENFORCED = "enforced"
    CHALLENGED = "challenged"
    AMENDED = "amended"
    SUSPENDED = "suspended"
    REPEALED = "repealed"
    EXPIRED = "expired"


class PolicyReviewState(str, Enum):
    UNREVIEWED = "unreviewed"
    CORROBORATED = "corroborated"
    REJECTED = "rejected"
    PROMOTED = "promoted"


class ExpectationStatus(str, Enum):
    UNKNOWN = "unknown"


_TRANSITIONS: dict[GovernmentActionStatus | None, frozenset[GovernmentActionStatus]] = {
    None: frozenset(
        {
            GovernmentActionStatus.RUMORED,
            GovernmentActionStatus.PROPOSED,
            GovernmentActionStatus.CONSULTATION,
            GovernmentActionStatus.SUBMITTED,
            GovernmentActionStatus.APPROVED,
            GovernmentActionStatus.PUBLISHED,
        }
    ),
    GovernmentActionStatus.RUMORED: frozenset({GovernmentActionStatus.PROPOSED}),
    GovernmentActionStatus.PROPOSED: frozenset(
        {
            GovernmentActionStatus.CONSULTATION,
            GovernmentActionStatus.SUBMITTED,
            GovernmentActionStatus.APPROVED,
            GovernmentActionStatus.SUSPENDED,
        }
    ),
    GovernmentActionStatus.CONSULTATION: frozenset(
        {GovernmentActionStatus.SUBMITTED, GovernmentActionStatus.APPROVED}
    ),
    GovernmentActionStatus.SUBMITTED: frozenset(
        {GovernmentActionStatus.COMMITTEE, GovernmentActionStatus.APPROVED}
    ),
    GovernmentActionStatus.COMMITTEE: frozenset(
        {GovernmentActionStatus.APPROVED, GovernmentActionStatus.SUSPENDED}
    ),
    GovernmentActionStatus.APPROVED: frozenset(
        {
            GovernmentActionStatus.PUBLISHED,
            GovernmentActionStatus.EFFECTIVE,
            GovernmentActionStatus.CHALLENGED,
        }
    ),
    GovernmentActionStatus.PUBLISHED: frozenset(
        {
            GovernmentActionStatus.EFFECTIVE,
            GovernmentActionStatus.AMENDED,
            GovernmentActionStatus.CHALLENGED,
        }
    ),
    GovernmentActionStatus.EFFECTIVE: frozenset(
        {
            GovernmentActionStatus.ENFORCED,
            GovernmentActionStatus.AMENDED,
            GovernmentActionStatus.CHALLENGED,
            GovernmentActionStatus.SUSPENDED,
            GovernmentActionStatus.REPEALED,
            GovernmentActionStatus.EXPIRED,
        }
    ),
    GovernmentActionStatus.ENFORCED: frozenset(
        {
            GovernmentActionStatus.AMENDED,
            GovernmentActionStatus.CHALLENGED,
            GovernmentActionStatus.SUSPENDED,
            GovernmentActionStatus.REPEALED,
            GovernmentActionStatus.EXPIRED,
        }
    ),
    GovernmentActionStatus.CHALLENGED: frozenset(
        {
            GovernmentActionStatus.EFFECTIVE,
            GovernmentActionStatus.SUSPENDED,
            GovernmentActionStatus.REPEALED,
        }
    ),
    GovernmentActionStatus.AMENDED: frozenset(
        {
            GovernmentActionStatus.PUBLISHED,
            GovernmentActionStatus.EFFECTIVE,
            GovernmentActionStatus.REPEALED,
        }
    ),
    GovernmentActionStatus.SUSPENDED: frozenset(
        {GovernmentActionStatus.EFFECTIVE, GovernmentActionStatus.REPEALED}
    ),
    GovernmentActionStatus.REPEALED: frozenset(),
    GovernmentActionStatus.EXPIRED: frozenset(),
}


def validate_transition(
    previous: GovernmentActionStatus | None, current: GovernmentActionStatus
) -> None:
    if current not in _TRANSITIONS.get(previous, frozenset()):
        raise ValidationError(f"invalid government lifecycle transition: {previous} -> {current}")


@dataclass(frozen=True, slots=True)
class GovernmentAction:
    jurisdiction: str
    issuing_body: str
    action_type: GovernmentActionType
    title: str
    description_reference: str
    status: GovernmentActionStatus
    announced_at: datetime | None
    published_at: datetime | None
    effective_at: datetime | None
    first_observed_at: datetime
    expires_at: datetime | None
    supersedes_action_id: str | None
    source_evidence_ids: tuple[str, ...]
    affected_entities: tuple[str, ...]
    affected_sectors: tuple[str, ...]
    candidate_mechanisms: tuple[str, ...]
    confidence: float
    provenance: tuple[str, ...]
    version: int
    expectation_status: ExpectationStatus = ExpectationStatus.UNKNOWN
    action_id: str = field(init=False)

    def __post_init__(self) -> None:
        observed = require_aware_utc(self.first_observed_at, "first_observed_at")
        object.__setattr__(self, "first_observed_at", observed)
        for name in ("announced_at", "published_at", "effective_at", "expires_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, require_aware_utc(value, name))
        if self.published_at is not None and self.published_at > observed:
            raise ValidationError("government publication cannot be observed before publication")
        if (
            self.expires_at is not None
            and self.effective_at is not None
            and self.expires_at < self.effective_at
        ):
            raise ValidationError("expiration cannot precede effectiveness")
        if not self.jurisdiction or not self.issuing_body or not self.title.strip():
            raise ValidationError("government action identity is required")
        if not self.source_evidence_ids or not self.provenance or self.version < 1:
            raise ValidationError("government action provenance and version are required")
        if not 0 <= self.confidence <= 1:
            raise ValidationError("government action confidence must be between zero and one")
        if self.version > 1 and self.supersedes_action_id is None:
            raise ValidationError("revised government actions must identify superseded action")
        object.__setattr__(self, "action_id", content_id("government-action", self))


@dataclass(frozen=True, slots=True)
class GovernmentTransition:
    action_id: str
    from_status: GovernmentActionStatus | None
    to_status: GovernmentActionStatus
    transitioned_at: datetime
    evidence_ids: tuple[str, ...]
    rationale: str
    sequence: int
    transition_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "transitioned_at",
            require_aware_utc(self.transitioned_at, "transitioned_at"),
        )
        validate_transition(self.from_status, self.to_status)
        if not self.evidence_ids or not self.rationale.strip() or self.sequence < 0:
            raise ValidationError("government transition requires provenance and sequence")
        object.__setattr__(self, "transition_id", content_id("government-transition", self))


@dataclass(frozen=True, slots=True)
class GovernmentActionCandidate:
    evidence_ids: tuple[str, ...]
    issuing_body: str | None
    possible_action_type: GovernmentActionType | None
    possible_transition: GovernmentActionStatus | None
    explicit_dates: tuple[datetime, ...]
    explicit_values: tuple[str, ...]
    entities: tuple[str, ...]
    candidate_mechanisms: tuple[str, ...]
    extraction_method: str
    confidence: float
    created_at: datetime
    review_state: PolicyReviewState = PolicyReviewState.UNREVIEWED
    expectation_status: ExpectationStatus = ExpectationStatus.UNKNOWN
    candidate_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", require_aware_utc(self.created_at, "created_at"))
        object.__setattr__(
            self,
            "explicit_dates",
            tuple(require_aware_utc(item, "explicit_date") for item in self.explicit_dates),
        )
        if not self.evidence_ids or not self.extraction_method:
            raise ValidationError("government candidate requires evidence and extraction method")
        if not 0 <= self.confidence <= 1:
            raise ValidationError("candidate confidence must be between zero and one")
        object.__setattr__(self, "candidate_id", content_id("government-candidate", self))


@dataclass(frozen=True, slots=True)
class PolicyExpectation:
    action_type: GovernmentActionType
    as_of: datetime
    status: ExpectationStatus = ExpectationStatus.UNKNOWN

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", require_aware_utc(self.as_of, "as_of"))
