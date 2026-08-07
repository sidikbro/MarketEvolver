"""Small repository interfaces and SQLAlchemy implementations."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Generic, Protocol, TypeVar

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_evolver.errors import IntegrityViolation
from market_evolver.provenance import canonical_json
from market_evolver.schemas import (
    DecisionRecommendation,
    Event,
    Evidence,
    Hypothesis,
    ResearchDecision,
    Source,
    SourceKind,
    TrustLevel,
)
from market_evolver.storage.artifacts import Artifact
from market_evolver.storage.models import (
    ArtifactModel,
    EventModel,
    EvidenceModel,
    HypothesisModel,
    ResearchDecisionModel,
    SourceModel,
)
from market_evolver.time import require_aware_utc


class ProvenanceRecord(Protocol):
    @property
    def provenance_id(self) -> str: ...


RecordT = TypeVar("RecordT", bound=ProvenanceRecord)


class Repository(Protocol[RecordT]):
    def add(self, record: RecordT) -> RecordT: ...
    def get(self, provenance_id: str) -> RecordT | None: ...


class SourceRepository(Repository[Source], Protocol):
    pass


class EvidenceRepository(Repository[Evidence], Protocol):
    def visible_at(self, cutoff: datetime) -> list[Evidence]: ...


class EventRepository(Repository[Event], Protocol):
    pass


class HypothesisRepository(Repository[Hypothesis], Protocol):
    pass


class ResearchDecisionRepository(Repository[ResearchDecision], Protocol):
    pass


class _SqlRepository(Generic[RecordT]):
    model: type

    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, record: RecordT) -> RecordT:
        existing = self.session.get(self.model, record.provenance_id)
        if existing is not None:
            restored = self._to_domain(existing)
            if canonical_json(restored) != canonical_json(record):
                raise IntegrityViolation("provenance ID collision or immutable record mismatch")
            return restored
        self.session.add(self._to_model(record))
        self.session.flush()
        return record

    def get(self, provenance_id: str) -> RecordT | None:
        model = self.session.get(self.model, provenance_id)
        return None if model is None else self._to_domain(model)

    def _to_model(self, record: RecordT):  # type: ignore[no-untyped-def]
        raise NotImplementedError

    def _to_domain(self, model):  # type: ignore[no-untyped-def]
        raise NotImplementedError


class SqlSourceRepository(_SqlRepository[Source]):
    model = SourceModel

    def _to_model(self, record: Source) -> SourceModel:
        digest = record.content_digest.removeprefix("sha256:")
        artifact = self.session.get(ArtifactModel, digest)
        return SourceModel(
            provenance_id=record.provenance_id,
            uri=record.uri,
            kind=record.kind.value,
            publisher=record.publisher,
            published_at=record.published_at,
            observed_at=record.observed_at,
            ingested_at=record.ingested_at,
            effective_at=record.effective_at,
            trust=record.trust.value,
            content_digest=record.content_digest,
            mime_type=record.mime_type,
            artifact_sha256=None if artifact is None else digest,
        )

    def _to_domain(self, model: SourceModel) -> Source:
        return Source(
            uri=model.uri,
            kind=SourceKind(model.kind),
            publisher=model.publisher,
            published_at=None if model.published_at is None else _utc(model.published_at),
            observed_at=_utc(model.observed_at),
            ingested_at=_utc(model.ingested_at),
            effective_at=None if model.effective_at is None else _utc(model.effective_at),
            trust=TrustLevel(model.trust),
            content_digest=model.content_digest,
            mime_type=model.mime_type,
        )


class SqlEvidenceRepository(_SqlRepository[Evidence]):
    model = EvidenceModel

    def _to_model(self, record: Evidence) -> EvidenceModel:
        sources = [self.session.get(SourceModel, source_id) for source_id in record.source_ids]
        missing = [
            source_id
            for source_id, source in zip(record.source_ids, sources, strict=True)
            if source is None
        ]
        if missing:
            raise IntegrityViolation(f"unknown source provenance: {missing}")
        for source in sources:
            assert source is not None
            if _utc(source.observed_at) > record.observed_at:
                raise IntegrityViolation("evidence observed_at precedes its source")
        return EvidenceModel(
            provenance_id=record.provenance_id,
            claim=record.claim,
            source_ids=list(record.source_ids),
            observed_at=record.observed_at,
            excerpt_digest=record.excerpt_digest,
            embedding=None,
        )

    def _to_domain(self, model: EvidenceModel) -> Evidence:
        return Evidence(
            claim=model.claim,
            source_ids=tuple(model.source_ids),
            observed_at=_utc(model.observed_at),
            excerpt_digest=model.excerpt_digest,
        )

    def visible_at(self, cutoff: datetime) -> list[Evidence]:
        normalized = require_aware_utc(cutoff, "cutoff")
        statement = (
            select(EvidenceModel)
            .where(EvidenceModel.observed_at <= normalized)
            .order_by(EvidenceModel.observed_at, EvidenceModel.provenance_id)
        )
        return [self._to_domain(item) for item in self.session.scalars(statement)]


class SqlEventRepository(_SqlRepository[Event]):
    model = EventModel

    def _to_model(self, record: Event) -> EventModel:
        _require_ids(self.session, EvidenceModel, record.evidence_ids, "evidence")
        return EventModel(
            provenance_id=record.provenance_id,
            title=record.title,
            occurred_at=record.occurred_at,
            known_at=record.known_at,
            evidence_ids=list(record.evidence_ids),
        )

    def _to_domain(self, model: EventModel) -> Event:
        return Event(
            title=model.title,
            occurred_at=_utc(model.occurred_at),
            known_at=_utc(model.known_at),
            evidence_ids=tuple(model.evidence_ids),
        )


class SqlHypothesisRepository(_SqlRepository[Hypothesis]):
    model = HypothesisModel

    def _to_model(self, record: Hypothesis) -> HypothesisModel:
        _require_ids(self.session, EvidenceModel, record.evidence_ids, "evidence")
        _require_ids(self.session, EventModel, record.event_ids, "event")
        return HypothesisModel(
            provenance_id=record.provenance_id,
            statement=record.statement,
            as_of=record.as_of,
            evidence_ids=list(record.evidence_ids),
            event_ids=list(record.event_ids),
            confidence=record.confidence,
        )

    def _to_domain(self, model: HypothesisModel) -> Hypothesis:
        return Hypothesis(
            statement=model.statement,
            as_of=_utc(model.as_of),
            evidence_ids=tuple(model.evidence_ids),
            event_ids=tuple(model.event_ids),
            confidence=model.confidence,
        )


class SqlResearchDecisionRepository(_SqlRepository[ResearchDecision]):
    model = ResearchDecisionModel

    def _to_model(self, record: ResearchDecision) -> ResearchDecisionModel:
        _require_ids(self.session, HypothesisModel, record.hypothesis_ids, "hypothesis")
        _require_ids(self.session, EvidenceModel, record.evidence_ids, "evidence")
        hypotheses = [self.session.get(HypothesisModel, item) for item in record.hypothesis_ids]
        evidence = [self.session.get(EvidenceModel, item) for item in record.evidence_ids]
        if any(
            _utc(item.as_of) > record.knowledge_cutoff for item in hypotheses if item is not None
        ) or any(
            _utc(item.observed_at) > record.knowledge_cutoff
            for item in evidence
            if item is not None
        ):
            raise IntegrityViolation("decision provenance includes post-cutoff information")
        return ResearchDecisionModel(
            provenance_id=record.provenance_id,
            recommendation=record.recommendation.value,
            rationale=record.rationale,
            decided_at=record.decided_at,
            knowledge_cutoff=record.knowledge_cutoff,
            hypothesis_ids=list(record.hypothesis_ids),
            evidence_ids=list(record.evidence_ids),
        )

    def _to_domain(self, model: ResearchDecisionModel) -> ResearchDecision:
        return ResearchDecision(
            recommendation=DecisionRecommendation(model.recommendation),
            rationale=model.rationale,
            decided_at=_utc(model.decided_at),
            knowledge_cutoff=_utc(model.knowledge_cutoff),
            hypothesis_ids=tuple(model.hypothesis_ids),
            evidence_ids=tuple(model.evidence_ids),
        )


def add_artifact_metadata(session: Session, artifact: Artifact, created_at: datetime) -> Artifact:
    existing = session.get(ArtifactModel, artifact.sha256)
    if existing is not None:
        if (
            existing.size_bytes != artifact.size_bytes
            or existing.mime_type != artifact.mime_type
            or existing.relative_path != artifact.relative_path
        ):
            raise IntegrityViolation("artifact metadata mismatch")
        return artifact
    session.add(
        ArtifactModel(
            sha256=artifact.sha256,
            size_bytes=artifact.size_bytes,
            mime_type=artifact.mime_type,
            relative_path=artifact.relative_path,
            created_at=require_aware_utc(created_at, "created_at"),
        )
    )
    session.flush()
    return artifact


def _require_ids(session: Session, model: type, ids: tuple[str, ...], label: str) -> None:
    missing = [item for item in ids if session.get(model, item) is None]
    if missing:
        raise IntegrityViolation(f"unknown {label} provenance: {missing}")


def _utc(value: datetime) -> datetime:
    # SQLite drops timezone metadata; PostgreSQL preserves the instant.
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
