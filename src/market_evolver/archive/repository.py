from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from market_evolver.archive.schemas import (
    ArchiveCoverage,
    ArchiveGap,
    ArchiveRunManifest,
    EvidenceVintage,
)
from market_evolver.errors import IntegrityViolation
from market_evolver.storage.models import (
    ArchiveGapModel,
    ArchiveRunModel,
    ArtifactModel,
    EvidenceVintageModel,
)


class SqlArchiveRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_vintage(self, item: EvidenceVintage) -> bool:
        if self.session.get(EvidenceVintageModel, item.vintage_id):
            return False
        if self.session.get(ArtifactModel, item.artifact_id.removeprefix("sha256:")) is None:
            raise IntegrityViolation("vintage references unknown artifact")
        if item.revision_of:
            previous = self.session.get(EvidenceVintageModel, item.revision_of)
            if (
                previous is None
                or previous.source_id != item.source_id
                or previous.canonical_uri != item.canonical_uri
                or _utc(previous.first_observed_at) >= item.first_observed_at
            ):
                raise IntegrityViolation("invalid evidence vintage revision chain")
        self.session.add(EvidenceVintageModel.from_domain(item))
        self.session.flush()
        return True

    def add_run(self, item: ArchiveRunManifest) -> bool:
        if self.session.get(ArchiveRunModel, item.run_id):
            return False
        self.session.add(ArchiveRunModel.from_domain(item))
        self.session.flush()
        return True

    def add_gap(self, item: ArchiveGap) -> bool:
        if self.session.get(ArchiveGapModel, item.gap_id):
            return False
        self.session.add(ArchiveGapModel.from_domain(item))
        self.session.flush()
        return True

    def vintages_for_uri(self, canonical_uri: str) -> tuple[EvidenceVintageModel, ...]:
        return tuple(
            self.session.scalars(
                select(EvidenceVintageModel)
                .where(EvidenceVintageModel.canonical_uri == canonical_uri)
                .order_by(EvidenceVintageModel.first_observed_at)
            )
        )

    def recent_runs(self, limit: int = 50) -> tuple[ArchiveRunModel, ...]:
        return tuple(
            self.session.scalars(
                select(ArchiveRunModel).order_by(ArchiveRunModel.started_at.desc()).limit(limit)
            )
        )

    def coverage(self) -> tuple[ArchiveCoverage, ...]:
        sources = tuple(self.session.scalars(select(EvidenceVintageModel.source_id).distinct()))
        gap_sources = tuple(self.session.scalars(select(ArchiveGapModel.source_id).distinct()))
        output = []
        for source_id in sorted({*sources, *gap_sources}):
            snapshots = (
                self.session.scalar(
                    select(func.count())
                    .select_from(EvidenceVintageModel)
                    .where(EvidenceVintageModel.source_id == source_id)
                )
                or 0
            )
            size = (
                self.session.scalar(
                    select(func.coalesce(func.sum(ArtifactModel.size_bytes), 0))
                    .select_from(EvidenceVintageModel)
                    .join(
                        ArtifactModel, ArtifactModel.sha256 == EvidenceVintageModel.artifact_sha256
                    )
                    .where(EvidenceVintageModel.source_id == source_id)
                )
                or 0
            )
            revisions = (
                self.session.scalar(
                    select(func.count())
                    .select_from(EvidenceVintageModel)
                    .where(
                        EvidenceVintageModel.source_id == source_id,
                        EvidenceVintageModel.revision_of.is_not(None),
                    )
                )
                or 0
            )
            gaps = (
                self.session.scalar(
                    select(func.count())
                    .select_from(ArchiveGapModel)
                    .where(
                        ArchiveGapModel.source_id == source_id,
                        ArchiveGapModel.resolved_by_vintage_id.is_(None),
                    )
                )
                or 0
            )
            latest = self.session.scalar(
                select(func.max(EvidenceVintageModel.first_observed_at)).where(
                    EvidenceVintageModel.source_id == source_id
                )
            )
            output.append(
                ArchiveCoverage(
                    source_id,
                    int(snapshots),
                    int(size),
                    int(revisions),
                    int(gaps),
                    None if latest is None else _utc(latest),
                    "critical raw evidence retained; normalized rebuildable; media separate",
                )
            )
        return tuple(output)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
