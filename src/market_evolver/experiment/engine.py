from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from statistics import mean, pstdev

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_evolver.errors import IntegrityViolation
from market_evolver.experiment.costs import affordable_quantity, transaction_costs
from market_evolver.experiment.schemas import (
    BacktestResult,
    CostBreakdown,
    DatasetManifest,
    EntryRule,
    ExitRule,
    ExperimentSpecification,
    ExperimentStatus,
    PositionPath,
    SignalObservation,
)
from market_evolver.market.schemas import MarketObservation, TradingSession
from market_evolver.market.store import MarketDataStore
from market_evolver.storage.models import (
    MarketObservationModel,
    MarketPartitionModel,
    TradingSessionModel,
)
from market_evolver.time import require_aware_utc


@dataclass(frozen=True, slots=True)
class ExecutionPoint:
    timestamp: datetime
    price: Decimal
    observation_id: str


def select_execution_point(
    signal_at: datetime,
    rule: EntryRule,
    sessions: tuple[TradingSession, ...],
    observations: tuple[MarketObservation, ...],
) -> ExecutionPoint:
    signal = require_aware_utc(signal_at, "signal_at")
    visible_sessions = tuple(
        session for session in sessions if session.is_trading_day and session.observed_at <= signal
    )
    for market_session in sorted(visible_sessions, key=lambda item: item.opens_at or signal):
        assert market_session.opens_at is not None and market_session.closes_at is not None
        if rule in {EntryRule.NEXT_OPEN, EntryRule.NEXT_VALID_SESSION}:
            if market_session.opens_at <= signal:
                continue
            bar = _bar_for_session(observations, market_session)
            if bar is None or bar.open is None:
                raise IntegrityViolation("unknown next-open execution price")
            return ExecutionPoint(market_session.opens_at, Decimal(bar.open), bar.observation_id)
        if market_session.closes_at <= signal:
            continue
        bar = _bar_for_session(observations, market_session)
        if bar is None or bar.close is None:
            raise IntegrityViolation("unknown next-close execution price")
        return ExecutionPoint(market_session.closes_at, Decimal(bar.close), bar.observation_id)
    raise IntegrityViolation("no valid market session after signal")


