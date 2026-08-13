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


class ExecutionStatus(str, Enum):
    PASS = "PASS"
    BLOCKED_DATASET = "BLOCKED_DATASET"
    BLOCKED_PROVIDER = "BLOCKED_PROVIDER"
    NON_EQUIVALENT = "NON_EQUIVALENT"
    PARTIALLY_COMPARABLE = "PARTIALLY_COMPARABLE"
    FAILED_EXTERNAL = "FAILED_EXTERNAL"
    FAILED_MARKETEVOLVER = "FAILED_MARKETEVOLVER"


class EndpointClass(str, Enum):
    OPENAI_COMPATIBLE_CHAT = "openai_compatible_chat"


class DatasetClassification(str, Enum):
    RUNNABLE_NATIVE = "RUNNABLE_NATIVE"
    RUNNABLE_NON_CAUSAL = "RUNNABLE_NON_CAUSAL"
    BLOCKED_DATASET = "BLOCKED_DATASET"
    PARTIALLY_REPRODUCIBLE = "PARTIALLY_REPRODUCIBLE"


class ReadinessState(str, Enum):
    READY = "READY"
    MISMATCH = "MISMATCH"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"


class BenchmarkDecision(str, Enum):
    READY_EXACT = "READY_EXACT"
    READY_PARTIAL = "READY_PARTIAL"
    BLOCKED_PROVIDER = "BLOCKED_PROVIDER"
    BLOCKED_DATASET = "BLOCKED_DATASET"
    BLOCKED_DEPENDENCY = "BLOCKED_DEPENDENCY"
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
class ProviderExecutionProfile:
    provider_id: str
    provider_name: str
    model_id: str
    endpoint_class: EndpointClass
    endpoint: str
    temperature: float
    max_tokens: int
    timeout_seconds: int
    retry_attempts: int
    retry_backoff_seconds: float
    structured_output: bool
    input_price_per_million_tokens: str | None
    output_price_per_million_tokens: str | None
    created_at: datetime
    provenance_version: str
    profile_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", require_aware_utc(self.created_at, "created_at"))
        if fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", self.provider_id) is None:
            raise ValidationError("invalid provider ID")
        if not self.endpoint.startswith("https://"):
            raise ValidationError("provider endpoint must use HTTPS")
        if not 0 <= self.temperature <= 2 or self.max_tokens <= 0 or self.timeout_seconds <= 0:
            raise ValidationError("invalid provider sampling or timeout settings")
        if self.retry_attempts < 1 or self.retry_backoff_seconds < 0:
            raise ValidationError("invalid provider retry policy")
        if not all((self.provider_name, self.model_id, self.provenance_version)):
            raise ValidationError("provider profile metadata is required")
        object.__setattr__(self, "profile_id", content_id("provider-execution-profile", self))


@dataclass(frozen=True, slots=True)
class ProviderValidationResult:
    profile_id: str
    status: ExecutionStatus
    authenticated: bool | None
    reachable: bool
    model_available: bool
    structured_response: bool
    input_tokens: int
    output_tokens: int
    latency_ms: int
    raw_response_hash: str | None
    provider_request_id: str | None
    returned_model_id: str | None
    response_metadata: tuple[tuple[str, str], ...]
    error_summary: str | None
    validated_at: datetime
    failure_category: str | None = None
    http_status: int | None = None
    content_type: str | None = None
    sanitized_response_preview: str | None = None
    estimated_cost: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "validated_at", require_aware_utc(self.validated_at, "validated_at")
        )
        if min(self.input_tokens, self.output_tokens, self.latency_ms) < 0:
            raise ValidationError("provider accounting cannot be negative")
        if self.http_status is not None and not 100 <= self.http_status <= 599:
            raise ValidationError("invalid provider HTTP status")
        if self.sanitized_response_preview is not None and len(
            self.sanitized_response_preview
        ) > 256:
            raise ValidationError("provider response preview is not bounded")


@dataclass(frozen=True, slots=True)
class UsageAccounting:
    input_tokens: int
    output_tokens: int
    calls: int
    latency_ms: int
    estimated_cost: str | None

    def __post_init__(self) -> None:
        if min(self.input_tokens, self.output_tokens, self.calls, self.latency_ms) < 0:
            raise ValidationError("usage accounting cannot be negative")


