import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from market_evolver.errors import IntegrityViolation, ValidationError
from market_evolver.ingestion.repositories import SqlObservationRepository
from market_evolver.ingestion.schemas import NormalizedObservation
from market_evolver.observatory.entities import DEFAULT_ENTITY_REGISTRY
from market_evolver.observatory.extraction import BoiEventExtractionPipeline
from market_evolver.observatory.mechanisms import DEFAULT_MECHANISM_REGISTRY
from market_evolver.observatory.repositories import (
    SqlCanonicalEventRepository,
    observatory_summary,
)
from market_evolver.observatory.schemas import (
    EventStatus,
    EventTransition,
    EventType,
    ReviewerStatus,
    RevisionState,
)
from market_evolver.schemas import Evidence, Source, SourceKind, TrustLevel
from market_evolver.storage.artifacts import Artifact
from market_evolver.storage.models import (
    Base,
    EventMechanismLinkModel,
    EventSupportModel,
)
from market_evolver.storage.repositories import (
    SqlEvidenceRepository,
    SqlSourceRepository,
    add_artifact_metadata,
)

T1 = datetime(2025, 1, 2, 12, tzinfo=UTC)
T2 = datetime(2025, 1, 2, 14, tzinfo=UTC)


class ObservatoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def _observation(
        self,
        *,
        observed_at: datetime,
        value: str,
        digest_character: str,
        currency: str = "USD",
        period_offset: int = 0,
    ) -> NormalizedObservation:
        sha256 = digest_character * 64
        add_artifact_metadata(
            self.session,
            Artifact(
                sha256=sha256,
                size_bytes=10,
                mime_type="application/json",
                relative_path=f"sha256/{sha256[:2]}/{sha256[2:4]}/{sha256}",
            ),
            observed_at,
        )
        source = SqlSourceRepository(self.session).add(
            Source(
                uri=f"https://www.boi.org.il/rates/{sha256}",
                kind=SourceKind.MARKET_DATA,
                publisher="Bank of Israel",
                published_at=observed_at - timedelta(minutes=30),
                observed_at=observed_at,
                ingested_at=observed_at,
                trust=TrustLevel.AUTHORITATIVE,
                content_digest=f"sha256:{sha256}",
                mime_type="application/json",
            )
        )
        period = (observed_at + timedelta(days=period_offset)).date()
        observation = NormalizedObservation(
            registry_source_id="il.boi",
            source_record_id=source.provenance_id,
            dataset="representative-exchange-rates",
            item_key=currency,
            period_start=period,
            period_end=period,
            published_at=observed_at - timedelta(minutes=30),
            first_observed_at=observed_at,
            effective_at=observed_at - timedelta(minutes=30),
            superseded_at=None,
            value=value,
            unit=f"ILS per 1 {currency}",
            raw_artifact_sha256=sha256,
            content_hash=f"sha256:{sha256}",
            parser_version="test/1",
        )
        SqlObservationRepository(self.session).add(observation)
        SqlEvidenceRepository(self.session).add(
            Evidence(
                claim=f"{currency} rate {value}",
                source_ids=(source.provenance_id,),
                observed_at=observed_at,
                excerpt_digest=observation.provenance_id,
            )
        )
        self.session.flush()
        return observation

    def test_revision_replay_isolation_and_original_immutability(self) -> None:
        self._observation(observed_at=T1, value="3.40", digest_character="a")
        pipeline = BoiEventExtractionPipeline(self.session)
        pipeline.run_pending()
        self.session.commit()
        repository = SqlCanonicalEventRepository(self.session)
        at_t1 = repository.get_events_visible_at(T1)
        original = next(
            item
            for item in at_t1
            if item.event_type is EventType.REPRESENTATIVE_EXCHANGE_RATE_UPDATE
        )
        self.assertEqual(repository.current_status(original.event_id, T1), EventStatus.CONFIRMED)
        with self.assertRaises(ValidationError):
            replace(
                original,
                first_observed_at=datetime(2025, 1, 2, 12),  # noqa: DTZ001
            )

        self._observation(observed_at=T2, value="3.45", digest_character="b")
        pipeline.run_pending()
        self.session.commit()
        still_at_t1 = repository.get_events_visible_at(T1)
        after_t2 = repository.get_events_visible_at(T2)
        updates = [
            item
            for item in after_t2
            if item.event_type is EventType.REPRESENTATIVE_EXCHANGE_RATE_UPDATE
        ]

        self.assertEqual([item.event_id for item in still_at_t1], [original.event_id])
        self.assertEqual(len(updates), 2)
        revision = next(item for item in updates if item.event_id != original.event_id)
        self.assertEqual(revision.supersedes_event_id, original.event_id)
        self.assertEqual(revision.revision_state, RevisionState.CORRECTED)
        self.assertEqual(repository.get(original.event_id), original)
        self.assertEqual(repository.current_status(original.event_id, T2), EventStatus.SUPERSEDED)
        self.assertEqual(
            [item.to_status for item in repository.transitions(original.event_id)],
            [EventStatus.OBSERVED, EventStatus.CONFIRMED, EventStatus.SUPERSEDED],
        )

    def test_event_deduplication_uses_material_identity_not_text(self) -> None:
        self._observation(observed_at=T1, value="3.40", digest_character="a")
        pipeline = BoiEventExtractionPipeline(self.session)
        first = pipeline.run_pending()
        second = pipeline.run_pending()
        self.assertEqual(first, (1, 0))
        self.assertEqual(second, (0, 1))

    def test_same_material_event_adds_support_but_change_requires_revision(self) -> None:
        self._observation(observed_at=T1, value="3.40", digest_character="a")
        BoiEventExtractionPipeline(self.session).run_pending()
        repository = SqlCanonicalEventRepository(self.session)
        existing = repository.get_events_visible_at(T1)[0]
        second_source = SqlSourceRepository(self.session).add(
            Source(
                uri="https://official.example.test/corroboration",
                kind=SourceKind.MARKET_DATA,
                publisher="Second official record",
                published_at=existing.published_at,
                observed_at=T2,
                ingested_at=T2,
                trust=TrustLevel.AUTHORITATIVE,
                content_digest="sha256:" + "c" * 64,
                mime_type="application/json",
            )
        )
        second_evidence = SqlEvidenceRepository(self.session).add(
            Evidence(
                claim="Corroborating official USD rate",
                source_ids=(second_source.provenance_id,),
                observed_at=T2,
                excerpt_digest="sha256:corroboration",
            )
        )
        duplicate = replace(
            existing,
            source_ids=(second_source.provenance_id,),
            evidence_ids=(second_evidence.provenance_id,),
            first_observed_at=T2,
        )
        persisted, created = repository.add(duplicate)
        self.assertFalse(created)
        self.assertEqual(persisted.event_id, existing.event_id)
        self.assertEqual(
            self.session.query(EventSupportModel)
            .filter(EventSupportModel.event_id == existing.event_id)
            .count(),
            2,
        )
        changed = replace(
            existing,
            attributes=tuple(
                ("value", "3.50") if key == "value" else (key, value)
                for key, value in existing.attributes
            ),
        )
        with self.assertRaises(IntegrityViolation):
            repository.add(changed)

    def test_entity_mechanism_linking_and_summary(self) -> None:
        self._observation(observed_at=T1, value="3.40", digest_character="a")
        self._observation(
            observed_at=T2,
            value="3.50",
            digest_character="b",
            period_offset=1,
        )
        BoiEventExtractionPipeline(self.session).run_pending()
        summary = observatory_summary(self.session, T2)
        events = SqlCanonicalEventRepository(self.session).get_events_visible_at(T2)

        self.assertIn("institution.boi", summary.entities_referenced)
        self.assertIn("currency.ils", summary.entities_referenced)
        self.assertIn("currency.usd", summary.entities_referenced)
        self.assertIn("currency_translation", summary.mechanisms_referenced)
        self.assertEqual(summary.events_by_type["rate_movement"], 1)
        self.assertEqual(summary.events_by_type["unusual_fx_move"], 1)
        self.assertGreater(
            self.session.query(EventMechanismLinkModel).count(),
            0,
        )
        self.assertEqual(summary.coverage_started_at, T1)
        self.assertEqual(summary.coverage_ended_at, T2)
        self.assertEqual(sum(summary.events_by_type.values()), len(events))


