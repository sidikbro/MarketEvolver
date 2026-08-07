"""SQLAlchemy persistence models."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    event,
)
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
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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


class RawIngestionModel(Base):
    __tablename__ = "raw_ingestions"
    __table_args__ = (
        UniqueConstraint(
            "registry_source_id",
            "dataset",
            "artifact_sha256",
            name="uq_raw_ingestion_source_dataset_artifact",
        ),
    )

    receipt_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    registry_source_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    dataset: Mapped[str] = mapped_column(String(128), nullable=False)
    source_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(ForeignKey("artifacts.sha256"), nullable=False)
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class NormalizedObservationModel(ImmutableMixin, Base):
    __tablename__ = "normalized_observations"

    registry_source_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_record_id: Mapped[str] = mapped_column(ForeignKey("sources.provenance_id"))
    dataset: Mapped[str] = mapped_column(String(128), nullable=False)
    item_key: Mapped[str] = mapped_column(String(256), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    value: Mapped[str] = mapped_column(String(256), nullable=False)
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_artifact_sha256: Mapped[str] = mapped_column(ForeignKey("artifacts.sha256"), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)


class IngestionManifestModel(Base):
    __tablename__ = "ingestion_manifests"

    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    dataset: Mapped[str] = mapped_column(String(128), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    items_fetched: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duplicates: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bytes_downloaded: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    raw_artifacts_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    error_summary: Mapped[str | None] = mapped_column(String(2048))


class CanonicalEventModel(Base):
    __tablename__ = "canonical_events"
    __table_args__ = (
        UniqueConstraint(
            "deduplication_key",
            "material_fingerprint",
            name="uq_canonical_event_material",
        ),
    )

    event_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    source_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    geography: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    entities: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    sectors: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    affected_asset_classes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    event_status: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    novelty: Mapped[float] = mapped_column(nullable=False)
    revision_state: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    supersedes_event_id: Mapped[str | None] = mapped_column(ForeignKey("canonical_events.event_id"))
    causal_mechanisms: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    attributes: Mapped[list[list[str]]] = mapped_column(JSON, nullable=False)
    deduplication_key: Mapped[str] = mapped_column(String(512), nullable=False)
    material_fingerprint: Mapped[str] = mapped_column(String(96), nullable=False)


class EventSupportModel(Base):
    __tablename__ = "event_support"

    event_id: Mapped[str] = mapped_column(ForeignKey("canonical_events.event_id"), primary_key=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.provenance_id"), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.provenance_id"), primary_key=True)
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class EventTransitionModel(Base):
    __tablename__ = "event_transitions"
    __table_args__ = (
        UniqueConstraint(
            "event_id",
            "sequence",
            name="uq_event_transition_sequence",
        ),
    )

    transition_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("canonical_events.event_id"), nullable=False, index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(16))
    to_status: Mapped[str] = mapped_column(String(16), nullable=False)
    transitioned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    rationale: Mapped[str] = mapped_column(String, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    reviewer_status: Mapped[str] = mapped_column(String(24), nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)


class EventMechanismLinkModel(Base):
    __tablename__ = "event_mechanism_links"

    link_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("canonical_events.event_id"), nullable=False, index=True
    )
    mechanism_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    confidence: Mapped[float] = mapped_column(nullable=False)
    expected_horizon: Mapped[str] = mapped_column(String(16), nullable=False)
    rationale: Mapped[str] = mapped_column(String, nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    reviewer_status: Mapped[str] = mapped_column(String(24), nullable=False)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class KnowledgeEntityModel(Base):
    __tablename__ = "knowledge_entities"
    __table_args__ = (UniqueConstraint("entity_id", "version", name="uq_knowledge_entity_version"),)

    entity_version_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    canonical_name: Mapped[str] = mapped_column(String(512), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    hebrew_name: Mapped[str | None] = mapped_column(String(512))
    english_name: Mapped[str] = mapped_column(String(512), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    geography: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    identifiers: Mapped[list[list[str]]] = mapped_column(JSON, nullable=False)
    active_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    active_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    provenance: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class KnowledgeAliasModel(Base):
    __tablename__ = "knowledge_aliases"

    alias_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    alias: Mapped[str] = mapped_column(String(512), nullable=False)
    normalized_alias: Mapped[str] = mapped_column(String(512), nullable=False, index=True)
    entity_version_id: Mapped[str] = mapped_column(
        ForeignKey("knowledge_entities.entity_version_id"), nullable=False, index=True
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    provenance: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class KnowledgeRelationshipModel(Base):
    __tablename__ = "knowledge_relationships"
    __table_args__ = (
        UniqueConstraint(
            "source_entity",
            "target_entity",
            "relation_type",
            "version",
            name="uq_knowledge_relationship_version",
        ),
    )

    relationship_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    relation_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_entity: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    target_entity: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    confidence: Mapped[float] = mapped_column(nullable=False)
    provenance: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class KnowledgeExposureModel(Base):
    __tablename__ = "knowledge_exposures"
    __table_args__ = (
        UniqueConstraint(
            "subject_entity",
            "target_entity",
            "exposure_type",
            "version",
            name="uq_knowledge_exposure_version",
        ),
    )

    exposure_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    exposure_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    subject_entity: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    target_entity: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(24), nullable=False)
    strength: Mapped[str] = mapped_column(String(16), nullable=False)
    unit: Mapped[str | None] = mapped_column(String(64))
    value: Mapped[str | None] = mapped_column(String(128))
    effective_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    effective_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    confidence: Mapped[float] = mapped_column(nullable=False)
    source_evidence: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class NewsItemModel(Base):
    __tablename__ = "news_items"

    news_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body: Mapped[str] = mapped_column(String, nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_modified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    canonical_uri: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    content_hash: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    raw_artifact_sha256: Mapped[str] = mapped_column(ForeignKey("artifacts.sha256"), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    trust_class: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_security_class: Mapped[str] = mapped_column(String(32), nullable=False)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.provenance_id"), nullable=False)
    revision_of: Mapped[str | None] = mapped_column(String(96), index=True)
    extraction_status: Mapped[str] = mapped_column(String(24), nullable=False)
    quarantine_reason: Mapped[str | None] = mapped_column(String(1024))
    provenance: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    duplicate_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    normalized_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)


class NewsEntityModel(Base):
    __tablename__ = "news_entities"

    news_id: Mapped[str] = mapped_column(ForeignKey("news_items.news_id"), primary_key=True)
    entity_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    supporting_span: Mapped[str] = mapped_column(String(512), primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class NewsCandidateModel(Base):
    __tablename__ = "news_event_candidates"

    candidate_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    news_id: Mapped[str] = mapped_column(ForeignKey("news_items.news_id"), nullable=False)
    extracted_entities: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    possible_event_type: Mapped[str] = mapped_column(String(128), nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(128), nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    supporting_spans: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    review_state: Mapped[str] = mapped_column(String(24), nullable=False)


class NewsCandidateReviewModel(Base):
    __tablename__ = "news_candidate_reviews"

    review_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("news_event_candidates.candidate_id"), nullable=False, index=True
    )
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    reviewer: Mapped[str] = mapped_column(String(256), nullable=False)
    rationale: Mapped[str] = mapped_column(String, nullable=False)


class NewsCorroborationModel(Base):
    __tablename__ = "news_corroborations"

    corroboration_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("news_event_candidates.candidate_id"), nullable=False, index=True
    )
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    independence_assumptions: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    timestamp_ordering: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    contradictions: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class EvidenceContradictionModel(Base):
    __tablename__ = "evidence_contradictions"

    contradiction_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    evidence_a: Mapped[str] = mapped_column(ForeignKey("evidence.provenance_id"), nullable=False)
    evidence_b: Mapped[str] = mapped_column(ForeignKey("evidence.provenance_id"), nullable=False)
    contradiction_type: Mapped[str] = mapped_column(String(128), nullable=False)
    detected_by: Mapped[str] = mapped_column(String(128), nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class GovernmentActionModel(Base):
    __tablename__ = "government_actions"

    action_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    jurisdiction: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    issuing_body: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String, nullable=False)
    description_reference: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    announced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    supersedes_action_id: Mapped[str | None] = mapped_column(String(96), index=True)
    source_evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    affected_entities: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    affected_sectors: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    candidate_mechanisms: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    provenance: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    expectation_status: Mapped[str] = mapped_column(String(16), nullable=False)


class GovernmentTransitionModel(Base):
    __tablename__ = "government_transitions"

    transition_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    action_id: Mapped[str] = mapped_column(
        ForeignKey("government_actions.action_id"), nullable=False, index=True
    )
    from_status: Mapped[str | None] = mapped_column(String(24))
    to_status: Mapped[str] = mapped_column(String(24), nullable=False)
    transitioned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    rationale: Mapped[str] = mapped_column(String, nullable=False)
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)


class GovernmentCandidateModel(Base):
    __tablename__ = "government_action_candidates"

    candidate_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    issuing_body: Mapped[str | None] = mapped_column(String(128))
    possible_action_type: Mapped[str | None] = mapped_column(String(32))
    possible_transition: Mapped[str | None] = mapped_column(String(24))
    explicit_dates: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    explicit_values: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    entities: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    candidate_mechanisms: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(128), nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    review_state: Mapped[str] = mapped_column(String(24), nullable=False)
    expectation_status: Mapped[str] = mapped_column(String(16), nullable=False)


def _forbid_mutation(_mapper: Any, _connection: Any, target: Any) -> None:
    raise ImmutableRecordError(
        f"{type(target).__name__} {getattr(target, 'provenance_id', '')} is immutable"
    )


for _model in (
    ArtifactModel,
    CanonicalEventModel,
    EventMechanismLinkModel,
    EventSupportModel,
    EventTransitionModel,
    KnowledgeAliasModel,
    KnowledgeEntityModel,
    KnowledgeExposureModel,
    KnowledgeRelationshipModel,
    NewsCandidateModel,
    NewsCandidateReviewModel,
    NewsCorroborationModel,
    NewsEntityModel,
    NewsItemModel,
    EvidenceContradictionModel,
    GovernmentActionModel,
    GovernmentCandidateModel,
    GovernmentTransitionModel,
    SourceModel,
    EvidenceModel,
    EventModel,
    HypothesisModel,
    NormalizedObservationModel,
    RawIngestionModel,
    ResearchDecisionModel,
):
    event.listen(_model, "before_update", _forbid_mutation)
    event.listen(_model, "before_delete", _forbid_mutation)
