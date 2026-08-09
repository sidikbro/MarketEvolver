from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from market_evolver.errors import ValidationError
from market_evolver.provenance import content_id
from market_evolver.time import require_aware_utc


class TopologyProposalType(str, Enum):
    CREATE_EXPERT = "create_expert"
    SPLIT_EXPERT = "split_expert"
    MERGE_EXPERTS = "merge_experts"
    RETIRE_EXPERT = "retire_expert"
    FORM_PANEL = "form_panel"
    CHANGE_ROUTING = "change_routing"
    CHANGE_DOMAIN_SCOPE = "change_domain_scope"


class TopologyProposalStatus(str, Enum):
    PROPOSED = "proposed"
    EVALUATING = "evaluating"
    ELIGIBLE = "eligible"
    REJECTED = "rejected"
    QUARANTINED = "quarantined"
    APPROVED = "approved"
    ACTIVATED = "activated"
    ROLLED_BACK = "rolled_back"


class TopologyState(str, Enum):
    CHALLENGER = "challenger"
    CERTIFIED_PENDING_APPROVAL = "certified_pending_approval"
    ACTIVE = "active"
    RETIRED = "retired"
    QUARANTINED = "quarantined"
    REJECTED = "rejected"


class TopologyAction(str, Enum):
    INITIAL_ACTIVATION = "initial_activation"
    ACTIVATION = "activation"
    ROLLBACK = "rollback"


class GapCategory(str, Enum):
    REVIEWER_REJECTION = "reviewer_rejection"
    LOW_MECHANISM_COVERAGE = "low_mechanism_coverage"
    SAFE_TOOL_DENIALS = "safe_tool_denials"
    HIGH_DISAGREEMENT = "high_disagreement"
    UNRESOLVED_QUESTIONS = "unresolved_questions"
    LOW_RETRIEVAL_RELEVANCE = "low_retrieval_relevance"
    CALIBRATION_WEAKNESS = "calibration_weakness"
    LATENCY_COST_BOTTLENECK = "latency_cost_bottleneck"
    DOMAIN_OVERLOAD = "domain_overload"


class RelationshipType(str, Enum):
    ROUTES_TO = "routes_to"
    PANEL_MEMBER = "panel_member"
    FALLBACK = "fallback"
    PARENT_CHILD = "parent_child"


CRITICAL_TOPOLOGY_KEYS = frozenset(
    {
        "risk_policy",
        "runtime_access",
        "broker_access",
        "write_tools",
        "provenance_enforcement",
        "cutoff_enforcement",
        "trust_boundary",
    }
)


@dataclass(frozen=True, slots=True)
class ProposedExpert:
    expert_id: str
    name: str
    domain: str
    parent_expert_ids: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    allowed_sources: tuple[str, ...]
    mechanisms: tuple[str, ...]
    horizons: tuple[str, ...]
    initial_template: tuple[str, ...]
    routing_conditions: tuple[tuple[str, str], ...]
    benchmark_case_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not all(
            (
                self.expert_id,
                self.name,
                self.domain,
                self.parent_expert_ids,
                self.allowed_tools,
                self.allowed_sources,
                self.horizons,
                self.initial_template,
                self.routing_conditions,
                self.benchmark_case_ids,
            )
        ):
            raise ValidationError("proposed expert definition is incomplete")
        if any(
            token in tool
            for tool in self.allowed_tools
            for token in ("write", "runtime", "broker", "risk_policy")
        ):
            raise ValidationError("proposed expert requests forbidden capability")


@dataclass(frozen=True, slots=True)
class TopologyProposal:
    proposal_type: TopologyProposalType
    triggering_evidence_ids: tuple[str, ...]
    source_expert_ids: tuple[str, ...]
    proposed_experts: tuple[ProposedExpert, ...]
    routing_changes: tuple[tuple[str, str], ...]
    rationale: str
    expected_benefit: str
    failure_modes: tuple[str, ...]
    benchmark_plan: tuple[str, ...]
    created_by: str
    created_at: datetime
    status: TopologyProposalStatus
    provenance: tuple[str, ...]
    proposal_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", require_aware_utc(self.created_at, "created_at"))
        if not self.triggering_evidence_ids or not self.source_expert_ids or not self.rationale:
            raise ValidationError("topology proposal requires evidence, sources, and rationale")
        if not self.benchmark_plan or not self.provenance:
            raise ValidationError("topology proposal requires benchmark and provenance")
        keys = {key for key, _ in self.routing_changes}
        if keys & CRITICAL_TOPOLOGY_KEYS:
            raise ValidationError("topology proposal attempts immutable safety mutation")
        if (
            self.created_by.startswith(("expert:", "model:"))
            and self.status is not TopologyProposalStatus.PROPOSED
        ):
            raise ValidationError("untrusted generator cannot advance topology proposal status")
        object.__setattr__(self, "proposal_id", content_id("topology-proposal", self))


