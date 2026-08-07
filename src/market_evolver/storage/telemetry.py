"""Measured storage and ingestion growth, without forecasting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from market_evolver.storage.models import (
    ArtifactModel,
    CanonicalEventModel,
    EventMechanismLinkModel,
    EventModel,
    EventSupportModel,
    EventTransitionModel,
    EvidenceContradictionModel,
    EvidenceModel,
    GovernmentActionModel,
    GovernmentCandidateModel,
    GovernmentTransitionModel,
    HypothesisModel,
    IngestionManifestModel,
    KnowledgeAliasModel,
    KnowledgeEntityModel,
    KnowledgeExposureModel,
    KnowledgeRelationshipModel,
    NewsCandidateModel,
    NewsCandidateReviewModel,
    NewsCorroborationModel,
    NewsEntityModel,
    NewsItemModel,
    NormalizedObservationModel,
    RawIngestionModel,
    ResearchDecisionModel,
    SourceModel,
)


@dataclass(frozen=True, slots=True)
class DailyMeasurement:
    day: date
    value: int


@dataclass(frozen=True, slots=True)
class StorageTelemetry:
    raw_artifact_bytes: int
    database_record_counts: dict[str, int]
    ingestion_bytes_by_day: tuple[DailyMeasurement, ...]
    item_growth_by_day: tuple[DailyMeasurement, ...]
    news_items_by_day: tuple[DailyMeasurement, ...] = ()
    raw_news_bytes_by_day: tuple[DailyMeasurement, ...] = ()
    news_duplicates_by_day: tuple[DailyMeasurement, ...] = ()
    news_revisions_by_day: tuple[DailyMeasurement, ...] = ()
    quarantined_news_by_day: tuple[DailyMeasurement, ...] = ()
    news_items_by_source: dict[str, int] | None = None
    news_bytes_by_source: dict[str, int] | None = None
    policy_documents_by_day: tuple[DailyMeasurement, ...] = ()
    policy_revisions_by_day: tuple[DailyMeasurement, ...] = ()
    policy_transitions_by_day: tuple[DailyMeasurement, ...] = ()
    raw_government_bytes_by_day: tuple[DailyMeasurement, ...] = ()
    policy_candidate_count: int = 0
    policy_promotion_count: int = 0


def measure_storage(session: Session) -> StorageTelemetry:
    counts = {
        model.__tablename__: _count(session, model)
        for model in (
            ArtifactModel,
            SourceModel,
            EvidenceModel,
            EventModel,
            HypothesisModel,
            ResearchDecisionModel,
            NormalizedObservationModel,
            RawIngestionModel,
            IngestionManifestModel,
            CanonicalEventModel,
            EventSupportModel,
            EventTransitionModel,
            EventMechanismLinkModel,
            KnowledgeEntityModel,
            KnowledgeAliasModel,
            KnowledgeRelationshipModel,
            KnowledgeExposureModel,
            NewsItemModel,
            NewsEntityModel,
            NewsCandidateModel,
            NewsCandidateReviewModel,
            NewsCorroborationModel,
            EvidenceContradictionModel,
            GovernmentActionModel,
            GovernmentTransitionModel,
            GovernmentCandidateModel,
        )
    }
    raw_bytes = int(
        session.scalar(select(func.coalesce(func.sum(ArtifactModel.size_bytes), 0))) or 0
    )
    ingestion_rows = session.execute(
        select(
            func.date(IngestionManifestModel.started_at),
            func.sum(IngestionManifestModel.bytes_downloaded),
        )
        .group_by(func.date(IngestionManifestModel.started_at))
        .order_by(func.date(IngestionManifestModel.started_at))
    )
    growth_rows = session.execute(
        select(
            func.date(NormalizedObservationModel.first_observed_at),
            func.count(NormalizedObservationModel.provenance_id),
        )
        .group_by(func.date(NormalizedObservationModel.first_observed_at))
        .order_by(func.date(NormalizedObservationModel.first_observed_at))
    )
    news_models = tuple(session.scalars(select(NewsItemModel)))
    artifact_sizes = {
        item.sha256: item.size_bytes for item in session.scalars(select(ArtifactModel))
    }
    news_by_day: dict[date, int] = {}
    duplicate_by_day: dict[date, int] = {}
    revision_by_day: dict[date, int] = {}
    quarantine_by_day: dict[date, int] = {}
    source_volume: dict[str, int] = {}
    source_artifacts: dict[str, set[str]] = {}
    artifact_days: dict[date, set[str]] = {}
    for item in news_models:
        day = item.first_observed_at.date()
        news_by_day[day] = news_by_day.get(day, 0) + 1
        source_volume[item.source_id] = source_volume.get(item.source_id, 0) + 1
        source_artifacts.setdefault(item.source_id, set()).add(item.raw_artifact_sha256)
        artifact_days.setdefault(day, set()).add(item.raw_artifact_sha256)
        if item.duplicate_kind in {"reingested", "syndicated"}:
            duplicate_by_day[day] = duplicate_by_day.get(day, 0) + 1
        if item.duplicate_kind == "revision":
            revision_by_day[day] = revision_by_day.get(day, 0) + 1
        if item.evidence_security_class == "quarantined":
            quarantine_by_day[day] = quarantine_by_day.get(day, 0) + 1
    policy_actions = tuple(session.scalars(select(GovernmentActionModel)))
    policy_transitions = tuple(session.scalars(select(GovernmentTransitionModel)))
    policy_candidates = tuple(session.scalars(select(GovernmentCandidateModel)))
    policy_by_day: dict[date, int] = {}
    policy_revisions: dict[date, int] = {}
    transition_by_day: dict[date, int] = {}
    for policy_action in policy_actions:
        day = policy_action.first_observed_at.date()
        policy_by_day[day] = policy_by_day.get(day, 0) + 1
        if policy_action.version > 1:
            policy_revisions[day] = policy_revisions.get(day, 0) + 1
    for policy_transition in policy_transitions:
        day = policy_transition.transitioned_at.date()
        transition_by_day[day] = transition_by_day.get(day, 0) + 1
    government_artifacts: dict[date, set[str]] = {}
    for receipt in session.scalars(
        select(RawIngestionModel).where(RawIngestionModel.dataset == "policy-interest-rate")
    ):
        government_artifacts.setdefault(receipt.first_observed_at.date(), set()).add(
            receipt.artifact_sha256
        )
    return StorageTelemetry(
        raw_artifact_bytes=raw_bytes,
        database_record_counts=counts,
        ingestion_bytes_by_day=tuple(
            DailyMeasurement(date.fromisoformat(str(day)), int(value))
            for day, value in ingestion_rows
        ),
        item_growth_by_day=tuple(
            DailyMeasurement(date.fromisoformat(str(day)), int(value)) for day, value in growth_rows
        ),
        news_items_by_day=_measurements(news_by_day),
        raw_news_bytes_by_day=_measurements(
            {
                day: sum(artifact_sizes.get(digest, 0) for digest in digests)
                for day, digests in artifact_days.items()
            }
        ),
        news_duplicates_by_day=_measurements(duplicate_by_day),
        news_revisions_by_day=_measurements(revision_by_day),
        quarantined_news_by_day=_measurements(quarantine_by_day),
        news_items_by_source=dict(sorted(source_volume.items())),
        news_bytes_by_source={
            source_id: sum(artifact_sizes.get(digest, 0) for digest in digests)
            for source_id, digests in sorted(source_artifacts.items())
        },
        policy_documents_by_day=_measurements(policy_by_day),
        policy_revisions_by_day=_measurements(policy_revisions),
        policy_transitions_by_day=_measurements(transition_by_day),
        raw_government_bytes_by_day=_measurements(
            {
                day: sum(artifact_sizes.get(digest, 0) for digest in digests)
                for day, digests in government_artifacts.items()
            }
        ),
        policy_candidate_count=len(policy_candidates),
        policy_promotion_count=sum(item.review_state == "promoted" for item in policy_candidates),
    )


def _count(session: Session, model: type) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _measurements(values: dict[date, int]) -> tuple[DailyMeasurement, ...]:
    return tuple(DailyMeasurement(day, values[day]) for day in sorted(values))
