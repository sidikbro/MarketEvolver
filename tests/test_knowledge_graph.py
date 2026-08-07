import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from market_evolver.errors import ImmutableRecordError
from market_evolver.knowledge.repositories import SqlKnowledgeGraph
from market_evolver.knowledge.schemas import (
    EntityVersion,
    Exposure,
    ExposureDirection,
    ExposureStrength,
    ExposureType,
    KnowledgeEntityType,
    RecordStatus,
    Relationship,
    RelationType,
    ResolutionStatus,
)
from market_evolver.knowledge.seed import (
    SEED_ACTIVE_FROM,
    seed_knowledge_graph,
)
from market_evolver.observatory.repositories import SqlCanonicalEventRepository
from market_evolver.observatory.schemas import (
    CanonicalEvent,
    EventStatus,
    EventType,
    RevisionState,
)
from market_evolver.schemas import Evidence, Source, SourceKind, TrustLevel
from market_evolver.storage.models import Base, KnowledgeRelationshipModel
from market_evolver.storage.repositories import SqlEvidenceRepository, SqlSourceRepository

T1 = datetime(2025, 1, 2, 12, tzinfo=UTC)
T2 = datetime(2025, 1, 3, 12, tzinfo=UTC)


class KnowledgeGraphTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.graph = SqlKnowledgeGraph(self.session)
        self.seed_counts = seed_knowledge_graph(self.session)
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def test_seed_is_idempotent_and_contains_required_taxonomy(self) -> None:
        self.assertGreaterEqual(self.seed_counts[0], 40)
        self.assertGreaterEqual(self.seed_counts[1], 25)
        self.assertEqual(self.seed_counts[2], 3)
        self.assertEqual(seed_knowledge_graph(self.session), (0, 0, 0))
        for entity_id in (
            "country.il",
            "institution.boi",
            "currency.ils",
            "currency.usd",
            "currency.eur",
            "exchange.tase",
            "sector.technology",
            "sector.cybersecurity",
            "sector.semiconductors",
            "sector.software",
            "sector.banks",
            "sector.real_estate",
            "sector.construction",
        ):
            self.assertIsNotNone(self.graph.get_entity_at(entity_id, T1))

    def test_deterministic_hebrew_english_and_identifier_aliases(self) -> None:
        for alias in ("Bank of Israel", "בנק ישראל", "BOI"):
            result = self.graph.resolve_alias(alias, T1)
            self.assertEqual(result.status, ResolutionStatus.RESOLVED)
            self.assertEqual(result.candidates[0].entity_id, "institution.boi")
        for alias in ("USD/ILS", "USDILS", "USD ILS", "דולר שקל"):
            result = self.graph.resolve_alias(alias, T1)
            self.assertEqual(result.status, ResolutionStatus.RESOLVED)
            self.assertEqual(result.candidates[0].entity_id, "asset.fx.usdils")
        self.assertEqual(
            self.graph.resolve_alias("XTAE", T1).candidates[0].entity_id,
            "exchange.tase",
        )
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            self.graph.get_entity_at(
                "country.il",
                datetime(2025, 1, 2),  # noqa: DTZ001 - deliberate fail-closed test
            )

    def test_ambiguous_alias_returns_multiple_candidates(self) -> None:
        for suffix in ("one", "two"):
            self.graph.add_entity(
                EntityVersion(
                    entity_id=f"indicator.{suffix}",
                    canonical_name=f"Indicator {suffix}",
                    aliases=("shared indicator",),
                    hebrew_name=None,
                    english_name=f"Indicator {suffix}",
                    entity_type=KnowledgeEntityType.ECONOMIC_INDICATOR,
                    geography=("IL",),
                    identifiers=(),
                    active_from=SEED_ACTIVE_FROM,
                    active_until=None,
                    observed_at=T1,
                    provenance=("test:ambiguous",),
                    confidence=1.0,
                    version=1,
                )
            )
        result = self.graph.resolve_alias("Shared-Indicator", T1)
        self.assertEqual(result.status, ResolutionStatus.AMBIGUOUS)
        self.assertEqual(
            tuple(item.entity_id for item in result.candidates),
            ("indicator.one", "indicator.two"),
        )

    def test_relationship_validity_and_no_future_knowledge_leak(self) -> None:
        bounded = Relationship(
            relation_type=RelationType.SENSITIVE_TO,
            source_entity="sector.software",
            target_entity="mechanism.regulation_cost",
            valid_from=T1,
            valid_until=T2,
            observed_at=T1,
            confidence=0.8,
            provenance=("test:bounded",),
            status=RecordStatus.ACTIVE,
            version=1,
        )
        future = Relationship(
            relation_type=RelationType.SENSITIVE_TO,
            source_entity="sector.software",
            target_entity="mechanism.tax_burden",
            valid_from=T1,
            valid_until=None,
            observed_at=T2,
            confidence=0.7,
            provenance=("test:future",),
            status=RecordStatus.ACTIVE,
            version=1,
        )
        self.graph.add_relationship(bounded)
        self.graph.add_relationship(future)

        at_t1 = self.graph.get_relationships("sector.software", T1)
        after_t2 = self.graph.get_relationships("sector.software", T2 + timedelta(seconds=1))
        self.assertIn(bounded.relationship_id, {item.relationship_id for item in at_t1})
        self.assertNotIn(future.relationship_id, {item.relationship_id for item in at_t1})
        self.assertNotIn(bounded.relationship_id, {item.relationship_id for item in after_t2})
        self.assertIn(future.relationship_id, {item.relationship_id for item in after_t2})

    def test_exposure_versioning_is_point_in_time(self) -> None:
        first = self.graph.get_exposures("sector.banks", T1)[0]
        second = replace(
            first,
            observed_at=T2,
            strength=ExposureStrength.MEDIUM,
            source_evidence=("test:exposure-v2",),
            version=2,
        )
        self.graph.add_exposure(second)
        self.assertEqual(
            self.graph.get_exposures("sector.banks", T1)[0].version,
            1,
        )
        latest = self.graph.get_exposures("sector.banks", T2)[0]
        self.assertEqual(latest.version, 2)
        self.assertEqual(latest.strength, ExposureStrength.MEDIUM)
        self.assertIsNone(latest.value)
        self.assertIsNone(latest.unit)

    def test_event_propagation_preserves_paths_versions_and_provenance(self) -> None:
        event = self._risk_event()
        trace = self.graph.trace_event(event.event_id, T1)

        self.assertIn("institution.boi", trace.direct_entities)
        self.assertEqual(trace.candidate_mechanisms, ("mechanism.risk_premium",))
        self.assertTrue(trace.paths)
        self.assertTrue(any("sector.real_estate" in path.entity_ids for path in trace.paths))
        self.assertTrue(
            any(
                path.entity_ids[:3]
                == (
                    "mechanism.risk_premium",
                    "mechanism.financing_cost",
                    "mechanism.credit_demand",
                )
                for path in trace.paths
            )
        )
        for path in trace.paths:
            self.assertTrue(path.cutoff_validated)
            self.assertEqual(len(path.relationship_ids), len(path.relationship_versions))
            self.assertTrue(all(version == 1 for version in path.relationship_versions))
            self.assertIn("seed:marketevolver:v0.5", path.provenance)
            self.assertIn(event.evidence_ids[0], path.provenance)
            self.assertGreater(path.confidence, 0)
            self.assertLessEqual(path.confidence, 1)

    def test_future_propagation_edge_does_not_leak_backward(self) -> None:
        event = self._risk_event()
        future = Relationship(
            relation_type=RelationType.AFFECTS,
            source_entity="mechanism.risk_premium",
            target_entity="sector.tourism",
            valid_from=T1,
            valid_until=None,
            observed_at=T2,
            confidence=0.6,
            provenance=("test:future-propagation",),
            status=RecordStatus.ACTIVE,
            version=1,
        )
        self.graph.add_relationship(future)
        at_t1 = self.graph.trace_event(event.event_id, T1)
        at_t2 = self.graph.trace_event(event.event_id, T2)
        self.assertFalse(any("sector.tourism" in path.entity_ids for path in at_t1.paths))
        self.assertTrue(any("sector.tourism" in path.entity_ids for path in at_t2.paths))

    def test_orm_rejects_relationship_mutation(self) -> None:
        model = self.session.query(KnowledgeRelationshipModel).first()
        assert model is not None
        model.confidence = 0.1
        with self.assertRaises(ImmutableRecordError):
            self.session.flush()
        self.session.rollback()

    def _risk_event(self) -> CanonicalEvent:
        source = SqlSourceRepository(self.session).add(
            Source(
                uri="https://www.boi.org.il/test-risk",
                kind=SourceKind.MARKET_DATA,
                publisher="Bank of Israel",
                published_at=T1 - timedelta(minutes=30),
                observed_at=T1,
                ingested_at=T1,
                trust=TrustLevel.AUTHORITATIVE,
                content_digest="sha256:" + "d" * 64,
                mime_type="application/json",
            )
        )
        evidence = SqlEvidenceRepository(self.session).add(
            Evidence(
                claim="Official risk-premium observation",
                source_ids=(source.provenance_id,),
                observed_at=T1,
                excerpt_digest="sha256:risk",
            )
        )
        event = CanonicalEvent(
            event_type=EventType.RATE_MOVEMENT,
            source_ids=(source.provenance_id,),
            evidence_ids=(evidence.provenance_id,),
            geography=("IL",),
            entities=(
                "institution.boi",
                "currency.ils",
                "currency.usd",
                "country.il",
            ),
            sectors=("sector.financial",),
            affected_asset_classes=("foreign_exchange",),
            published_at=T1 - timedelta(minutes=30),
            first_observed_at=T1,
            effective_at=T1 - timedelta(minutes=30),
            event_status=EventStatus.CONFIRMED,
            confidence=0.9,
            novelty=0.8,
            revision_state=RevisionState.ORIGINAL,
            supersedes_event_id=None,
            causal_mechanisms=("risk_premium",),
            tags=("test",),
            attributes=(("change_percent", "1.2"),),
            deduplication_key="test:risk-event",
        )
        SqlCanonicalEventRepository(self.session).add(event)
        self.session.flush()
        return event


class KnowledgeSchemaTests(unittest.TestCase):
    def test_quantitative_exposure_requires_value_and_unit_together(self) -> None:
        with self.assertRaisesRegex(ValueError, "value and unit"):
            Exposure(
                exposure_type=ExposureType.CURRENCY_REVENUE,
                subject_entity="company.test",
                target_entity="currency.usd",
                direction=ExposureDirection.REVENUE,
                strength=ExposureStrength.UNKNOWN,
                unit="percent",
                value=None,
                effective_from=T1,
                effective_until=None,
                observed_at=T1,
                confidence=0.5,
                source_evidence=("test:evidence",),
                status=RecordStatus.ACTIVE,
                version=1,
            )


if __name__ == "__main__":
    unittest.main()
