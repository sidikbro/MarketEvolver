import tempfile
import unittest
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from market_evolver.errors import ImmutableRecordError, IntegrityViolation, ValidationError
from market_evolver.ingestion.schemas import NormalizedObservation
from market_evolver.macro.connectors import boi_fx_macro_observation
from market_evolver.macro.repository import SqlMacroRepository
from market_evolver.macro.schemas import (
    ExpectationStatus,
    MacroCategory,
    MacroObservation,
    SeasonalAdjustment,
    TrendDivergence,
    TrendHorizon,
    TrendState,
)
from market_evolver.macro.seed import STRUCTURAL_TREND_NAMES
from market_evolver.macro.trends import calculate_trend
from market_evolver.market.store import MarketDataStore
from market_evolver.replay.engine import ReplayEngine
from market_evolver.replay.schemas import ReplayCase, ReplayCaseType
from market_evolver.sources.registry import DEFAULT_REGISTRY
from market_evolver.storage.models import Base, MacroObservationModel
from market_evolver.storage.telemetry import measure_storage

T0 = datetime(2025, 1, 1, tzinfo=UTC)


class MacroLabTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.repo = SqlMacroRepository(self.session)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def observation(
        self,
        period: str,
        value: str,
        observed: datetime,
        *,
        revision_of: str | None = None,
        adjustment: SeasonalAdjustment = SeasonalAdjustment.UNADJUSTED,
        expected: str | None = None,
    ) -> MacroObservation:
        return MacroObservation(
            "il.cpi.headline",
            "il.cbs",
            "IL",
            MacroCategory.INFLATION,
            period,
            value,
            "index",
            observed - timedelta(hours=1),
            observed,
            revision_of,
            adjustment,
            (f"source:{period}:{observed.isoformat()}:{adjustment.value}",),
            "test/1",
            "Consumer Price Index",
            "מדד המחירים לצרכן",
            None,
            expected,
            None if expected is None else "expectation:test",
            None if expected is None else observed - timedelta(hours=2),
        )

    def test_revision_history_and_future_revision_do_not_leak(self) -> None:
        original = self.observation("2025-01", "100", T0 + timedelta(days=1))
        revised = self.observation(
            "2025-01", "101", T0 + timedelta(days=2), revision_of=original.observation_id
        )
        self.assertTrue(self.repo.add_observation(original))
        self.assertTrue(self.repo.add_observation(revised))
        self.assertEqual(
            self.repo.observations_visible_at("il.cpi.headline", T0 + timedelta(days=1))[0],
            original,
        )
        self.assertEqual(
            self.repo.observations_visible_at("il.cpi.headline", T0 + timedelta(days=3))[0],
            revised,
        )
        self.assertIsNotNone(self.session.get(MacroObservationModel, original.observation_id))

    def test_revision_identity_and_causal_order_are_enforced(self) -> None:
        original = self.observation("2025-01", "100", T0 + timedelta(days=2))
        self.repo.add_observation(original)
        invalid = self.observation(
            "2025-02", "101", T0 + timedelta(days=3), revision_of=original.observation_id
        )
        with self.assertRaises(IntegrityViolation):
            self.repo.add_observation(invalid)

    def test_publication_period_timezone_and_expectation_semantics(self) -> None:
        item = self.observation("2024-Q4", "108.4", T0 + timedelta(days=1))
        self.assertEqual(item.observation_period, "2024-Q4")
        self.assertEqual(item.expectation_status, ExpectationStatus.UNKNOWN)
        self.assertIsNone(item.surprise)
        expected = self.observation("2025-Q1", "3.2", T0 + timedelta(days=2), expected="3.0")
        self.assertEqual(expected.surprise, "0.2")
        with self.assertRaises(ValidationError):
            self.observation("2025-Q2", "3", T0.replace(tzinfo=None))

    def test_expectation_must_predate_publication(self) -> None:
        with self.assertRaises(ValidationError):
            MacroObservation(
                "il.cpi",
                "il.cbs",
                "IL",
                MacroCategory.INFLATION,
                "2025-01",
                "3",
                "percent",
                T0,
                T0 + timedelta(hours=1),
                None,
                SeasonalAdjustment.UNADJUSTED,
                ("source:test",),
                "test/1",
                "CPI",
                "מדד",
                expected_value="2",
                expectation_source="survey",
                expectation_observed_at=T0 + timedelta(minutes=1),
            )

    def test_seasonal_adjustments_are_distinct(self) -> None:
        raw = self.observation("2025-01", "100", T0 + timedelta(days=1))
        adjusted = self.observation(
            "2025-01",
            "99",
            T0 + timedelta(days=1),
            adjustment=SeasonalAdjustment.SEASONALLY_ADJUSTED,
        )
        self.repo.add_observation(raw)
        self.repo.add_observation(adjusted)
        self.assertEqual(
            len(self.repo.observations_visible_at("il.cpi.headline", T0 + timedelta(days=2))), 2
        )

    def test_malformed_units_and_nonfinite_values_fail(self) -> None:
        with self.assertRaises(ValidationError):
            self.observation("2025-01", "3", T0 + timedelta(days=1)).__class__(
                "x",
                "il.cbs",
                "IL",
                MacroCategory.INFLATION,
                "2025",
                "3",
                "bananas",
                T0,
                T0,
                None,
                SeasonalAdjustment.UNADJUSTED,
                ("p",),
                "v",
                "X",
            )
        with self.assertRaises(ValidationError):
            self.observation("2025-01", "NaN", T0 + timedelta(days=1))

    def test_horizons_can_disagree_and_mechanisms_are_direction_neutral(self) -> None:
        values = ("12", "11", "10", "9", "8", "7", "6", "5", "4", "3", "4", "5")
        items = tuple(
            self.observation(f"2025-{index + 1:02d}", value, T0 + timedelta(days=index + 1))
            for index, value in enumerate(values)
        )
        short = calculate_trend(items, TrendHorizon.SHORT, T0 + timedelta(days=20))
        long = calculate_trend(items, TrendHorizon.LONG, T0 + timedelta(days=20))
        self.assertEqual(short.state, TrendState.RISING)
        self.assertEqual(long.state, TrendState.FALLING)
        self.assertNotIn("buy", short.mechanism_ids)

    def test_divergence_is_preserved_not_collapsed(self) -> None:
        items = tuple(
            self.observation(f"2025-0{x}", str(x), T0 + timedelta(days=x)) for x in range(1, 4)
        )
        for item in items:
            self.repo.add_observation(item)
        left = calculate_trend(items, TrendHorizon.SHORT, T0 + timedelta(days=4))
        right = calculate_trend(items, TrendHorizon.MEDIUM, T0 + timedelta(days=4))
        self.repo.add_trend(left)
        self.repo.add_trend(right)
        divergence = TrendDivergence(
            left.trend_id,
            right.trend_id,
            "CPI and wages disagree",
            T0 + timedelta(days=4),
            (left.trend_id, right.trend_id),
        )
        self.repo.add_divergence(divergence)
        self.assertEqual(self.repo.divergences_visible_at(T0 + timedelta(days=3)), ())
        self.assertEqual(self.repo.divergences_visible_at(T0 + timedelta(days=5)), (divergence,))

    def test_append_only_idempotency_telemetry_and_registry(self) -> None:
        item = self.observation("2025-01", "100", T0 + timedelta(days=1))
        self.assertTrue(self.repo.add_observation(item))
        self.assertFalse(self.repo.add_observation(item))
        self.session.flush()
        self.session.commit()
        row = self.session.get(MacroObservationModel, item.observation_id)
        assert row is not None
        row.value = "999"
        with self.assertRaises(ImmutableRecordError):
            self.session.flush()
        self.session.rollback()
        telemetry = measure_storage(self.session)
        self.assertEqual(telemetry.macro_series_count, 1)
        self.assertEqual(telemetry.macro_revision_rate, 0)
        self.assertEqual(len(STRUCTURAL_TREND_NAMES), 8)
        self.assertTrue(DEFAULT_REGISTRY.get("il.cbs").enabled)
        for source_id in (
            "us.fred",
            "eu.ecb.data",
            "global.worldbank",
            "global.oecd.sdmx",
            "us.eia",
        ):
            self.assertFalse(DEFAULT_REGISTRY.get(source_id).enabled)

    def test_replay_snapshot_reconstructs_macro_vintage(self) -> None:
        original = self.observation("2025-01", "100", T0 + timedelta(days=1))
        revised = self.observation(
            "2025-01", "101", T0 + timedelta(days=3), revision_of=original.observation_id
        )
        self.repo.add_observation(original)
        self.repo.add_observation(revised)
        trend = calculate_trend((original,), TrendHorizon.SHORT, T0 + timedelta(days=1))
        self.repo.add_trend(trend)
        case = ReplayCase(
            ReplayCaseType.QUIET,
            ("country.israel",),
            ("asset.fx.usdils",),
            T0 + timedelta(days=2),
            "1 month",
            "manifest:test",
            None,
            "research-hypothesis/v1",
            "macro-outcome/1",
            "macro-test/1",
            T0 + timedelta(days=2),
        )
        with tempfile.TemporaryDirectory() as directory:
            snapshot = ReplayEngine(
                self.session, MarketDataStore(self.session, Path(directory))
            ).snapshot(case)
        self.assertEqual(snapshot.macro_observation_ids, (original.observation_id,))
        self.assertEqual(snapshot.trend_ids, (trend.trend_id,))

    def test_reviewed_boi_fx_transformation_preserves_provenance(self) -> None:
        digest = "a" * 64
        normalized = NormalizedObservation(
            "il.boi",
            "boi:USD:2025-01-01",
            "representative-exchange-rates",
            "USD",
            date(2025, 1, 1),
            date(2025, 1, 1),
            T0,
            T0 + timedelta(minutes=1),
            T0,
            None,
            "3.65",
            "ILS per 1 USD",
            digest,
            f"sha256:{digest}",
            "boi/1",
        )
        macro = boi_fx_macro_observation(normalized)
        self.assertEqual(macro.series_id, "il.boi.fx.usd.ils")
        self.assertEqual(macro.value, "3.65")
        self.assertIn(normalized.provenance_id, macro.provenance)


if __name__ == "__main__":
    unittest.main()