class BacktestEngine:
    def __init__(self, session: Session, market: MarketDataStore):
        self.session = session
        self.market = market

    def run(
        self,
        spec: ExperimentSpecification,
        signals: tuple[SignalObservation, ...],
        *,
        cutoff: datetime,
        initial_cash: Decimal = Decimal(2000),
        seed: int = 0,
        invalidation_times: dict[str, tuple[datetime, ...]] | None = None,
    ) -> tuple[DatasetManifest, BacktestResult]:
        cutoff = require_aware_utc(cutoff, "cutoff")
        if spec.status not in {ExperimentStatus.VALIDATED, ExperimentStatus.RUNNING}:
            raise IntegrityViolation("backtest requires validated experiment")
        if "survivorship_reviewed" not in spec.exclusion_rules:
            raise IntegrityViolation("survivorship caveat was not reviewed")
        if "corporate_actions_verified" not in spec.exclusion_rules:
            raise IntegrityViolation("corporate-action history is unavailable or unverified")
        if cutoff < spec.evaluation_window.test_end:
            raise IntegrityViolation("test outcome market data is not yet legally visible")
        sessions = self._sessions(spec, cutoff)
        paths: list[PositionPath] = []
        nav: list[tuple[str, str]] = []
        observation_ids: set[str] = set()
        skipped = 0
        cash = initial_cash
        benchmark_values = self.market.get_market_data(
            spec.benchmark,
            spec.evaluation_window.test_start,
            spec.evaluation_window.test_end,
            cutoff,
        )
        if len(benchmark_values) < 2:
            raise IntegrityViolation("benchmark mismatch or missing benchmark prices")
        benchmark_return = _return(
            Decimal(benchmark_values[0].effective_close),
            Decimal(benchmark_values[-1].effective_close),
        )
        for asset_id in spec.asset_universe:
            asset = self.market.get_asset_at(asset_id, spec.cutoff)
            if asset is None:
                raise IntegrityViolation("asset was not visible at experiment cutoff")
            if asset.benchmark_asset_id != spec.benchmark:
                raise IntegrityViolation("benchmark mismatch")
            bars = tuple(
                self.market.get_market_data(
                    asset_id,
                    spec.evaluation_window.test_start,
                    spec.evaluation_window.test_end,
                    cutoff,
                )
            )
            if not bars:
                raise IntegrityViolation("missing market data")
            for signal in (item for item in signals if item.asset_id == asset_id):
                if signal.observed_at > cutoff:
                    raise IntegrityViolation("future signal leakage")
                if not spec.signal_definition.evaluate(dict(signal.values)):
                    skipped += 1
                    continue
                entry = select_execution_point(signal.observed_at, spec.entry_rule, sessions, bars)
                later = tuple(bar for bar in bars if bar.market_timestamp > entry.timestamp)
                selected = _select_exit(
                    spec,
                    entry,
                    later,
                    () if invalidation_times is None else invalidation_times.get(asset_id, ()),
                )
                if selected is None:
                    skipped += 1
                    continue
                exit_bar, actual_holding = selected
                exit_price = Decimal(exit_bar.effective_close)
                if entry.price <= 0 or exit_price <= 0:
                    raise IntegrityViolation("execution prices must be positive")
                allocation = cash / max(1, len(spec.asset_universe))
                quantity = affordable_quantity(allocation, entry.price, spec.cost_model)
                if quantity <= 0:
                    skipped += 1
                    continue
                notional = quantity * entry.price
                entry_cost = transaction_costs(
                    notional, spec.cost_model, requires_fx=asset.currency != "ILS"
                )
                if notional + entry_cost.total > allocation:
                    quantity = affordable_quantity(
                        max(Decimal(0), allocation - entry_cost.total),
                        entry.price,
                        spec.cost_model,
                    )
                    notional = quantity * entry.price
                    entry_cost = transaction_costs(
                        notional, spec.cost_model, requires_fx=asset.currency != "ILS"
                    )
                if quantity <= 0 or notional + entry_cost.total > allocation:
                    skipped += 1
                    continue
                proceeds = quantity * exit_price
                gross_gain = proceeds - notional
                exit_cost = transaction_costs(
                    proceeds,
                    spec.cost_model,
                    requires_fx=asset.currency != "ILS",
                    taxable_gain=gross_gain,
                )
                costs = _sum_costs(entry_cost, exit_cost)
                cash += gross_gain - costs.total
                if cash < 0:
                    raise IntegrityViolation("simulation would require margin")
                path_bars = later[:actual_holding]
                returns = tuple(
                    _return(entry.price, Decimal(bar.effective_close)) for bar in path_bars
                )
                realized = _return(entry.price, exit_price)
                paths.append(
                    PositionPath(
                        asset_id,
                        entry.timestamp,
                        exit_bar.market_timestamp,
                        str(quantity),
                        str(entry.price),
                        str(exit_price),
                        str(max(returns)),
                        str(min(returns)),
                        actual_holding,
                        str(realized),
                        str(realized - benchmark_return),
                        costs,
                    )
                )
                observation_ids.update(
                    (entry.observation_id, *(bar.observation_id for bar in path_bars))
                )
                nav.append((exit_bar.market_timestamp.isoformat(), str(cash)))
        rejection_reasons: tuple[str, ...]
        signal_count = len(signals)
        if not paths and signal_count > 0:
            rejection_reasons = ("all signals skipped",)
        else:
            rejection_reasons = ()
        partitions = self._partitions_for_observations(observation_ids)
        if not partitions:
            raise IntegrityViolation("dataset provenance is missing")
        parameter_hash = (
            "sha256:" + hashlib.sha256(json.dumps(spec.parameter_manifest).encode()).hexdigest()
        )
        manifest = DatasetManifest(
            "market-v0.16",
            tuple(row.sha256 for row in partitions),
            tuple(
                sorted(
                    {
                        bar.parser_version
                        for asset in spec.asset_universe
                        for bar in self.market.get_market_data(
                            asset,
                            spec.evaluation_window.test_start,
                            spec.evaluation_window.test_end,
                            cutoff,
                        )
                    }
                )
            ),
            parameter_hash,
            seed,
            len(observation_ids),
            sum(row.size_bytes for row in partitions),
        )
        gross = sum((Decimal(path.realized_return) for path in paths), Decimal(0))
        costs_total = _sum_costs(*(path.costs for path in paths))
        net = (cash - initial_cash) / initial_cash
        daily = _nav_returns(nav, initial_cash)
        result = BacktestResult(
            spec.experiment_id,
            manifest.manifest_id,
            (
                ("experiment_spec_hash", spec.experiment_id),
                ("code_version_hash", spec.code_version_hash),
                ("parameter_hash", manifest.parameter_hash),
                ("seed", str(manifest.seed)),
                ("parquet_hashes", ",".join(manifest.parquet_hashes)),
                ("source_versions", ",".join(manifest.source_versions)),
            ),
            spec.evaluation_window.test_end,
            spec.evaluation_window.test_end,
            str(gross),
            str(net),
            str(benchmark_return),
            str(net - benchmark_return),
            str(pstdev(daily) if len(daily) > 1 else 0),
            str(_max_drawdown(nav, initial_cash)),
            str(_sharpe(daily)),
            str(_sortino(daily)),
            str(
                sum(Decimal(path.realized_return) > 0 for path in paths) / len(paths)
                if paths
                else 0
            ),
            str(
                sum(Decimal(path.quantity) * Decimal(path.entry_price) for path in paths)
                / initial_cash
            ),
            costs_total,
            len(signals),
            len(paths),
            skipped,
            rejection_reasons,
            tuple(nav),
            tuple(paths),
            0,
            manifest.bytes_read,
        )
        return manifest, result

    def _sessions(
        self, spec: ExperimentSpecification, cutoff: datetime
    ) -> tuple[TradingSession, ...]:
        venues: set[str] = set()
        for asset_id in spec.asset_universe:
            asset = self.market.get_asset_at(asset_id, spec.cutoff)
            if asset is not None:
                venues.add(asset.venue)
        rows = self.session.scalars(
            select(TradingSessionModel).where(
                TradingSessionModel.venue.in_(venues), TradingSessionModel.observed_at <= cutoff
            )
        )
        return tuple(
            TradingSession(
                row.venue,
                row.session_date,
                None if row.opens_at is None else _utc(row.opens_at),
                None if row.closes_at is None else _utc(row.closes_at),
                row.is_trading_day,
                _utc(row.observed_at),
                row.source_id,
                row.parser_version,
            )
            for row in rows
        )

    def _partitions_for_observations(self, ids: set[str]) -> tuple[MarketPartitionModel, ...]:
        hashes = set(
            self.session.scalars(
                select(MarketObservationModel.partition_sha256).where(
                    MarketObservationModel.observation_id.in_(ids)
                )
            )
        )
        return tuple(
            row
            for digest in sorted(hashes)
            if (row := self.session.get(MarketPartitionModel, digest)) is not None
        )


