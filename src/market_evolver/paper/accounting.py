from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from market_evolver.errors import IntegrityViolation
from market_evolver.paper.schemas import (
    PaperAccountSnapshot,
    PaperFill,
    PaperPosition,
    PaperSide,
)


def apply_fill(
    snapshot: PaperAccountSnapshot, fill: PaperFill, at: datetime, marks: dict[str, Decimal]
) -> PaperAccountSnapshot:
    positions = {p.asset_id: p for p in snapshot.positions}
    old = positions.get(fill.asset_id)
    old_qty = Decimal(0 if old is None else old.quantity)
    quantity = Decimal(fill.quantity)
    price = Decimal(fill.price)
    costs = Decimal(fill.fees) + Decimal(fill.fx_costs)
    cash = Decimal(snapshot.cash)
    realized = Decimal(snapshot.realized_pnl)
    if fill.side is PaperSide.BUY:
        new_qty = old_qty + quantity
        debit = quantity * price + costs
        cash -= debit
        if cash != Decimal(fill.cash_after):
            raise IntegrityViolation("fill cash reconciliation failed")
        average = (
            (old_qty * Decimal(0 if old is None else old.average_cost)) + quantity * price
        ) / new_qty
    else:
        if quantity > old_qty:
            raise IntegrityViolation("paper sell would create a short position")
        new_qty = old_qty - quantity
        credit = quantity * price - costs
        cash += credit
        if cash != Decimal(fill.cash_after):
            raise IntegrityViolation("fill cash reconciliation failed")
        average = Decimal(0 if old is None else old.average_cost)
        realized += quantity * (price - average) - costs
    if new_qty != Decimal(fill.position_after) or cash < 0:
        raise IntegrityViolation("fill position reconciliation failed")
    if new_qty == 0:
        positions.pop(fill.asset_id, None)
    else:
        positions[fill.asset_id] = PaperPosition(
            fill.asset_id,
            str(new_qty),
            str(average),
            str(marks.get(fill.asset_id, price)),
            "unknown" if old is None else old.sector,
            "unknown" if old is None else old.currency,
        )
    marked = sum(
        Decimal(p.quantity) * marks.get(p.asset_id, Decimal(p.mark_price))
        for p in positions.values()
    )
    nav = cash + marked
    peak = max(Decimal(snapshot.peak_nav), nav)
    drawdown = (peak - nav) / peak if peak else Decimal(0)
    return PaperAccountSnapshot(
        snapshot.portfolio_id,
        at,
        str(cash),
        str(marked),
        str(nav),
        str(realized),
        str(
            nav
            - cash
            - sum(Decimal(p.quantity) * Decimal(p.average_cost) for p in positions.values())
        ),
        str(Decimal(snapshot.transaction_costs) + Decimal(fill.fees)),
        str(Decimal(snapshot.fx_costs) + Decimal(fill.fx_costs)),
        snapshot.tax_estimate,
        str(marked / nav if nav else 0),
        snapshot.sector_exposure,
        snapshot.currency_exposure,
        str(drawdown),
        str(peak),
        tuple(positions.values()),
        snapshot.benchmark_nav,
        snapshot.kill_state,
    )
