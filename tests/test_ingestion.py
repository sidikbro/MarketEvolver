import tempfile
import unittest
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from market_evolver.errors import ValidationError
from market_evolver.ingestion.boi import BankOfIsraelConnector
from market_evolver.ingestion.connectors import FetchedPayload, ObservedPayload, PersistedPayload
from market_evolver.ingestion.repositories import SqlManifestRepository
from market_evolver.ingestion.runner import IngestionRunner
from market_evolver.ingestion.schemas import IngestionStatus, NormalizedObservation
from market_evolver.storage.artifacts import ArtifactStore, LocalArtifactStore
from market_evolver.storage.models import (
    Base,
    EvidenceModel,
    NormalizedObservationModel,
    RawIngestionModel,
    SourceModel,
)
from market_evolver.storage.telemetry import measure_storage

PAYLOAD = b"""{
  "exchangeRates": [
    {
      "key": "USD",
      "currentExchangeRate": 3.41,
      "currentChange": -0.2,
      "unit": 1,
      "lastUpdate": "2025-01-02T10:00:00Z"
    },
    {
      "key": "EUR",
      "currentExchangeRate": 3.52,
      "currentChange": 0.1,
      "unit": 1,
      "lastUpdate": "2025-01-02T10:00:00Z"
    }
  ]
}"""
START = datetime(2025, 1, 2, 12, tzinfo=UTC)


class IncrementingClock:
    def __init__(self) -> None:
        self.current = START

    def __call__(self) -> datetime:
        value = self.current
        self.current += timedelta(seconds=1)
        return value


class MockBoiConnector(BankOfIsraelConnector):
    def __init__(self, events: list[str] | None = None, payload: bytes = PAYLOAD) -> None:
        self.events = events if events is not None else []
        self.payload = payload

    def fetch(self, dataset: str) -> FetchedPayload:
        self.events.append("fetch")
        return FetchedPayload(self.payload, self.endpoint, "application/json")

    def persist_raw(
        self, payload: ObservedPayload, artifact_store: ArtifactStore
    ) -> PersistedPayload:
        self.events.append("persist_raw")
        return super().persist_raw(payload, artifact_store)

    def normalize(self, payload: PersistedPayload) -> PersistedPayload:
        self.events.append("normalize")
        return super().normalize(payload)

    def parse(self, payload: PersistedPayload, dataset: str):
        self.events.append("parse")
        return super().parse(payload, dataset)

    def emit_evidence(self, item, source, observation):
        self.events.append("emit_evidence")
        return super().emit_evidence(item, source, observation)


class IngestionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.store = LocalArtifactStore(self.directory.name)
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.clock = IncrementingClock()

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()
        self.directory.cleanup()

    def test_mocked_official_ingestion_raw_before_parse_and_provenance(self) -> None:
        events: list[str] = []
        manifest = IngestionRunner(self.session, self.store, clock=self.clock).run(
            MockBoiConnector(events), BankOfIsraelConnector.dataset_name
        )

        self.assertEqual(manifest.status, IngestionStatus.SUCCEEDED)
        self.assertEqual(manifest.items_inserted, 2)
        self.assertLess(events.index("persist_raw"), events.index("parse"))
        self.assertEqual(self.session.query(RawIngestionModel).count(), 1)
        self.assertEqual(self.session.query(SourceModel).count(), 1)
        self.assertEqual(self.session.query(NormalizedObservationModel).count(), 2)
        self.assertEqual(self.session.query(EvidenceModel).count(), 2)

        observations = tuple(self.session.scalars(select(NormalizedObservationModel)))
        source = self.session.scalar(select(SourceModel))
        assert source is not None
        for observation in observations:
            self.assertEqual(observation.source_record_id, source.provenance_id)
            self.assertEqual(
                observation.content_hash,
                f"sha256:{observation.raw_artifact_sha256}",
            )
            self.assertEqual(observation.first_observed_at, source.observed_at)
            self.assertEqual(observation.period_start.isoformat(), "2025-01-02")
            self.assertIsNotNone(observation.published_at)
            self.assertIsNotNone(observation.effective_at)

    def test_idempotent_reingestion_preserves_first_observed(self) -> None:
        runner = IngestionRunner(self.session, self.store, clock=self.clock)
        first = runner.run(MockBoiConnector(), BankOfIsraelConnector.dataset_name)
        receipt = self.session.scalar(select(RawIngestionModel))
        assert receipt is not None
        first_observed = receipt.first_observed_at
        second = runner.run(MockBoiConnector(), BankOfIsraelConnector.dataset_name)

        self.assertEqual(first.items_inserted, 2)
        self.assertEqual(second.items_inserted, 0)
        self.assertEqual(second.duplicates, 2)
        self.assertEqual(second.raw_artifacts_created, 0)
        self.assertEqual(self.session.query(SourceModel).count(), 1)
        self.assertEqual(self.session.query(NormalizedObservationModel).count(), 2)
        self.assertEqual(
            self.session.scalar(select(RawIngestionModel)).first_observed_at,
            first_observed,
        )

    def test_failed_parse_records_manifest_and_preserves_raw(self) -> None:
        manifest = IngestionRunner(self.session, self.store, clock=self.clock).run(
            MockBoiConnector(payload=b"not-json"), BankOfIsraelConnector.dataset_name
        )

        self.assertEqual(manifest.status, IngestionStatus.FAILED)
        self.assertIn("invalid Bank of Israel JSON", manifest.error_summary or "")
        self.assertEqual(self.session.query(RawIngestionModel).count(), 1)
        receipt = self.session.scalar(select(RawIngestionModel))
        assert receipt is not None
        self.assertTrue(self.store.exists(receipt.artifact_sha256))
        persisted = SqlManifestRepository(self.session).recent(1)[0]
        self.assertEqual(persisted.status, IngestionStatus.FAILED)

    def test_storage_telemetry_measures_bytes_records_and_daily_growth(self) -> None:
        runner = IngestionRunner(self.session, self.store, clock=self.clock)
        runner.run(MockBoiConnector(), BankOfIsraelConnector.dataset_name)
        runner.run(MockBoiConnector(), BankOfIsraelConnector.dataset_name)

        telemetry = measure_storage(self.session)
        self.assertEqual(telemetry.raw_artifact_bytes, len(PAYLOAD))
        self.assertEqual(telemetry.database_record_counts["normalized_observations"], 2)
        self.assertEqual(telemetry.ingestion_bytes_by_day[0].value, len(PAYLOAD) * 2)
        self.assertEqual(telemetry.item_growth_by_day[0].value, 2)


class PointInTimeObservationTests(unittest.TestCase):
    def _observation(self, **changes) -> NormalizedObservation:
        values = {
            "registry_source_id": "il.boi",
            "source_record_id": "source:sha256:x",
            "dataset": "rates",
            "item_key": "USD",
            "period_start": START.date(),
            "period_end": START.date(),
            "published_at": START - timedelta(hours=1),
            "first_observed_at": START,
            "effective_at": START - timedelta(hours=1),
            "superseded_at": None,
            "value": "3.41",
            "unit": "ILS per USD",
            "raw_artifact_sha256": "a" * 64,
            "content_hash": "sha256:" + "a" * 64,
            "parser_version": "test/1",
        }
        values.update(changes)
        return NormalizedObservation(**values)

    def test_timestamp_dimensions_remain_separate(self) -> None:
        observation = self._observation()
        self.assertNotEqual(observation.period_start, observation.published_at)
        self.assertNotEqual(observation.published_at, observation.first_observed_at)

    def test_naive_and_future_publication_timestamps_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            self._observation(first_observed_at=datetime(2025, 1, 2))  # noqa: DTZ001
        with self.assertRaises(ValidationError):
            self._observation(published_at=START + timedelta(seconds=1))


if __name__ == "__main__":
    unittest.main()
