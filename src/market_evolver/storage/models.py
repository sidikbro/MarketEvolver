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
    Text,
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


class CompanyModel(Base):
    __tablename__ = "companies"

    company_version_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    legal_name: Mapped[str] = mapped_column(String(512), nullable=False)
    hebrew_name: Mapped[str | None] = mapped_column(String(512))
    english_name: Mapped[str] = mapped_column(String(512), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    listings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    isin: Mapped[str | None] = mapped_column(String(32), index=True)
    sector_id: Mapped[str] = mapped_column(String(128), nullable=False)
    industry_id: Mapped[str | None] = mapped_column(String(128))
    domicile: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    dual_listed: Mapped[bool] = mapped_column(nullable=False)
    identifiers: Mapped[list[list[str]]] = mapped_column(JSON, nullable=False)
    provenance: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class FilingModel(Base):
    __tablename__ = "filings"

    filing_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    filing_type: Mapped[str] = mapped_column(String(32), nullable=False)
    form_type: Mapped[str] = mapped_column(String(32), nullable=False)
    accession_number: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    source_uri: Mapped[str] = mapped_column(String(2048), nullable=False)
    filed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fiscal_period_start: Mapped[date] = mapped_column(Date, nullable=False)
    fiscal_period_end: Mapped[date] = mapped_column(Date, nullable=False)
    raw_artifact_sha256: Mapped[str] = mapped_column(ForeignKey("artifacts.sha256"), nullable=False)
    source_evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    restates_filing_id: Mapped[str | None] = mapped_column(ForeignKey("filings.filing_id"))


class FundamentalModel(Base):
    __tablename__ = "fundamentals"

    observation_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    filing_id: Mapped[str] = mapped_column(ForeignKey("filings.filing_id"), nullable=False)
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[str] = mapped_column(String(128), nullable=False)
    currency: Mapped[str | None] = mapped_column(String(8))
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    fiscal_period_start: Mapped[date] = mapped_column(Date, nullable=False)
    fiscal_period_end: Mapped[date] = mapped_column(Date, nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    restatement_status: Mapped[str] = mapped_column(String(16), nullable=False)
    restates_observation_id: Mapped[str | None] = mapped_column(
        ForeignKey("fundamentals.observation_id")
    )
    dimensions: Mapped[list[list[str]]] = mapped_column(JSON, nullable=False)


class DerivedFundamentalModel(Base):
    __tablename__ = "derived_fundamentals"

    derived_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    metric: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[str] = mapped_column(String(128), nullable=False)
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    fiscal_period_end: Mapped[date] = mapped_column(Date, nullable=False)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    input_observation_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    formula_version: Mapped[str] = mapped_column(String(64), nullable=False)


class CompanyExposureModel(Base):
    __tablename__ = "company_exposures"

    exposure_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    company_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    exposure_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target: Mapped[str] = mapped_column(String(128), nullable=False)
    value: Mapped[str | None] = mapped_column(String(128))
    unit: Mapped[str | None] = mapped_column(String(64))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class ResearchContextModel(Base):
    __tablename__ = "research_contexts"

    research_context_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    subject_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    items: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    anonymized: Mapped[bool] = mapped_column(nullable=False)


class ContextManifestModel(Base):
    __tablename__ = "research_context_manifests"

    manifest_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    research_context_id: Mapped[str] = mapped_column(
        ForeignKey("research_contexts.research_context_id"), nullable=False, index=True
    )
    cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    subject_id: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    event_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    policy_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    filing_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    fundamental_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    graph_versions: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AnonymizationMappingModel(Base):
    __tablename__ = "research_anonymization_mappings"

    mapping_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    research_context_id: Mapped[str] = mapped_column(
        ForeignKey("research_contexts.research_context_id"), nullable=False, index=True
    )
    values: Mapped[list[list[str]]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProviderCallModel(Base):
    __tablename__ = "research_provider_calls"

    call_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    provider_id: Mapped[str] = mapped_column(String(128), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    responded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    settings: Mapped[list[list[str]]] = mapped_column(JSON, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    token_usage: Mapped[list[list[Any]]] = mapped_column(JSON, nullable=False)
    raw_response_hash: Mapped[str] = mapped_column(String(72), nullable=False)
    structured_result: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)


class ResearchClaimModel(Base):
    __tablename__ = "research_claims"

    claim_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    claim_type: Mapped[str] = mapped_column(String(16), nullable=False)
    text: Mapped[str] = mapped_column(String, nullable=False)
    supporting_evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    contradicting_evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    entities: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    mechanisms: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    horizon: Mapped[str] = mapped_column(String(256), nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    review_state: Mapped[str] = mapped_column(String(16), nullable=False)


class ResearchHypothesisModel(Base):
    __tablename__ = "research_hypotheses_v2"

    hypothesis_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    subject_entities: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    mechanism_chain: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    evidence_basis: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    counterevidence: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    expected_horizon: Mapped[str] = mapped_column(String(256), nullable=False)
    measurable_outcome: Mapped[str] = mapped_column(String, nullable=False)
    falsification_criterion: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    generated_by: Mapped[str] = mapped_column(String(128), nullable=False)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)


class ResearchReviewModel(Base):
    __tablename__ = "research_reviews"

    reviewer_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    hypothesis_id: Mapped[str] = mapped_column(
        ForeignKey("research_hypotheses_v2.hypothesis_id"), nullable=False, index=True
    )
    accepted: Mapped[bool] = mapped_column(nullable=False)
    issues: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    alternative_explanations: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    stale_evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    model_id: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)


class ResearchTraceModel(Base):
    __tablename__ = "research_traces"

    trace_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    manifest_id: Mapped[str] = mapped_column(
        ForeignKey("research_context_manifests.manifest_id"), nullable=False
    )
    provider_call_id: Mapped[str] = mapped_column(
        ForeignKey("research_provider_calls.call_id"), nullable=False
    )
    claim_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    hypothesis_id: Mapped[str | None] = mapped_column(String(96))
    reviewer_id: Mapped[str | None] = mapped_column(String(96))
    validation_state: Mapped[str] = mapped_column(String(32), nullable=False)
    accepted: Mapped[bool] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AssetModel(Base):
    __tablename__ = "assets"

    asset_version_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    symbol: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    venue: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    asset_type: Mapped[str] = mapped_column(String(16), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    company_id: Mapped[str | None] = mapped_column(String(128), index=True)
    entity_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    benchmark_asset_id: Mapped[str | None] = mapped_column(String(128))
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provenance: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class MarketPartitionModel(Base):
    __tablename__ = "market_partitions"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    relative_path: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(64), nullable=False)


class MarketObservationModel(Base):
    __tablename__ = "market_observations"

    observation_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    venue: Mapped[str] = mapped_column(String(32), nullable=False)
    observation_type: Mapped[str] = mapped_column(String(16), nullable=False)
    market_timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    adjustment_status: Mapped[str] = mapped_column(String(16), nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    provenance: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    partition_sha256: Mapped[str] = mapped_column(
        ForeignKey("market_partitions.sha256"), nullable=False, index=True
    )


class CorporateActionModel(Base):
    __tablename__ = "corporate_actions"

    action_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    asset_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    announced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    value: Mapped[str | None] = mapped_column(String(128))
    currency: Mapped[str | None] = mapped_column(String(8))
    old_symbol: Mapped[str | None] = mapped_column(String(64))
    new_symbol: Mapped[str | None] = mapped_column(String(64))


class TradingSessionModel(Base):
    __tablename__ = "trading_sessions"

    session_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    venue: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    session_date: Mapped[str] = mapped_column(String(10), nullable=False)
    opens_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    closes_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_trading_day: Mapped[bool] = mapped_column(nullable=False)
    observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)


class ReplayCaseModel(Base):
    __tablename__ = "replay_cases"

    case_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    case_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entity_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    asset_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    horizon: Mapped[str] = mapped_column(String(64), nullable=False)
    available_evidence_manifest_id: Mapped[str] = mapped_column(String(96), nullable=False)
    benchmark_asset_id: Mapped[str | None] = mapped_column(String(128))
    expected_output_schema: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluation_protocol: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReplayCommitmentModel(Base):
    __tablename__ = "replay_commitments"

    commitment_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("replay_cases.case_id"), nullable=False)
    replay_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    context_manifest_id: Mapped[str] = mapped_column(String(96), nullable=False)
    hypothesis_id: Mapped[str] = mapped_column(String(96), nullable=False)
    expected_horizon: Mapped[str] = mapped_column(String(64), nullable=False)
    measurable_outcome: Mapped[str] = mapped_column(String, nullable=False)
    falsification_criterion: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    reviewer_decision: Mapped[str] = mapped_column(String(32), nullable=False)
    research_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    committed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ReplayRunModel(Base):
    __tablename__ = "replay_runs"

    run_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("replay_cases.case_id"), nullable=False)
    commitment_id: Mapped[str] = mapped_column(
        ForeignKey("replay_commitments.commitment_id"), nullable=False
    )
    named: Mapped[bool] = mapped_column(nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    runtime_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)


class OutcomeEvaluationModel(Base):
    __tablename__ = "outcome_evaluations"

    evaluation_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("replay_runs.run_id"), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    horizon_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    forward_return: Mapped[str | None] = mapped_column(String(128))
    benchmark_relative_return: Mapped[str | None] = mapped_column(String(128))
    maximum_adverse_excursion: Mapped[str | None] = mapped_column(String(128))
    maximum_favorable_excursion: Mapped[str | None] = mapped_column(String(128))
    volatility: Mapped[str | None] = mapped_column(String(128))
    drawdown: Mapped[str | None] = mapped_column(String(128))
    direction: Mapped[str | None] = mapped_column(String(16))
    provenance_observation_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class BenchmarkPairModel(Base):
    __tablename__ = "benchmark_pairs"

    pair_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    case_id: Mapped[str] = mapped_column(ForeignKey("replay_cases.case_id"), nullable=False)
    named_run_id: Mapped[str] = mapped_column(ForeignKey("replay_runs.run_id"), nullable=False)
    anonymized_run_id: Mapped[str] = mapped_column(ForeignKey("replay_runs.run_id"), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class MacroObservationModel(Base):
    __tablename__ = "macro_observations"

    observation_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    series_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    geography: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    observation_period: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    value: Mapped[str] = mapped_column(String(128), nullable=False)
    unit: Mapped[str] = mapped_column(String(64), nullable=False)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    revision_of: Mapped[str | None] = mapped_column(ForeignKey("macro_observations.observation_id"))
    seasonal_adjustment: Mapped[str] = mapped_column(String(32), nullable=False)
    provenance: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    parser_version: Mapped[str] = mapped_column(String(64), nullable=False)
    name_en: Mapped[str] = mapped_column(String(256), nullable=False)
    name_he: Mapped[str | None] = mapped_column(String(256))
    prior_value: Mapped[str | None] = mapped_column(String(128))
    expected_value: Mapped[str | None] = mapped_column(String(128))
    expectation_source: Mapped[str | None] = mapped_column(String(128))
    expectation_observed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TrendSignalModel(Base):
    __tablename__ = "trend_signals"

    trend_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    series_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    geography: Mapped[str] = mapped_column(String(32), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    horizon: Mapped[str] = mapped_column(String(16), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    as_of_period: Mapped[str] = mapped_column(String(32), nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    calculation_version: Mapped[str] = mapped_column(String(64), nullable=False)
    input_observation_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    slope: Mapped[str | None] = mapped_column(String(128))
    rolling_mean: Mapped[str | None] = mapped_column(String(128))
    z_score: Mapped[str | None] = mapped_column(String(128))
    mechanism_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class TrendDivergenceModel(Base):
    __tablename__ = "trend_divergences"

    divergence_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    left_trend_id: Mapped[str] = mapped_column(ForeignKey("trend_signals.trend_id"), nullable=False)
    right_trend_id: Mapped[str] = mapped_column(
        ForeignKey("trend_signals.trend_id"), nullable=False
    )
    description: Mapped[str] = mapped_column(String, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    provenance_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class StructuralTrendModel(Base):
    __tablename__ = "structural_trends"

    structural_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str] = mapped_column(String, nullable=False)
    geography: Mapped[str] = mapped_column(String(32), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    mechanism_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    curated: Mapped[bool] = mapped_column(nullable=False)


class GeopoliticalEventModel(Base):
    __tablename__ = "geopolitical_events"

    event_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    event_type: Mapped[str] = mapped_column(String(48), nullable=False, index=True)
    geography: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    actors: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    announced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confidence: Mapped[float] = mapped_column(nullable=False)
    confirmation_state: Mapped[str] = mapped_column(String(32), nullable=False)
    revision_of: Mapped[str | None] = mapped_column(ForeignKey("geopolitical_events.event_id"))
    provenance: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class GeopoliticalCandidateModel(Base):
    __tablename__ = "geopolitical_candidates"

    candidate_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    source_evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    event_type: Mapped[str | None] = mapped_column(String(48))
    actors: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    geography: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    explicit_timestamps: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    mechanism_candidates: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    review_state: Mapped[str] = mapped_column(String(24), nullable=False)
    supporting_spans: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class GeopoliticalCandidateReviewModel(Base):
    __tablename__ = "geopolitical_candidate_reviews"

    review_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("geopolitical_candidates.candidate_id"), nullable=False, index=True
    )
    state: Mapped[str] = mapped_column(String(24), nullable=False)
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    reviewer: Mapped[str] = mapped_column(String(128), nullable=False)
    rationale: Mapped[str] = mapped_column(String, nullable=False)


class GeopoliticalTransmissionModel(Base):
    __tablename__ = "geopolitical_transmission_paths"

    path_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    event_id: Mapped[str] = mapped_column(
        ForeignKey("geopolitical_events.event_id"), nullable=False, index=True
    )
    mechanisms: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    affected_entities: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    horizon: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    rationale: Mapped[str] = mapped_column(String, nullable=False)
    provenance_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GeopoliticalCorroborationModel(Base):
    __tablename__ = "geopolitical_corroborations"

    corroboration_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("geopolitical_candidates.candidate_id"), nullable=False, index=True
    )
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    rationale: Mapped[str] = mapped_column(String, nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)


class SocialSourceModel(Base):
    __tablename__ = "social_sources"
    source_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    native_source_id: Mapped[str] = mapped_column(String(256), nullable=False)
    display_name: Mapped[str] = mapped_column(String(256), nullable=False)
    canonical_uri: Mapped[str | None] = mapped_column(String(2048))
    languages: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    geography: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    verification_state: Mapped[str] = mapped_column(String(32), nullable=False)
    accessibility: Mapped[str] = mapped_column(String(16), nullable=False)
    provenance: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    active: Mapped[bool] = mapped_column(nullable=False)
    __table_args__ = (
        UniqueConstraint("platform", "native_source_id", name="uq_social_source_identity"),
    )


class SocialPostModel(Base):
    __tablename__ = "social_posts"
    post_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("social_sources.source_id"), nullable=False, index=True
    )
    native_post_id: Mapped[str] = mapped_column(String(256), nullable=False)
    thread_parent_id: Mapped[str | None] = mapped_column(String(96))
    reply_parent_id: Mapped[str | None] = mapped_column(String(96))
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    original_text: Mapped[str] = mapped_column(String, nullable=False)
    normalized_text: Mapped[str] = mapped_column(String, nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    urls: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    mentions: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    quoted_source_id: Mapped[str | None] = mapped_column(String(96))
    metrics: Mapped[list[list[Any]]] = mapped_column(JSON, nullable=False)
    raw_artifact_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    media_references: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    provenance: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    revision_of: Mapped[str | None] = mapped_column(ForeignKey("social_posts.post_id"))


class NarrativeCandidateModel(Base):
    __tablename__ = "narrative_candidates"
    candidate_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    topics: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    entities: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    supporting_post_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    earliest_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    proposition: Mapped[str] = mapped_column(String, nullable=False)
    language: Mapped[str] = mapped_column(String(16), nullable=False)
    extraction_method: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    corroboration_state: Mapped[str] = mapped_column(String(32), nullable=False)
    contradiction_state: Mapped[str] = mapped_column(String(32), nullable=False)
    lifecycle_state: Mapped[str] = mapped_column(String(16), nullable=False)
    reviewed: Mapped[bool] = mapped_column(nullable=False)


class RumorClaimModel(Base):
    __tablename__ = "rumor_claims"
    claim_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    proposition: Mapped[str] = mapped_column(String, nullable=False)
    entities: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    origin_post_id: Mapped[str] = mapped_column(String(96), nullable=False)
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    supporting_post_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    contradicting_post_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    official_evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    news_evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    revision_of: Mapped[str | None] = mapped_column(ForeignKey("rumor_claims.claim_id"))
    version: Mapped[int] = mapped_column(Integer, nullable=False)


class SocialPropagationModel(Base):
    __tablename__ = "social_propagation_edges"
    edge_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    source_post_id: Mapped[str] = mapped_column(ForeignKey("social_posts.post_id"), nullable=False)
    target_post_id: Mapped[str] = mapped_column(ForeignKey("social_posts.post_id"), nullable=False)
    relation: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    provenance: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class CoordinationCandidateModel(Base):
    __tablename__ = "coordination_candidates"
    coordination_candidate_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    post_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    features: Mapped[list[list[str]]] = mapped_column(JSON, nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    provenance: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class SocialReputationModel(Base):
    __tablename__ = "social_reputation_snapshots"
    snapshot_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    source_id: Mapped[str] = mapped_column(
        ForeignKey("social_sources.source_id"), nullable=False, index=True
    )
    domain: Mapped[str] = mapped_column(String(32), nullable=False)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    claims_originated: Mapped[int] = mapped_column(Integer, nullable=False)
    confirmed: Mapped[int] = mapped_column(Integer, nullable=False)
    contradicted: Mapped[int] = mapped_column(Integer, nullable=False)
    unresolved: Mapped[int] = mapped_column(Integer, nullable=False)
    median_confirmation_lead_seconds: Mapped[int | None] = mapped_column(Integer)
    copy_rate: Mapped[float] = mapped_column(nullable=False)
    original_content_rate: Mapped[float] = mapped_column(nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    uncertainty: Mapped[str] = mapped_column(String(128), nullable=False)


class TelegramReceiptModel(Base):
    __tablename__ = "telegram_receipts"
    receipt_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    allowlist_source_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    post_id: Mapped[str] = mapped_column(
        ForeignKey("social_posts.post_id"), nullable=False, index=True
    )
    native_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    forward_source: Mapped[str | None] = mapped_column(String(256))
    forward_message_id: Mapped[int | None] = mapped_column(Integer)
    forward_hidden: Mapped[bool] = mapped_column(nullable=False)
    artifact_sha256: Mapped[str] = mapped_column(ForeignKey("artifacts.sha256"), nullable=False)
    payload_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class TelegramCheckpointModel(Base):
    __tablename__ = "telegram_checkpoints"
    checkpoint_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    last_message_id: Mapped[int] = mapped_column(Integer, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class TelegramRunModel(Base):
    __tablename__ = "telegram_runs"
    run_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    messages_fetched: Mapped[int] = mapped_column(Integer, nullable=False)
    inserted: Mapped[int] = mapped_column(Integer, nullable=False)
    duplicates: Mapped[int] = mapped_column(Integer, nullable=False)
    edits: Mapped[int] = mapped_column(Integer, nullable=False)
    forwards: Mapped[int] = mapped_column(Integer, nullable=False)
    deletions: Mapped[int] = mapped_column(Integer, nullable=False)
    bytes_downloaded: Mapped[int] = mapped_column(Integer, nullable=False)
    error_summary: Mapped[str | None] = mapped_column(String)


class UnifiedClaimModel(Base):
    __tablename__ = "unified_claims"
    claim_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    proposition: Mapped[str] = mapped_column(Text, nullable=False)
    claim_type: Mapped[str] = mapped_column(String(32), nullable=False)
    entities: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    geography: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    domain: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source_evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    originating_source_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    first_observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(nullable=False)
    provenance: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_of: Mapped[str | None] = mapped_column(ForeignKey("unified_claims.claim_id"))


class ClaimLineageModel(Base):
    __tablename__ = "claim_lineage"
    lineage_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    source_claim_id: Mapped[str] = mapped_column(
        ForeignKey("unified_claims.claim_id"), nullable=False
    )
    target_claim_id: Mapped[str] = mapped_column(
        ForeignKey("unified_claims.claim_id"), nullable=False
    )
    relationship: Mapped[str] = mapped_column(String(24), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False)


class ClaimCorroborationModel(Base):
    __tablename__ = "claim_corroborations"
    record_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    claim_id: Mapped[str] = mapped_column(
        ForeignKey("unified_claims.claim_id"), nullable=False, index=True
    )
    evidence_id: Mapped[str] = mapped_column(String(96), nullable=False)
    source_id: Mapped[str] = mapped_column(String(256), nullable=False)
    independence: Mapped[str] = mapped_column(String(24), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    rationale: Mapped[str] = mapped_column(Text, nullable=False)


class ClaimResolutionModel(Base):
    __tablename__ = "claim_resolutions"
    resolution_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    claim_id: Mapped[str] = mapped_column(
        ForeignKey("unified_claims.claim_id"), nullable=False, index=True
    )
    outcome: Mapped[str] = mapped_column(String(24), nullable=False)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    supporting_evidence_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    resolving_source_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    resolved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    rationale: Mapped[str] = mapped_column(Text, nullable=False)


class ClaimContradictionModel(Base):
    __tablename__ = "claim_contradictions"
    contradiction_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    claim_id: Mapped[str] = mapped_column(
        ForeignKey("unified_claims.claim_id"), nullable=False, index=True
    )
    proposition_a: Mapped[str] = mapped_column(Text, nullable=False)
    proposition_b: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_a: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    evidence_b: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    resolution_status: Mapped[str] = mapped_column(String(24), nullable=False)
    ambiguity: Mapped[str] = mapped_column(Text, nullable=False)


class FusionScoreModel(Base):
    __tablename__ = "fusion_scores"
    score_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    claim_id: Mapped[str] = mapped_column(
        ForeignKey("unified_claims.claim_id"), nullable=False, index=True
    )
    source_authority: Mapped[float] = mapped_column(nullable=False)
    independence: Mapped[float] = mapped_column(nullable=False)
    corroboration_count: Mapped[float] = mapped_column(nullable=False)
    provenance_completeness: Mapped[float] = mapped_column(nullable=False)
    contradiction_burden: Mapped[float] = mapped_column(nullable=False)
    temporal_consistency: Mapped[float] = mapped_column(nullable=False)
    historical_reputation: Mapped[float] = mapped_column(nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )


class FusionReputationModel(Base):
    __tablename__ = "fusion_reputation_snapshots"
    snapshot_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    claims_originated: Mapped[int] = mapped_column(Integer, nullable=False)
    confirmed: Mapped[int] = mapped_column(Integer, nullable=False)
    contradicted: Mapped[int] = mapped_column(Integer, nullable=False)
    unresolved: Mapped[int] = mapped_column(Integer, nullable=False)
    precision_resolved: Mapped[float] = mapped_column(nullable=False)
    median_confirmation_lead_seconds: Mapped[int | None] = mapped_column(Integer)
    contradiction_rate: Mapped[float] = mapped_column(nullable=False)
    copy_forward_rate: Mapped[float] = mapped_column(nullable=False)
    original_content_rate: Mapped[float] = mapped_column(nullable=False)
    sample_size: Mapped[int] = mapped_column(Integer, nullable=False)
    uncertainty: Mapped[str] = mapped_column(String(128), nullable=False)


class ExperimentSpecificationModel(Base):
    __tablename__ = "experiment_specifications"
    experiment_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    hypothesis_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    cutoff: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    research_context_id: Mapped[str] = mapped_column(String(96), nullable=False)
    asset_universe: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    benchmark: Mapped[str] = mapped_column(String(96), nullable=False)
    signal_definition: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    entry_rule: Mapped[str] = mapped_column(String(24), nullable=False)
    exit_rule: Mapped[str] = mapped_column(String(32), nullable=False)
    holding_period: Mapped[int] = mapped_column(Integer, nullable=False)
    rebalance_frequency: Mapped[str] = mapped_column(String(24), nullable=False)
    position_policy: Mapped[str] = mapped_column(String(24), nullable=False)
    cost_model: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    evaluation_window: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    exclusion_rules: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    parameter_manifest: Mapped[list[list[str]]] = mapped_column(JSON, nullable=False)
    code_version_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    provenance: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_of: Mapped[str | None] = mapped_column(
        ForeignKey("experiment_specifications.experiment_id")
    )


class BacktestDatasetModel(Base):
    __tablename__ = "backtest_datasets"
    manifest_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    dataset_version: Mapped[str] = mapped_column(String(64), nullable=False)
    parquet_hashes: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    source_versions: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    parameter_hash: Mapped[str] = mapped_column(String(80), nullable=False)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    rows_read: Mapped[int] = mapped_column(Integer, nullable=False)
    bytes_read: Mapped[int] = mapped_column(BigInteger, nullable=False)


class BacktestResultModel(Base):
    __tablename__ = "backtest_results"
    result_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("experiment_specifications.experiment_id"), nullable=False, index=True
    )
    dataset_manifest_id: Mapped[str] = mapped_column(
        ForeignKey("backtest_datasets.manifest_id"), nullable=False
    )
    reproducibility: Mapped[list[list[str]]] = mapped_column(JSON, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    transaction_costs: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False)
    number_of_signals: Mapped[int] = mapped_column(Integer, nullable=False)
    executed_trades: Mapped[int] = mapped_column(Integer, nullable=False)
    skipped_signals: Mapped[int] = mapped_column(Integer, nullable=False)
    rejection_reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    nav: Mapped[list[list[str]]] = mapped_column(JSON, nullable=False)
    position_paths: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    runtime_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    parquet_bytes_read: Mapped[int] = mapped_column(BigInteger, nullable=False)


class TestSetAccessModel(Base):
    __tablename__ = "test_set_accesses"
    audit_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(
        ForeignKey("experiment_specifications.experiment_id"), nullable=False, index=True
    )
    partition: Mapped[str] = mapped_column(String(16), nullable=False)
    accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    purpose: Mapped[str] = mapped_column(String(256), nullable=False)
    actor: Mapped[str] = mapped_column(String(128), nullable=False)


class ExperimentRegistryModel(Base):
    __tablename__ = "experiment_registry_snapshots"
    snapshot_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    hypotheses_generated: Mapped[int] = mapped_column(Integer, nullable=False)
    experiments_executed: Mapped[int] = mapped_column(Integer, nullable=False)
    rejected_experiments: Mapped[int] = mapped_column(Integer, nullable=False)
    reported_experiments: Mapped[int] = mapped_column(Integer, nullable=False)


class PaperRiskPolicyModel(Base):
    __tablename__ = "paper_risk_policies"
    policy_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    limits: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    provenance: Mapped[list[str]] = mapped_column(JSON, nullable=False)


class PaperPortfolioModel(Base):
    __tablename__ = "paper_portfolios"
    portfolio_version_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    configuration: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    revision_of: Mapped[str | None] = mapped_column(String(160))


class PaperAccountSnapshotModel(Base):
    __tablename__ = "paper_account_snapshots"
    snapshot_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    account: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class PaperSignalModel(Base):
    __tablename__ = "paper_signals"
    signal_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class PaperOrderModel(Base):
    __tablename__ = "paper_orders"
    candidate_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    signal_id: Mapped[str] = mapped_column(ForeignKey("paper_signals.signal_id"), nullable=False)
    portfolio_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class PaperRiskEvaluationModel(Base):
    __tablename__ = "paper_risk_evaluations"
    evaluation_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("paper_orders.candidate_id"), nullable=False
    )
    portfolio_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class PaperExecutionDecisionModel(Base):
    __tablename__ = "paper_execution_decisions"
    decision_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(
        ForeignKey("paper_orders.candidate_id"), nullable=False
    )
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class PaperFillModel(Base):
    __tablename__ = "paper_fills"
    fill_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    decision_id: Mapped[str] = mapped_column(
        ForeignKey("paper_execution_decisions.decision_id"), nullable=False
    )
    portfolio_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    filled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


class PaperAuditModel(Base):
    __tablename__ = "paper_audit_journal"
    audit_id: Mapped[str] = mapped_column(String(96), primary_key=True)
    portfolio_id: Mapped[str] = mapped_column(String(96), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)


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
    CompanyModel,
    FilingModel,
    FundamentalModel,
    DerivedFundamentalModel,
    CompanyExposureModel,
    ResearchContextModel,
    ContextManifestModel,
    AnonymizationMappingModel,
    ProviderCallModel,
    ResearchClaimModel,
    ResearchHypothesisModel,
    ResearchReviewModel,
    ResearchTraceModel,
    AssetModel,
    MarketPartitionModel,
    MarketObservationModel,
    CorporateActionModel,
    TradingSessionModel,
    ReplayCaseModel,
    ReplayCommitmentModel,
    ReplayRunModel,
    OutcomeEvaluationModel,
    BenchmarkPairModel,
    MacroObservationModel,
    TrendSignalModel,
    TrendDivergenceModel,
    StructuralTrendModel,
    GeopoliticalEventModel,
    GeopoliticalCandidateModel,
    GeopoliticalCandidateReviewModel,
    GeopoliticalTransmissionModel,
    GeopoliticalCorroborationModel,
    SocialSourceModel,
    SocialPostModel,
    NarrativeCandidateModel,
    RumorClaimModel,
    SocialPropagationModel,
    CoordinationCandidateModel,
    SocialReputationModel,
    TelegramReceiptModel,
    TelegramCheckpointModel,
    TelegramRunModel,
    UnifiedClaimModel,
    ClaimLineageModel,
    ClaimCorroborationModel,
    ClaimResolutionModel,
    ClaimContradictionModel,
    FusionScoreModel,
    FusionReputationModel,
    ExperimentSpecificationModel,
    BacktestDatasetModel,
    BacktestResultModel,
    TestSetAccessModel,
    ExperimentRegistryModel,
    PaperRiskPolicyModel,
    PaperPortfolioModel,
    PaperAccountSnapshotModel,
    PaperSignalModel,
    PaperOrderModel,
    PaperRiskEvaluationModel,
    PaperExecutionDecisionModel,
    PaperFillModel,
    PaperAuditModel,
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
