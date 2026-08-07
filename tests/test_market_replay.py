import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from market_evolver.company.seed import seed_companies
from market_evolver.errors import ImmutableRecordError, IntegrityViolation
from market_evolver.knowledge.seed import seed_knowledge_graph
from market_evolver.market.schemas import (
    AdjustmentStatus,
    CorporateAction,
    CorporateActionType,
    MarketObservation,
    ObservationType,
)
from market_evolver.market.seed import seed_assets
from market_evolver.market.store import MarketDataStore
from market_evolver.replay.audit import audit_snapshot
from market_evolver.replay.benchmark import BenchmarkRunner, baseline_research, curated_cases
from market_evolver.replay.engine import ReplayClock, ReplayEngine
from market_evolver.replay.repositories import SqlReplayRepository
from market_evolver.replay.schemas import (
    ReplayCase,
    ReplayCaseType,
    ReplayRun,
    ReplayStepMode,
    ResearchCommitment,
    ResearchMode,
)
from market_evolver.storage.models import Base, BenchmarkPairModel, ReplayCommitmentModel
from market_evolver.storage.telemetry import measure_storage

T0 = datetime(2025, 1, 1, 16, tzinfo=UTC)
T1 = T0 + timedelta(days=1)
T2 = T1 + timedelta(days=1)
T3 = T2 + timedelta(days=1)
T4 = T3 + timedelta(days=1)


class MarketReplayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        seed_knowledge_graph(self.session)
        seed_companies(self.session)
        self.store = MarketDataStore(self.session, Path(self.temporary.name))
        self.assertEqual(seed_assets(self.session, self.store), 18)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()
        self.temporary.cleanup()

    def observation(
        self,
        market_at: datetime,
        observed_at: datetime,
        close: str,
        *,
        asset_id: str = "asset.xtae.nice",
        status: AdjustmentStatus = AdjustmentStatus.RAW,
    ) -> MarketObservation:
        value = float(close)
        return MarketObservation(
            asset_id,
            "XTAE" if "xtae" in asset_id else "ARCX",
            ObservationType.OHLCV,
            market_at,
            observed_at,
            "test.official.market",
            status,
            "ILS" if "xtae" in asset_id else "USD",
            "test-market/1",
            (f"source:{market_at.isoformat()}:{observed_at.isoformat()}:{asset_id}",),
            f"{value - 1:g}",
            f"{value + 1:g}",
            f"{value - 2:g}",
            close,
            "1000",
        )

    def test_parquet_duckdb_round_trip_cutoff_and_revisions(self) -> None:
        original = self.observation(T1, T1 + timedelta(hours=1), "100")
        revised = self.observation(T1, T3, "101")
        partition, inserted, duplicates = self.store.write_observations(
            (original, revised), dataset_version="test/1", created_at=T3
        )
        self.assertEqual((inserted, duplicates, partition.row_count), (2, 0, 2))
        before = self.store.get_market_data("asset.xtae.nice", T1, T1, T2)
        after = self.store.get_market_data("asset.xtae.nice", T1, T1, T4)
        self.assertEqual(before, [original])
        self.assertEqual(after, [revised])
        self.assertGreater((Path(self.temporary.name) / partition.relative_path).stat().st_size, 0)
        telemetry = measure_storage(self.session)
        self.assertEqual(telemetry.market_assets, 18)
        self.assertEqual(sum(item.value for item in telemetry.market_rows_by_day), 2)
        self.assertEqual(telemetry.parquet_bytes_by_day[0].value, partition.size_bytes)
        _, inserted_again, duplicates_again = self.store.write_observations(
            (original, revised), dataset_version="test/1", created_at=T3
        )
        self.assertEqual((inserted_again, duplicates_again), (0, 2))

    def test_raw_and_adjusted_are_separate_and_raw_is_retained(self) -> None:
        raw = self.observation(T1, T1, "100")
        adjusted = self.observation(T1, T1, "50", status=AdjustmentStatus.ADJUSTED)
        self.store.write_observations((raw, adjusted), dataset_version="test/1")
        self.assertEqual(self.store.get_market_data("asset.xtae.nice", T1, T1, T2), [raw])
        self.assertEqual(
            self.store.get_market_data(
                "asset.xtae.nice", T1, T1, T2, adjustment_status=AdjustmentStatus.ADJUSTED
            ),
            [adjusted],
        )

    def test_corporate_action_is_point_in_time(self) -> None:
        action = CorporateAction(
            "asset.xtae.nice",
            CorporateActionType.DIVIDEND,
            T3,
            T1,
            T2,
            "test.exchange",
            ("evidence:dividend",),
            "1.25",
            "ILS",
        )
        self.store.add_corporate_action(action)
        self.assertEqual(self.store.corporate_actions("asset.xtae.nice", T1), [])
        self.assertEqual(self.store.corporate_actions("asset.xtae.nice", T2), [action])

    def replay_case(self) -> ReplayCase:
        return ReplayCase(
            ReplayCaseType.COMPANY_FILING,
            ("company.nice",),
            ("asset.xtae.nice",),
            T2,
            "2 days",
            "manifest:test",
            "asset.arcx.spy",
            "research-hypothesis/v1",
            "forward-market-outcome/1",
            "test/1",
            T2,
        )

    def commitment(self, case: ReplayCase) -> ResearchCommitment:
        return ResearchCommitment(
            case.case_id,
            case.cutoff,
            "snapshot:test",
            "hypothesis:test",
            case.horizon,
            "Close changes over the horizon.",
            "Close does not change.",
            0.5,
            "reviewed",
            ResearchMode.EVENT_RULES,
            T2,
        )

    def test_replay_clock_requires_immutable_commitment_and_snapshot_has_no_future_price(
        self,
    ) -> None:
        original = self.observation(T1, T1, "100")
        future = self.observation(T3, T3, "105")
        self.store.write_observations((original, future), dataset_version="test/1")
        case = self.replay_case()
        repository = SqlReplayRepository(self.session)
        repository.add_case(case)
        replay = ReplayEngine(self.session, self.store)
        snapshot = replay.snapshot(case)
        self.assertEqual(snapshot.market_observation_ids, (original.observation_id,))
        self.assertTrue(audit_snapshot(case, snapshot).passed)
        commitment = self.commitment(case)
        replay.commit(commitment)
        clock = ReplayClock(T2, ReplayStepMode.DAILY)
        self.assertEqual(clock.advance(commitment), T3)
        model = self.session.get(ReplayCommitmentModel, commitment.commitment_id)
        assert model is not None
        model.confidence = 0.9
        with self.assertRaises(ImmutableRecordError):
            self.session.flush()

    def test_outcome_evaluation_is_deterministic_and_not_profit(self) -> None:
        observations = (
            self.observation(T1, T1, "100"),
            self.observation(T2, T2, "102"),
            self.observation(T3, T3, "99"),
            self.observation(T4, T4, "110"),
        )
        benchmark = (
            self.observation(T1, T1, "200", asset_id="asset.arcx.spy"),
            self.observation(T2, T2, "202", asset_id="asset.arcx.spy"),
            self.observation(T3, T3, "204", asset_id="asset.arcx.spy"),
            self.observation(T4, T4, "206", asset_id="asset.arcx.spy"),
        )
        self.store.write_observations((*observations, *benchmark), dataset_version="test/1")
        case = self.replay_case()
        repository = SqlReplayRepository(self.session)
        repository.add_case(case)
        commitment = self.commitment(case)
        replay = ReplayEngine(self.session, self.store)
        replay.commit(commitment)
        run = ReplayRun(case.case_id, commitment.commitment_id, True, T2, T2, 0, "committed")
        replay.record_run(run)
        outcome = replay.evaluate(run, horizon_end=T4, evaluated_at=T4, direction_requested=True)
        self.assertEqual(outcome.forward_return, "0.078431372549")
        self.assertEqual(outcome.benchmark_relative_return, "0.058629392351")
        self.assertEqual(outcome.direction, "up")
        self.assertFalse(hasattr(outcome, "profit"))
        with self.assertRaises(IntegrityViolation):
            replay.evaluate(run, horizon_end=T4, evaluated_at=T3)

    def test_curated_benchmark_has_seven_diverse_cases_and_all_modes(self) -> None:
        cases = curated_cases()
        self.assertEqual(len(cases), 7)
        self.assertEqual({item.case_type for item in cases}, set(ReplayCaseType))
        self.assertEqual(len(ResearchMode), 7)
        self.assertIn(
            "Trailing market change",
            baseline_research(ResearchMode.MOMENTUM, trailing_values=(100.0, 105.0))[0],
        )
        runner = BenchmarkRunner(self.session, ReplayEngine(self.session, self.store))
        self.assertEqual(runner.seed_cases(), 7)
        runs = runner.run_all(T4)
        self.assertEqual(len(runs), 98)
        self.assertEqual(
            self.session.scalar(select(func.count()).select_from(BenchmarkPairModel)), 49
        )
        telemetry = measure_storage(self.session)
        self.assertEqual(telemetry.replay_cases, 7)


if __name__ == "__main__":
    unittest.main()
