from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum

from market_evolver.errors import ValidationError
from market_evolver.provenance import content_id
from market_evolver.time import require_aware_utc


class ExperimentStatus(str, Enum):
    PROPOSED = "proposed"
    VALIDATED = "validated"
    RUNNING = "running"
    COMPLETED = "completed"
    INVALID = "invalid"
    REJECTED = "rejected"


class SignalKind(str, Enum):
    EVENT_TYPE = "event_type"
    CORROBORATION_STATE = "corroboration_state"
    MACRO_TREND = "macro_trend"
    FUNDAMENTAL_RATIO = "fundamental_ratio"
    PRICE_MOMENTUM = "price_momentum"
    CLAIM_REPUTATION = "claim_reputation"
    MECHANISM_EXPOSURE = "mechanism_exposure"


class RuleOperator(str, Enum):
    EQ = "eq"
    GTE = "gte"
    LTE = "lte"
    IN = "in"


class EntryRule(str, Enum):
    NEXT_OPEN = "next_open"
    NEXT_CLOSE = "next_close"
    NEXT_VALID_SESSION = "next_valid_session"


class ExitRule(str, Enum):
    FIXED_HOLDING_PERIOD = "fixed_holding_period"
    EVENT_INVALIDATION = "event_invalidation"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    END_OF_WINDOW = "end_of_window"


class PositionPolicy(str, Enum):
    SINGLE_POSITION = "single_position"
    EQUAL_WEIGHT = "equal_weight"
    FIXED_NOTIONAL = "fixed_notional"


class RebalanceFrequency(str, Enum):
    DAILY = "daily"
    EVENT_DRIVEN = "event_driven"


class PartitionKind(str, Enum):
    RESEARCH = "research"
    VALIDATION = "validation"
    TEST = "test"


@dataclass(frozen=True, slots=True)
class SignalClause:
    kind: SignalKind
    field_name: str
    operator: RuleOperator
    value: str
    lookback_days: int | None = None

    def __post_init__(self) -> None:
        if (
            not self.field_name
            or not self.value
            or self.lookback_days is not None
            and self.lookback_days < 1
        ):
            raise ValidationError("invalid typed signal clause")
        if any(token in self.value for token in ("__", "import ", "lambda", "eval(")):
            raise ValidationError("signal values cannot contain executable code")


@dataclass(frozen=True, slots=True)
class SignalDefinition:
    clauses: tuple[SignalClause, ...]
    require_all: bool = True
    signal_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.clauses:
            raise ValidationError("signal definition requires typed clauses")
        object.__setattr__(self, "signal_id", content_id("signal-definition", self))

    def evaluate(self, values: dict[str, str]) -> bool:
        outcomes = tuple(
            _evaluate(clause, values.get(clause.field_name)) for clause in self.clauses
        )
        return all(outcomes) if self.require_all else any(outcomes)


@dataclass(frozen=True, slots=True)
class SignalObservation:
    asset_id: str
    observed_at: datetime
    values: tuple[tuple[str, str], ...]
    provenance: tuple[str, ...]
    signal_observation_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", require_aware_utc(self.observed_at, "observed_at"))
        if not self.asset_id or not self.values or not self.provenance:
            raise ValidationError("signal observation requires values and provenance")
        object.__setattr__(self, "signal_observation_id", content_id("signal-observation", self))


@dataclass(frozen=True, slots=True)
class CostModel:
    commission_rate: str = "0"
    spread_bps: str = "0"
    slippage_bps: str = "0"
    fx_conversion_bps: str = "0"
    minimum_commission: str = "0"
    tax_rate: str = "0"
    fractional_shares: bool = True

    def __post_init__(self) -> None:
        values = tuple(
            _decimal(getattr(self, name))
            for name in (
                "commission_rate",
                "spread_bps",
                "slippage_bps",
                "fx_conversion_bps",
                "minimum_commission",
                "tax_rate",
            )
        )
        if any(value < 0 for value in values):
            raise ValidationError("transaction costs cannot be negative")


@dataclass(frozen=True, slots=True)
class EvaluationWindow:
    research_start: datetime
    research_end: datetime
    validation_start: datetime
    validation_end: datetime
    test_start: datetime
    test_end: datetime

    def __post_init__(self) -> None:
        names = (
            "research_start",
            "research_end",
            "validation_start",
            "validation_end",
            "test_start",
            "test_end",
        )
        for name in names:
            object.__setattr__(self, name, require_aware_utc(getattr(self, name), name))
        if (
            not self.research_start
            <= self.research_end
            < self.validation_start
            <= self.validation_end
            < self.test_start
            <= self.test_end
        ):
            raise ValidationError("train/validation/test windows must be ordered and disjoint")


