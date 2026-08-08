import unittest
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from market_evolver.errors import IntegrityViolation, ValidationError
from market_evolver.fusion.benchmark import run_false_rumor_benchmark
from market_evolver.fusion.engine import (
    calculate_metrics,
    calculate_reputation,
    classify_independence,
    current_corroboration_state,
    deterministic_match,
    fusion_score,
)
from market_evolver.fusion.repository import SqlFusionRepository
from market_evolver.fusion.schemas import (
    ClaimContradiction,
    ClaimLineage,
    ClaimResolution,
    ClaimStatus,
    CorroborationRecord,
    CorroborationState,
    FusionScore,
    IndependenceClass,
    LineageType,
    ResolutionOutcome,
    UnifiedClaim,
    UnifiedClaimType,
)
from market_evolver.storage.models import Base
from market_evolver.storage.telemetry import measure_storage

T0 = datetime(2025, 1, 1, tzinfo=UTC)
T1 = T0 + timedelta(days=1)
T2 = T0 + timedelta(days=2)


def claim(
    proposition="A defense contract was awarded",
    source="social.alpha",
    at=T0,
    evidence="e:1",
    claim_type=UnifiedClaimType.RUMOR,
):
    return UnifiedClaim(
        proposition,
        claim_type,
        ("company.elbit",),
        ("IL",),
        "defense",
        (evidence,),
        source,
        at,
        at,
        None,
        ClaimStatus.ACTIVE,
        0.5,
        (evidence,),
    )


class FusionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        self.repo = SqlFusionRepository(self.session)

    def tearDown(self):
        self.session.close()
        self.engine.dispose()

    def test_claim_type_and_timezone_validation(self):
        forecast = claim(claim_type=UnifiedClaimType.FORECAST)
        self.assertIs(forecast.claim_type, UnifiedClaimType.FORECAST)
        with self.assertRaises(ValidationError):
            claim(at=datetime(2025, 1, 1))  # noqa: DTZ001

    def test_deterministic_match_requires_identity_not_similarity(self):
        a = claim()
        b = claim(source="news.beta", at=T1, evidence="e:2")
        vague = claim("Contract expected soon", source="news.c", at=T1, evidence="e:3")
        self.assertTrue(deterministic_match(a, b))
        self.assertFalse(deterministic_match(a, vague))

    def test_claim_revision_cutoff(self):
        original = claim()
        self.repo.add_claim(original)
        revised = UnifiedClaim(
            "A smaller defense contract was awarded",
            original.claim_type,
            original.entities,
            original.geography,
            original.domain,
            ("e:2",),
            original.originating_source_id,
            T1,
            T1,
            None,
            ClaimStatus.CORRECTED,
            0.7,
            ("e:2",),
            2,
            original.claim_id,
        )
        self.repo.add_claim(revised)
        self.session.flush()
        self.assertEqual(self.repo.claims_visible_at(T0), (original,))
        self.assertEqual(self.repo.claims_visible_at(T1), (revised,))

    def test_lineage_cutoff_and_independence(self):
        origin = claim()
        copied = claim(source="news.copy", at=T1, evidence="e:2")
        self.repo.add_claim(origin)
        self.repo.add_claim(copied)
        edge = ClaimLineage(
            origin.claim_id,
            copied.claim_id,
            LineageType.COPIED_FROM,
            T1,
            ("e:2",),
            "exact fingerprint and declared source",
        )
        self.repo.add_lineage(edge)
        self.session.flush()
        self.assertEqual(self.repo.lineage_visible_at(T0), ())
        self.assertEqual(self.repo.lineage_visible_at(T1), (edge,))
        self.assertIs(
            classify_independence(copied, "news.copy", (edge,)),
            IndependenceClass.SAME_PRIMARY_SOURCE,
        )
        self.assertIs(classify_independence(origin, "news.copy", (edge,)), IndependenceClass.COPIED)

    def test_corroboration_and_future_confirmation_isolation(self):
        item = claim()
        self.repo.add_claim(item)
        record = CorroborationRecord(
            item.claim_id,
            "e:official",
            "official.boi",
            IndependenceClass.INDEPENDENT,
            CorroborationState.OFFICIALLY_CONFIRMED,
            T2,
            "official release",
        )
        self.repo.add_corroboration(record)
        self.session.flush()
        self.assertIs(
            current_corroboration_state(self.session, item.claim_id, T1),
            CorroborationState.UNCORROBORATED,
        )
        self.assertIs(
            current_corroboration_state(self.session, item.claim_id, T2),
            CorroborationState.OFFICIALLY_CONFIRMED,
        )

    def test_self_resolution_rejected_without_primary_authority(self):
        item = claim()
        self.repo.add_claim(item)
        resolution = ClaimResolution(
            item.claim_id,
            ResolutionOutcome.CONFIRMED,
            CorroborationState.RESOLVED,
            ("e:1",),
            ("social.alpha",),
            T1,
            "self assertion",
        )
        with self.assertRaises(IntegrityViolation):
            self.repo.add_resolution(resolution)

    def test_resolution_causal_ordering_fails_closed(self):
        item = claim(at=T1)
        self.repo.add_claim(item)
        resolution = ClaimResolution(
            item.claim_id,
            ResolutionOutcome.CONFIRMED,
            CorroborationState.RESOLVED,
            ("e:o",),
            ("official.mod",),
            T0,
            "impossible early resolution",
        )
        with self.assertRaises(IntegrityViolation):
            self.repo.add_resolution(resolution)

    def test_resolution_history_and_future_reputation_isolation(self):
        item = claim()
        self.repo.add_claim(item)
        resolution = ClaimResolution(
            item.claim_id,
            ResolutionOutcome.CONFIRMED,
            CorroborationState.RESOLVED,
            ("e:official",),
            ("official.mod",),
            T2,
            "official evidence",
        )
        self.repo.add_resolution(resolution)
        self.session.flush()
        early = calculate_reputation(self.session, "social.alpha", "defense", T1)
        late = calculate_reputation(self.session, "social.alpha", "defense", T2)
        self.assertEqual((early.confirmed, early.unresolved), (0, 1))
        self.assertEqual((late.confirmed, late.unresolved), (1, 0))

    def test_contradiction_preserves_both_sides(self):
        item = claim()
        self.repo.add_claim(item)
        contradiction = ClaimContradiction(
            item.claim_id,
            item.proposition,
            "No contract was awarded",
            ("e:1",),
            ("e:2",),
            T1,
            "unresolved",
            "scope may differ",
        )
        self.repo.add_contradiction(contradiction)
        self.session.flush()
        self.assertEqual(self.repo.contradictions_visible_at(T1), (contradiction,))

    def test_fusion_score_exposes_components(self):
        item = claim()
        score = fusion_score(
            item,
            authority=0.2,
            independence=IndependenceClass.INDEPENDENT,
            independent_count=2,
            provenance_complete=True,
            contradiction_count=1,
            temporally_consistent=True,
            historical_precision=None,
            calculated_at=T1,
        )
        self.assertIsInstance(score, FusionScore)
        self.assertAlmostEqual(score.contradiction_burden, 1 / 3)
        self.assertGreater(score.total, 0)

    def test_lead_time_by_source_class(self):
        item = claim()
        self.repo.add_claim(item)
        self.repo.add_corroboration(
            CorroborationRecord(
                item.claim_id,
                "e:n",
                "news.provider",
                IndependenceClass.INDEPENDENT,
                CorroborationState.WEAKLY_CORROBORATED,
                T1,
                "news report",
            )
        )
        self.repo.add_resolution(
            ClaimResolution(
                item.claim_id,
                ResolutionOutcome.CONFIRMED,
                CorroborationState.RESOLVED,
                ("e:o",),
                ("official.mod",),
                T2,
                "official confirmation",
            )
        )
        self.session.flush()
        lead = self.repo.lead_time(item.claim_id, T2)
        self.assertEqual(lead.first_news, T1)
        self.assertEqual(lead.confirmation_time, T2)

    def test_false_rumor_benchmark(self):
        result = run_false_rumor_benchmark()
        self.assertEqual(result.cases, 7)
        self.assertEqual(result.precision, 1.0)
        self.assertEqual(result.syndicated_false_independent_count, 1)
        self.assertEqual(result.future_reputation_leakage_rate, 0.0)

    def test_fusion_telemetry(self):
        item = claim()
        self.repo.add_claim(item)
        self.repo.add_resolution(
            ClaimResolution(
                item.claim_id,
                ResolutionOutcome.CONFIRMED,
                CorroborationState.RESOLVED,
                ("e:o",),
                ("official.mod",),
                T1,
                "official confirmation",
            )
        )
        self.session.flush()
        telemetry = measure_storage(self.session)
        self.assertEqual(telemetry.unified_claims_by_day[0].value, 1)
        self.assertEqual(telemetry.corroborated_claims_by_day[0].value, 1)
        self.assertEqual(telemetry.average_confirmation_lag_seconds, 86400)
        metrics = calculate_metrics(self.session, T1)
        self.assertEqual(metrics.claim_resolution_precision, 1.0)
        self.assertEqual(metrics.future_reputation_leakage_rate, 0.0)


if __name__ == "__main__":
    unittest.main()
