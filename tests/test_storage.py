import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from market_evolver.config import DatabaseConfig
from market_evolver.errors import (
    ConfigurationError,
    ImmutableRecordError,
    IntegrityViolation,
    ValidationError,
)
from market_evolver.schemas import (
    DecisionRecommendation,
    Event,
    Evidence,
    Hypothesis,
    ResearchDecision,
    Source,
    SourceKind,
)
from market_evolver.storage.artifacts import LocalArtifactStore
from market_evolver.storage.models import Base, SourceModel
from market_evolver.storage.repositories import (
    SqlEventRepository,
    SqlEvidenceRepository,
    SqlHypothesisRepository,
    SqlResearchDecisionRepository,
    SqlSourceRepository,
    add_artifact_metadata,
)

NOW = datetime(2025, 1, 2, 12, tzinfo=UTC)


class StorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def _source(self, observed_at: datetime = NOW) -> Source:
        return Source(
            uri="https://example.test/report",
            kind=SourceKind.GOVERNMENT,
            publisher="Example Authority",
            published_at=observed_at - timedelta(hours=1),
            observed_at=observed_at,
            ingested_at=observed_at + timedelta(minutes=1),
            effective_at=observed_at - timedelta(days=1),
            content_digest="sha256:" + "a" * 64,
            mime_type="application/pdf",
        )

    def test_persistence_round_trip_and_provenance_chain(self) -> None:
        source = SqlSourceRepository(self.session).add(self._source())
        evidence = SqlEvidenceRepository(self.session).add(
            Evidence("A supported claim", (source.provenance_id,), NOW, "sha256:excerpt")
        )
        event = SqlEventRepository(self.session).add(
            Event("Reported event", NOW - timedelta(days=1), NOW, (evidence.provenance_id,))
        )
        hypothesis = SqlHypothesisRepository(self.session).add(
            Hypothesis(
                "A testable statement",
                NOW,
                (evidence.provenance_id,),
                (event.provenance_id,),
                0.6,
            )
        )
        decision = SqlResearchDecisionRepository(self.session).add(
            ResearchDecision(
                DecisionRecommendation.INVESTIGATE,
                "Evidence warrants more research",
                NOW + timedelta(minutes=2),
                NOW,
                (hypothesis.provenance_id,),
                (evidence.provenance_id,),
            )
        )
        self.session.commit()
        self.assertEqual(SqlSourceRepository(self.session).get(source.provenance_id), source)
        self.assertEqual(SqlEvidenceRepository(self.session).get(evidence.provenance_id), evidence)
        self.assertEqual(SqlEventRepository(self.session).get(event.provenance_id), event)
        self.assertEqual(
            SqlHypothesisRepository(self.session).get(hypothesis.provenance_id),
            hypothesis,
        )
        self.assertEqual(
            SqlResearchDecisionRepository(self.session).get(decision.provenance_id),
            decision,
        )

    def test_duplicate_ingestion_is_idempotent(self) -> None:
        repository = SqlSourceRepository(self.session)
        first = repository.add(self._source())
        second = repository.add(self._source())
        self.assertEqual(first, second)
        self.assertEqual(self.session.query(SourceModel).count(), 1)

    def test_cutoff_query_correctness(self) -> None:
        source_repo = SqlSourceRepository(self.session)
        evidence_repo = SqlEvidenceRepository(self.session)
        early_source = source_repo.add(self._source(NOW))
        late_source = source_repo.add(self._source(NOW + timedelta(hours=2)))
        early = evidence_repo.add(
            Evidence("early", (early_source.provenance_id,), NOW, "sha256:early")
        )
        evidence_repo.add(
            Evidence(
                "late",
                (late_source.provenance_id,),
                NOW + timedelta(hours=2),
                "sha256:late",
            )
        )
        self.assertEqual(evidence_repo.visible_at(NOW), [early])

    def test_causally_impossible_evidence_is_rejected(self) -> None:
        source = SqlSourceRepository(self.session).add(self._source(NOW))
        evidence = Evidence(
            "too early",
            (source.provenance_id,),
            NOW - timedelta(seconds=1),
            "sha256:early",
        )
        with self.assertRaises(IntegrityViolation):
            SqlEvidenceRepository(self.session).add(evidence)

    def test_timezone_naive_cutoff_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            SqlEvidenceRepository(self.session).visible_at(
                datetime(2025, 1, 2)  # noqa: DTZ001 - deliberately naive
            )

    def test_persisted_records_cannot_be_updated(self) -> None:
        source = SqlSourceRepository(self.session).add(self._source())
        model = self.session.get(SourceModel, source.provenance_id)
        assert model is not None
        model.publisher = "Mutated"
        with self.assertRaises(ImmutableRecordError):
            self.session.flush()
        self.session.rollback()

    def test_artifact_metadata_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            artifact = LocalArtifactStore(directory).put(b"raw", mime_type="text/plain")
            add_artifact_metadata(self.session, artifact, NOW)
            add_artifact_metadata(self.session, artifact, NOW)


class ArtifactTests(unittest.TestCase):
    def test_immutable_idempotent_artifacts_and_hash_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = LocalArtifactStore(directory)
            first = store.put(b"content", mime_type="text/plain")
            second = store.put(b"content", mime_type="text/plain")
            self.assertEqual(first, second)
            self.assertEqual(store.read(first), b"content")
            with self.assertRaises(IntegrityViolation):
                store.put(b"other", mime_type="text/plain", expected_sha256=first.sha256)

            path = Path(directory) / first.relative_path
            path.write_bytes(b"tampered")
            with self.assertRaises(IntegrityViolation):
                store.put(b"content", mime_type="text/plain")


class DatabaseConfigurationTests(unittest.TestCase):
    def test_database_configuration_fails_closed(self) -> None:
        config = DatabaseConfig()
        with self.assertRaises(ConfigurationError):
            config.resolve_url({})
        with self.assertRaises(ConfigurationError):
            config.resolve_url({"MARKET_EVOLVER_DATABASE_URL": "sqlite:///unsafe.db"})

    def test_database_requires_tls(self) -> None:
        resolved = DatabaseConfig().resolve_url(
            {"MARKET_EVOLVER_DATABASE_URL": "postgresql+psycopg://db/research"}
        )
        self.assertIn("sslmode=require", resolved)


if __name__ == "__main__":
    unittest.main()