def _bar_for_session(
    observations: tuple[MarketObservation, ...], session: TradingSession
) -> MarketObservation | None:
    assert session.closes_at is not None
    return next(
        (bar for bar in observations if bar.market_timestamp.date() == session.closes_at.date()),
        None,
    )


def _select_exit(
    spec: ExperimentSpecification,
    entry: ExecutionPoint,
    later: tuple[MarketObservation, ...],
    invalidations: tuple[datetime, ...],
) -> tuple[MarketObservation, int] | None:
    if not later:
        return None
    if spec.exit_rule is ExitRule.END_OF_WINDOW:
        return later[-1], len(later)
    if spec.exit_rule is ExitRule.EVENT_INVALIDATION:
        visible = sorted(
            require_aware_utc(value, "invalidation_at")
            for value in invalidations
            if require_aware_utc(value, "invalidation_at") > entry.timestamp
        )
        if not visible:
            raise IntegrityViolation("event invalidation exit lacks an observed invalidation")
        for index, bar in enumerate(later, 1):
            if bar.market_timestamp >= visible[0]:
                return bar, index
        return None
    if spec.exit_rule in {ExitRule.STOP_LOSS, ExitRule.TAKE_PROFIT}:
        parameters = dict(spec.parameter_manifest)
        key = "stop_loss" if spec.exit_rule is ExitRule.STOP_LOSS else "take_profit"
        if key not in parameters:
            raise IntegrityViolation(f"{key} threshold is missing")
        threshold = Decimal(parameters[key])
        if threshold <= 0:
            raise IntegrityViolation(f"{key} threshold must be positive")
        for index, bar in enumerate(later[: spec.holding_period], 1):
            realized = _return(entry.price, Decimal(bar.effective_close))
            if (spec.exit_rule is ExitRule.STOP_LOSS and realized <= -threshold) or (
                spec.exit_rule is ExitRule.TAKE_PROFIT and realized >= threshold
            ):
                return bar, index
    if len(later) < spec.holding_period:
        return None
    return later[spec.holding_period - 1], spec.holding_period


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _return(start: Decimal, end: Decimal) -> Decimal:
    return (end / start) - 1


def _sum_costs(*values: CostBreakdown) -> CostBreakdown:
    names = ("commission", "spread", "slippage", "fx_conversion", "tax")
    totals = (
        sum((Decimal(getattr(value, name)) for value in values), Decimal(0)) for name in names
    )
    return CostBreakdown(*(str(total) for total in totals))


def _nav_returns(nav: list[tuple[str, str]], initial: Decimal) -> list[float]:
    values = [initial, *(Decimal(value) for _, value in nav)]
    return [float(values[index] / values[index - 1] - 1) for index in range(1, len(values))]


def _max_drawdown(nav: list[tuple[str, str]], initial: Decimal) -> Decimal:
    peak = initial
    worst = Decimal(0)
    for _, value in nav:
        current = Decimal(value)
        peak = max(peak, current)
        worst = min(worst, current / peak - 1)
    return worst


def _sharpe(values: list[float]) -> float:
    return (
        0.0
        if len(values) < 2 or pstdev(values) == 0
        else mean(values) / pstdev(values) * math.sqrt(252)
    )


def _sortino(values: list[float]) -> float:
    downside = [value for value in values if value < 0]
    return (
        0.0
        if not downside or pstdev(downside) == 0
        else mean(values) / pstdev(downside) * math.sqrt(252)
    )