@dataclass(frozen=True, slots=True)
class RepeatedRunSummary:
    status: ExecutionStatus
    repeats_requested: int
    repeats_completed: int
    metric_name: str
    mean: float | None
    population_variance: float | None
    usage: UsageAccounting

    def __post_init__(self) -> None:
        if self.repeats_requested < 1 or not 0 <= self.repeats_completed <= self.repeats_requested:
            raise ValidationError("invalid repeated-run counts")
        if self.status is ExecutionStatus.PASS and self.repeats_completed != self.repeats_requested:
            raise ValidationError("successful repeats must all complete")


@dataclass(frozen=True, slots=True)
class ExternalEnvironmentManifest:
    benchmark_id: str
    repository_manifest_id: str
    provider_profile_id: str
    python_version: str
    dependency_state_hash: str
    required_datasets: tuple[str, ...]
    missing_datasets: tuple[str, ...]
    expected_environment_variables: tuple[str, ...]
    present_environment_variables: tuple[str, ...]
    benchmark_config_hash: str
    command: tuple[str, ...]
    expected_outputs: tuple[str, ...]
    runtime_requirements: tuple[str, ...]
    patch_hash: str | None
    patched_baseline: bool
    status: ExecutionStatus
    manifest_id: str = field(init=False)

    def __post_init__(self) -> None:
        if self.patched_baseline != (self.patch_hash is not None):
            raise ValidationError("patched baseline label and patch hash must agree")
        for value in (self.dependency_state_hash, self.benchmark_config_hash):
            if fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValidationError("environment manifests require SHA-256 hashes")
        if not all((self.benchmark_id, self.repository_manifest_id, self.provider_profile_id)):
            raise ValidationError("external environment manifest is incomplete")
        object.__setattr__(self, "manifest_id", content_id("external-environment", self))


@dataclass(frozen=True, slots=True)
class EnvironmentSetupManifest:
    benchmark_id: str
    external_git_sha: str
    python_version: str
    pip_freeze_hash: str
    dependency_manifest_path: str
    dependency_manifest_hash: str
    platform: str
    setup_at: datetime
    install_command: tuple[str, ...]
    install_succeeded: bool
    smoke_outcome: str
    manifest_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "setup_at", require_aware_utc(self.setup_at, "setup_at"))
        for value in (self.pip_freeze_hash, self.dependency_manifest_hash):
            if fullmatch(r"[0-9a-f]{64}", value) is None:
                raise ValidationError("environment setup requires SHA-256 hashes")
        if fullmatch(r"[0-9a-f]{40}", self.external_git_sha) is None:
            raise ValidationError("environment setup requires exact external SHA")
        if not all((self.benchmark_id, self.python_version, self.platform, self.install_command)):
            raise ValidationError("environment setup manifest is incomplete")
        object.__setattr__(self, "manifest_id", content_id("environment-setup", self))


@dataclass(frozen=True, slots=True)
class NetworkDomainManifest:
    benchmark_id: str
    domains: tuple[str, ...]
    credential_variables: tuple[str, ...]
    download_classes: tuple[str, ...]
    broad_network_allowed: bool = False

    def __post_init__(self) -> None:
        if self.broad_network_allowed or not self.benchmark_id:
            raise ValidationError("external benchmark network must remain allowlisted")
        if any("/" in domain or ":" in domain for domain in self.domains):
            raise ValidationError("network manifest entries must be bare domains")


@dataclass(frozen=True, slots=True)
class DatasetAudit:
    benchmark_id: str
    classification: DatasetClassification
    file_count: int
    assets: tuple[str, ...]
    period_start: str | None
    period_end: str | None
    schemas: tuple[str, ...]
    provenance_metadata: tuple[str, ...]
    information_timestamps: bool
    limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        if self.file_count < 0 or not self.limitations:
            raise ValidationError("dataset audit requires counts and limitations")


@dataclass(frozen=True, slots=True)
class ProviderCostLimit:
    maximum_calls: int
    maximum_input_tokens: int
    maximum_output_tokens: int
    maximum_estimated_cost: str

    def __post_init__(self) -> None:
        if min(self.maximum_calls, self.maximum_input_tokens, self.maximum_output_tokens) < 1:
            raise ValidationError("provider guard limits must be positive")
        if float(self.maximum_estimated_cost) <= 0:
            raise ValidationError("provider cost limit must be positive")


@dataclass(frozen=True, slots=True)
class ReadinessRow:
    dimension: str
    market_evolver: ReadinessState
    stockbench: ReadinessState
    tradingagents: ReadinessState
    rationale: str

    def __post_init__(self) -> None:
        if not self.dimension or not self.rationale:
            raise ValidationError("readiness row requires dimension and rationale")


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
