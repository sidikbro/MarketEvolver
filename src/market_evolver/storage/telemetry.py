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
    EvidenceModel,
    HypothesisModel,
    IngestionManifestModel,
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
    )


def _count(session: Session, model: type) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)
