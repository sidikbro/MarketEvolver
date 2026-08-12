from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from market_evolver.errors import GovernanceViolation, ValidationError
from market_evolver.provenance import content_id
from market_evolver.time import require_aware_utc


class VintageClassification(str, Enum):
    OBSERVED_LIVE_AT_TIME = "observed_live_at_time"
    OFFICIAL_ARCHIVED_VINTAGE = "official_archived_vintage"
    THIRD_PARTY_ARCHIVED_SNAPSHOT = "third_party_archived_snapshot"
    RETROSPECTIVELY_AVAILABLE_CURRENT_COPY = "retrospectively_available_current_copy"
    TEMPORALLY_AMBIGUOUS = "temporally_ambiguous"
    UNUSABLE_FOR_CAUSAL_REPLAY = "unusable_for_causal_replay"

    @property
    def proves_historical_availability(self) -> bool:
        return self in {
            self.OBSERVED_LIVE_AT_TIME,
            self.OFFICIAL_ARCHIVED_VINTAGE,
            self.THIRD_PARTY_ARCHIVED_SNAPSHOT,
        }


class ArchiveConfidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    UNKNOWN = "unknown"


class RetentionClass(str, Enum):
    CRITICAL_RAW_EVIDENCE = "critical_raw_evidence"
    NORMALIZED_REBUILDABLE = "normalized_rebuildable"
    DERIVED_CACHE = "derived_cache"
    MEDIA_SEPARATE_POLICY = "media_separate_policy"


class ArchiveRunStatus(str, Enum):
    SUCCEEDED = "succeeded"
    DEGRADED = "degraded"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class EvidenceVintage:
    source_id: str
    artifact_id: str
    canonical_uri: str
    source_published_at: datetime | None
    first_observed_at: datetime
    archived_at: datetime
    retrieval_at: datetime
    valid_from: datetime
    valid_until: datetime | None
    revision_of: str | None
    archive_source: str
    archive_confidence: ArchiveConfidence
    classification: VintageClassification
    provenance: tuple[str, ...]
    server_date_at: datetime | None = None
    source_timezone: str = "UTC"
    response_metadata: tuple[tuple[str, str], ...] = ()
    retention_class: RetentionClass = RetentionClass.CRITICAL_RAW_EVIDENCE
    vintage_id: str = field(init=False)

    def __post_init__(self) -> None:
        for name in (
            "source_published_at",
            "first_observed_at",
            "archived_at",
            "retrieval_at",
            "valid_from",
            "valid_until",
            "server_date_at",
        ):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, require_aware_utc(value, name))
        if not self.artifact_id.startswith("sha256:") or len(self.artifact_id) != 71:
            raise ValidationError("vintage requires a SHA-256 artifact ID")
        if not self.source_id or not self.canonical_uri.startswith("https://"):
            raise ValidationError("vintage source and canonical HTTPS URI are required")
        if self.archived_at < self.retrieval_at or self.first_observed_at < self.retrieval_at:
            raise ValidationError("archive observation cannot predate local retrieval")
        if self.valid_until is not None and self.valid_until <= self.valid_from:
            raise ValidationError("vintage validity interval is invalid")
        if not self.provenance or not self.archive_source or not self.source_timezone:
            raise ValidationError("archive proof and provenance are required")
        if self.classification is VintageClassification.OBSERVED_LIVE_AT_TIME:
            if self.archive_source != "direct_live_observation":
                raise GovernanceViolation("live vintage requires direct observation proof")
            if self.valid_from != self.first_observed_at:
                raise GovernanceViolation("live vintage visibility starts at first observation")
        if self.classification is VintageClassification.OFFICIAL_ARCHIVED_VINTAGE:
            if self.source_published_at is None or not any(
                key == "official_archive_proof" and value for key, value in self.response_metadata
            ):
                raise GovernanceViolation("official archive requires release/version proof")
            if self.archive_confidence is not ArchiveConfidence.HIGH:
                raise GovernanceViolation("official archive proof must be high confidence")
        if self.classification is VintageClassification.THIRD_PARTY_ARCHIVED_SNAPSHOT and (
            self.source_published_at is None
            or not any(
                key == "trusted_snapshot_at" and value for key, value in self.response_metadata
            )
        ):
            raise GovernanceViolation("third-party archive requires trusted snapshot proof")
        object.__setattr__(self, "vintage_id", content_id("evidence-vintage", self))

    @property
    def replay_eligible(self) -> bool:
        return self.classification.proves_historical_availability


@dataclass(frozen=True, slots=True)
class ArchiveRunManifest:
    run_id: str
    source_id: str
    started_at: datetime
    finished_at: datetime
    status: ArchiveRunStatus
    snapshots: int
    inserted: int
    duplicates: int
    bytes_downloaded: int
    revisions: int
    gaps: int
    error_summary: str | None

    def __post_init__(self) -> None:
        for name in ("started_at", "finished_at"):
            object.__setattr__(self, name, require_aware_utc(getattr(self, name), name))
        if self.finished_at < self.started_at or any(
            value < 0
            for value in (
                self.snapshots,
                self.inserted,
                self.duplicates,
                self.bytes_downloaded,
                self.revisions,
                self.gaps,
            )
        ):
            raise ValidationError("invalid archive run timing/counters")


@dataclass(frozen=True, slots=True)
class ArchiveGap:
    source_id: str
    expected_at: datetime
    detected_at: datetime
    reason: str
    resolved_by_vintage_id: str | None = None
    gap_id: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("expected_at", "detected_at"):
            object.__setattr__(self, name, require_aware_utc(getattr(self, name), name))
        if self.detected_at < self.expected_at or not self.source_id or not self.reason:
            raise ValidationError("archive gap requires an elapsed expected observation")
        object.__setattr__(self, "gap_id", content_id("archive-gap", self))


@dataclass(frozen=True, slots=True)
class ArchiveCoverage:
    source_id: str
    snapshots: int
    bytes_archived: int
    revisions: int
    gaps: int
    last_successful_observation: datetime | None
    retention_policy: str


@dataclass(frozen=True, slots=True)
class ReplayEligibilityDecision:
    prior_case_id: str
    prior_version: int
    eligible: bool
    supporting_vintage_ids: tuple[str, ...]
    missing_uris: tuple[str, ...]
    required_new_case_version: int
