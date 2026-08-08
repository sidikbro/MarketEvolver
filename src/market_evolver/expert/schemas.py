from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from re import search

from market_evolver.errors import ValidationError
from market_evolver.provenance import content_id
from market_evolver.time import require_aware_utc


class ExpertStatus(str, Enum):
    DRAFT = "draft"
    EVALUATION = "evaluation"
    APPROVED = "approved"
    SUSPENDED = "suspended"
    RETIRED = "retired"


class Horizon(str, Enum):
    IMMEDIATE = "immediate_event"
    SHORT_TERM = "short_term"
    MEDIUM_TERM = "medium_term"
    LONG_TERM = "long_term"


class AuditDecision(str, Enum):
    ALLOWED = "allowed"
    DENIED = "denied"


class SessionStatus(str, Enum):
    CREATED = "created"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ExpertDefinition:
    expert_id: str
    name: str
    domain: str
    geography: tuple[str, ...]
    supported_horizons: tuple[Horizon, ...]
    allowed_entity_types: tuple[str, ...]
    allowed_source_classes: tuple[str, ...]
    allowed_tools: tuple[str, ...]
    allowed_research_tasks: tuple[str, ...]
    allowed_mechanisms: tuple[str, ...]
    forbidden_capabilities: tuple[str, ...]
    prompt_version: str
    model_policy: str
    created_at: datetime
    status: ExpertStatus
    provenance: tuple[str, ...]
    version: int = 1
    revision_of: str | None = None
    definition_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", require_aware_utc(self.created_at, "created_at"))
        required = (
            self.expert_id,
            self.name,
            self.domain,
            self.geography,
            self.supported_horizons,
            self.allowed_entity_types,
            self.allowed_source_classes,
            self.allowed_tools,
            self.allowed_research_tasks,
            self.prompt_version,
            self.model_policy,
            self.forbidden_capabilities,
            self.provenance,
        )
        if not all(required):
            raise ValidationError("expert capability manifest is incomplete")
        mandatory_forbidden = {
            "paper_order",
            "risk_policy_mutation",
            "broker_access",
            "expert_creation",
            "topology_mutation",
        }
        if not mandatory_forbidden <= set(self.forbidden_capabilities):
            raise ValidationError("expert definition omits mandatory forbidden capabilities")
        if self.version < 1 or (self.version == 1) != (self.revision_of is None):
            raise ValidationError("expert definition version lineage is invalid")
        object.__setattr__(self, "definition_id", content_id("expert-definition", self))


@dataclass(frozen=True, slots=True)
class ToolRequestAudit:
    expert_definition_id: str
    session_id: str
    tool_name: str
    requested_at: datetime
    cutoff: datetime
    entity_id: str | None
    entity_type: str | None
    source_class: str | None
    decision: AuditDecision
    reason_code: str
    audit_id: str = field(init=False)

    def __post_init__(self) -> None:
        requested = require_aware_utc(self.requested_at, "requested_at")
        cutoff = require_aware_utc(self.cutoff, "cutoff")
        object.__setattr__(self, "requested_at", requested)
        object.__setattr__(self, "cutoff", cutoff)
        if (
            self.decision is AuditDecision.ALLOWED
            and cutoff > requested
            or not self.tool_name
            or not self.reason_code
        ):
            raise ValidationError("tool audit timeline or identity is invalid")
        object.__setattr__(self, "audit_id", content_id("expert-tool-audit", self))