@dataclass(frozen=True, slots=True)
class GapSignal:
    expert_id: str
    domain: str
    category: GapCategory
    observed_count: int
    threshold: int
    evidence_ids: tuple[str, ...]
    observed_at: datetime
    signal_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", require_aware_utc(self.observed_at, "observed_at"))
        if self.observed_count < self.threshold or self.threshold < 1 or not self.evidence_ids:
            raise ValidationError("knowledge gap does not meet deterministic review threshold")
        object.__setattr__(self, "signal_id", content_id("topology-gap-signal", self))


@dataclass(frozen=True, slots=True)
class TopologyNode:
    expert_id: str
    expert_version_id: str
    domain: str
    active_from: datetime
    active_until: datetime | None = None

    def __post_init__(self) -> None:
        active = require_aware_utc(self.active_from, "active_from")
        object.__setattr__(self, "active_from", active)
        if self.active_until is not None:
            until = require_aware_utc(self.active_until, "active_until")
            if until <= active:
                raise ValidationError("topology node validity is reversed")
            object.__setattr__(self, "active_until", until)


@dataclass(frozen=True, slots=True)
class TopologyEdge:
    source_id: str
    target_id: str
    relationship: RelationshipType
    conditions: tuple[tuple[str, str], ...]
    priority: int


@dataclass(frozen=True, slots=True)
class TopologyVersion:
    parent_topology_version_id: str | None
    proposal_id: str | None
    nodes: tuple[TopologyNode, ...]
    edges: tuple[TopologyEdge, ...]
    panel_rules: tuple[tuple[str, tuple[str, ...]], ...]
    router_version: str
    created_at: datetime
    created_by: str
    state: TopologyState
    benchmark_manifest_id: str | None
    safety_status: str
    provenance: tuple[str, ...]
    topology_version_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", require_aware_utc(self.created_at, "created_at"))
        if self.parent_topology_version_id is None and self.proposal_id is not None:
            raise ValidationError("root topology cannot reference proposal")
        if self.parent_topology_version_id is not None and not self.proposal_id:
            raise ValidationError("topology challenger requires proposal")
        ids = [item.expert_id for item in self.nodes]
        if not ids or len(ids) != len(set(ids)):
            raise ValidationError("topology expert nodes must be unique")
        if any(edge.source_id not in ids or edge.target_id not in ids for edge in self.edges):
            raise ValidationError("topology edge references missing node")
        if not self.router_version or not self.provenance:
            raise ValidationError("topology router and provenance are required")
        object.__setattr__(self, "topology_version_id", content_id("expert-topology-version", self))


@dataclass(frozen=True, slots=True)
class TopologyMetrics:
    benchmark_quality: float
    grounded_claim_rate: float
    reviewer_acceptance: float
    safety_violations: int
    routing_accuracy: float
    unresolved_rate: float
    provider_cost: float
    latency_ms: int
    expert_count: int
    calls_per_task: float
    average_panel_size: float
    duplicate_retrieval_rate: float


@dataclass(frozen=True, slots=True)
class TopologyEvaluation:
    proposal_id: str
    champion_topology_id: str
    challenger_topology_id: str
    benchmark_manifest_id: str
    champion_metrics: TopologyMetrics
    challenger_metrics: TopologyMetrics
    route_results: tuple[tuple[str, str], ...]
    certification_checks: tuple[tuple[str, bool], ...]
    safety_veto: bool
    decision: str
    reasons: tuple[str, ...]
    evaluated_at: datetime
    evaluation_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evaluated_at", require_aware_utc(self.evaluated_at, "evaluated_at")
        )
        required = {
            "provenance",
            "temporal",
            "capability",
            "adversarial",
            "generalist",
            "domain",
            "holdout",
            "cost_latency",
        }
        if {key for key, _ in self.certification_checks} != required:
            raise ValidationError("topology certification checklist is incomplete")
        object.__setattr__(self, "evaluation_id", content_id("topology-evaluation", self))


@dataclass(frozen=True, slots=True)
class TopologyRegistryEvent:
    topology_version_id: str
    previous_topology_version_id: str | None
    action: TopologyAction
    actor: str
    reason: str
    occurred_at: datetime
    event_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "occurred_at", require_aware_utc(self.occurred_at, "occurred_at"))
        if not self.actor or self.actor.startswith(("expert:", "model:")):
            raise ValidationError("topology activation requires governance identity")
        if (
            self.action in {TopologyAction.ACTIVATION, TopologyAction.ROLLBACK}
            and not self.previous_topology_version_id
        ):
            raise ValidationError("topology change must retain prior version")
        object.__setattr__(self, "event_id", content_id("topology-registry-event", self))


@dataclass(frozen=True, slots=True)
class TopologyHoldoutAccess:
    topology_version_id: str
    benchmark_manifest_id: str
    accessed_at: datetime
    actor: str
    purpose: str
    access_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "accessed_at", require_aware_utc(self.accessed_at, "accessed_at"))
        if not self.actor or not self.purpose:
            raise ValidationError("topology holdout access requires actor and purpose")
        object.__setattr__(self, "access_id", content_id("topology-holdout-access", self))
