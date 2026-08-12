from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from sqlalchemy.orm import Session

from market_evolver.archive.repository import SqlArchiveRepository
from market_evolver.archive.schemas import (
    ArchiveConfidence,
    ArchiveGap,
    ArchiveRunManifest,
    ArchiveRunStatus,
    EvidenceVintage,
    ReplayEligibilityDecision,
    RetentionClass,
    VintageClassification,
)
from market_evolver.errors import GovernanceViolation, IntegrityViolation, ValidationError
from market_evolver.replay.real import HistoricalReplayCase, ReplayDataRole
from market_evolver.sources.registry import DEFAULT_REGISTRY
from market_evolver.storage.artifacts import LocalArtifactStore
from market_evolver.storage.models import ArtifactModel


@dataclass(frozen=True, slots=True)
class ArchivePayload:
    source_id: str
    canonical_uri: str
    content: bytes
    mime_type: str
    retrieved_at: datetime
    source_published_at: datetime | None
    server_date_at: datetime | None
    source_timezone: str
    headers: tuple[tuple[str, str], ...]
    classification: VintageClassification
    archive_source: str
    archive_confidence: ArchiveConfidence
    proof_metadata: tuple[tuple[str, str], ...] = ()
    revision_of: str | None = None


class ArchiveAdapter(Protocol):
    source_id: str

    def fetch(self) -> tuple[ArchivePayload, ...]: ...


@dataclass(frozen=True, slots=True)
class ArchiveJobDefinition:
    source_id: str
    family: str
    enabled: bool
    expected_frequency: str
    archive_discovery: str


ARCHIVE_JOBS = (
    ArchiveJobDefinition(
        "il.boi",
        "boi",
        True,
        "daily + policy calendar",
        "official publications and current snapshots kept distinct",
    ),
    ArchiveJobDefinition(
        "uk.bbc.business",
        "news",
        True,
        "hourly",
        "forward RSS snapshots; operator-supplied licensed archives only",
    ),
    ArchiveJobDefinition(
        "us.sec.edgar",
        "sec",
        True,
        "daily",
        "accession history, submissions, and companyfacts with compliant User-Agent",
    ),
    ArchiveJobDefinition(
        "il.cbs",
        "cbs",
        True,
        "daily",
        "forward current-response archive; official releases separate",
    ),
    ArchiveJobDefinition(
        "il.mof", "government", False, "daily", "official publication archive contract pending"
    ),
    ArchiveJobDefinition(
        "il.tase.maya",
        "disclosures",
        False,
        "daily",
        "disabled until access and revision contract review",
    ),
    ArchiveJobDefinition(
        "global.geopolitical.official",
        "geopolitical",
        False,
        "daily",
        "source-specific official feeds required",
    ),
    ArchiveJobDefinition(
        "telegram.allowlisted",
        "social",
        False,
        "operator schedule",
        "future public allowlist text only",
    ),
)


