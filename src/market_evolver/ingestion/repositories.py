"""Persistence for normalized observations and ingestion operations."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_evolver.errors import IntegrityViolation
from market_evolver.ingestion.schemas import (
    IngestionManifest,
    IngestionStatus,
    NormalizedObservation,
)
from market_evolver.provenance import canonical_json
from market_evolver.storage.models import (
    ArtifactModel,
    IngestionManifestModel,
    NormalizedObservationModel,
    SourceModel,
)


class SqlObservationRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add(self, observation: NormalizedObservation) -> tuple[NormalizedObservation, bool]:
        existing = self.session.get(NormalizedObservationModel, observation.provenance_id)
        if existing is not None:
            restored = self._to_domain(existing)
            if canonical_json(restored) != canonical_json(observation):
                raise IntegrityViolation("observation provenance collision")
            return restored, False
        if self.session.get(SourceModel, observation.source_record_id) is None:
            raise IntegrityViolation("observation references an unknown source record")
        artifact = self.session.get(ArtifactModel, observation.raw_artifact_sha256)
        if artifact is None:
            raise IntegrityViolation("observation references an unknown raw artifact")
        if observation.content_hash != f"sha256:{artifact.sha256}":
            raise IntegrityViolation("observation content hash does not match artifact")
        self.session.add(
            NormalizedObservationModel(
                provenance_id=observation.provenance_id,
                registry_source_id=observation.registry_source_id,
                source_record_id=observation.source_record_id,
                dataset=observation.dataset,
                item_key=observation.item_key,
                period_start=observation.period_start,
                period_end=observation.period_end,
                published_at=observation.published_at,
                first_observed_at=observation.first_observed_at,
                effective_at=observation.effective_at,
                superseded_at=observation.superseded_at,
                value=observation.value,
                unit=observation.unit,
                raw_artifact_sha256=observation.raw_artifact_sha256,
                content_hash=observation.content_hash,
                parser_version=observation.parser_version,
            )
        )
        self.session.flush()
        return observation, True

    def count_for_artifact(self, source_id: str, dataset: str, sha256: str) -> int:
        statement = select(NormalizedObservationModel).where(
            NormalizedObservationModel.registry_source_id == source_id,
            NormalizedObservationModel.dataset == dataset,
            NormalizedObservationModel.raw_artifact_sha256 == sha256,
        )
        return len(tuple(self.session.scalars(statement)))

    def list_for_source(self, source_id: str) -> list[NormalizedObservation]:
        statement = (
            select(NormalizedObservationModel)
            .where(NormalizedObservationModel.registry_source_id == source_id)
            .order_by(
                NormalizedObservationModel.item_key,
                NormalizedObservationModel.period_start,
                NormalizedObservationModel.first_observed_at,
                NormalizedObservationModel.provenance_id,
            )
        )
        return [self._to_domain(model) for model in self.session.scalars(statement)]

    @staticmethod
    def _to_domain(model: NormalizedObservationModel) -> NormalizedObservation:
        return NormalizedObservation(
            registry_source_id=model.registry_source_id,
            source_record_id=model.source_record_id,
            dataset=model.dataset,
            item_key=model.item_key,
            period_start=model.period_start,
            period_end=model.period_end,
            published_at=_utc_optional(model.published_at),
            first_observed_at=_utc(model.first_observed_at),
            effective_at=_utc_optional(model.effective_at),
            superseded_at=_utc_optional(model.superseded_at),
            value=model.value,
            unit=model.unit,
            raw_artifact_sha256=model.raw_artifact_sha256,
            content_hash=model.content_hash,
            parser_version=model.parser_version,
        )


class SqlManifestRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def start(self, manifest: IngestionManifest) -> None:
        self.session.add(self._to_model(manifest))
        self.session.flush()

    def finish(self, manifest: IngestionManifest) -> None:
        model = self.session.get(IngestionManifestModel, manifest.run_id)
        if model is None:
            raise IntegrityViolation("ingestion manifest disappeared")
        for field in (
            "finished_at",
            "status",
            "items_fetched",
            "items_inserted",
            "duplicates",
            "bytes_downloaded",
            "raw_artifacts_created",
            "error_summary",
        ):
            value = getattr(manifest, field)
            setattr(model, field, value.value if isinstance(value, IngestionStatus) else value)
        self.session.flush()

    def recent(self, limit: int = 20) -> list[IngestionManifest]:
        statement = (
            select(IngestionManifestModel)
            .order_by(IngestionManifestModel.started_at.desc())
            .limit(limit)
        )
        return [self._to_domain(model) for model in self.session.scalars(statement)]

    @staticmethod
    def _to_model(manifest: IngestionManifest) -> IngestionManifestModel:
        return IngestionManifestModel(
            run_id=manifest.run_id,
            source_id=manifest.source_id,
            dataset=manifest.dataset,
            started_at=manifest.started_at,
            finished_at=manifest.finished_at,
            status=manifest.status.value,
            items_fetched=manifest.items_fetched,
            items_inserted=manifest.items_inserted,
            duplicates=manifest.duplicates,
            bytes_downloaded=manifest.bytes_downloaded,
            raw_artifacts_created=manifest.raw_artifacts_created,
            parser_version=manifest.parser_version,
            error_summary=manifest.error_summary,
        )

    @staticmethod
    def _to_domain(model: IngestionManifestModel) -> IngestionManifest:
        return IngestionManifest(
            run_id=model.run_id,
            source_id=model.source_id,
            dataset=model.dataset,
            started_at=_utc(model.started_at),
            finished_at=_utc_optional(model.finished_at),
            status=IngestionStatus(model.status),
            items_fetched=model.items_fetched,
            items_inserted=model.items_inserted,
            duplicates=model.duplicates,
            bytes_downloaded=model.bytes_downloaded,
            raw_artifacts_created=model.raw_artifacts_created,
            parser_version=model.parser_version,
            error_summary=model.error_summary,
        )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _utc_optional(value: datetime | None) -> datetime | None:
    return None if value is None else _utc(value)
