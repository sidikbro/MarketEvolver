import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from market_evolver.errors import ImmutableRecordError, IntegrityViolation, ValidationError
from market_evolver.experiment.schemas import CostBreakdown
from market_evolver.paper.accounting import apply_fill
from market_evolver.paper.nav_store import NavHistoryStore
from market_evolver.paper.performance import performance
from market_evolver.paper.policy import NIS_2000_POLICY
from market_evolver.paper.repository import SqlPaperRepository
from market_evolver.paper.risk import evaluate_order
from market_evolver.paper.schemas import (
    AllocationPolicy,
    AuditRecord,
    ExecutionDecision,
    KillState,
    PaperAccountSnapshot,
    PaperFill,
    PaperOrderCandidate,
    PaperPortfolio,
    PaperSide,
    PortfolioStatus,
    RiskAction,
    SignalIntent,
)
from market_evolver.storage.models import Base, PaperSignalModel

T0 = datetime(2025, 1, 2, 10, tzinfo=UTC)


def account(**changes):
    item = PaperAccountSnapshot(
        "paper:test",
        T0,
        "2000",
        "0",
        "2000",
        "0",
        "0",
        "0",
        "0",
        "0",
        "0",
        (),
        (),
        "0",
        "2000",
        (),
        "2000",
        KillState.NORMAL,
    )
    return replace(item, **changes)


def signal(**changes):
    item = SignalIntent(
        "paper:test",
        "asset.xtae.nice",
        PaperSide.BUY,
        T0,
        "2025-01-03",
        "next_open",
        "experiment:validated",
        None,
        None,
        "300",
        ("evidence:1", "evidence:2"),
        2,
        T0 - timedelta(hours=1),
        ("experiment:validated", "evidence:1"),
    )
    return replace(item, **changes)


def candidate(item=None, notional="300", quantity="3"):
    item = item or signal()
    return PaperOrderCandidate(
        item.signal_id,
        item.portfolio_id,
        item.asset_id,
        item.side,
        quantity,
        notional,
        item.strategy_id or item.operator_approval_id or "",
        item.generated_at,
        item.intended_session,
        item.execution_rule,
        item.provenance,
    )


def evaluate(item=None, acct=None, **kwargs):
    item = item or signal()
    order = candidate(item)
    defaults = {
        "evaluated_at": T0,
        "market_observed_at": T0,
        "asset_class": "equity",
        "exchange": "XTAE",
        "sector": "technology",
        "currency": "ILS",
        "costs": CostBreakdown("1", "1", "0", "0", "0"),
        "strategy_valid": True,
        "evidence_valid": True,
    }
    defaults.update(kwargs)
    return evaluate_order(item, order, acct or account(), NIS_2000_POLICY, **defaults)