class ArchiveService:
    def __init__(self, session: Session, root: Path) -> None:
        self.session = session
        self.artifacts = LocalArtifactStore(root)
        self.repository = SqlArchiveRepository(session)

    def archive(self, payload: ArchivePayload) -> tuple[EvidenceVintage, bool]:
        try:
            DEFAULT_REGISTRY.get(payload.source_id)
        except ValidationError:
            if payload.source_id != "us.sec.edgar":
                raise
        artifact = self.artifacts.put(payload.content, mime_type=payload.mime_type)
        if self.session.get(ArtifactModel, artifact.sha256) is None:
            self.session.add(
                ArtifactModel(
                    sha256=artifact.sha256,
                    size_bytes=artifact.size_bytes,
                    mime_type=artifact.mime_type,
                    relative_path=artifact.relative_path,
                    created_at=payload.retrieved_at,
                )
            )
            self.session.flush()
        first_observed = payload.retrieved_at
        valid_from = (
            payload.source_published_at
            if payload.classification
            in {
                VintageClassification.OFFICIAL_ARCHIVED_VINTAGE,
                VintageClassification.THIRD_PARTY_ARCHIVED_SNAPSHOT,
            }
            and payload.source_published_at is not None
            else first_observed
        )
        vintage = EvidenceVintage(
            payload.source_id,
            f"sha256:{artifact.sha256}",
            payload.canonical_uri,
            payload.source_published_at,
            first_observed,
            payload.retrieved_at,
            payload.retrieved_at,
            valid_from,
            None,
            payload.revision_of,
            payload.archive_source,
            payload.archive_confidence,
            payload.classification,
            (f"artifact:sha256:{artifact.sha256}", f"retrieval:{payload.canonical_uri}"),
            payload.server_date_at,
            payload.source_timezone,
            (*payload.headers, *payload.proof_metadata),
            RetentionClass.CRITICAL_RAW_EVIDENCE,
        )
        inserted = self.repository.add_vintage(vintage)
        self.session.commit()
        return vintage, inserted

    def run(self, adapter: ArchiveAdapter) -> ArchiveRunManifest:
        started = datetime.now(UTC)
        inserted = duplicates = revisions = bytes_downloaded = 0
        error = None
        status = ArchiveRunStatus.SUCCEEDED
        try:
            payloads = adapter.fetch()
            for payload in payloads:
                if payload.source_id != adapter.source_id:
                    raise IntegrityViolation("archive adapter returned a different source")
                _, created = self.archive(payload)
                inserted += int(created)
                duplicates += int(not created)
                revisions += int(payload.revision_of is not None and created)
                bytes_downloaded += len(payload.content)
        except (OSError, RuntimeError, IntegrityViolation, GovernanceViolation) as exc:
            self.session.rollback()
            payloads = ()
            status = ArchiveRunStatus.FAILED
            error = type(exc).__name__
        finished = datetime.now(UTC)
        manifest = ArchiveRunManifest(
            uuid4().hex,
            adapter.source_id,
            started,
            finished,
            status,
            len(payloads),
            inserted,
            duplicates,
            bytes_downloaded,
            revisions,
            0,
            error,
        )
        self.repository.add_run(manifest)
        self.session.commit()
        return manifest

    def record_gap(self, source_id: str, expected_at: datetime, reason: str) -> ArchiveGap:
        gap = ArchiveGap(source_id, expected_at, datetime.now(UTC), reason)
        self.repository.add_gap(gap)
        self.session.commit()
        return gap


def evaluate_replay_upgrade(
    case: HistoricalReplayCase, vintages: tuple[EvidenceVintage, ...]
) -> ReplayEligibilityDecision:
    required = {
        item.source_uri
        for item in case.source_manifest
        if item.role is ReplayDataRole.RETROSPECTIVE_METADATA
    }
    proven = {
        vintage.canonical_uri: vintage
        for vintage in vintages
        if vintage.replay_eligible and vintage.canonical_uri in required
    }
    missing = tuple(sorted(required - proven.keys()))
    return ReplayEligibilityDecision(
        case.case_id,
        case.version,
        bool(required) and not missing,
        tuple(sorted(item.vintage_id for item in proven.values())),
        missing,
        case.version + 1,
    )


def archive_storage_projection(coverage_bytes_per_day: int) -> tuple[dict[str, int | str], ...]:
    if coverage_bytes_per_day < 0:
        raise IntegrityViolation("archive storage rate cannot be negative")
    scenarios = (
        ("official_only", 1.0),
        ("official_plus_news", 5.0),
        ("official_news_telegram_text", 8.0),
        ("media_enabled_hypothetical", 100.0),
    )
    return tuple(
        {
            "scenario": name,
            "raw_bytes_per_day": round(coverage_bytes_per_day * multiplier),
            "revision_multiplier_basis_points": 11000,
            "projected_year_bytes": round(coverage_bytes_per_day * multiplier * 365 * 1.1),
        }
        for name, multiplier in scenarios
    )


def replay_backfill_report(
    cases: tuple[HistoricalReplayCase, ...],
) -> tuple[dict[str, object], ...]:
    output: list[dict[str, object]] = []
    for case in cases:
        if case.status.value != "UNUSABLE_FOR_CAUSAL_REPLAY":
            continue
        possible = []
        for item in case.source_manifest:
            if item.role is ReplayDataRole.RETROSPECTIVE_METADATA:
                possible.append(item.source_id)
        recoverability = "unknown"
        output.append(
            {
                "case_id": case.case_id,
                "title": case.title,
                "missing_evidence_type": list(case.domains),
                "missing_vintage_proof": list(case.expected_replay_limitations),
                "possible_official_archive_source": sorted(set(possible)),
                "recoverability": recoverability,
            }
        )
    return tuple(output)


def write_archive_reports(root: Path, session: Session) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    repository = SqlArchiveRepository(session)
    coverage = [asdict(item) for item in repository.coverage()]
    daily = sum(int(item["bytes_archived"]) for item in coverage)
    document = {
        "coverage": coverage,
        "storage_projection": archive_storage_projection(daily),
        "retention": "critical raw evidence retained; normalized rebuildable; derived caches rebuildable; media separate",
    }
    path = root / "archive-status.json"
    path.write_text(json.dumps(document, default=str, indent=2, sort_keys=True), encoding="utf-8")
    return path
