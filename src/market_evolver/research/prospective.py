"""Prospective campaign governance layered on the v0.32 research primitives."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import Enum

from market_evolver.errors import GovernanceViolation, IntegrityViolation, ValidationError
from market_evolver.external.schemas import UsageAccounting
from market_evolver.provenance import content_id
from market_evolver.research.governed import GroundingStatus
from market_evolver.research.schemas import ResearchClaim
from market_evolver.time import require_aware_utc


class CaseReason(str, Enum):
    SCHEDULED = "SCHEDULED"
    OFFICIAL_EVENT = "OFFICIAL_EVENT"
    CORROBORATED_NEWS = "CORROBORATED_NEWS"
    QUIET_CONTROL = "QUIET_CONTROL"
    NEGATIVE_CONTROL = "NEGATIVE_CONTROL"


class CaseEligibility(str, Enum):
    SCHEDULED = "SCHEDULED"
    ELIGIBLE = "ELIGIBLE"
    BLOCKED_EVIDENCE = "BLOCKED_EVIDENCE"


class LedgerState(str, Enum):
    SEALED = "SEALED"
    AWAITING_OUTCOME = "AWAITING_OUTCOME"
    MATURED = "MATURED"
    EVALUATED = "EVALUATED"
    UNUSABLE_OUTCOME_DATA = "UNUSABLE_OUTCOME_DATA"


class OutcomeStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    FALSIFIED = "FALSIFIED"
    INCONCLUSIVE = "INCONCLUSIVE"


class ComparisonOperator(str, Enum):
    GREATER_THAN_OR_EQUAL = "gte"
    LESS_THAN_OR_EQUAL = "lte"


@dataclass(frozen=True, slots=True)
class EvaluationRule:
    metric: str
    operator: ComparisonOperator
    supported_threshold: float
    falsified_threshold: float
    unit: str
    missing_is_inconclusive: bool = True

    def __post_init__(self) -> None:
        if not self.metric or not self.unit:
            raise ValidationError("evaluation rule requires a metric and unit")
        if self.operator is ComparisonOperator.GREATER_THAN_OR_EQUAL:
            valid = self.supported_threshold > self.falsified_threshold
        else:
            valid = self.supported_threshold < self.falsified_threshold
        if not valid:
            raise ValidationError("evaluation thresholds must leave an inconclusive interval")

    def evaluate(self, value: float | None) -> OutcomeStatus:
        if value is None:
            if self.missing_is_inconclusive:
                return OutcomeStatus.INCONCLUSIVE
            raise IntegrityViolation("required outcome observation is absent")
        if self.operator is ComparisonOperator.GREATER_THAN_OR_EQUAL:
            if value >= self.supported_threshold:
                return OutcomeStatus.SUPPORTED
            if value <= self.falsified_threshold:
                return OutcomeStatus.FALSIFIED
        else:
            if value <= self.supported_threshold:
                return OutcomeStatus.SUPPORTED
            if value >= self.falsified_threshold:
                return OutcomeStatus.FALSIFIED
        return OutcomeStatus.INCONCLUSIVE


@dataclass(frozen=True, slots=True)
class CampaignDefinition:
    campaign_id: str
    start_date: date
    planned_end_date: date
    universe: tuple[str, ...]
    horizons_days: tuple[int, ...]
    evidence_requirements: tuple[str, ...]
    expert_modes: tuple[str, ...]
    provider: str
    model: str
    sampling_policy: tuple[str, ...]
    evaluation_policy: tuple[EvaluationRule, ...]
    predeclared_metrics: tuple[str, ...]
    sealed_at: datetime
    definition_hash: str = field(init=False)

    def __post_init__(self) -> None:
        sealed = require_aware_utc(self.sealed_at, "sealed_at")
        object.__setattr__(self, "sealed_at", sealed)
        required = (
            self.campaign_id,
            self.universe,
            self.horizons_days,
            self.evidence_requirements,
            self.expert_modes,
            self.provider,
            self.model,
            self.sampling_policy,
            self.evaluation_policy,
            self.predeclared_metrics,
        )
        if not all(required) or self.planned_end_date < self.start_date:
            raise ValidationError("campaign definition is incomplete")
        if any(days <= 0 for days in self.horizons_days):
            raise ValidationError("campaign horizons must be positive")
        object.__setattr__(self, "definition_hash", content_id("prospective-campaign", self))


@dataclass(frozen=True, slots=True)
class ScheduledCase:
    campaign_id: str
    target: str
    observation_date: date
    reason: CaseReason
    horizon_days: int
    eligibility: CaseEligibility = CaseEligibility.SCHEDULED
    evidence_gate_reasons: tuple[str, ...] = ()
    case_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.campaign_id or not self.target or self.horizon_days <= 0:
            raise ValidationError("scheduled case is incomplete")
        if self.eligibility is CaseEligibility.BLOCKED_EVIDENCE and not self.evidence_gate_reasons:
            raise ValidationError("blocked case must retain evidence gate reasons")
        object.__setattr__(self, "case_id", content_id("prospective-case", self))


def deterministic_schedule(
    campaign: CampaignDefinition,
    *,
    weekdays: tuple[int, ...] = (1, 3),
    quiet_weekday: int = 0,
) -> tuple[ScheduledCase, ...]:
    """Preselect dates from the calendar, never from observed market movement."""
    output: list[ScheduledCase] = []
    current = campaign.start_date
    while current <= campaign.planned_end_date:
        for target in campaign.universe:
            for horizon in campaign.horizons_days:
                if current.weekday() in weekdays:
                    output.append(
                        ScheduledCase(
                            campaign.campaign_id,
                            target,
                            current,
                            CaseReason.SCHEDULED,
                            horizon,
                        )
                    )
                elif current.weekday() == quiet_weekday:
                    output.append(
                        ScheduledCase(
                            campaign.campaign_id,
                            target,
                            current,
                            CaseReason.QUIET_CONTROL,
                            horizon,
                        )
                    )
        current += timedelta(days=1)
    return tuple(output)


@dataclass(frozen=True, slots=True)
class CanonicalEntity:
    entity_id: str
    canonical_name: str
    aliases: tuple[str, ...] = ()
    forbidden_expansions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EntityAudit:
    claim_id: str
    accepted: bool
    conflicts: tuple[str, ...]


def audit_entity_integrity(
    claims: Iterable[ResearchClaim],
    source_ids: Iterable[str],
    registry: dict[str, CanonicalEntity],
) -> tuple[EntityAudit, ...]:
    constraints = tuple(registry[source_id] for source_id in sorted(set(source_ids)) if source_id in registry)
    audits = []
    for claim in claims:
        text = " ".join((claim.text, *claim.entities)).casefold()
        conflicts = tuple(
            f"{entity.entity_id}:{forbidden}"
            for entity in constraints
            for forbidden in entity.forbidden_expansions
            if forbidden.casefold() in text
        )
        audits.append(EntityAudit(claim.claim_id, not conflicts, conflicts))
    return tuple(audits)


@dataclass(frozen=True, slots=True)
class ReviewerClaimAudit:
    claim_id: str
    grounding_status: GroundingStatus
    reviewer_accepted: bool
    deterministic_accepted: bool


@dataclass(frozen=True, slots=True)
class ReviewerMetrics:
    unsupported_claims_caught: int
    unsupported_claims_missed: int
    supported_claims_incorrectly_rejected: int
    contradictions_caught: int
    precision: float | None
    recall: float | None


def reviewer_metrics(audits: Iterable[ReviewerClaimAudit]) -> ReviewerMetrics:
    rows = tuple(audits)
    bad = {GroundingStatus.UNSUPPORTED, GroundingStatus.CONTRADICTED}
    caught = sum(row.grounding_status in bad and not row.reviewer_accepted for row in rows)
    missed = sum(row.grounding_status in bad and row.reviewer_accepted for row in rows)
    incorrect = sum(
        row.grounding_status in {GroundingStatus.SUPPORTED, GroundingStatus.PARTIALLY_SUPPORTED}
        and not row.reviewer_accepted
        and row.deterministic_accepted
        for row in rows
    )
    contradictions = sum(
        row.grounding_status is GroundingStatus.CONTRADICTED and not row.reviewer_accepted
        for row in rows
    )
    rejected = sum(not row.reviewer_accepted for row in rows)
    precision = caught / rejected if rejected else None
    relevant = caught + missed
    recall = caught / relevant if relevant else None
    return ReviewerMetrics(caught, missed, incorrect, contradictions, precision, recall)


@dataclass(frozen=True, slots=True)
class ModeEfficiency:
    calls: int
    input_tokens: int
    output_tokens: int
    reasoning_tokens: int
    visible_tokens: int
    latency_ms: int
    cost_usd: float
    accepted_claims: int

    @property
    def cost_per_accepted_claim(self) -> float | None:
        return self.cost_usd / self.accepted_claims if self.accepted_claims else None

    @property
    def tokens_per_accepted_claim(self) -> float | None:
        total = self.input_tokens + self.output_tokens
        return total / self.accepted_claims if self.accepted_claims else None

    @property
    def reasoning_visible_ratio(self) -> float | None:
        return self.reasoning_tokens / self.visible_tokens if self.visible_tokens else None

    @property
    def latency_per_accepted_claim_ms(self) -> float | None:
        return self.latency_ms / self.accepted_claims if self.accepted_claims else None

    @classmethod
    def from_usage(
        cls,
        usages: Iterable[UsageAccounting],
        *,
        reasoning_tokens: int,
        visible_tokens: int,
        accepted_claims: int,
    ) -> ModeEfficiency:
        rows = tuple(usages)
        return cls(
            len(rows),
            sum(row.input_tokens for row in rows),
            sum(row.output_tokens for row in rows),
            reasoning_tokens,
            visible_tokens,
            sum(row.latency_ms for row in rows),
            sum(float(row.estimated_cost or "0") for row in rows),
            accepted_claims,
        )


@dataclass(frozen=True, slots=True)
class ProspectiveCommitment:
    campaign_id: str
    case_id: str
    cutoff: datetime
    target: str
    horizon_days: int
    prediction: str
    measurable_outcome: str
    evaluation_rule: EvaluationRule
    confidence: float
    uncertainty: str
    evidence_ids: tuple[str, ...]
    expert_mode: str
    provider: str
    model: str
    evaluation_start: datetime
    evaluation_end: datetime
    created_at: datetime
    original_commitment_id: str | None = None
    commitment_id: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("cutoff", "evaluation_start", "evaluation_end", "created_at"):
            object.__setattr__(self, name, require_aware_utc(getattr(self, name), name))
        if self.created_at < self.cutoff or self.evaluation_start < self.created_at:
            raise ValidationError("commitment timeline is not prospective")
        if self.evaluation_end < self.evaluation_start or not self.evidence_ids:
            raise ValidationError("commitment requires an evaluation window and evidence")
        if not 0 <= self.confidence <= 1:
            raise ValidationError("commitment confidence must be between zero and one")
        object.__setattr__(self, "commitment_id", content_id("prospective-commitment", self))


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    campaign_id: str
    case_id: str
    commitment_id: str
    maturity_date: datetime
    state: LedgerState
    recorded_at: datetime
    outcome_status: OutcomeStatus | None = None
    outcome_data_hash: str | None = None
    entry_id: str = field(init=False)

    def __post_init__(self) -> None:
        maturity = require_aware_utc(self.maturity_date, "maturity_date")
        recorded = require_aware_utc(self.recorded_at, "recorded_at")
        object.__setattr__(self, "maturity_date", maturity)
        object.__setattr__(self, "recorded_at", recorded)
        if self.state is LedgerState.EVALUATED and (
            self.outcome_status is None or not self.outcome_data_hash
        ):
            raise ValidationError("evaluated ledger entry requires a hashed outcome")
        if self.state is not LedgerState.EVALUATED and self.outcome_status is not None:
            raise GovernanceViolation("future outcome annotations are forbidden")
        object.__setattr__(self, "entry_id", content_id("prospective-ledger-entry", self))


class CommitmentLedger:
    """Append-only in-memory ledger; persistence is a sequence of immutable entries."""

    def __init__(self, entries: Iterable[LedgerEntry] = ()) -> None:
        self._entries = list(entries)

    @property
    def entries(self) -> tuple[LedgerEntry, ...]:
        return tuple(self._entries)

    def append(self, entry: LedgerEntry) -> None:
        previous = next(
            (row for row in reversed(self._entries) if row.commitment_id == entry.commitment_id),
            None,
        )
        allowed = {
            None: {LedgerState.SEALED},
            LedgerState.SEALED: {LedgerState.AWAITING_OUTCOME},
            LedgerState.AWAITING_OUTCOME: {LedgerState.MATURED, LedgerState.UNUSABLE_OUTCOME_DATA},
            LedgerState.MATURED: {LedgerState.EVALUATED, LedgerState.UNUSABLE_OUTCOME_DATA},
            LedgerState.EVALUATED: set(),
            LedgerState.UNUSABLE_OUTCOME_DATA: set(),
        }
        if entry.state not in allowed[previous.state if previous else None]:
            raise GovernanceViolation("invalid or non-append-only ledger transition")
        if previous and entry.recorded_at < previous.recorded_at:
            raise IntegrityViolation("ledger entries cannot be backdated")
        if entry.state in {LedgerState.MATURED, LedgerState.EVALUATED} and (
            entry.recorded_at < entry.maturity_date
        ):
            raise GovernanceViolation("outcome cannot be exposed before maturity")
        self._entries.append(entry)