@dataclass(frozen=True, slots=True)
class ExperimentSpecification:
    hypothesis_id: str
    created_at: datetime
    cutoff: datetime
    research_context_id: str
    asset_universe: tuple[str, ...]
    benchmark: str
    signal_definition: SignalDefinition
    entry_rule: EntryRule
    exit_rule: ExitRule
    holding_period: int
    rebalance_frequency: RebalanceFrequency
    position_policy: PositionPolicy
    cost_model: CostModel
    evaluation_window: EvaluationWindow
    exclusion_rules: tuple[str, ...]
    parameter_manifest: tuple[tuple[str, str], ...]
    code_version_hash: str
    provenance: tuple[str, ...]
    status: ExperimentStatus = ExperimentStatus.PROPOSED
    version: int = 1
    revision_of: str | None = None
    experiment_id: str = field(init=False)

    def __post_init__(self) -> None:
        created = require_aware_utc(self.created_at, "created_at")
        cutoff = require_aware_utc(self.cutoff, "cutoff")
        object.__setattr__(self, "created_at", created)
        object.__setattr__(self, "cutoff", cutoff)
        if created < cutoff or not self.hypothesis_id or not self.research_context_id:
            raise ValidationError("experiment identity/timeline is invalid")
        if not self.asset_universe or not self.benchmark or self.holding_period < 1:
            raise ValidationError("experiment requires assets, benchmark, and holding period")
        if not self.code_version_hash.startswith("sha256:") or not self.provenance:
            raise ValidationError("experiment code hash and provenance are required")
        if self.version < 1 or (self.version == 1) != (self.revision_of is None):
            raise ValidationError("experiment version lineage is invalid")
        if (
            self.status
            in {ExperimentStatus.VALIDATED, ExperimentStatus.RUNNING, ExperimentStatus.COMPLETED}
            and self.cutoff > self.evaluation_window.research_end
        ):
            raise ValidationError("validated experiment cutoff follows research window")
        object.__setattr__(self, "experiment_id", content_id("experiment-specification", self))


@dataclass(frozen=True, slots=True)
class DatasetManifest:
    dataset_version: str
    parquet_hashes: tuple[str, ...]
    source_versions: tuple[str, ...]
    parameter_hash: str
    seed: int
    rows_read: int
    bytes_read: int
    manifest_id: str = field(init=False)

    def __post_init__(self) -> None:
        if (
            not self.dataset_version
            or not self.parquet_hashes
            or self.rows_read < 1
            or self.bytes_read < 1
        ):
            raise ValidationError("backtest dataset manifest is incomplete")
        if not self.parameter_hash.startswith("sha256:") or any(
            len(value) != 64 for value in self.parquet_hashes
        ):
            raise ValidationError("invalid reproducibility hash")
        object.__setattr__(self, "manifest_id", content_id("backtest-dataset", self))


@dataclass(frozen=True, slots=True)
class CostBreakdown:
    commission: str
    spread: str
    slippage: str
    fx_conversion: str
    tax: str

    @property
    def total(self) -> Decimal:
        return sum(
            (
                _decimal(getattr(self, name))
                for name in ("commission", "spread", "slippage", "fx_conversion", "tax")
            ),
            Decimal(0),
        )


@dataclass(frozen=True, slots=True)
class SimulatedPosition:
    asset_id: str
    quantity: str
    entry_price: str
    mark_price: str
    unrealized_pnl: str
    realized_pnl: str
    transaction_costs: str
    exposure: str

    def __post_init__(self) -> None:
        values = tuple(
            _decimal(getattr(self, name))
            for name in (
                "quantity",
                "entry_price",
                "mark_price",
                "unrealized_pnl",
                "realized_pnl",
                "transaction_costs",
                "exposure",
            )
        )
        if not self.asset_id or values[0] < 0 or values[1] <= 0 or values[2] <= 0 or values[6] < 0:
            raise ValidationError("invalid long-only simulated position")


