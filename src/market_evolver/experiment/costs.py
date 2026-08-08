from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from market_evolver.experiment.schemas import CostBreakdown, CostModel

BPS = Decimal(10000)


def transaction_costs(
    notional: Decimal,
    model: CostModel,
    *,
    requires_fx: bool,
    taxable_gain: Decimal = Decimal(0),
) -> CostBreakdown:
    commission = max(notional * Decimal(model.commission_rate), Decimal(model.minimum_commission))
    spread = notional * Decimal(model.spread_bps) / BPS
    slippage = notional * Decimal(model.slippage_bps) / BPS
    fx = notional * Decimal(model.fx_conversion_bps) / BPS if requires_fx else Decimal(0)
    tax = max(taxable_gain, Decimal(0)) * Decimal(model.tax_rate)
    return CostBreakdown(*(_fmt(value) for value in (commission, spread, slippage, fx, tax)))


def affordable_quantity(cash: Decimal, price: Decimal, model: CostModel) -> Decimal:
    if cash <= 0 or price <= 0:
        return Decimal(0)
    raw = cash / price
    return raw if model.fractional_shares else raw.quantize(Decimal(1), rounding=ROUND_DOWN)


def _fmt(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.000001")), "f")
