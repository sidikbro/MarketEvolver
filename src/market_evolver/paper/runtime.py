"""Explicit-step paper runtime. It never schedules work or calls a broker/provider."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from decimal import ROUND_DOWN, Decimal

from market_evolver.errors import GovernanceViolation, IntegrityViolation
from market_evolver.experiment.costs import transaction_costs
from market_evolver.experiment.schemas import CostModel, ExperimentStatus
from market_evolver.paper.accounting import apply_fill
from market_evolver.paper.repository import SqlPaperRepository
from market_evolver.paper.risk import evaluate_order
from market_evolver.paper.schemas import (
    ExecutionDecision,
    KillState,
    PaperAccountSnapshot,
    PaperFill,
    PaperOrderCandidate,
    PaperPortfolio,
    PaperSide,
    RiskAction,
    RiskEvaluation,
    RiskPolicy,
    RuntimeMode,
    SignalIntent,
)
from market_evolver.time import require_aware_utc


class PaperRuntime:
    def __init__(
        self,
        repository: SqlPaperRepository,
        policy: RiskPolicy,
        cost_model: CostModel,
        mode: RuntimeMode,
    ):
        self.repository = repository
        self.policy = policy
        self.cost_model = cost_model
        self.mode = mode

    @staticmethod
    def initial_snapshot(portfolio: PaperPortfolio) -> PaperAccountSnapshot:
        return PaperAccountSnapshot(
            portfolio.portfolio_id,
            portfolio.created_at,
            portfolio.initial_cash,
            "0",
            portfolio.initial_cash,
            "0",
            "0",
            "0",
            "0",
            "0",
            "0",
            (),
            (),
            "0",
            portfolio.initial_cash,
            (),
            portfolio.initial_cash,
            KillState.NORMAL,
        )

    def propose(
        self,
        signal: SignalIntent,
        *,
        price: Decimal,
        experiment_status: ExperimentStatus | None,
        fractional: bool,
    ) -> PaperOrderCandidate:
        if signal.strategy_id and experiment_status not in {
            ExperimentStatus.VALIDATED,
            ExperimentStatus.RUNNING,
        }:
            raise GovernanceViolation("only validated experiment signals cross runtime boundary")
        if price <= 0:
            raise IntegrityViolation("impossible execution price")
        notional = Decimal(signal.requested_notional or "0")
        quantity = Decimal(signal.requested_quantity or "0")
        if notional:
            quantity = notional / price
            if not fractional:
                quantity = quantity.quantize(Decimal(1), rounding=ROUND_DOWN)
            notional = quantity * price
        else:
            notional = quantity * price
        candidate = PaperOrderCandidate(
            signal.signal_id,
            signal.portfolio_id,
            signal.asset_id,
            signal.side,
            str(quantity),
            str(notional),
            signal.strategy_id or signal.operator_approval_id or "",
            signal.generated_at,
            signal.intended_session,
            signal.execution_rule,
            signal.provenance,
        )
        self.repository.add_signal(signal)
        self.repository.add_order(candidate)
        return candidate

    def evaluate(
        self,
        signal: SignalIntent,
        candidate: PaperOrderCandidate,
        account: PaperAccountSnapshot,
        *,
        at: datetime,
        market_observed_at: datetime,
        asset_class: str,
        exchange: str,
        sector: str,
        currency: str,
        strategy_valid: bool,
        evidence_valid: bool,
        trades_today: int = 0,
        turnover_today: Decimal = Decimal(0),
    ) -> RiskEvaluation:
        costs = transaction_costs(
            Decimal(candidate.notional), self.cost_model, requires_fx=currency != "ILS"
        )
        result = evaluate_order(
            signal,
            candidate,
            account,
            self.policy,
            evaluated_at=at,
            market_observed_at=market_observed_at,
            asset_class=asset_class,
            exchange=exchange,
            sector=sector,
            currency=currency,
            costs=costs,
            strategy_valid=strategy_valid,
            evidence_valid=evidence_valid,
            trades_today=trades_today,
            turnover_today=turnover_today,
        )
        self.repository.add_evaluation(result)
        return result

    def fill(
        self,
        candidate: PaperOrderCandidate,
        evaluation: RiskEvaluation,
        account: PaperAccountSnapshot,
        *,
        at: datetime,
        price: Decimal,
        market_observation_id: str,
        marks: dict[str, Decimal],
    ) -> tuple[ExecutionDecision, PaperFill | None, PaperAccountSnapshot]:
        at = require_aware_utc(at, "at")
        if evaluation.action not in {RiskAction.APPROVED, RiskAction.RESIZED}:
            decision = ExecutionDecision(
                candidate.candidate_id,
                evaluation.evaluation_id,
                at,
                False,
                evaluation.action.value,
                None,
            )
            self.repository.add_decision(decision)
            return decision, None, account
        quantity = Decimal(evaluation.approved_quantity)
        notional = quantity * price
        costs = transaction_costs(notional, self.cost_model, requires_fx=False)
        debit = notional + costs.total
        if candidate.side is PaperSide.BUY:
            cash_after = Decimal(account.cash) - debit
            old_quantity = next(
                (
                    Decimal(p.quantity)
                    for p in account.positions
                    if p.asset_id == candidate.asset_id
                ),
                Decimal(0),
            )
            position_after = old_quantity + quantity
        else:
            cash_after = Decimal(account.cash) + notional - costs.total
            old_quantity = next(
                (
                    Decimal(p.quantity)
                    for p in account.positions
                    if p.asset_id == candidate.asset_id
                ),
                Decimal(0),
            )
            position_after = old_quantity - quantity
        decision = ExecutionDecision(
            candidate.candidate_id,
            evaluation.evaluation_id,
            at,
            True,
            "risk-approved",
            market_observation_id,
        )
        fill = PaperFill(
            decision.decision_id,
            candidate.portfolio_id,
            candidate.asset_id,
            candidate.side,
            at,
            str(quantity),
            str(price),
            str(
                Decimal(costs.commission)
                + Decimal(costs.spread)
                + Decimal(costs.slippage)
                + Decimal(costs.tax)
            ),
            costs.fx_conversion,
            str(cash_after),
            str(position_after),
            market_observation_id,
        )
        updated = apply_fill(
            replace(account, kill_state=evaluation.resulting_kill_state), fill, at, marks
        )
        self.repository.add_decision(decision)
        self.repository.add_fill(fill)
        self.repository.add_snapshot(updated)
        return decision, fill, updated