@dataclass(frozen=True, slots=True)
class ExpertResearchSession:
    expert_definition_id: str
    task: str
    subject_id: str
    entity_type: str
    domain: str
    horizon: Horizon
    cutoff: datetime
    context_manifest_id: str
    tools_authorized: tuple[str, ...]
    tools_used: tuple[str, ...]
    provider_id: str
    model_id: str
    prompt_version: str
    started_at: datetime
    completed_at: datetime | None
    status: SessionStatus
    anonymized: bool = False
    session_id: str = field(init=False)

    def __post_init__(self) -> None:
        cutoff = require_aware_utc(self.cutoff, "cutoff")
        started = require_aware_utc(self.started_at, "started_at")
        object.__setattr__(self, "cutoff", cutoff)
        object.__setattr__(self, "started_at", started)
        if cutoff > started or not set(self.tools_used) <= set(self.tools_authorized):
            raise ValidationError("session has temporal leakage or unauthorized tool use")
        if self.completed_at is not None:
            completed = require_aware_utc(self.completed_at, "completed_at")
            if completed < started:
                raise ValidationError("session completion predates start")
            object.__setattr__(self, "completed_at", completed)
        object.__setattr__(self, "session_id", content_id("expert-session", self))


@dataclass(frozen=True, slots=True)
class AssessmentItem:
    text: str
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.text or not self.evidence_ids:
            raise ValidationError("assessment item requires evidence")
        if search(
            r"\b(buy|sell|trade|order|paperorder|allocate|allocation|recommend)\b",
            self.text.casefold(),
        ):
            raise ValidationError("expert output contains an action recommendation")


@dataclass(frozen=True, slots=True)
class ExpertAssessment:
    session_id: str
    observations: tuple[AssessmentItem, ...]
    inferences: tuple[AssessmentItem, ...]
    hypotheses: tuple[AssessmentItem, ...]
    counterevidence: tuple[AssessmentItem, ...]
    mechanism_chains: tuple[tuple[str, ...], ...]
    uncertainties: tuple[str, ...]
    horizon: Horizon
    confidence: float
    evidence_ids: tuple[str, ...]
    unresolved_questions: tuple[str, ...]
    created_at: datetime
    assessment_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", require_aware_utc(self.created_at, "created_at"))
        referenced = {
            item
            for group in (self.observations, self.inferences, self.hypotheses, self.counterevidence)
            for entry in group
            for item in entry.evidence_ids
        }
        if not 0 <= self.confidence <= 1 or not referenced <= set(self.evidence_ids):
            raise ValidationError("assessment confidence or evidence attribution is invalid")
        object.__setattr__(self, "assessment_id", content_id("expert-assessment", self))


@dataclass(frozen=True, slots=True)
class RoutingDecision:
    subject_id: str
    cutoff: datetime
    selected_expert_ids: tuple[str, ...]
    reason: str
    confidence: float
    fallback_expert_id: str
    tags: tuple[str, ...]
    routing_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "cutoff", require_aware_utc(self.cutoff, "cutoff"))
        if not self.selected_expert_ids or not self.reason or not 0 <= self.confidence <= 1:
            raise ValidationError("routing decision is invalid")
        object.__setattr__(self, "routing_id", content_id("expert-routing", self))


@dataclass(frozen=True, slots=True)
class ExpertScorecard:
    expert_definition_id: str
    cutoff: datetime
    benchmark_cases: int
    grounded_claim_rate: float
    unsupported_claim_rate: float
    contradiction_handling: float
    calibration: float
    mechanism_coverage: float
    hypothesis_testability: float
    tool_denials: int
    latency_ms: int
    tokens: int
    cost: str
    failures: int
    leakage_violations: int
    fabricated_provenance: int
    action_attempts: int
    capability_violations: int
    generalist_delta: float
    scorecard_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "cutoff", require_aware_utc(self.cutoff, "cutoff"))
        rates = (
            self.grounded_claim_rate,
            self.unsupported_claim_rate,
            self.contradiction_handling,
            self.calibration,
            self.mechanism_coverage,
            self.hypothesis_testability,
        )
        if self.benchmark_cases < 0 or any(not 0 <= value <= 1 for value in rates):
            raise ValidationError("expert scorecard components are invalid")
        object.__setattr__(self, "scorecard_id", content_id("expert-scorecard", self))
