"""News persistence, replay, review, corroboration, and contradiction records."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_evolver.errors import GovernanceViolation, IntegrityViolation
from market_evolver.news.schemas import (
    CandidateReview,
    ContradictionStatus,
    Corroboration,
    DuplicateKind,
    EvidenceContradiction,
    EvidenceSecurityClass,
    ExtractionStatus,
    NewsEventCandidate,
    NewsItem,
    ReviewState,
)
from market_evolver.sources.registry import TrustClass
from market_evolver.storage.models import (
    ArtifactModel,
    EvidenceContradictionModel,
    EvidenceModel,
    NewsCandidateModel,
    NewsCandidateReviewModel,
    NewsCorroborationModel,
    NewsEntityModel,
    NewsItemModel,
)
from market_evolver.time import require_aware_utc


class SqlNewsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def classify_duplicate(
        self, *, source_id: str, canonical_uri: str, content_hash: str, fingerprint: str
    ) -> tuple[DuplicateKind, str | None]:
        exact = self.session.scalar(
            select(NewsItemModel).where(
                NewsItemModel.source_id == source_id,
                NewsItemModel.canonical_uri == canonical_uri,
                NewsItemModel.content_hash == content_hash,
            )
        )
        if exact is not None:
            return DuplicateKind.REINGESTED, exact.news_id
        prior_uri = self.session.scalar(
            select(NewsItemModel)
            .where(
                NewsItemModel.source_id == source_id,
                NewsItemModel.canonical_uri == canonical_uri,
            )
            .order_by(NewsItemModel.first_observed_at.desc())
            .limit(1)
        )
        if prior_uri is not None:
            return DuplicateKind.REVISION, prior_uri.news_id
        syndicated = self.session.scalar(
            select(NewsItemModel).where(
                NewsItemModel.normalized_fingerprint == fingerprint,
                NewsItemModel.source_id != source_id,
            )
        )
        if syndicated is not None:
            return DuplicateKind.SYNDICATED, syndicated.news_id
        return DuplicateKind.ORIGINAL, None

    def add_news(self, item: NewsItem) -> tuple[NewsItem, bool]:
        existing = self.session.get(NewsItemModel, item.news_id)
        if existing is not None:
            restored = self._news(existing)
            if restored != item:
                raise IntegrityViolation("immutable news identity collision")
            return restored, False
        if self.session.get(ArtifactModel, item.raw_artifact_sha256) is None:
            raise IntegrityViolation("news references unknown raw artifact")
        if self.session.get(EvidenceModel, item.evidence_id) is None:
            raise IntegrityViolation("news references unknown evidence")
        if (
            item.revision_of is not None
            and self.session.get(NewsItemModel, item.revision_of) is None
        ):
            raise IntegrityViolation("news revision references unknown original")
        self.session.add(
            NewsItemModel(
                news_id=item.news_id,
                source_id=item.source_id,
                title=item.title,
                body=item.body,
                language=item.language,
                published_at=item.published_at,
                first_observed_at=item.first_observed_at,
                updated_at=item.updated_at,
                last_modified_at=item.last_modified_at,
                canonical_uri=item.canonical_uri,
                content_hash=item.content_hash,
                raw_artifact_sha256=item.raw_artifact_sha256,
                parser_version=item.parser_version,
                trust_class=item.trust_class.value,
                evidence_security_class=item.evidence_security_class.value,
                evidence_id=item.evidence_id,
                revision_of=item.revision_of,
                extraction_status=item.extraction_status.value,
                quarantine_reason=item.quarantine_reason,
                provenance=list(item.provenance),
                duplicate_kind=item.duplicate_kind.value,
                normalized_fingerprint=item.normalized_fingerprint,
            )
        )
        self.session.flush()
        return item, True

    def add_candidate(self, candidate: NewsEventCandidate) -> tuple[NewsEventCandidate, bool]:
        if self.session.get(NewsItemModel, candidate.news_id) is None:
            raise IntegrityViolation("candidate references unknown news")
        existing = self.session.get(NewsCandidateModel, candidate.candidate_id)
        if existing is not None:
            return self._candidate(existing), False
        self.session.add(
            NewsCandidateModel(
                candidate_id=candidate.candidate_id,
                news_id=candidate.news_id,
                extracted_entities=list(candidate.extracted_entities),
                possible_event_type=candidate.possible_event_type,
                extraction_method=candidate.extraction_method,
                confidence=candidate.confidence,
                supporting_spans=list(candidate.supporting_spans),
                created_at=candidate.created_at,
                review_state=candidate.review_state.value,
            )
        )
        for entity_id, span in zip(
            candidate.extracted_entities, candidate.supporting_spans, strict=False
        ):
            self.session.add(
                NewsEntityModel(
                    news_id=candidate.news_id,
                    entity_id=entity_id,
                    supporting_span=span,
                    observed_at=candidate.created_at,
                )
            )
        self.session.flush()
        return candidate, True

    def record_review(self, review: CandidateReview) -> CandidateReview:
        candidate = self.session.get(NewsCandidateModel, review.candidate_id)
        if candidate is None:
            raise IntegrityViolation("review references unknown candidate")
        news = self.session.get(NewsItemModel, candidate.news_id)
        assert news is not None
        if review.reviewed_at < _utc(candidate.created_at):
            raise IntegrityViolation("review predates candidate")
        if review.state is ReviewState.PROMOTED:
            if news.evidence_security_class in {
                EvidenceSecurityClass.UNTRUSTED_UNSTRUCTURED.value,
                EvidenceSecurityClass.QUARANTINED.value,
            }:
                raise GovernanceViolation("untrusted or quarantined news cannot be promoted")
            current = self._review_state(candidate.candidate_id, review.reviewed_at)
            if current is not ReviewState.CORROBORATED:
                raise GovernanceViolation("promotion requires prior corroboration")
        if self.session.get(NewsCandidateReviewModel, review.review_id) is None:
            self.session.add(
                NewsCandidateReviewModel(
                    review_id=review.review_id,
                    candidate_id=review.candidate_id,
                    state=review.state.value,
                    reviewed_at=review.reviewed_at,
                    reviewer=review.reviewer,
                    rationale=review.rationale,
                )
            )
            self.session.flush()
        return review

    def add_corroboration(self, record: Corroboration) -> Corroboration:
        if self.session.get(NewsCandidateModel, record.candidate_id) is None:
            raise IntegrityViolation("corroboration references unknown candidate")
        evidence = [self.session.get(EvidenceModel, item) for item in record.evidence_ids]
        if any(item is None for item in evidence):
            raise IntegrityViolation("corroboration references unknown evidence")
        if any(_utc(item.observed_at) > record.created_at for item in evidence if item):
            raise IntegrityViolation("corroboration predates evidence")
        if self.session.get(NewsCorroborationModel, record.corroboration_id) is None:
            self.session.add(
                NewsCorroborationModel(
                    corroboration_id=record.corroboration_id,
                    candidate_id=record.candidate_id,
                    evidence_ids=list(record.evidence_ids),
                    source_ids=list(record.source_ids),
                    independence_assumptions=list(record.independence_assumptions),
                    timestamp_ordering=list(record.timestamp_ordering),
                    confidence=record.confidence,
                    contradictions=list(record.contradictions),
                    created_at=record.created_at,
                )
            )
            self.session.flush()
        return record

    def add_contradiction(self, record: EvidenceContradiction) -> EvidenceContradiction:
        if any(
            self.session.get(EvidenceModel, item) is None
            for item in (record.evidence_a, record.evidence_b)
        ):
            raise IntegrityViolation("contradiction references unknown evidence")
        if self.session.get(EvidenceContradictionModel, record.contradiction_id) is None:
            self.session.add(
                EvidenceContradictionModel(
                    contradiction_id=record.contradiction_id,
                    evidence_a=record.evidence_a,
                    evidence_b=record.evidence_b,
                    contradiction_type=record.contradiction_type,
                    detected_by=record.detected_by,
                    confidence=record.confidence,
                    status=record.status.value,
                    created_at=record.created_at,
                )
            )
            self.session.flush()
        return record

    def corroborations_visible_at(self, cutoff: datetime) -> list[Corroboration]:
        at = require_aware_utc(cutoff, "cutoff")
        models = self.session.scalars(
            select(NewsCorroborationModel).where(NewsCorroborationModel.created_at <= at)
        )
        return [
            Corroboration(
                candidate_id=item.candidate_id,
                evidence_ids=tuple(item.evidence_ids),
                source_ids=tuple(item.source_ids),
                independence_assumptions=tuple(item.independence_assumptions),
                timestamp_ordering=tuple(item.timestamp_ordering),
                confidence=item.confidence,
                contradictions=tuple(item.contradictions),
                created_at=_utc(item.created_at),
            )
            for item in models
        ]

    def get(self, news_id: str) -> NewsItem | None:
        model = self.session.get(NewsItemModel, news_id)
        return None if model is None else self._news(model)

    def get_news_visible_at(self, cutoff: datetime) -> list[NewsItem]:
        at = require_aware_utc(cutoff, "cutoff")
        models = self.session.scalars(
            select(NewsItemModel)
            .where(NewsItemModel.first_observed_at <= at)
            .order_by(NewsItemModel.first_observed_at, NewsItemModel.news_id)
        )
        return [self._news(item) for item in models]

    def get_news_for_entity(self, entity_id: str, cutoff: datetime) -> list[NewsItem]:
        at = require_aware_utc(cutoff, "cutoff")
        models = self.session.scalars(
            select(NewsItemModel)
            .join(NewsEntityModel, NewsEntityModel.news_id == NewsItemModel.news_id)
            .where(
                NewsEntityModel.entity_id == entity_id,
                NewsEntityModel.observed_at <= at,
                NewsItemModel.first_observed_at <= at,
            )
            .order_by(NewsItemModel.first_observed_at, NewsItemModel.news_id)
        )
        return [self._news(item) for item in models]

    def get_event_candidates_visible_at(self, cutoff: datetime) -> list[NewsEventCandidate]:
        at = require_aware_utc(cutoff, "cutoff")
        models = self.session.scalars(
            select(NewsCandidateModel)
            .where(NewsCandidateModel.created_at <= at)
            .order_by(NewsCandidateModel.created_at, NewsCandidateModel.candidate_id)
        )
        return [
            replace(self._candidate(item), review_state=self._review_state(item.candidate_id, at))
            for item in models
        ]

    def quarantined(self, cutoff: datetime) -> list[NewsItem]:
        at = require_aware_utc(cutoff, "cutoff")
        models = self.session.scalars(
            select(NewsItemModel).where(
                NewsItemModel.first_observed_at <= at,
                NewsItemModel.evidence_security_class == EvidenceSecurityClass.QUARANTINED.value,
            )
        )
        return [self._news(item) for item in models]

    def contradictions_visible_at(self, cutoff: datetime) -> list[EvidenceContradiction]:
        at = require_aware_utc(cutoff, "cutoff")
        models = self.session.scalars(
            select(EvidenceContradictionModel).where(EvidenceContradictionModel.created_at <= at)
        )
        return [
            EvidenceContradiction(
                evidence_a=item.evidence_a,
                evidence_b=item.evidence_b,
                contradiction_type=item.contradiction_type,
                detected_by=item.detected_by,
                confidence=item.confidence,
                status=ContradictionStatus(item.status),
                created_at=_utc(item.created_at),
            )
            for item in models
        ]

    def _review_state(self, candidate_id: str, cutoff: datetime) -> ReviewState:
        model = self.session.scalar(
            select(NewsCandidateReviewModel)
            .where(
                NewsCandidateReviewModel.candidate_id == candidate_id,
                NewsCandidateReviewModel.reviewed_at <= cutoff,
            )
            .order_by(
                NewsCandidateReviewModel.reviewed_at.desc(),
                NewsCandidateReviewModel.review_id.desc(),
            )
            .limit(1)
        )
        return ReviewState.UNREVIEWED if model is None else ReviewState(model.state)

    @staticmethod
    def _news(model: NewsItemModel) -> NewsItem:
        item = NewsItem(
            source_id=model.source_id,
            title=model.title,
            body=model.body,
            language=model.language,
            published_at=_utc(model.published_at),
            first_observed_at=_utc(model.first_observed_at),
            updated_at=_utc_optional(model.updated_at),
            last_modified_at=_utc_optional(model.last_modified_at),
            canonical_uri=model.canonical_uri,
            content_hash=model.content_hash,
            raw_artifact_sha256=model.raw_artifact_sha256,
            parser_version=model.parser_version,
            trust_class=TrustClass(model.trust_class),
            evidence_security_class=EvidenceSecurityClass(model.evidence_security_class),
            evidence_id=model.evidence_id,
            revision_of=model.revision_of,
            extraction_status=ExtractionStatus(model.extraction_status),
            quarantine_reason=model.quarantine_reason,
            provenance=tuple(model.provenance),
            duplicate_kind=DuplicateKind(model.duplicate_kind),
            normalized_fingerprint=model.normalized_fingerprint,
        )
        if item.news_id != model.news_id:
            raise IntegrityViolation("stored news failed identity verification")
        return item

    @staticmethod
    def _candidate(model: NewsCandidateModel) -> NewsEventCandidate:
        candidate = NewsEventCandidate(
            news_id=model.news_id,
            extracted_entities=tuple(model.extracted_entities),
            possible_event_type=model.possible_event_type,
            extraction_method=model.extraction_method,
            confidence=model.confidence,
            supporting_spans=tuple(model.supporting_spans),
            created_at=_utc(model.created_at),
            review_state=ReviewState(model.review_state),
        )
        if candidate.candidate_id != model.candidate_id:
            raise IntegrityViolation("stored candidate failed identity verification")
        return candidate


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _utc_optional(value: datetime | None) -> datetime | None:
    return None if value is None else _utc(value)
