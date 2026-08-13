from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from re import fullmatch

from market_evolver.errors import ValidationError
from market_evolver.provenance import content_id
from market_evolver.time import require_aware_utc


class ExternalBenchmarkStatus(str, Enum):
    REGISTERED = "registered"
    INSPECTED = "inspected"
    RUNNABLE = "runnable"
    INCOMPATIBLE = "incompatible"
    EVALUATED = "evaluated"


class Comparability(str, Enum):
    EXACTLY_COMPARABLE = "EXACTLY_COMPARABLE"
    PARTIALLY_COMPARABLE = "PARTIALLY_COMPARABLE"
    NON_EQUIVALENT = "NON_EQUIVALENT"


class ComparisonMode(str, Enum):
    NATIVE_REFERENCE = "stockbench_native_reference"
    GENERALIST = "marketevolver_generalist"
    SPECIALIST = "marketevolver_specialist"
    SPECIALIST_REVIEWED = "marketevolver_specialist_skeptical_reviewer"
    ANONYMIZED = "marketevolver_anonymized"
    FIXED_TOPOLOGY = "marketevolver_fixed_topology"
    GOVERNED_EVOLVED_TOPOLOGY = "marketevolver_governed_evolved_topology"


@dataclass(frozen=True, slots=True)
class ExternalBenchmarkDefinition:
    benchmark_id: str
    name: str
    repository_uri: str
    local_path: str | None
    pinned_git_sha: str | None
    license: str
    paper_reference: str
    benchmark_type: str
    supported_assets: tuple[str, ...]
    evaluation_period: str
    required_inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    contamination_notes: str
    execution_requirements: tuple[str, ...]
    status: ExternalBenchmarkStatus
    provenance: tuple[str, ...]
    definition_id: str = field(init=False)

    def __post_init__(self) -> None:
        if fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", self.benchmark_id) is None:
            raise ValidationError("invalid external benchmark ID")
        if not self.repository_uri.startswith("https://"):
            raise ValidationError("external repository URI must use HTTPS")
        if (
            self.pinned_git_sha is not None
            and fullmatch(r"[0-9a-f]{40}", self.pinned_git_sha) is None
        ):
            raise ValidationError("external benchmark SHA must be a full Git SHA")
        if self.status is not ExternalBenchmarkStatus.REGISTERED and self.pinned_git_sha is None:
            raise ValidationError("inspected external benchmarks require an immutable Git pin")
        required = (
            self.name,
            self.license,
            self.paper_reference,
            self.benchmark_type,
            self.evaluation_period,
            self.contamination_notes,
        )
        if not all(required) or not self.provenance:
            raise ValidationError("external benchmark metadata and provenance are required")
        object.__setattr__(self, "definition_id", content_id("external-benchmark", self))


@dataclass(frozen=True, slots=True)
class ExternalRepositoryManifest:
    benchmark_id: str
    git_sha: str
    git_remote: str
    dirty: bool
    python_version: str
    dependency_manifest_hash: str
    license_hash: str
    benchmark_config_hashes: tuple[tuple[str, str], ...]
    inspected_at: datetime
    manifest_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "inspected_at", require_aware_utc(self.inspected_at, "inspected_at")
        )
        hashes = (self.git_sha, self.dependency_manifest_hash, self.license_hash)
        if fullmatch(r"[0-9a-f]{40}", self.git_sha) is None:
            raise ValidationError("repository manifest requires an exact Git SHA")
        config_hashes = tuple(value for _, value in self.benchmark_config_hashes)
        if any(
            fullmatch(r"[0-9a-f]{64}", value) is None for value in (*hashes[1:], *config_hashes)
        ):
            raise ValidationError("repository files require SHA-256 hashes")
        if not self.git_remote or not self.python_version:
            raise ValidationError("repository environment metadata is required")
        object.__setattr__(self, "manifest_id", content_id("external-repository-manifest", self))


@dataclass(frozen=True, slots=True)
class FairComparisonManifest:
    asset_universe: tuple[str, ...]
    time_period: str
    initial_capital: str
    transaction_costs: str
    execution_timing: str
    information_set: str
    model_provider: str
    model_settings: str
    number_of_agent_calls: int
    benchmark: str
    currency: str
    fractional_share_policy: str
    mode: ComparisonMode
    provenance: tuple[str, ...]
    manifest_id: str = field(init=False)

    def __post_init__(self) -> None:
        values = (
            self.time_period,
            self.initial_capital,
            self.transaction_costs,
            self.execution_timing,
            self.information_set,
            self.model_provider,
            self.model_settings,
            self.benchmark,
            self.currency,
            self.fractional_share_policy,
        )
        if not self.asset_universe or not all(values) or not self.provenance:
            raise ValidationError("fair-comparison metadata cannot be omitted")
        if self.number_of_agent_calls < 0:
            raise ValidationError("agent call count cannot be negative")
        object.__setattr__(self, "manifest_id", content_id("fair-comparison", self))


@dataclass(frozen=True, slots=True)
class ExternalActionProposal:
    symbol: str
    action: str
    quantity: str
    rationale: str
    context_id: str
    expert_version_id: str
    reviewer_decision: str
    provenance_ids: tuple[str, ...]
    proposal_id: str = field(init=False)

    def __post_init__(self) -> None:
        if self.action not in {"BUY", "SELL", "HOLD"}:
            raise ValidationError("external action must be BUY, SELL, or HOLD")
        if not all(
            (self.symbol, self.quantity, self.rationale, self.context_id, self.expert_version_id)
        ):
            raise ValidationError("external action proposal is incomplete")
        if not self.provenance_ids or self.reviewer_decision not in {
            "approved",
            "rejected",
            "not_required",
        }:
            raise ValidationError("external action requires governance and provenance")
        object.__setattr__(self, "proposal_id", content_id("external-action-proposal", self))


@dataclass(frozen=True, slots=True)
class ExternalRunImport:
    benchmark_id: str
    repository_manifest_id: str
    market_evolver_sha: str
    dataset_hashes: tuple[str, ...]
    config_hashes: tuple[str, ...]
    model_provider: str
    prompt_hashes: tuple[str, ...]
    seeds: tuple[int, ...]
    environment: tuple[tuple[str, str], ...]
    started_at: datetime
    finished_at: datetime
    decisions: tuple[str, ...]
    portfolio_path_hash: str
    reported_metrics: tuple[tuple[str, float], ...]
    runtime_ms: int
    reproducibility_log_hash: str
    run_id: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("started_at", "finished_at"):
            object.__setattr__(self, name, require_aware_utc(getattr(self, name), name))
        if self.finished_at < self.started_at or self.runtime_ms < 0:
            raise ValidationError("invalid external run timing")
        if not all((self.repository_manifest_id, self.market_evolver_sha, self.config_hashes)):
            raise ValidationError("external run provenance is incomplete")
        if fullmatch(r"[0-9a-f]{40}", self.market_evolver_sha) is None:
            raise ValidationError("external run requires exact MarketEvolver Git SHA")
        hashes = (
            *self.dataset_hashes,
            *self.config_hashes,
            *self.prompt_hashes,
            self.portfolio_path_hash,
            self.reproducibility_log_hash,
        )
        if any(fullmatch(r"[0-9a-f]{64}", value) is None for value in hashes):
            raise ValidationError("external run artifacts require SHA-256 hashes")
        if not self.model_provider or not self.environment:
            raise ValidationError("external run environment and model/provider are required")
        object.__setattr__(self, "run_id", content_id("external-run-import", self))