@dataclass(frozen=True, slots=True)
class PortfolioState:
    observed_at: datetime
    cash: str
    positions: tuple[SimulatedPosition, ...]
    nav: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", require_aware_utc(self.observed_at, "observed_at"))
        if _decimal(self.cash) < 0 or _decimal(self.nav) < 0:
            raise ValidationError("cash portfolio cannot use margin")


@dataclass(frozen=True, slots=True)
class PositionPath:
    asset_id: str
    entry_at: datetime
    exit_at: datetime
    quantity: str
    entry_price: str
    exit_price: str
    maximum_favorable_excursion: str
    maximum_adverse_excursion: str
    holding_period: int
    realized_return: str
    benchmark_relative_return: str
    costs: CostBreakdown
    path_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "entry_at", require_aware_utc(self.entry_at, "entry_at"))
        object.__setattr__(self, "exit_at", require_aware_utc(self.exit_at, "exit_at"))
        if self.exit_at <= self.entry_at or self.holding_period < 1:
            raise ValidationError("invalid position path")
        object.__setattr__(self, "path_id", content_id("position-path", self))


@dataclass(frozen=True, slots=True)
class BacktestResult:
    experiment_id: str
    dataset_manifest_id: str
    reproducibility: tuple[tuple[str, str], ...]
    started_at: datetime
    finished_at: datetime
    gross_return: str
    net_return: str
    benchmark_return: str
    excess_return: str
    volatility: str
    max_drawdown: str
    sharpe: str
    sortino: str
    hit_rate: str
    turnover: str
    transaction_costs: CostBreakdown
    number_of_signals: int
    executed_trades: int
    skipped_signals: int
    rejection_reasons: tuple[str, ...]
    nav: tuple[tuple[str, str], ...]
    position_paths: tuple[PositionPath, ...]
    runtime_ms: int
    parquet_bytes_read: int
    result_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "started_at", require_aware_utc(self.started_at, "started_at"))
        object.__setattr__(self, "finished_at", require_aware_utc(self.finished_at, "finished_at"))
        required = {
            "experiment_spec_hash",
            "code_version_hash",
            "parameter_hash",
            "seed",
            "parquet_hashes",
            "source_versions",
        }
        if not required <= {key for key, _ in self.reproducibility}:
            raise ValidationError("backtest reproducibility manifest is incomplete")
        if (
            self.finished_at < self.started_at
            or self.runtime_ms < 0
            or self.executed_trades > self.number_of_signals
        ):
            raise ValidationError("invalid backtest result accounting")
        object.__setattr__(self, "result_id", content_id("backtest-result", self))


@dataclass(frozen=True, slots=True)
class TestSetAccess:
    experiment_id: str
    partition: PartitionKind
    accessed_at: datetime
    purpose: str
    actor: str
    audit_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "accessed_at", require_aware_utc(self.accessed_at, "accessed_at"))
        if not self.purpose or not self.actor:
            raise ValidationError("test-set access requires purpose and actor")
        object.__setattr__(self, "audit_id", content_id("test-set-access", self))


@dataclass(frozen=True, slots=True)
class ExperimentRegistrySnapshot:
    observed_at: datetime
    hypotheses_generated: int
    experiments_executed: int
    rejected_experiments: int
    reported_experiments: int
    snapshot_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", require_aware_utc(self.observed_at, "observed_at"))
        if (
            min(
                self.hypotheses_generated,
                self.experiments_executed,
                self.rejected_experiments,
                self.reported_experiments,
            )
            < 0
        ):
            raise ValidationError("experiment registry counts cannot be negative")
        object.__setattr__(self, "snapshot_id", content_id("experiment-registry", self))


def _decimal(value: str) -> Decimal:
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise ValidationError("numeric values must be decimal strings") from exc


def _evaluate(clause: SignalClause, actual: str | None) -> bool:
    if actual is None:
        return False
    if clause.operator is RuleOperator.EQ:
        return actual == clause.value
    if clause.operator is RuleOperator.IN:
        return actual in tuple(part.strip() for part in clause.value.split(","))
    try:
        left, right = Decimal(actual), Decimal(clause.value)
    except InvalidOperation:
        return False
    return left >= right if clause.operator is RuleOperator.GTE else left <= right


SMALL_ACCOUNT_NIS_2000 = CostModel(
    commission_rate="0.001",
    spread_bps="10",
    slippage_bps="5",
    fx_conversion_bps="50",
    minimum_commission="10",
    tax_rate="0",
    fractional_shares=False,
)
