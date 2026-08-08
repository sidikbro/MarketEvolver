"""Pure deterministic order admission; this module deliberately has no model providers."""

from __future__ import annotations

from datetime import datetime
from decimal import ROUND_DOWN, Decimal

from market_evolver.experiment.schemas import CostBreakdown
from market_evolver.paper.schemas import (
    KillState,
    PaperAccountSnapshot,
    PaperOrderCandidate,
    PaperSide,
    RiskAction,
    RiskAttribution,
    RiskEvaluation,
    RiskPolicy,
    SignalIntent,
)
from market_evolver.time import require_aware_utc


def evaluate_order(
    signal: SignalIntent,
    candidate: PaperOrderCandidate,
    account: PaperAccountSnapshot,
    policy: RiskPolicy,
    *,
    evaluated_at: datetime,
    market_observed_at: datetime,
    asset_class: str,
    exchange: str,
    sector: str,
    currency: str,
    costs: CostBreakdown,
    strategy_valid: bool,
    evidence_valid: bool,
    trades_today: int = 0,
    turnover_today: Decimal = Decimal(0),
    rejected_actions: int = 0,
) -> RiskEvaluation:
    now = require_aware_utc(evaluated_at, "evaluated_at")
    observed = require_aware_utc(market_observed_at, "market_observed_at")
    nav = Decimal(account.nav)
    requested = Decimal(candidate.notional)
    quantity = Decimal(candidate.quantity)
    expected_cost = costs.total
    reasons: list[str] = []
    attrs: list[RiskAttribution] = []
    state = account.kill_state

    hard_failure: str | None = None
    if nav <= 0 or Decimal(account.cash) < 0:
        hard_failure = "ACCOUNTING_INVARIANT"
    elif observed > now or now < signal.generated_at:
        hard_failure = "CAUSAL_ORDERING"
    elif now.timestamp() - observed.timestamp() > policy.max_stale_seconds:
        reasons.append("STALE_DATA")
    elif not strategy_valid:
        reasons.append("UNAPPROVED_STRATEGY")
    elif not evidence_valid or signal.corroboration_count < policy.min_corroboration:
        reasons.append("EVIDENCE_REQUIREMENT")
    elif (
        asset_class not in policy.allowed_asset_classes or exchange not in policy.allowed_exchanges
    ):
        reasons.append("UNAPPROVED_ASSET")
    elif account.kill_state in {KillState.PAUSED, KillState.HALTED}:
        reasons.append("PORTFOLIO_STATE")
    elif account.kill_state is KillState.ENTRY_RESTRICTED and signal.side is PaperSide.BUY:
        reasons.append("ENTRY_RESTRICTED")
    if rejected_actions >= 10:
        hard_failure = "EXCESSIVE_REJECTIONS"
    if hard_failure:
        return _result(
            candidate,
            now,
            RiskAction.PORTFOLIO_HALTED,
            (hard_failure,),
            Decimal(0),
            Decimal(0),
            expected_cost,
            nav,
            (),
            KillState.HALTED,
        )
    if reasons:
        return _result(
            candidate,
            now,
            RiskAction.REJECTED,
            tuple(reasons),
            Decimal(0),
            Decimal(0),
            expected_cost,
            nav,
            (),
            state,
        )

    if trades_today >= policy.max_trades_per_day:
        reasons.append("MAX_TRADES")
    if signal.side is PaperSide.SELL_EXISTING_POSITION:
        held = next(
            (Decimal(p.quantity) for p in account.positions if p.asset_id == signal.asset_id),
            Decimal(0),
        )
        if held <= 0:
            reasons.append("NO_EXISTING_POSITION")
        elif quantity > held:
            quantity = held
            requested = quantity * (Decimal(candidate.notional) / Decimal(candidate.quantity))
            reasons.append("NO_SHORT_SELLING")
    else:
        if len(account.positions) >= policy.max_concurrent_positions and not any(
            p.asset_id == signal.asset_id for p in account.positions
        ):
            reasons.append("MAX_POSITIONS")
        caps = {
            "ORDER_LIMIT": Decimal(policy.max_order_notional),
            "POSITION_LIMIT": nav * Decimal(policy.max_position_weight),
            "GROSS_EXPOSURE": nav * Decimal(policy.max_gross_exposure)
            - Decimal(account.market_value),
            "CASH_RESERVE": Decimal(account.cash)
            - nav * Decimal(policy.min_cash_reserve)
            - expected_cost,
            "DAILY_TURNOVER": nav * Decimal(policy.max_daily_turnover) - turnover_today,
        }
        current_sector = Decimal(dict(account.sector_exposure).get(sector, "0")) * nav
        current_currency = Decimal(dict(account.currency_exposure).get(currency, "0")) * nav
        caps["SECTOR_LIMIT"] = nav * Decimal(policy.max_sector_exposure) - current_sector
        caps["CURRENCY_LIMIT"] = nav * Decimal(policy.max_currency_exposure) - current_currency
        limiting, allowed = min(caps.items(), key=lambda pair: pair[1])
        if allowed < requested:
            attrs.append(
                RiskAttribution(
                    limiting,
                    "0",
                    str(requested),
                    str(max(allowed, 0)),
                    RiskAction.RESIZED if allowed > 0 else RiskAction.REJECTED,
                )
            )
            reasons.append(limiting)
            if allowed > 0:
                ratio = allowed / requested
                requested = allowed
                quantity = (quantity * ratio).quantize(Decimal("0.000001"), rounding=ROUND_DOWN)
            else:
                quantity = requested = Decimal(0)
    cost_order = expected_cost / requested if requested > 0 else Decimal("Infinity")
    cost_nav = expected_cost / nav if nav > 0 else Decimal("Infinity")
    if cost_order > Decimal(policy.max_cost_order_ratio) or cost_nav > Decimal(
        policy.max_cost_nav_ratio
    ):
        reasons.append("COST_TOO_LARGE")
        quantity = requested = Decimal(0)
    if Decimal(account.drawdown) >= Decimal(policy.max_portfolio_drawdown):
        return _result(
            candidate,
            now,
            RiskAction.PORTFOLIO_HALTED,
            ("DRAWDOWN_LIMIT",),
            Decimal(0),
            Decimal(0),
            expected_cost,
            nav,
            tuple(attrs),
            KillState.HALTED,
        )
    if Decimal(account.drawdown) >= Decimal(policy.entry_restricted_drawdown):
        state = KillState.ENTRY_RESTRICTED
        if signal.side is PaperSide.BUY:
            reasons.append("DRAWDOWN_ENTRY_RESTRICTED")
            quantity = requested = Decimal(0)
    action = (
        RiskAction.REJECTED
        if requested <= 0
        else RiskAction.RESIZED
        if reasons
        else RiskAction.APPROVED
    )
    return _result(
        candidate,
        now,
        action,
        tuple(dict.fromkeys(reasons)),
        quantity,
        requested,
        expected_cost,
        nav,
        tuple(attrs),
        state,
    )


def _result(
    candidate: PaperOrderCandidate,
    at: datetime,
    action: RiskAction,
    reasons: tuple[str, ...],
    quantity: Decimal,
    notional: Decimal,
    cost: Decimal,
    nav: Decimal,
    attrs: tuple[RiskAttribution, ...],
    state: KillState,
) -> RiskEvaluation:
    order_ratio = cost / notional if notional > 0 else Decimal(0)
    nav_ratio = cost / nav if nav > 0 else Decimal(0)
    return RiskEvaluation(
        candidate.candidate_id,
        candidate.portfolio_id,
        at,
        action,
        reasons,
        str(quantity),
        str(notional),
        str(cost),
        str(order_ratio),
        str(nav_ratio),
        attrs,
        state,
    )
