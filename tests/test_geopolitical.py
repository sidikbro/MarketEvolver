import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from market_evolver.errors import ImmutableRecordError, IntegrityViolation, ValidationError
from market_evolver.geopolitical.baselines import calculate_baseline
from market_evolver.geopolitical.corroboration import classify_corroboration
from market_evolver.geopolitical.extraction import extract_candidate
from market_evolver.geopolitical.repository import SqlGeopoliticalRepository
from market_evolver.geopolitical.schemas import (
    CandidateReviewState,
    ConfirmationState,
    CorroborationKind,
    GeopoliticalCandidateReview,
    GeopoliticalCorroboration,
    GeopoliticalEvent,
    GeopoliticalEventType,
    GeopoliticalStatus,
    TransmissionHorizon,
    TransmissionPath,
)
from market_evolver.geopolitical.transmission import templates_for
from market_evolver.market.store import MarketDataStore
from market_evolver.replay.engine import ReplayEngine
from market_evolver.replay.schemas import ReplayCase, ReplayCaseType
from market_evolver.storage.models import Base, EvidenceModel, GeopoliticalEventModel
from market_evolver.storage.telemetry import measure_storage

T0 = datetime(2025, 1, 1, 12, tzinfo=UTC)
T1 = T0 + timedelta(days=1)
T2 = T0 + timedelta(days=2)
T3 = T0 + timedelta(days=3)


class GeopoliticalLabTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.repository = SqlGeopoliticalRepository(self.session)
        self.add_evidence("evidence:rumor", T1, "Israel airport closed")
        self.add_evidence("evidence:official", T2, "Israel airport remains open")
        self.add_evidence("evidence:update", T3, "Israel airport reopened")

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def add_evidence(self, evidence_id: str, observed_at: datetime, claim: str) -> None:
        self.session.add(
            EvidenceModel(
                provenance_id=evidence_id,
                claim=claim,
                source_ids=(f"source:{evidence_id}",),
                observed_at=observed_at,
                excerpt_digest=f"sha256:{'a' * 64}",
                embedding=None,
            )
        )
        self.session.flush()

    def event(
        self,
        observed_at: datetime,
        state: ConfirmationState,
        *,
        event_type: GeopoliticalEventType = GeopoliticalEventType.AIRSPACE_DISRUPTION,
        evidence_id: str = "evidence:rumor",
        revision_of: str | None = None,
        version: int = 1,
        status: GeopoliticalStatus = GeopoliticalStatus.REPORTED,
        ended_at: datetime | None = None,
    ) -> GeopoliticalEvent:
        return GeopoliticalEvent(
            event_type,
            ("Israel",),
            ("Israel",),
            (evidence_id,),
            status,
            T1,
            T1,
            observed_at,
            ended_at,
            0.6 if state is ConfirmationState.UNVERIFIED else 0.95,
            state,
            revision_of,
            (evidence_id,),
            version,
        )

    def test_rumor_later_disproven_without_backward_leakage(self) -> None:
        rumor = self.event(T1, ConfirmationState.UNVERIFIED)
        contradicted = self.event(
            T2,
            ConfirmationState.CONTRADICTED,
            evidence_id="evidence:official",
            revision_of=rumor.event_id,
            version=2,
            status=GeopoliticalStatus.WITHDRAWN,
        )
        self.repository.add_event(rumor)
        self.repository.add_event(contradicted)
        self.assertEqual(self.repository.events_visible_at(T1), (rumor,))
        self.assertEqual(self.repository.events_visible_at(T2), (contradicted,))
        self.assertEqual(self.repository.get(rumor.event_id), rumor)

    def test_confirmation_after_cutoff_and_conflicting_reports(self) -> None:
        rumor = self.event(T1, ConfirmationState.UNVERIFIED)
        confirmed = self.event(
            T2,
            ConfirmationState.CONFIRMED,
            evidence_id="evidence:official",
            revision_of=rumor.event_id,
            version=2,
            status=GeopoliticalStatus.ONGOING,
        )
        self.repository.add_event(rumor)
        self.repository.add_event(confirmed)
        candidate = extract_candidate("Israel airport closed", "evidence:rumor", T1)
        self.repository.add_candidate(candidate)
        contradiction = GeopoliticalCorroboration(
            candidate.candidate_id,
            ("evidence:rumor", "evidence:official"),
            ("uk.bbc.business", "il.pmo.statements"),
            CorroborationKind.OFFICIAL_CONTRADICTION,
            T2,
            "Official statement contradicts the report.",
            0.9,
        )
        self.repository.add_corroboration(contradiction)
        self.assertEqual(
            self.repository.events_visible_at(T1)[0].confirmation_state,
            ConfirmationState.UNVERIFIED,
        )
        self.assertEqual(self.repository.corroborations_visible_at(T1), ())
        self.assertEqual(
            self.repository.events_visible_at(T2)[0].confirmation_state, ConfirmationState.CONFIRMED
        )
        self.assertEqual(self.repository.corroborations_visible_at(T2), (contradiction,))

    def test_ceasefire_violation_closure_reopening_and_sanction_amendment_are_versions(
        self,
    ) -> None:
        cases = (
            (
                GeopoliticalEventType.CEASEFIRE,
                GeopoliticalStatus.ANNOUNCED,
                GeopoliticalStatus.ONGOING,
            ),
            (
                GeopoliticalEventType.AIRSPACE_DISRUPTION,
                GeopoliticalStatus.ONGOING,
                GeopoliticalStatus.ENDED,
            ),
            (
                GeopoliticalEventType.SANCTIONS,
                GeopoliticalStatus.ONGOING,
                GeopoliticalStatus.AMENDED,
            ),
        )
        for index, (event_type, first_status, later_status) in enumerate(cases):
            original = self.event(
                T1, ConfirmationState.CONFIRMED, event_type=event_type, status=first_status
            )
            revised = self.event(
                T3,
                ConfirmationState.DISPUTED
                if event_type is GeopoliticalEventType.CEASEFIRE
                else ConfirmationState.RESOLVED,
                event_type=event_type,
                evidence_id="evidence:update",
                revision_of=original.event_id,
                version=2,
                status=later_status,
                ended_at=T3 if later_status is GeopoliticalStatus.ENDED else None,
            )
            self.repository.add_event(original)
            self.repository.add_event(revised)
            self.assertIn(original, self.repository.events_visible_at(T2))
            self.assertIn(revised, self.repository.events_visible_at(T3))
            self.assertEqual(revised.version, 2, index)

    def test_candidate_promotion_is_separate_and_governed(self) -> None:
        candidate = extract_candidate("Israel airspace closed", "evidence:rumor", T1)
        self.repository.add_candidate(candidate)
        event = self.event(
            T2, ConfirmationState.PARTIALLY_CONFIRMED, evidence_id="evidence:official"
        )
        with self.assertRaises(IntegrityViolation):
            self.repository.add_event(event, candidate_id=candidate.candidate_id)
        review = GeopoliticalCandidateReview(
            candidate.candidate_id,
            CandidateReviewState.PROMOTED,
            T2,
            "human-reviewer",
            "Explicit closure and named geography were verified.",
        )
        self.repository.review_candidate(review)
        self.assertTrue(self.repository.add_event(event, candidate_id=candidate.candidate_id))

    def test_syndicated_copy_is_not_independent_confirmation(self) -> None:
        candidate = extract_candidate("Israel airspace closed", "evidence:rumor", T1)
        self.repository.add_candidate(candidate)
        syndicated = GeopoliticalCorroboration(
            candidate.candidate_id,
            ("evidence:rumor", "evidence:rumor"),
            ("wire.copy", "wire.copy"),
            CorroborationKind.SYNDICATED,
            T1,
            "Identical source and evidence are a syndicated duplicate.",
            0.0,
        )
        self.repository.add_corroboration(syndicated)
        self.assertEqual(
            self.repository.corroborations_visible_at(T1)[0].kind, CorroborationKind.SYNDICATED
        )
        self.assertEqual(
            classify_corroboration(
                source_a="wire.a",
                fingerprint_a="same",
                source_b="publisher.b",
                fingerprint_b="same",
            ),
            CorroborationKind.SYNDICATED,
        )
        self.assertEqual(
            classify_corroboration(
                source_a="news",
                fingerprint_a="a",
                source_b="official",
                fingerprint_b="b",
                official_response=True,
                contradiction=True,
            ),
            CorroborationKind.OFFICIAL_CONTRADICTION,
        )

    def test_transmission_paths_support_opposite_uncertain_horizons_without_direction(self) -> None:
        event = self.event(T1, ConfirmationState.CONFIRMED, status=GeopoliticalStatus.ONGOING)
        self.repository.add_event(event)
        immediate = TransmissionPath(
            event.event_id,
            ("airline_capacity", "tourism_demand"),
            ("country.israel",),
            TransmissionHorizon.IMMEDIATE,
            0.8,
            "Closure can constrain capacity while active.",
            event.source_evidence_ids,
            T1,
            T2,
        )
        long = TransmissionPath(
            event.event_id,
            ("airline_capacity", "tourism_demand"),
            ("country.israel",),
            TransmissionHorizon.LONG,
            0.2,
            "Long-horizon consequence remains uncertain after reopening.",
            event.source_evidence_ids,
            T1,
        )
        self.repository.add_path(immediate)
        self.repository.add_path(long)
        self.assertEqual(self.repository.paths_visible_at(T1), (immediate, long))
        self.assertEqual(self.repository.paths_visible_at(T2), (long,))
        with self.assertRaises(ValidationError):
            TransmissionPath(
                event.event_id,
                ("tourism_demand",),
                (),
                TransmissionHorizon.SHORT,
                0.8,
                "Buy airlines because the market will rise.",
                event.source_evidence_ids,
                T1,
            )

    def test_extraction_ignores_casualty_forecast_outcome_and_future_timestamp(self) -> None:
        candidate = extract_candidate(
            "Israel airport closed. Casualties will reach 100. War outcome is certain. "
            "Reopens 2030-01-01T00:00:00Z.",
            "evidence:rumor",
            T1,
        )
        self.assertEqual(candidate.event_type, GeopoliticalEventType.AIRSPACE_DISRUPTION)
        self.assertEqual(candidate.explicit_timestamps, ())
        self.assertNotIn("casualty", " ".join(candidate.supporting_spans))

    def test_malformed_timestamps_and_revision_order_fail(self) -> None:
        with self.assertRaises(ValidationError):
            self.event(T1.replace(tzinfo=None), ConfirmationState.UNVERIFIED)
        original = self.event(T2, ConfirmationState.CONFIRMED)
        self.repository.add_event(original)
        revised = self.event(
            T1,
            ConfirmationState.RESOLVED,
            revision_of=original.event_id,
            version=2,
        )
        with self.assertRaises(IntegrityViolation):
            self.repository.add_event(revised)

    def test_baseline_templates_telemetry_and_append_only(self) -> None:
        event = self.event(T1, ConfirmationState.CONFIRMED, status=GeopoliticalStatus.ONGOING)
        self.repository.add_event(event)
        path = TransmissionPath(
            event.event_id,
            ("airline_capacity",),
            ("country.israel",),
            TransmissionHorizon.IMMEDIATE,
            0.8,
            "Capacity is an explicit candidate mechanism.",
            event.source_evidence_ids,
            T1,
        )
        self.repository.add_path(path)
        candidate = extract_candidate("Israel airport closed", "evidence:rumor", T1)
        self.repository.add_candidate(candidate)
        self.session.commit()
        baseline = calculate_baseline((event,), (path,), T2)
        self.assertTrue(baseline.event_present)
        self.assertEqual(baseline.confirmed_event_count, 1)
        self.assertEqual(baseline.mechanism_exposure_count, 1)
        self.assertTrue(templates_for(GeopoliticalEventType.AIRSPACE_DISRUPTION))
        telemetry = measure_storage(self.session)
        self.assertEqual(telemetry.geopolitical_replay_inclusions, 1)
        self.assertEqual(telemetry.geopolitical_affected_mechanisms, {"airline_capacity": 1})
        row = self.session.get(GeopoliticalEventModel, event.event_id)
        assert row is not None
        row.confidence = 0
        with self.assertRaises(ImmutableRecordError):
            self.session.flush()

    def test_replay_includes_only_cutoff_visible_geopolitical_state(self) -> None:
        rumor = self.event(T1, ConfirmationState.UNVERIFIED)
        confirmed = self.event(
            T2,
            ConfirmationState.CONFIRMED,
            evidence_id="evidence:official",
            revision_of=rumor.event_id,
            version=2,
            status=GeopoliticalStatus.ONGOING,
        )
        self.repository.add_event(rumor)
        self.repository.add_event(confirmed)
        path = TransmissionPath(
            confirmed.event_id,
            ("airline_capacity",),
            ("country.israel",),
            TransmissionHorizon.SHORT,
            0.7,
            "Capacity is a candidate mechanism.",
            ("evidence:official",),
            T2,
        )
        self.repository.add_path(path)
        case = ReplayCase(
            ReplayCaseType.QUIET,
            ("country.israel",),
            ("asset.fx.usdils",),
            T1,
            "1 month",
            "manifest:geo",
            None,
            "research-hypothesis/v1",
            "geo-outcome/1",
            "geo-test/1",
            T1,
        )
        with tempfile.TemporaryDirectory() as directory:
            snapshot = ReplayEngine(
                self.session, MarketDataStore(self.session, Path(directory))
            ).snapshot(case)
        self.assertEqual(snapshot.geopolitical_event_ids, (rumor.event_id,))
        self.assertEqual(snapshot.geopolitical_path_ids, ())


if __name__ == "__main__":
    unittest.main()
