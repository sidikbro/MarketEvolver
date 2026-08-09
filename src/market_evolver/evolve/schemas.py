from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from market_evolver.errors import ValidationError
from market_evolver.provenance import content_id
from market_evolver.time import require_aware_utc


class ProposalStatus(str, Enum):
    PROPOSED = "proposed"
    QUEUED = "queued"
    EVALUATING = "evaluating"
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"
    SUPERSEDED = "superseded"


class ProposalType(str, Enum):
    PROMPT_TEMPLATE = "prompt_template"
    REASONING_CHECKLIST = "reasoning_checklist"
    RETRIEVAL_POLICY = "retrieval_policy"
    TOOL_SELECTION_POLICY = "tool_selection_policy"
    SOURCE_PRIORITY = "source_priority"
    CONTEXT_BUDGET = "context_budget"
    ROUTING_METADATA = "routing_metadata"
    DOMAIN_TAXONOMY_HINT = "domain_taxonomy_hint"


class ApprovalState(str, Enum):
    CHALLENGER = "challenger"
    ELIGIBLE = "eligible_for_promotion"
    CHAMPION = "champion"
    RETIRED = "retired"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"


class FailureCategory(str, Enum):
    UNSUPPORTED_CLAIM = "unsupported_claim"
    MISSING_RELEVANT_EVIDENCE = "missing_relevant_evidence"
    INCORRECT_ENTITY_SCOPE = "incorrect_entity_scope"
    MECHANISM_GAP = "mechanism_gap"
    CONTRADICTION_MISSED = "contradiction_missed"
    POOR_CALIBRATION = "poor_calibration"
    UNTESTABLE_HYPOTHESIS = "untestable_hypothesis"
    EXCESSIVE_TOOL_USAGE = "excessive_tool_usage"
    IRRELEVANT_RETRIEVAL = "irrelevant_retrieval"
    REVIEWER_REJECTION = "reviewer_rejection"
    TIMEOUT_PROVIDER_FAILURE = "timeout_provider_failure"
    CAPABILITY_VIOLATION = "capability_violation"
    TEMPORAL_LEAKAGE = "temporal_leakage"
    FABRICATED_PROVENANCE = "fabricated_provenance"
    RECOMMENDATION_ATTEMPT = "recommendation_attempt"


CRITICAL_FAILURES = frozenset(
    {
        FailureCategory.CAPABILITY_VIOLATION,
        FailureCategory.TEMPORAL_LEAKAGE,
        FailureCategory.FABRICATED_PROVENANCE,
        FailureCategory.RECOMMENDATION_ATTEMPT,
    }
)


class DatasetPartition(str, Enum):
    DEVELOPMENT = "development"
    VALIDATION = "validation"
    PROTECTED_CHALLENGE = "protected_challenge"
    FINAL_HOLDOUT = "final_holdout"


class RegistryAction(str, Enum):
    INITIAL_CHAMPION = "initial_champion"
    PROMOTION = "promotion"
    ROLLBACK = "rollback"
    REVIEW_REQUIRED = "review_required"


FORBIDDEN_CHANGE_KEYS = frozenset(
    {
        "risk_limits",
        "execution_permissions",
        "broker_permissions",
        "cutoff_rules",
        "leakage_rules",
        "provenance_validation",
        "append_only_guarantees",
        "evidence_trust_boundary",
        "allowed_tools",
        "forbidden_capabilities",
    }
)


@dataclass(frozen=True, slots=True)
class ImprovementProposal:
    expert_id: str
    parent_expert_version: str
    proposal_type: ProposalType
    proposed_change: tuple[tuple[str, str], ...]
    rationale: str
    failure_case_ids: tuple[str, ...]
    generated_by: str
    evidence_trace_ids: tuple[str, ...]
    created_at: datetime
    status: ProposalStatus
    provenance: tuple[str, ...]
    version: int = 1
    supersedes: str | None = None
    proposal_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", require_aware_utc(self.created_at, "created_at"))
        keys = {key for key, _ in self.proposed_change}
        if keys & FORBIDDEN_CHANGE_KEYS:
            raise ValidationError("improvement attempts to modify immutable host safety controls")
        if not self.proposed_change or len(self.proposed_change) > 3:
            raise ValidationError("challenger changes must be minimal and explicitly bounded")
        if not all(
            (
                self.expert_id,
                self.parent_expert_version,
                self.rationale,
                self.generated_by,
                self.evidence_trace_ids,
                self.provenance,
            )
        ):
            raise ValidationError("improvement proposal provenance is incomplete")
        if self.version < 1 or (self.version == 1) != (self.supersedes is None):
            raise ValidationError("proposal version lineage is invalid")
        object.__setattr__(self, "proposal_id", content_id("improvement-proposal", self))


