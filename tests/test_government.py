import tempfile
import unittest
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from market_evolver.errors import ImmutableRecordError, IntegrityViolation, ValidationError
from market_evolver.government.connectors import BankOfIsraelPolicyConnector
from market_evolver.government.extraction import extract_policy_candidate
from market_evolver.government.repositories import SqlGovernmentRepository
from market_evolver.government.schemas import (
    ExpectationStatus,
    GovernmentAction,
    GovernmentActionStatus,
    GovernmentActionType,
    PolicyExpectation,
)
from market_evolver.ingestion.connectors import FetchedPayload
from market_evolver.ingestion.runner import IngestionRunner
from market_evolver.knowledge.seed import seed_knowledge_graph
from market_evolver.schemas import Evidence, Source, SourceKind, TrustLevel
from market_evolver.storage.artifacts import LocalArtifactStore
from market_evolver.storage.models import Base, GovernmentActionModel
from market_evolver.storage.repositories import SqlEvidenceRepository, SqlSourceRepository
from market_evolver.storage.telemetry import measure_storage

T1 = datetime(2025, 1, 1, 10, tzinfo=UTC)
T2 = T1 + timedelta(days=1)
T3 = T2 + timedelta(days=1)
T4 = T3 + timedelta(days=1)


class GovernmentLabTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        seed_knowledge_graph(self.session)
        self.session.commit()
        self.repository = SqlGovernmentRepository(self.session)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def evidence(self, at: datetime, claim: str = "Official policy publication") -> Evidence:
        digest = "sha256:" + f"{int(at.timestamp()):064x}"[-64:]
        source = Source(
            uri=f"https://www.boi.org.il/policy/{int(at.timestamp())}",
            kind=SourceKind.GOVERNMENT,
            publisher="Bank of Israel",
            published_at=at,
            observed_at=at,
            ingested_at=at,
            trust=TrustLevel.AUTHORITATIVE,
            content_digest=digest,
            mime_type="application/json",
        )
        SqlSourceRepository(self.session).add(source)
        evidence = Evidence(
            claim=claim,
            source_ids=(source.provenance_id,),
            observed_at=at,
            excerpt_digest=digest,
        )
        SqlEvidenceRepository(self.session).add(evidence)
        return evidence

    def action(self, evidence: Evidence, **changes) -> GovernmentAction:
        values = {
            "jurisdiction": "IL",
            "issuing_body": "institution.boi",
            "action_type": GovernmentActionType.MONETARY_POLICY,
            "title": "Policy rate action",
            "description_reference": "Official decision record",
            "status": GovernmentActionStatus.PROPOSED,
            "announced_at": evidence.observed_at,
            "published_at": evidence.observed_at,
            "effective_at": None,
            "first_observed_at": evidence.observed_at,
            "expires_at": None,
            "supersedes_action_id": None,
            "source_evidence_ids": (evidence.provenance_id,),
            "affected_entities": ("institution.boi",),
            "affected_sectors": ("sector.banks",),
            "candidate_mechanisms": (
                "financing_cost",
                "refinancing_cost",
                "credit_demand",
                "interest_margin",
            ),
            "confidence": 1.0,
            "provenance": (evidence.provenance_id,),
            "version": 1,
        }
        values.update(changes)
        return GovernmentAction(**values)

    def test_lifecycle_replay_proposed_approved_effective_amended(self) -> None:
        e1, e2, e3, e4 = (self.evidence(at) for at in (T1, T2, T3, T4))
        action = self.action(e1)
        self.repository.add_action(action)
        self.repository.transition(
            action.action_id,
            from_status=GovernmentActionStatus.PROPOSED,
            to_status=GovernmentActionStatus.APPROVED,
            transitioned_at=T2,
            evidence_ids=(e2.provenance_id,),
            rationale="Official approval",
        )
        self.repository.transition(
            action.action_id,
            from_status=GovernmentActionStatus.APPROVED,
            to_status=GovernmentActionStatus.EFFECTIVE,
            transitioned_at=T3,
            evidence_ids=(e3.provenance_id,),
            rationale="Effective date reached",
        )
        self.repository.transition(
            action.action_id,
            from_status=GovernmentActionStatus.EFFECTIVE,
            to_status=GovernmentActionStatus.AMENDED,
            transitioned_at=T4,
            evidence_ids=(e4.provenance_id,),
            rationale="Official amendment",
        )
        self.assertEqual(
            self.repository.current_status(action.action_id, T1), GovernmentActionStatus.PROPOSED
        )
        self.assertEqual(
            self.repository.current_status(action.action_id, T2), GovernmentActionStatus.APPROVED
        )
        self.assertEqual(
            self.repository.current_status(action.action_id, T3), GovernmentActionStatus.EFFECTIVE
        )
        self.assertEqual(
            self.repository.current_status(action.action_id, T4), GovernmentActionStatus.AMENDED
        )
        self.assertEqual(len(self.repository.transitions(action.action_id, T2)), 2)

    def test_corrected_release_is_new_version_and_does_not_leak(self) -> None:
        first_evidence = self.evidence(T1)
        original = self.action(first_evidence)
        self.repository.add_action(original)
        correction_evidence = self.evidence(T2, "Corrected official policy number")
        correction = self.action(
            correction_evidence,
            title="Corrected policy rate action",
            supersedes_action_id=original.action_id,
            version=2,
        )
        self.repository.add_action(correction)
        self.assertEqual(self.repository.get_actions_visible_at(T1), [original])
        self.assertEqual(self.repository.get_actions_visible_at(T2), [original, correction])

    def test_duplicate_official_publication_is_idempotent(self) -> None:
        action = self.action(self.evidence(T1))
        self.assertTrue(self.repository.add_action(action)[1])
        self.assertFalse(self.repository.add_action(action)[1])

    def test_effective_date_ordering_and_malformed_timezone(self) -> None:
        evidence = self.evidence(T2)
        legally_prior = self.action(evidence, effective_at=T1)
        self.assertEqual(legally_prior.effective_at, T1)
        later = self.action(evidence, effective_at=T3)
        self.assertEqual(later.effective_at, T3)
        with self.assertRaises(ValidationError):
            self.action(evidence, effective_at=datetime(2025, 1, 1))  # noqa: DTZ001

    def test_news_proposal_candidate_cannot_create_official_action(self) -> None:
        news = self.evidence(T1, "News reports proposed housing regulation")
        candidate = extract_policy_candidate(
            evidence_id=news.provenance_id,
            text="Proposed housing regulation effective 2025-02-01",
            created_at=T1,
        )
        self.repository.add_candidate(candidate)
        self.assertEqual(self.repository.get_actions_visible_at(T1), [])
        self.assertEqual(candidate.expectation_status, ExpectationStatus.UNKNOWN)

    def test_ambiguous_issuing_body_remains_unresolved(self) -> None:
        evidence = self.evidence(T1)
        candidate = extract_policy_candidate(
            evidence_id=evidence.provenance_id,
            text="Approved regulation 2.5% effective 2025-02-01",
            created_at=T1,
        )
        self.assertIsNone(candidate.issuing_body)
        self.assertEqual(candidate.explicit_values, ("2.5%",))

    def test_invalid_transition_fails_closed(self) -> None:
        e1, e2 = self.evidence(T1), self.evidence(T2)
        action = self.action(e1)
        self.repository.add_action(action)
        with self.assertRaises(ValidationError):
            self.repository.transition(
                action.action_id,
                from_status=GovernmentActionStatus.PROPOSED,
                to_status=GovernmentActionStatus.ENFORCED,
                transitioned_at=T2,
                evidence_ids=(e2.provenance_id,),
                rationale="Invalid skip",
            )

    def test_append_only_action_mutation_is_rejected(self) -> None:
        action = self.action(self.evidence(T1))
        self.repository.add_action(action)
        model = self.session.get(GovernmentActionModel, action.action_id)
        assert model is not None
        model.title = "mutated"
        with self.assertRaises(ImmutableRecordError):
            self.session.flush()

    def test_expectation_placeholder_is_always_unknown(self) -> None:
        expectation = PolicyExpectation(GovernmentActionType.MONETARY_POLICY, T1)
        self.assertEqual(expectation.status, ExpectationStatus.UNKNOWN)

    def test_policy_storage_telemetry(self) -> None:
        action = self.action(self.evidence(T1))
        self.repository.add_action(action)
        telemetry = measure_storage(self.session)
        self.assertEqual(telemetry.policy_documents_by_day[0].value, 1)
        self.assertEqual(telemetry.policy_transitions_by_day[0].value, 1)
        self.assertEqual(telemetry.policy_candidate_count, 0)

    def test_future_evidence_cannot_support_earlier_action(self) -> None:
        future = self.evidence(T2)
        action = self.action(
            future,
            first_observed_at=T1,
            announced_at=T1,
            published_at=T1,
        )
        with self.assertRaises(IntegrityViolation):
            self.repository.add_action(action)