class ObservatorySchemaTests(unittest.TestCase):
    def test_entity_and_mechanism_registries_have_required_entries(self) -> None:
        for entity_id in (
            "institution.boi",
            "currency.ils",
            "currency.usd",
            "currency.eur",
            "country.il",
            "sector.financial",
            "sector.real_estate",
            "cohort.exporters",
            "cohort.importers",
        ):
            self.assertEqual(DEFAULT_ENTITY_REGISTRY.get(entity_id).entity_id, entity_id)
        for mechanism_id in (
            "currency_translation",
            "import_cost",
            "export_competitiveness",
            "financing_cost",
            "credit_demand",
            "interest_margin",
            "risk_premium",
            "consumer_demand",
        ):
            self.assertEqual(
                DEFAULT_MECHANISM_REGISTRY.get(mechanism_id).mechanism_id,
                mechanism_id,
            )

    def test_lifecycle_validation_and_timezone_handling(self) -> None:
        with self.assertRaises(ValidationError):
            EventTransition(
                event_id="event:x",
                from_status=EventStatus.RETRACTED,
                to_status=EventStatus.CONFIRMED,
                transitioned_at=T1,
                rationale="Invalid terminal transition",
                evidence_ids=("evidence:x",),
                reviewer_status=ReviewerStatus.RULE_VALIDATED,
                sequence=1,
            )
        with self.assertRaises(ValidationError):
            EventTransition(
                event_id="event:x",
                from_status=None,
                to_status=EventStatus.OBSERVED,
                transitioned_at=datetime(2025, 1, 2),  # noqa: DTZ001
                rationale="Naive time",
                evidence_ids=("evidence:x",),
                reviewer_status=ReviewerStatus.RULE_VALIDATED,
                sequence=0,
            )


if __name__ == "__main__":
    unittest.main()