@dataclass(frozen=True, slots=True)
class ExpertVersion:
    expert_id: str
    parent_version: str | None
    proposal_id: str | None
    prompt_version: str
    retrieval_configuration: tuple[tuple[str, str], ...]
    tool_policy: tuple[str, ...]
    reasoning_template: tuple[str, ...]
    source_preferences: tuple[str, ...]
    model_policy: str
    created_at: datetime
    created_by: str
    approval_state: ApprovalState
    benchmark_manifest_id: str | None
    diff_manifest: tuple[tuple[str, str, str], ...]
    provenance: tuple[str, ...]
    expert_version_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", require_aware_utc(self.created_at, "created_at"))
        if self.parent_version is None and self.proposal_id is not None:
            raise ValidationError("root expert version cannot reference a proposal")
        if self.parent_version is not None and (not self.proposal_id or not self.diff_manifest):
            raise ValidationError("challenger requires proposal and diff manifest")
        if len(self.diff_manifest) > 3:
            raise ValidationError("challenger diff exceeds bounded change set")
        if not self.tool_policy or not self.reasoning_template or not self.provenance:
            raise ValidationError("expert version configuration and provenance are required")
        object.__setattr__(self, "expert_version_id", content_id("expert-version", self))


@dataclass(frozen=True, slots=True)
class ErrorAttribution:
    expert_version_id: str
    case_id: str
    category: FailureCategory
    rationale: str
    evidence_trace_ids: tuple[str, ...]
    attributed_at: datetime
    performance_failure: bool
    critical_safety_failure: bool = field(init=False)
    attribution_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "attributed_at", require_aware_utc(self.attributed_at, "attributed_at")
        )
        object.__setattr__(self, "critical_safety_failure", self.category in CRITICAL_FAILURES)
        if not self.rationale or not self.evidence_trace_ids:
            raise ValidationError("failure attribution requires rationale and traces")
        object.__setattr__(self, "attribution_id", content_id("evolution-error-attribution", self))


@dataclass(frozen=True, slots=True)
class BenchmarkManifest:
    dataset_version: str
    development_case_ids: tuple[str, ...]
    validation_case_ids: tuple[str, ...]
    protected_case_ids: tuple[str, ...]
    final_holdout_case_ids: tuple[str, ...]
    context_manifest_ids: tuple[str, ...]
    provider_id: str
    model_id: str
    tool_capability_hash: str
    created_at: datetime
    manifest_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", require_aware_utc(self.created_at, "created_at"))
        groups = (
            self.development_case_ids,
            self.validation_case_ids,
            self.protected_case_ids,
            self.final_holdout_case_ids,
        )
        flattened = tuple(case for group in groups for case in group)
        if len(flattened) != len(set(flattened)) or not all(groups):
            raise ValidationError("benchmark partitions must be nonempty and disjoint")
        if not self.tool_capability_hash.startswith("sha256:"):
            raise ValidationError("benchmark tool capability hash is invalid")
        object.__setattr__(self, "manifest_id", content_id("evolution-benchmark-manifest", self))


@dataclass(frozen=True, slots=True)
class HoldoutAccess:
    expert_version_id: str
    manifest_id: str
    partition: DatasetPartition
    accessed_at: datetime
    actor: str
    purpose: str
    access_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "accessed_at", require_aware_utc(self.accessed_at, "accessed_at"))
        if self.partition not in {
            DatasetPartition.PROTECTED_CHALLENGE,
            DatasetPartition.FINAL_HOLDOUT,
        }:
            raise ValidationError("ordinary dataset access does not use holdout audit")
        object.__setattr__(self, "access_id", content_id("evolution-holdout-access", self))


@dataclass(frozen=True, slots=True)
class VersionMetrics:
    grounded_claim_rate: float
    domain_quality: float
    reviewer_acceptance: float
    operational_cost: float
    mechanism_coverage: float
    safety_violations: int
    temporal_leakage: int
    fabricated_provenance: int
    action_attempts: int


@dataclass(frozen=True, slots=True)
class ChallengerEvaluation:
    champion_version_id: str
    challenger_version_id: str
    manifest_id: str
    case_deltas: tuple[float, ...]
    champion_metrics: VersionMetrics
    challenger_metrics: VersionMetrics
    wins: int
    ties: int
    losses: int
    effect_size: float
    confidence_interval: tuple[float, float] | None
    statistically_adequate: bool
    safety_veto: bool
    decision: str
    reasons: tuple[str, ...]
    evaluated_at: datetime
    evaluation_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evaluated_at", require_aware_utc(self.evaluated_at, "evaluated_at")
        )
        if self.wins + self.ties + self.losses != len(self.case_deltas):
            raise ValidationError("comparison counts do not match paired cases")
        object.__setattr__(self, "evaluation_id", content_id("challenger-evaluation", self))


@dataclass(frozen=True, slots=True)
class ChampionRegistryEvent:
    expert_id: str
    champion_version_id: str
    previous_champion_version_id: str | None
    action: RegistryAction
    actor: str
    reason: str
    occurred_at: datetime
    affected_session_ids: tuple[str, ...]
    evaluation_id: str | None
    event_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "occurred_at", require_aware_utc(self.occurred_at, "occurred_at"))
        if not self.actor or self.actor.startswith(("expert:", "model:")):
            raise ValidationError("promotion/rollback requires governance identity")
        if (
            self.action in {RegistryAction.PROMOTION, RegistryAction.ROLLBACK}
            and not self.previous_champion_version_id
        ):
            raise ValidationError("champion change must retain previous champion")
        object.__setattr__(self, "event_id", content_id("champion-registry-event", self))
