from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from statistics import pstdev

from market_evolver.paper.schemas import PaperAccountSnapshot, RiskAction, RiskEvaluation


@dataclass(frozen=True, slots=True)
class PaperPerformance:
    gross_return: str
    net_return: str
    benchmark_return: str | None
    excess_return: str | None
    volatility: str
    max_drawdown: str
    turnover: str
    transaction_costs: str
    cost_nav: str
    hit_rate: str
    average_holding_days: str
    rejected_order_rate: str
    risk_resize_rate: str


def performance(
    snapshots: tuple[PaperAccountSnapshot, ...],
    evaluations: tuple[RiskEvaluation, ...],
    turnover: Decimal = Decimal(0),
    winning_fills: int = 0,
    closed_fills: int = 0,
    holding_days: tuple[int, ...] = (),
) -> PaperPerformance:
    if not snapshots:
        raise ValueError("performance requires account snapshots")
    first, last = snapshots[0], snapshots[-1]
    initial = Decimal(first.nav)
    final = Decimal(last.nav)
    costs = Decimal(last.transaction_costs) + Decimal(last.fx_costs)
    net = final / initial - 1
    gross = (final + costs) / initial - 1
    returns = [
        Decimal(snapshots[i].nav) / Decimal(snapshots[i - 1].nav) - 1
        for i in range(1, len(snapshots))
    ]
    benchmark = None
    if first.benchmark_nav is not None and last.benchmark_nav is not None:
        benchmark = Decimal(last.benchmark_nav) / Decimal(first.benchmark_nav) - 1
    total = len(evaluations)
    rejected = sum(
        e.action in {RiskAction.REJECTED, RiskAction.PORTFOLIO_HALTED} for e in evaluations
    )
    resized = sum(e.action is RiskAction.RESIZED for e in evaluations)
    return PaperPerformance(
        str(gross),
        str(net),
        None if benchmark is None else str(benchmark),
        None if benchmark is None else str(net - benchmark),
        str(pstdev(float(value) for value in returns) if len(returns) > 1 else 0),
        str(max(Decimal(item.drawdown) for item in snapshots)),
        str(turnover),
        str(costs),
        str(costs / final if final else 0),
        str(Decimal(winning_fills) / closed_fills if closed_fills else 0),
        str(sum(holding_days) / len(holding_days) if holding_days else 0),
        str(Decimal(rejected) / total if total else 0),
        str(Decimal(resized) / total if total else 0),
    )