class PaperSafetyTests(unittest.TestCase):
    def test_small_account_policy_is_conservative(self):
        self.assertEqual(NIS_2000_POLICY.max_order_notional, "400")
        self.assertEqual(NIS_2000_POLICY.min_cash_reserve, "0.30")
        self.assertNotIn("derivative", NIS_2000_POLICY.allowed_asset_classes)

    def test_model_generated_direct_order_is_rejected(self):
        with self.assertRaises(ValidationError):
            signal(strategy_id="llm:gpt")

    def test_stale_market_and_revoked_strategy(self):
        self.assertEqual(
            evaluate(market_observed_at=T0 - timedelta(days=2)).reason_codes, ("STALE_DATA",)
        )
        self.assertEqual(evaluate(strategy_valid=False).reason_codes, ("UNAPPROVED_STRATEGY",))

    def test_invalidated_evidence_and_causal_ordering(self):
        self.assertEqual(evaluate(evidence_valid=False).reason_codes, ("EVIDENCE_REQUIREMENT",))
        self.assertEqual(
            evaluate(market_observed_at=T0 + timedelta(seconds=1)).action,
            RiskAction.PORTFOLIO_HALTED,
        )

    def test_order_flood_and_sector_concentration(self):
        self.assertEqual(evaluate(trades_today=3).reason_codes, ("MAX_TRADES",))
        concentrated = replace(account(), sector_exposure=(("technology", "0.34"),))
        result = evaluate(acct=concentrated, costs=CostBreakdown("0", "0", "0", "0", "0"))
        self.assertEqual(result.action, RiskAction.RESIZED)
        self.assertIn("SECTOR_LIMIT", result.reason_codes)

    def test_cash_exhaustion_and_cost_governor(self):
        low_cash = replace(account(), cash="610", market_value="1390", gross_exposure="0.695")
        self.assertIn(evaluate(acct=low_cash).action, {RiskAction.REJECTED, RiskAction.RESIZED})
        result = evaluate(costs=CostBreakdown("20", "10", "0", "0", "0"))
        self.assertEqual(result.action, RiskAction.REJECTED)
        self.assertIn("COST_TOO_LARGE", result.reason_codes)

    def test_drawdown_restricts_then_halts(self):
        restricted = evaluate(acct=replace(account(), drawdown="0.07"))
        self.assertEqual(restricted.resulting_kill_state, KillState.ENTRY_RESTRICTED)
        self.assertEqual(restricted.action, RiskAction.REJECTED)
        halted = evaluate(acct=replace(account(), drawdown="0.13"))
        self.assertEqual(halted.action, RiskAction.PORTFOLIO_HALTED)

    def test_sell_cannot_create_short(self):
        sell = signal(side=PaperSide.SELL_EXISTING_POSITION)
        self.assertIn("NO_EXISTING_POSITION", evaluate(sell).reason_codes)

    def test_corrupted_nav_fails_at_boundary(self):
        with self.assertRaises(ValidationError):
            replace(account(), nav="1999")

    def test_fill_reconciliation_and_gap_down(self):
        decision = ExecutionDecision("candidate", "evaluation", T0, True, "approved", "bar:1")
        fill = PaperFill(
            decision.decision_id,
            "paper:test",
            "asset.xtae.nice",
            PaperSide.BUY,
            T0,
            "3",
            "100",
            "2",
            "0",
            "1698",
            "3",
            "bar:1",
        )
        updated = apply_fill(
            account(), fill, T0 + timedelta(seconds=1), {"asset.xtae.nice": Decimal(50)}
        )
        self.assertEqual(Decimal(updated.nav), Decimal(1848))
        self.assertGreater(Decimal(updated.drawdown), 0)
        with self.assertRaises(IntegrityViolation):
            apply_fill(account(), replace(fill, cash_after="1700"), T0 + timedelta(seconds=1), {})

    def test_duplicate_signal_and_repository_append_only(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            repo = SqlPaperRepository(session)
            item = signal()
            self.assertTrue(repo.add_signal(item))
            session.flush()
            self.assertFalse(repo.add_signal(item))
            row = session.get(PaperSignalModel, item.signal_id)
            assert row is not None
            row.payload = {"mutated": True}
            with self.assertRaises(ImmutableRecordError):
                session.flush()
        engine.dispose()

    def test_portfolio_configuration_freezes_after_activation(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            repo = SqlPaperRepository(session)
            portfolio = PaperPortfolio(
                "paper:test",
                "Test",
                "ILS",
                "2000",
                T0,
                ("experiment:validated",),
                (),
                "asset.index.ta35",
                AllocationPolicy.FIXED_NOTIONAL,
                NIS_2000_POLICY.policy_id,
                "next-open-v1",
            )
            repo.add_portfolio(portfolio)
            audit = AuditRecord("paper:test", T0 + timedelta(seconds=1), "start", "operator", ())
            repo.transition("paper:test", PortfolioStatus.ACTIVE, audit)
            session.flush()
            with self.assertRaises(IntegrityViolation):
                repo.add_portfolio(
                    replace(portfolio, version=3, revision_of="paper:test:v2", initial_cash="2500")
                )
        engine.dispose()

    def test_orm_fill_is_immutable(self):
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            row = PaperSignalModel(signal_id="s", portfolio_id="p", generated_at=T0, payload={})
            session.add(row)
            session.flush()
            row.payload = {"changed": True}
            with self.assertRaises(ImmutableRecordError):
                session.flush()
        engine.dispose()

    def test_duckdb_parquet_nav_history_is_derived_and_immutable(self):
        with tempfile.TemporaryDirectory() as directory:
            store = NavHistoryStore(Path(directory))
            snapshots = (
                account(),
                replace(
                    account(),
                    timestamp=T0 + timedelta(days=1),
                    cash="1900",
                    market_value="90",
                    nav="1990",
                    drawdown="0.005",
                ),
            )
            path = store.export("paper-test", snapshots)
            self.assertEqual(store.rows(path), 2)
            self.assertEqual(len(store.sha256(path)), 64)
            with self.assertRaises(FileExistsError):
                store.export("paper-test", snapshots)

    def test_deterministic_performance_and_benchmark(self):
        snapshots = (
            account(),
            replace(
                account(),
                timestamp=T0 + timedelta(days=1),
                cash="2100",
                nav="2100",
                peak_nav="2100",
                benchmark_nav="2040",
            ),
        )
        metrics = performance(snapshots, (evaluate(),), turnover=Decimal("0.15"))
        self.assertEqual(Decimal(metrics.net_return), Decimal("0.05"))
        self.assertEqual(Decimal(metrics.benchmark_return or "0"), Decimal("0.02"))


if __name__ == "__main__":
    unittest.main()
