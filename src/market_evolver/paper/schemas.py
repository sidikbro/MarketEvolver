from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum

from market_evolver.errors import ValidationError
from market_evolver.provenance import content_id
from market_evolver.time import require_aware_utc


class PortfolioStatus(str, Enum):
    CONFIGURED = "configured"
    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETED = "completed"


class KillState(str, Enum):
    NORMAL = "normal"
    ENTRY_RESTRICTED = "entry_restricted"
    PAUSED = "paused"
    HALTED = "halted"


class PaperSide(str, Enum):
    BUY = "buy"
    SELL_EXISTING_POSITION = "sell_existing_position"


class RiskAction(str, Enum):
    APPROVED = "approved"
    RESIZED = "resized"
    REJECTED = "rejected"
    PORTFOLIO_HALTED = "portfolio_halted"


class AllocationPolicy(str, Enum):
    FIXED_NOTIONAL = "fixed_notional"
    EQUAL_WEIGHT = "equal_weight"
    PREDEFINED_STRATEGY = "predefined_strategy"


class RuntimeMode(str, Enum):
    HISTORICAL_REPLAY = "historical_replay"
    FORWARD_PAPER = "forward_paper"


class BookType(str, Enum):
    EVENT = "event"
    SHORT_TERM = "short_term"
    MEDIUM_TERM = "medium_term"
    LONG_TERM = "long_term"


@dataclass(frozen=True, slots=True)
class RiskPolicy:
    name: str
    created_at: datetime
    max_position_weight: str
    max_order_notional: str
    max_gross_exposure: str
    max_sector_exposure: str
    max_currency_exposure: str
    max_daily_turnover: str
    max_trades_per_day: int
    min_cash_reserve: str
    max_daily_loss: str
    entry_restricted_drawdown: str
    max_rolling_drawdown: str
    max_portfolio_drawdown: str
    min_corroboration: int
    allowed_asset_classes: tuple[str, ...]
    allowed_exchanges: tuple[str, ...]
    max_stale_seconds: int
    max_strategy_allocation: str
    max_concurrent_positions: int
    max_cost_order_ratio: str
    max_cost_nav_ratio: str
    provenance: tuple[str, ...]
    policy_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", require_aware_utc(self.created_at, "created_at"))
        ratios = (
            self.max_position_weight,
            self.max_gross_exposure,
            self.max_sector_exposure,
            self.max_currency_exposure,
            self.max_daily_turnover,
            self.min_cash_reserve,
            self.max_daily_loss,
            self.entry_restricted_drawdown,
            self.max_rolling_drawdown,
            self.max_portfolio_drawdown,
            self.max_strategy_allocation,
            self.max_cost_order_ratio,
            self.max_cost_nav_ratio,
        )
        try:
            parsed = tuple(Decimal(value) for value in ratios)
            order = Decimal(self.max_order_notional)
        except InvalidOperation as exc:
            raise ValidationError("risk limits must be decimal strings") from exc
        if any(value < 0 or value > 1 for value in parsed) or order <= 0:
            raise ValidationError("risk ratios must be within [0,1] and notional positive")
        if (
            min(
                self.max_trades_per_day,
                self.min_corroboration,
                self.max_stale_seconds,
                self.max_concurrent_positions,
            )
            < 1
        ):
            raise ValidationError("risk count limits must be positive")
        if not self.allowed_asset_classes or not self.allowed_exchanges or not self.provenance:
            raise ValidationError("risk policy allowlists and provenance are required")
        object.__setattr__(self, "policy_id", content_id("paper-risk-policy", self))


@dataclass(frozen=True, slots=True)
class PaperPortfolio:
    portfolio_id: str
    name: str
    base_currency: str
    initial_cash: str
    created_at: datetime
    strategy_ids: tuple[str, ...]
    operator_policy_ids: tuple[str, ...]
    benchmark_asset_id: str
    allocation_policy: AllocationPolicy
    risk_policy_id: str
    execution_policy_id: str
    status: PortfolioStatus = PortfolioStatus.CONFIGURED
    version: int = 1
    revision_of: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", require_aware_utc(self.created_at, "created_at"))
        if Decimal(self.initial_cash) <= 0 or not all(
            (
                self.portfolio_id,
                self.name,
                self.base_currency,
                self.benchmark_asset_id,
                self.risk_policy_id,
                self.execution_policy_id,
            )
        ):
            raise ValidationError("paper portfolio configuration is incomplete")
        if not self.strategy_ids and not self.operator_policy_ids:
            raise ValidationError("portfolio requires an admitted research policy")
        if self.version < 1 or (self.version == 1) != (self.revision_of is None):
            raise ValidationError("portfolio version lineage is invalid")


@dataclass(frozen=True, slots=True)
class BookAllocation:
    book: BookType
    capital_weight: str
    risk_budget: str
    strategy_allowlist: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.strategy_allowlist or not 0 < Decimal(self.capital_weight) <= 1:
            raise ValidationError("book allocation is invalid")


