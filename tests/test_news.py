import hashlib
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from market_evolver.errors import (
    GovernanceViolation,
    ImmutableRecordError,
    IntegrityViolation,
    ValidationError,
)
from market_evolver.ingestion.connectors import FetchedPayload
from market_evolver.knowledge.seed import seed_knowledge_graph
from market_evolver.news.connectors import BbcBusinessRssConnector
from market_evolver.news.extraction import detect_language
from market_evolver.news.repositories import SqlNewsRepository
from market_evolver.news.runner import NewsIngestionRunner
from market_evolver.news.schemas import (
    CandidateReview,
    ContradictionStatus,
    Corroboration,
    DuplicateKind,
    EvidenceContradiction,
    EvidenceSecurityClass,
    ReviewState,
    classify_evidence_security,
)
from market_evolver.sources.registry import DEFAULT_REGISTRY
from market_evolver.storage.artifacts import LocalArtifactStore
from market_evolver.storage.models import (
    Base,
    EvidenceModel,
    NewsItemModel,
    RawIngestionModel,
)
from market_evolver.storage.telemetry import measure_storage

T1 = datetime(2025, 1, 3, 12, tzinfo=UTC)
T2 = T1 + timedelta(days=1)


def feed(
    *,
    title: str = "Bank of Israel discusses USD and ILS",
    body: str = "Israel update from the Bank of Israel.",
    uri: str = "https://www.bbc.co.uk/news/business-123",
    published: str = "Thu, 02 Jan 2025 10:00:00 GMT",
) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><item>
<title>{title}</title><description>{body}</description>
<link>{uri}</link><pubDate>{published}</pubDate>
</item></channel></rss>""".encode()


class MockNewsConnector(BbcBusinessRssConnector):
    def __init__(
        self,
        payload: bytes,
        source_uri: str = BbcBusinessRssConnector.endpoint,
        content_type: str = "application/rss+xml",
    ) -> None:
        self.payload = payload
        self.source_uri = source_uri
        self.content_type = content_type

    def fetch(self) -> FetchedPayload:
        return FetchedPayload(self.payload, self.source_uri, self.content_type)


class Clock:
    def __init__(self, at: datetime) -> None:
        self.at = at

    def __call__(self) -> datetime:
        result = self.at
        self.at += timedelta(seconds=1)
        return result


class NewsLabTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.store = LocalArtifactStore(self.directory.name)
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        seed_knowledge_graph(self.session)
        self.session.commit()

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()
        self.directory.cleanup()

    def run_feed(self, payload: bytes, at: datetime = T1) -> tuple[int, int, int]:
        return NewsIngestionRunner(self.session, self.store, clock=Clock(at)).run(
            MockNewsConnector(payload)
        )

    def test_raw_before_parse_untrusted_boundary_and_entity_extraction(self) -> None:
        self.assertEqual(self.run_feed(feed()), (1, 0, 0))
        repository = SqlNewsRepository(self.session)
        item = repository.get_news_visible_at(T1 + timedelta(minutes=1))[0]
        self.assertEqual(item.evidence_security_class.value, "untrusted_unstructured")
        self.assertEqual(item.language, "en")
        self.assertTrue(self.store.exists(item.raw_artifact_sha256))
        receipt = self.session.query(RawIngestionModel).one()
        self.assertEqual(receipt.source_uri, BbcBusinessRssConnector.endpoint)
        self.assertIn(receipt.receipt_id, item.provenance)
        candidate = repository.get_event_candidates_visible_at(T1 + timedelta(minutes=1))[0]
        self.assertIn("institution.boi", candidate.extracted_entities)
        self.assertIn("currency.usd", candidate.extracted_entities)
        self.assertIn("country.il", candidate.extracted_entities)

    def test_registry_trust_maps_to_security_without_asserting_truth(self) -> None:
        official = DEFAULT_REGISTRY.get("il.boi")
        news = DEFAULT_REGISTRY.get("uk.bbc.business")
        self.assertEqual(
            classify_evidence_security(official, structured=True),
            EvidenceSecurityClass.TRUSTED_STRUCTURED,
        )
        self.assertEqual(
            classify_evidence_security(official, structured=False),
            EvidenceSecurityClass.TRUSTED_UNSTRUCTURED,
        )
        self.assertEqual(
            classify_evidence_security(news, structured=True),
            EvidenceSecurityClass.UNTRUSTED_UNSTRUCTURED,
        )

    def test_hebrew_english_and_mixed_language_detection(self) -> None:
        self.run_feed(
            feed(
                title="בנק ישראל Bank of Israel",
                body="ישראל USD ILS",
                uri="https://www.bbc.co.uk/news/business-456",
            )
        )
        item = SqlNewsRepository(self.session).get_news_visible_at(T2)[0]
        self.assertEqual(item.language, "mixed")
        entities = (
            SqlNewsRepository(self.session)
            .get_event_candidates_visible_at(T2)[0]
            .extracted_entities
        )
        self.assertIn("institution.boi", entities)
        self.assertEqual(detect_language("חדשות"), "he")

    def test_reingestion_revision_and_historical_replay(self) -> None:
        original = feed()
        edited = feed(body="Edited Israel update with explicit EUR.")
        self.assertEqual(self.run_feed(original, T1), (1, 0, 0))
        self.assertEqual(self.run_feed(original, T2), (0, 1, 0))
        self.assertEqual(self.run_feed(edited, T2), (1, 0, 0))

        repository = SqlNewsRepository(self.session)
        at_t1 = repository.get_news_visible_at(T1 + timedelta(hours=1))
        after_t2 = repository.get_news_visible_at(T2 + timedelta(hours=1))
        self.assertEqual(len(at_t1), 1)
        self.assertEqual(len(after_t2), 2)
        revision = next(item for item in after_t2 if item.duplicate_kind is DuplicateKind.REVISION)
        self.assertEqual(revision.revision_of, at_t1[0].news_id)

    def test_malformed_timestamp_and_corrupt_encoding_are_quarantined(self) -> None:
        self.assertEqual(self.run_feed(feed(published="not-a-date")), (0, 0, 1))
        self.assertEqual(self.run_feed(b"\xff\xfe broken xml", T2), (0, 0, 1))
        quarantined = SqlNewsRepository(self.session).quarantined(T2 + timedelta(hours=1))
        self.assertEqual(len(quarantined), 2)
        self.assertTrue(all(item.quarantine_reason for item in quarantined))

    def test_source_contract_violation_is_quarantined_after_raw_storage(self) -> None:
        connector = MockNewsConnector(feed(), source_uri="https://example.com/impersonation")
        result = NewsIngestionRunner(self.session, self.store, clock=Clock(T1)).run(connector)
        self.assertEqual(result, (0, 0, 1))
        item = SqlNewsRepository(self.session).quarantined(T2)[0]
        self.assertTrue(self.store.exists(item.raw_artifact_sha256))
        self.assertIn("source contract", item.quarantine_reason or "")

    def test_content_hash_mismatch_is_rejected(self) -> None:
        self.run_feed(feed())
        item = SqlNewsRepository(self.session).get_news_visible_at(T2)[0]
        with self.assertRaises(ValidationError):
            replace(item, content_hash="sha256:" + "0" * 64)
        with self.assertRaises(IntegrityViolation):
            self.store.put(b"body", mime_type="text/plain", expected_sha256="0" * 64)

    def test_untrusted_candidate_cannot_be_promoted_and_reviews_do_not_leak(self) -> None:
        self.run_feed(feed())
        repository = SqlNewsRepository(self.session)
        candidate = repository.get_event_candidates_visible_at(T2)[0]
        with self.assertRaises(GovernanceViolation):
            repository.record_review(
                CandidateReview(
                    candidate_id=candidate.candidate_id,
                    state=ReviewState.PROMOTED,
                    reviewed_at=T2,
                    reviewer="test-reviewer",
                    rationale="Must fail.",
                )
            )
        repository.record_review(
            CandidateReview(
                candidate_id=candidate.candidate_id,
                state=ReviewState.CORROBORATED,
                reviewed_at=T2,
                reviewer="test-reviewer",
                rationale="Independent evidence reviewed.",
            )
        )
        self.assertEqual(
            repository.get_event_candidates_visible_at(T1 + timedelta(hours=1))[0].review_state,
            ReviewState.UNREVIEWED,
        )
        self.assertEqual(
            repository.get_event_candidates_visible_at(T2)[0].review_state,
            ReviewState.CORROBORATED,
        )

    def test_future_corroboration_does_not_leak(self) -> None:
        self.run_feed(feed())
        self.run_feed(
            feed(
                title="Second explicit Israel report",
                body="Bank of Israel and USD are explicitly named.",
                uri="https://www.bbc.co.uk/news/business-independent",
            ),
            T1 + timedelta(hours=1),
        )
        repository = SqlNewsRepository(self.session)
        news = repository.get_news_visible_at(T2)
        candidate = repository.get_event_candidates_visible_at(T2)[0]
        evidence = [self.session.get(EvidenceModel, news_item.evidence_id) for news_item in news]
        assert evidence[0] is not None and evidence[1] is not None
        record = Corroboration(
            candidate_id=candidate.candidate_id,
            evidence_ids=(news[0].evidence_id, news[1].evidence_id),
            source_ids=(evidence[0].source_ids[0], evidence[1].source_ids[0]),
            independence_assumptions=("time-isolation fixture; independence not established",),
            timestamp_ordering=("first then second",),
            confidence=0.6,
            contradictions=(),
            created_at=T2,
        )
        repository.add_corroboration(record)
        self.assertEqual(repository.corroborations_visible_at(T1), [])
        self.assertEqual(repository.corroborations_visible_at(T2), [record])

    def test_alias_ambiguity_does_not_guess(self) -> None:
        self.run_feed(
            feed(
                title="Bank reports update",
                body="No canonical exact entity name.",
                uri="https://www.bbc.co.uk/news/business-789",
            )
        )
        candidate = SqlNewsRepository(self.session).get_event_candidates_visible_at(T2)[0]
        self.assertNotIn("sector.banks", candidate.extracted_entities)

    def test_contradiction_is_preserved(self) -> None:
        self.run_feed(feed())
        self.run_feed(
            feed(
                title="Israel report differs",
                body="A contradictory explicit fact.",
                uri="https://www.bbc.co.uk/news/business-999",
            ),
            T2,
        )
        news = SqlNewsRepository(self.session).get_news_visible_at(T2 + timedelta(hours=1))
        contradiction = EvidenceContradiction(
            evidence_a=news[0].evidence_id,
            evidence_b=news[1].evidence_id,
            contradiction_type="explicit_value_disagreement",
            detected_by="manual-test",
            confidence=0.8,
            status=ContradictionStatus.OPEN,
            created_at=T2 + timedelta(minutes=1),
        )
        repository = SqlNewsRepository(self.session)
        repository.add_contradiction(contradiction)
        self.assertEqual(repository.contradictions_visible_at(T1), [])
        self.assertEqual(
            repository.contradictions_visible_at(T2 + timedelta(hours=1)), [contradiction]
        )

    def test_telemetry_and_immutable_news(self) -> None:
        payload = feed()
        self.run_feed(payload)
        item = self.session.query(NewsItemModel).one()
        item.title = "mutation"
        with self.assertRaises(ImmutableRecordError):
            self.session.flush()
        self.session.rollback()
        telemetry = measure_storage(self.session)
        self.assertEqual(telemetry.news_items_by_day[0].value, 1)
        self.assertEqual(telemetry.raw_news_bytes_by_day[0].value, len(payload))
        self.assertEqual(telemetry.news_items_by_source, {"uk.bbc.business": 1})
        self.assertEqual(telemetry.news_bytes_by_source, {"uk.bbc.business": len(payload)})

    def test_syndication_fingerprint_is_not_independent(self) -> None:
        self.run_feed(feed())
        item = SqlNewsRepository(self.session).get_news_visible_at(T2)[0]
        kind, related = SqlNewsRepository(self.session).classify_duplicate(
            source_id="other.publisher",
            canonical_uri="https://example.com/copy",
            content_hash="sha256:" + hashlib.sha256(b"different").hexdigest(),
            fingerprint=item.normalized_fingerprint,
        )
        self.assertEqual(kind, DuplicateKind.SYNDICATED)
        self.assertEqual(related, item.news_id)


if __name__ == "__main__":
    unittest.main()