class MockPolicyConnector(BankOfIsraelPolicyConnector):
    payload = (
        b'{"currentInterest":3.5,"nextInterestDate":"2025-02-24T00:00:00Z",'
        b'"lastUpdate":"2025-01-06T14:00:00Z"}'
    )

    def fetch(self, dataset: str) -> FetchedPayload:
        return FetchedPayload(self.payload, self.endpoint, "application/json")


class BoiPolicyConnectorTests(unittest.TestCase):
    def test_mocked_policy_ingestion_preserves_raw_and_dates(self) -> None:
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        with tempfile.TemporaryDirectory() as directory, Session(engine) as session:
            manifest = IngestionRunner(
                session,
                LocalArtifactStore(directory),
                clock=lambda: datetime(2025, 2, 25, tzinfo=UTC),
            ).run(MockPolicyConnector(), BankOfIsraelPolicyConnector.dataset_name)
            self.assertEqual(manifest.status.value, "succeeded")
            self.assertEqual(manifest.items_inserted, 2)
            self.assertEqual(manifest.raw_artifacts_created, 1)
        engine.dispose()

    def test_malformed_policy_timestamp_fails_closed(self) -> None:
        connector = MockPolicyConnector()
        connector.payload = (
            b'{"currentInterest":3.5,"nextInterestDate":"not-a-date",'
            b'"lastUpdate":"2025-01-06T14:00:00Z"}'
        )
        engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(engine)
        with tempfile.TemporaryDirectory() as directory, Session(engine) as session:
            manifest = IngestionRunner(
                session,
                LocalArtifactStore(directory),
                clock=lambda: datetime(2025, 2, 25, tzinfo=UTC),
            ).run(connector, connector.dataset_name)
            self.assertEqual(manifest.status.value, "failed")
            self.assertIn("malformed BOI policy timestamp", manifest.error_summary or "")
        engine.dispose()


if __name__ == "__main__":
    unittest.main()
