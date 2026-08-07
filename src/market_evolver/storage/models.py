"""SQLAlchemy persistence models."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import JSON, BigInteger, DateTime, ForeignKey, String, event
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from market_evolver.errors import ImmutableRecordError


class Base(DeclarativeBase):
    pass


class ImmutableMixin:
    provenance_id: Mapped[str] = mapped_column(String(96), primary_key=True)


class ArtifactModel(Base):
    __tablename__ = "artifacts"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    relative_path: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SourceModel(ImmutableMixin, Base):
    __tablename__ = "sources"

    uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    publisher: Mapped[str] = mapped_column(String(512), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    ingested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    trust: Mapped[str] = mapped_column(String(32), nullable=False)
    content_digest: Mapped[str] = mapped_column(String(80), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    artifact_sha256: Mapped[str | None] = mapped_column(ForeignKey("artifacts.sha256"))


class EvidenceModel(ImmutableMixin, Base):
    __tablename__ = "evidence"

    claim: Mapped[str] = mapped_column(String, nullable=False)
    source_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    excerpt_digest: Mapped[str] = mapped_column(String(80), nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(1536).with_variant(JSON, "sqlite"), nullable=True
    )


class EventModel(ImmutableMixin, Base):
    __tablename__ = "events"

    title: Mapped[str] = mapped_column(String, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    known_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class HypothesisModel(ImmutableMixin, Base):
    __tablename__ = "hypotheses"

    statement: Mapped[str] = mapped_column(String, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    event_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)


class ResearchDecisionModel(ImmutableMixin, Base):
    __tablename__ = "research_decisions"

    recommendation: Mapped[str] = mapped_column(String(32), nullable=False)
    rationale: Mapped[str] = mapped_column(String, nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    knowledge_cutoff: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    hypothesis_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)


def _forbid_mutation(_mapper: Any, _connection: Any, target: Any) -> None:
    raise ImmutableRecordError(
        f"{type(target).__name__} {getattr(target, 'provenance_id', '')} is immutable"
    )


for _model in (
    ArtifactModel,
    SourceModel,
    EvidenceModel,
    EventModel,
    HypothesisModel,
    ResearchDecisionModel,
):
    event.listen(_model, "before_update", _forbid_mutation)
    event.listen(_model, "before_delete", _forbid_mutation)
