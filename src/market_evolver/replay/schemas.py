"""Versioned replay cases, commitments, runs, outcomes, and benchmark metrics."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from market_evolver.errors import ValidationError
from market_evolver.provenance import content_id
from market_evolver.time import require_aware_utc


class ReplayStepMode(str, Enum):
    DAILY = "daily"
    EVENT_DRIVEN = "event_driven"
    CONFIGURED = "configured"


class ResearchMode(str, Enum):
    NO_INFORMATION = "no_information"
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    EVENT_RULES = "event_rules"
    FUNDAMENTALS = "fundamentals"
    LLM = "llm"
    LLM_REVIEWED = "llm_reviewed"


class ReplayCaseType(str, Enum):
    FX_MOVEMENT = "fx_movement"
    BOI_POLICY = "boi_policy"
    COMPANY_FILING = "company_filing"
    NEWS_EVENT = "news_event"
    CONFLICTING_EVIDENCE = "conflicting_evidence"
    REVISED_EVIDENCE = "revised_evidence"
    QUIET = "quiet"


@dataclass(frozen=True, slots=True)
class ReplayCase:
    case_type: ReplayCaseType
    entity_ids: tuple[str, ...]
    asset_ids: tuple[str, ...]
    cutoff: datetime
    horizon: str
    available_evidence_manifest_id: str
    benchmark_asset_id: str | None
    expected_output_schema: str
    evaluation_protocol: str
    dataset_version: str
    created_at: datetime
    case_id: str = field(init=False)

    def __post_init__(self) -> None:
        cutoff = require_aware_utc(self.cutoff, "cutoff")
        created = require_aware_utc(self.created_at, "created_at")
        object.__setattr__(self, "cutoff", cutoff)
        object.__setattr__(self, "created_at", created)
        if not self.entity_ids or not self.asset_ids or not self.horizon:
            raise ValidationError("replay case requires entities, assets, and horizon")
        if not all(
            (
                self.available_evidence_manifest_id,
                self.expected_output_schema,
                self.evaluation_protocol,
                self.dataset_version,
            )
        ):
            raise ValidationError("replay case protocol and dataset metadata are required")
        object.__setattr__(self, "case_id", content_id("replay-case", self))


@dataclass(frozen=True, slots=True)
class ResearchCommitment:
    case_id: str
    replay_timestamp: datetime
    context_manifest_id: str
    hypothesis_id: str
    expected_horizon: str
    measurable_outcome: str
    falsification_criterion: str
    confidence: float
    reviewer_decision: str
    research_mode: ResearchMode
    committed_at: datetime
    commitment_id: str = field(init=False)

    def __post_init__(self) -> None:
        replay = require_aware_utc(self.replay_timestamp, "replay_timestamp")
        committed = require_aware_utc(self.committed_at, "committed_at")
        object.__setattr__(self, "replay_timestamp", replay)
        object.__setattr__(self, "committed_at", committed)
        if committed < replay:
            raise ValidationError("research commitment cannot predate replay timestamp")
        if not all(
            (
                self.case_id,
                self.context_manifest_id,
                self.hypothesis_id,
                self.expected_horizon,
                self.measurable_outcome,
                self.falsification_criterion,
                self.reviewer_decision,
            )
        ):
            raise ValidationError("research commitment must be complete before clock advance")
        if not 0 <= self.confidence <= 1:
            raise ValidationError("commitment confidence must be between zero and one")
        object.__setattr__(self, "commitment_id", content_id("research-commitment", self))


@dataclass(frozen=True, slots=True)
class ReplayRun:
    case_id: str
    commitment_id: str
    named: bool
    started_at: datetime
    finished_at: datetime
    runtime_ms: int
    status: str
    run_id: str = field(init=False)

    def __post_init__(self) -> None:
        started = require_aware_utc(self.started_at, "started_at")
        finished = require_aware_utc(self.finished_at, "finished_at")
        object.__setattr__(self, "started_at", started)
        object.__setattr__(self, "finished_at", finished)
        if finished < started or self.runtime_ms < 0:
            raise ValidationError("invalid replay run timing")
        object.__setattr__(self, "run_id", content_id("replay-run", self))


@dataclass(frozen=True, slots=True)
class OutcomeEvaluation:
    run_id: str
    evaluated_at: datetime
    horizon_end: datetime
    forward_return: str | None
    benchmark_relative_return: str | None
    maximum_adverse_excursion: str | None
    maximum_favorable_excursion: str | None
    volatility: str | None
    drawdown: str | None
    direction: str | None
    provenance_observation_ids: tuple[str, ...]
    evaluation_id: str = field(init=False)

    def __post_init__(self) -> None:
        evaluated = require_aware_utc(self.evaluated_at, "evaluated_at")
        horizon = require_aware_utc(self.horizon_end, "horizon_end")
        object.__setattr__(self, "evaluated_at", evaluated)
        object.__setattr__(self, "horizon_end", horizon)
        if evaluated < horizon:
            raise ValidationError("outcome cannot be evaluated before horizon maturity")
        if not self.provenance_observation_ids:
            raise ValidationError("outcome requires market-observation provenance")
        object.__setattr__(self, "evaluation_id", content_id("outcome-evaluation", self))


@dataclass(frozen=True, slots=True)
class BenchmarkPair:
    case_id: str
    named_run_id: str
    anonymized_run_id: str
    created_at: datetime
    pair_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", require_aware_utc(self.created_at, "created_at"))
        if self.named_run_id == self.anonymized_run_id:
            raise ValidationError("named and anonymized runs must be distinct")
        object.__setattr__(self, "pair_id", content_id("benchmark-pair", self))


@dataclass(frozen=True, slots=True)
class ReplaySnapshot:
    timestamp: datetime
    context_id: str
    market_observation_ids: tuple[str, ...]
    event_ids: tuple[str, ...]
    policy_ids: tuple[str, ...]
    news_ids: tuple[str, ...]
    fundamental_ids: tuple[str, ...]
    graph_version_ids: tuple[str, ...]
    macro_observation_ids: tuple[str, ...] = ()
    trend_ids: tuple[str, ...] = ()
    structural_trend_ids: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class BenchmarkMetrics:
    hypothesis_validity_rate: float
    reviewer_rejection_rate: float
    unsupported_claim_rate: float
    provenance_failure_rate: float
    temporal_leakage_rate: float
    calibration: float
    directional_accuracy: float | None
    benchmark_relative_outcome: float | None
    named_anonymized_gap: float | None
