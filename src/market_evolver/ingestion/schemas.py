"""Immutable temporal records and operational ingestion manifests."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum

from market_evolver.errors import ValidationError
from market_evolver.provenance import content_id
from market_evolver.time import require_aware_utc


class IngestionStatus(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class NormalizedObservation:
    registry_source_id: str
    source_record_id: str
    dataset: str
    item_key: str
    period_start: date
    period_end: date
    published_at: datetime | None
    first_observed_at: datetime
    effective_at: datetime | None
    superseded_at: datetime | None
    value: str
    unit: str
    raw_artifact_sha256: str
    content_hash: str
    parser_version: str
    provenance_id: str = field(init=False)

    def __post_init__(self) -> None:
        if self.period_end < self.period_start:
            raise ValidationError("period_end cannot precede period_start")
        observed = require_aware_utc(self.first_observed_at, "first_observed_at")
        object.__setattr__(self, "first_observed_at", observed)
        for name in ("published_at", "effective_at", "superseded_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, require_aware_utc(value, name))
        if self.published_at is not None and self.published_at > observed:
            raise ValidationError("published_at cannot be after first_observed_at")
        required = (
            self.registry_source_id,
            self.source_record_id,
            self.dataset,
            self.item_key,
            self.value,
            self.unit,
            self.raw_artifact_sha256,
            self.content_hash,
            self.parser_version,
        )
        if any(not value for value in required):
            raise ValidationError("normalized observation fields cannot be empty")
        if self.content_hash != f"sha256:{self.raw_artifact_sha256}":
            raise ValidationError("observation content hash must match raw artifact")
        object.__setattr__(self, "provenance_id", content_id("observation", self))


@dataclass(frozen=True, slots=True)
class IngestionManifest:
    run_id: str
    source_id: str
    dataset: str
    started_at: datetime
    finished_at: datetime | None
    status: IngestionStatus
    items_fetched: int
    items_inserted: int
    duplicates: int
    bytes_downloaded: int
    raw_artifacts_created: int
    parser_version: str
    error_summary: str | None = None

    def __post_init__(self) -> None:
        started = require_aware_utc(self.started_at, "started_at")
        object.__setattr__(self, "started_at", started)
        if self.finished_at is not None:
            finished = require_aware_utc(self.finished_at, "finished_at")
            if finished < started:
                raise ValidationError("finished_at cannot precede started_at")
            object.__setattr__(self, "finished_at", finished)
        counts = (
            self.items_fetched,
            self.items_inserted,
            self.duplicates,
            self.bytes_downloaded,
            self.raw_artifacts_created,
        )
        if any(value < 0 for value in counts):
            raise ValidationError("manifest counters cannot be negative")
