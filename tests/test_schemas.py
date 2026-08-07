import unittest
from datetime import UTC, datetime, timedelta

from market_evolver.errors import PointInTimeViolation, ValidationError
from market_evolver.schemas import (
    DecisionRecommendation,
    Evidence,
    ResearchDecision,
    Source,
    SourceKind,
)

NOW = datetime(2025, 1, 2, 12, tzinfo=UTC)


def source(observed_at: datetime = NOW) -> Source:
    return Source(
        uri="https://example.test/item",
        kind=SourceKind.NEWS,
        publisher="Example",
        published_at=NOW - timedelta(hours=1),
        observed_at=observed_at,
        ingested_at=observed_at,
        content_digest="sha256:abc",
    )


class SchemaTests(unittest.TestCase):
    def test_naive_timestamp_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValidationError, "timezone-aware"):
            source(datetime(2025, 1, 2, 12))  # noqa: DTZ001 - deliberately naive

    def test_impossible_source_timeline_is_rejected(self) -> None:
        with self.assertRaises(PointInTimeViolation):
            Source(
                uri="x",
                kind=SourceKind.NEWS,
                publisher="p",
                published_at=NOW,
                observed_at=NOW - timedelta(minutes=1),
                ingested_at=NOW,
            )

    def test_claim_without_provenance_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValidationError, "source provenance"):
            Evidence(claim="claim", source_ids=(), observed_at=NOW, excerpt_digest="sha256:x")

    def test_decision_rejects_lookahead_input(self) -> None:
        evidence = Evidence(
            claim="claim",
            source_ids=(source().provenance_id,),
            observed_at=NOW + timedelta(minutes=1),
            excerpt_digest="sha256:x",
        )
        decision = ResearchDecision(
            recommendation=DecisionRecommendation.WATCH,
            rationale="Needs more evidence",
            decided_at=NOW,
            knowledge_cutoff=NOW,
            hypothesis_ids=("hypothesis:sha256:x",),
            evidence_ids=(evidence.provenance_id,),
        )
        with self.assertRaises(PointInTimeViolation):
            decision.validate_inputs(evidence)


if __name__ == "__main__":
    unittest.main()
