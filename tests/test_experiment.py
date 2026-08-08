import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from market_evolver.company.seed import seed_companies
from market_evolver.errors import IntegrityViolation, ValidationError
from market_evolver.experiment.baselines import (
    BASELINES,
    false_rumor_safety_experiment,
    walk_forward_windows,
)
from market_evolver.experiment.costs import affordable_quantity, transaction_costs
from market_evolver.experiment.engine import BacktestEngine, select_execution_point
from market_evolver.experiment.repository import SqlExperimentRepository
from market_evolver.experiment.robustness import robustness_report
from market_evolver.experiment.schemas import (
    SMALL_ACCOUNT_NIS_2000,
    CostModel,
    EntryRule,
    EvaluationWindow,
    ExitRule,
    ExperimentSpecification,
    ExperimentStatus,
    PartitionKind,
    PositionPolicy,
    RebalanceFrequency,
    RuleOperator,
    SignalClause,
    SignalDefinition,
    SignalKind,
    SignalObservation,
)
from market_evolver.experiment.schemas import (
    TestSetAccess as AccessAudit,
)
from market_evolver.knowledge.seed import seed_knowledge_graph
from market_evolver.market.schemas import (
    AdjustmentStatus,
    MarketObservation,
    ObservationType,
    TradingSession,
)
from market_evolver.market.seed import seed_assets
from market_evolver.market.store import MarketDataStore
from market_evolver.storage.models import Base
from market_evolver.storage.telemetry import measure_storage

T0 = datetime(2025, 1, 1, tzinfo=UTC)


def window():
    return EvaluationWindow(
        T0,
        T0 + timedelta(days=1),
        T0 + timedelta(days=2),
        T0 + timedelta(days=3),
        T0 + timedelta(days=4),
        T0 + timedelta(days=9),
    )


def specification(status=ExperimentStatus.VALIDATED, benchmark="asset.index.ta35"):
    return ExperimentSpecification(
        "hypothesis:test",
        T0 + timedelta(days=1),
        T0 + timedelta(days=1),
        "context:test",
        ("asset.xtae.nice",),
        benchmark,
        SignalDefinition(
            (
                SignalClause(
                    SignalKind.CORROBORATION_STATE,
                    "corroboration",
                    RuleOperator.EQ,
                    "officially_confirmed",
                ),
            )
        ),
        EntryRule.NEXT_OPEN,
        ExitRule.FIXED_HOLDING_PERIOD,
        2,
        RebalanceFrequency.EVENT_DRIVEN,
        PositionPolicy.SINGLE_POSITION,
        CostModel(),
        window(),
        ("survivorship_reviewed", "corporate_actions_verified"),
        (("holding_period", "2"),),
        "sha256:" + "c" * 64,
        ("hypothesis:test", "context:test"),
        status,
    )


def signal(at):
    return SignalObservation(
        "asset.xtae.nice",
        at,
        (("corroboration", "officially_confirmed"),),
        ("fusion:claim:test",),
    )


class ExperimentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        seed_knowledge_graph(self.session)
        seed_companies(self.session)
        self.market = MarketDataStore(self.session, Path(self.tmp.name))
        seed_assets(self.session, self.market)
        sessions = []
        observations = []
        for offset in range(4, 10):
            day = T0 + timedelta(days=offset)
            opened = day.replace(hour=8)
            closed = day.replace(hour=16)
            sessions.append(
                TradingSession(
                    "XTAE",
                    day.date().isoformat(),
                    opened,
                    closed,
                    True,
                    T0,
                    "calendar.official",
                    "calendar/1",
                )
            )
            observations.extend(
                (
                    self.bar("asset.xtae.nice", "XTAE", closed, str(100 + offset), "ILS"),
                    self.bar("asset.index.ta35", "XTAE", closed, str(200 + offset), "ILS"),
                )
            )
        for item in sessions:
            self.market.add_session(item)
        self.partition, _, _ = self.market.write_observations(
            tuple(observations),
            dataset_version="experiment-test/1",
            created_at=T0 + timedelta(days=9),
        )
        self.sessions = tuple(sessions)

    def tearDown(self):
        self.session.close()
        self.engine.dispose()
        self.tmp.cleanup()

    def bar(self, asset, venue, at, close, currency):
        value = Decimal(close)
        return MarketObservation(
            asset,
            venue,
            ObservationType.OHLCV,
            at,
            at,
            "market.official",
            AdjustmentStatus.RAW,
            currency,
            "market/1",
            (f"source:{asset}:{at.isoformat()}",),
            str(value - 1),
            str(value + 1),
            str(value - 2),
            str(value),
            "1000",
        )

    def test_signal_dsl_is_typed_and_has_no_eval(self):
        signal = specification().signal_definition
        self.assertTrue(signal.evaluate({"corroboration": "officially_confirmed"}))
        with self.assertRaises(ValidationError):
            SignalClause(SignalKind.EVENT_TYPE, "event", RuleOperator.EQ, "__import__('os')")

    def test_after_hours_and_same_bar_lookahead(self):
        bars = tuple(
            self.market.get_market_data(
                "asset.xtae.nice", window().test_start, window().test_end, window().test_end
            )
        )
        after_close = window().test_start.replace(hour=17)
        point = select_execution_point(after_close, EntryRule.NEXT_OPEN, self.sessions, bars)
        self.assertEqual(point.timestamp.date(), (window().test_start + timedelta(days=1)).date())
        self.assertGreater(point.timestamp, after_close)

    def test_cost_components_minimum_fx_and_fractional_constraints(self):
        costs = transaction_costs(Decimal(2000), SMALL_ACCOUNT_NIS_2000, requires_fx=True)
        self.assertEqual(Decimal(costs.commission), Decimal(10))
        self.assertEqual(Decimal(costs.fx_conversion), Decimal(10))
        self.assertEqual(
            affordable_quantity(Decimal(2000), Decimal(333), SMALL_ACCOUNT_NIS_2000), 6
        )

    def test_deterministic_parquet_duckdb_backtest(self):
        spec = specification()
        observed_signal = signal(window().test_start.replace(hour=7))
        engine = BacktestEngine(self.session, self.market)
        first = engine.run(spec, (observed_signal,), cutoff=window().test_end)
        second = engine.run(spec, (observed_signal,), cutoff=window().test_end)
        self.assertEqual(first, second)
        manifest, result = first
        self.assertEqual(manifest.parquet_hashes, (self.partition.sha256,))
        self.assertEqual(result.executed_trades, 1)
        self.assertEqual(result.position_paths[0].holding_period, 2)
        self.assertGreater(result.parquet_bytes_read, 0)

    def test_backtest_persistence_replay_and_telemetry(self):
        spec = specification()
        repo = SqlExperimentRepository(self.session)
        repo.add_specification(spec)
        manifest, result = BacktestEngine(self.session, self.market).run(
            spec,
            (signal(window().test_start.replace(hour=7)),),
            cutoff=window().test_end,
        )
        repo.add_dataset(manifest)
        repo.add_result(result)
        repo.add_test_access(
            AccessAudit(
                spec.experiment_id,
                PartitionKind.TEST,
                window().test_end,
                "test",
                "fixture",
            )
        )
        self.session.flush()
        self.assertEqual(repo.result(result.result_id), result)
        telemetry = measure_storage(self.session)
        self.assertEqual(telemetry.trades_simulated, 1)
        self.assertEqual(telemetry.test_set_accesses, 1)
        self.assertEqual(telemetry.backtest_parquet_bytes_read, manifest.bytes_read)

    def test_missing_prices_benchmark_and_governance_fail_closed(self):
        engine = BacktestEngine(self.session, self.market)
        observed_signal = signal(window().test_start.replace(hour=7))
        with self.assertRaises(IntegrityViolation):
            engine.run(
                specification(benchmark="asset.arcx.spy"),
                (observed_signal,),
                cutoff=window().test_end,
            )
        with self.assertRaises(IntegrityViolation):
            engine.run(
                replace(specification(), exclusion_rules=("survivorship_reviewed",)),
                (observed_signal,),
                cutoff=window().test_end,
            )
        with self.assertRaises(IntegrityViolation):
            engine.run(
                specification(status=ExperimentStatus.PROPOSED),
                (observed_signal,),
                cutoff=window().test_end,
            )

    def test_future_evidence_signal_and_test_modification_fail_closed(self):
        spec = specification(status=ExperimentStatus.PROPOSED)
        repo = SqlExperimentRepository(self.session)
        repo.add_specification(spec)
        repo.add_test_access(
            AccessAudit(
                spec.experiment_id,
                PartitionKind.TEST,
                window().test_end,
                "final evaluation",
                "tester",
            )
        )
        revised = replace(
            spec, created_at=window().test_end, version=2, revision_of=spec.experiment_id
        )
        with self.assertRaises(IntegrityViolation):
            repo.add_specification(revised)
        with self.assertRaises(IntegrityViolation):
            BacktestEngine(self.session, self.market).run(
                specification(),
                (signal(window().test_end + timedelta(days=1)),),
                cutoff=window().test_end,
            )

    def test_robustness_walkforward_baselines_and_false_rumor(self):
        first = robustness_report((0.1, -0.05, 0.02), (("holding=2", 0.03),), seed=7)
        second = robustness_report((0.1, -0.05, 0.02), (("holding=2", 0.03),), seed=7)
        self.assertEqual(first, second)
        self.assertEqual(len(BASELINES), 7)
        self.assertEqual(len(walk_forward_windows(tuple(str(i) for i in range(10)), 3, 2, 1)), 5)
        rumor = false_rumor_safety_experiment()
        self.assertEqual(
            tuple(item.mode for item in rumor),
            (
                "first_social_rumor",
                "independent_corroboration",
                "official_confirmation",
                "no_trade",
            ),
        )
        self.assertGreater(rumor[0].false_positive_exposure, rumor[2].false_positive_exposure)

    def test_large_synthetic_parquet_history_is_exact(self):
        observations = tuple(
            self.bar(
                "asset.arcx.spy",
                "ARCX",
                T0 + timedelta(days=20 + index),
                str(300 + index),
                "USD",
            )
            for index in range(250)
        )
        partition, inserted, _ = self.market.write_observations(
            observations,
            dataset_version="large-synthetic/1",
            created_at=T0 + timedelta(days=270),
        )
        restored = self.market.get_market_data(
            "asset.arcx.spy",
            observations[0].market_timestamp,
            observations[-1].market_timestamp,
            T0 + timedelta(days=270),
        )
        self.assertEqual((inserted, len(restored), partition.row_count), (250, 250, 250))


if __name__ == "__main__":
    unittest.main()