@dataclass(frozen=True, slots=True)
class SignalIntent:
    portfolio_id: str
    asset_id: str
    side: PaperSide
    generated_at: datetime
    intended_session: str
    execution_rule: str
    strategy_id: str | None
    operator_approval_id: str | None
    requested_quantity: str | None
    requested_notional: str | None
    evidence_ids: tuple[str, ...]
    corroboration_count: int
    context_observed_at: datetime
    provenance: tuple[str, ...]
    book: BookType = BookType.SHORT_TERM
    signal_id: str = field(init=False)

    def __post_init__(self) -> None:
        generated = require_aware_utc(self.generated_at, "generated_at")
        context = require_aware_utc(self.context_observed_at, "context_observed_at")
        object.__setattr__(self, "generated_at", generated)
        object.__setattr__(self, "context_observed_at", context)
        if context > generated:
            raise ValidationError("research context cannot be observed in the future")
        if bool(self.strategy_id) == bool(self.operator_approval_id):
            raise ValidationError("exactly one validated signal admission path is required")
        if (self.strategy_id or "").startswith(("model:", "llm:")):
            raise ValidationError("model output cannot directly enter paper execution")
        if (self.requested_quantity is None) == (self.requested_notional is None):
            raise ValidationError("provide exactly one requested size")
        size = self.requested_quantity or self.requested_notional or "0"
        if Decimal(size) <= 0 or not self.evidence_ids or not self.provenance:
            raise ValidationError("signal size, evidence, and provenance are required")
        object.__setattr__(self, "signal_id", content_id("paper-signal", self))


@dataclass(frozen=True, slots=True)
class PaperPosition:
    asset_id: str
    quantity: str
    average_cost: str
    mark_price: str
    sector: str
    currency: str


@dataclass(frozen=True, slots=True)
class PaperAccountSnapshot:
    portfolio_id: str
    timestamp: datetime
    cash: str
    market_value: str
    nav: str
    realized_pnl: str
    unrealized_pnl: str
    transaction_costs: str
    fx_costs: str
    tax_estimate: str
    gross_exposure: str
    sector_exposure: tuple[tuple[str, str], ...]
    currency_exposure: tuple[tuple[str, str], ...]
    drawdown: str
    peak_nav: str
    positions: tuple[PaperPosition, ...]
    benchmark_nav: str | None
    kill_state: KillState
    snapshot_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", require_aware_utc(self.timestamp, "timestamp"))
        cash, market, nav = map(Decimal, (self.cash, self.market_value, self.nav))
        if cash < 0 or market < 0 or nav != cash + market:
            raise ValidationError("accounting invariant cash + marked positions = NAV failed")
        if any(Decimal(item.quantity) < 0 for item in self.positions):
            raise ValidationError("paper position cannot be short")
        object.__setattr__(self, "snapshot_id", content_id("paper-account-snapshot", self))


@dataclass(frozen=True, slots=True)
class PaperOrderCandidate:
    signal_id: str
    portfolio_id: str
    asset_id: str
    side: PaperSide
    quantity: str
    notional: str
    strategy_id: str
    generated_at: datetime
    intended_session: str
    execution_rule: str
    provenance: tuple[str, ...]
    candidate_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "generated_at", require_aware_utc(self.generated_at, "generated_at")
        )
        if Decimal(self.quantity) <= 0 or Decimal(self.notional) <= 0 or not self.provenance:
            raise ValidationError("order candidate must have positive size and provenance")
        object.__setattr__(self, "candidate_id", content_id("paper-order", self))


@dataclass(frozen=True, slots=True)
class RiskAttribution:
    rule: str
    current_exposure: str
    requested_exposure: str
    allowed_threshold: str
    action: RiskAction


@dataclass(frozen=True, slots=True)
class RiskEvaluation:
    candidate_id: str
    portfolio_id: str
    evaluated_at: datetime
    action: RiskAction
    reason_codes: tuple[str, ...]
    approved_quantity: str
    approved_notional: str
    expected_cost: str
    cost_order_ratio: str
    cost_nav_ratio: str
    attributions: tuple[RiskAttribution, ...]
    resulting_kill_state: KillState
    evaluation_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "evaluated_at", require_aware_utc(self.evaluated_at, "evaluated_at")
        )
        if self.action is not RiskAction.APPROVED and not self.reason_codes:
            raise ValidationError("non-approved risk action requires a reason")
        object.__setattr__(self, "evaluation_id", content_id("paper-risk-evaluation", self))


@dataclass(frozen=True, slots=True)
class ExecutionDecision:
    candidate_id: str
    evaluation_id: str
    decided_at: datetime
    execute: bool
    reason: str
    market_observation_id: str | None
    decision_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "decided_at", require_aware_utc(self.decided_at, "decided_at"))
        if self.execute != (self.market_observation_id is not None):
            raise ValidationError("execution decision and market provenance disagree")
        object.__setattr__(self, "decision_id", content_id("paper-execution-decision", self))


@dataclass(frozen=True, slots=True)
class PaperFill:
    decision_id: str
    portfolio_id: str
    asset_id: str
    side: PaperSide
    filled_at: datetime
    quantity: str
    price: str
    fees: str
    fx_costs: str
    cash_after: str
    position_after: str
    market_observation_id: str
    fill_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "filled_at", require_aware_utc(self.filled_at, "filled_at"))
        if any(
            Decimal(value) < 0
            for value in (
                self.quantity,
                self.price,
                self.fees,
                self.fx_costs,
                self.cash_after,
                self.position_after,
            )
        ):
            raise ValidationError("fill cannot produce negative values")
        object.__setattr__(self, "fill_id", content_id("paper-fill", self))


@dataclass(frozen=True, slots=True)
class AuditRecord:
    portfolio_id: str
    timestamp: datetime
    kind: str
    actor: str
    details: tuple[tuple[str, str], ...]
    prior_state: KillState | None = None
    resulting_state: KillState | None = None
    audit_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "timestamp", require_aware_utc(self.timestamp, "timestamp"))
        if not self.kind or not self.actor:
            raise ValidationError("audit record requires kind and actor")
        object.__setattr__(self, "audit_id", content_id("paper-audit", self))
