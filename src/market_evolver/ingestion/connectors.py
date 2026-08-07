"""Generic connector contract and shared immutable payload types."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol

from market_evolver.ingestion.schemas import NormalizedObservation
from market_evolver.schemas import Evidence, Source
from market_evolver.storage.artifacts import Artifact, ArtifactStore
from market_evolver.time import require_aware_utc


@dataclass(frozen=True, slots=True)
class FetchedPayload:
    body: bytes
    source_uri: str
    content_type: str


@dataclass(frozen=True, slots=True)
class ObservedPayload:
    fetched: FetchedPayload
    first_observed_at: datetime
    sha256: str

    @classmethod
    def observe(cls, fetched: FetchedPayload, observed_at: datetime) -> ObservedPayload:
        """Hash bytes immediately, before any normalization or parsing."""
        return cls(
            fetched=fetched,
            first_observed_at=require_aware_utc(observed_at, "first_observed_at"),
            sha256=hashlib.sha256(fetched.body).hexdigest(),
        )


@dataclass(frozen=True, slots=True)
class PersistedPayload:
    observed: ObservedPayload
    artifact: Artifact


@dataclass(frozen=True, slots=True)
class ParsedItem:
    item_key: str
    period_start: date
    period_end: date
    published_at: datetime | None
    effective_at: datetime | None
    superseded_at: datetime | None
    value: str
    unit: str


class IngestionConnector(Protocol):
    source_id: str
    parser_version: str

    def fetch(self, dataset: str) -> FetchedPayload: ...

    def persist_raw(
        self, payload: ObservedPayload, artifact_store: ArtifactStore
    ) -> PersistedPayload: ...

    def normalize(self, payload: PersistedPayload) -> PersistedPayload: ...

    def parse(self, payload: PersistedPayload, dataset: str) -> tuple[ParsedItem, ...]: ...

    def emit_evidence(
        self,
        item: ParsedItem,
        source: Source,
        observation: NormalizedObservation,
    ) -> Evidence: ...


class BaseConnector:
    """Shared no-overwrite raw persistence implementation."""

    def persist_raw(
        self, payload: ObservedPayload, artifact_store: ArtifactStore
    ) -> PersistedPayload:
        artifact = artifact_store.put(
            payload.fetched.body,
            mime_type=payload.fetched.content_type,
            expected_sha256=payload.sha256,
        )
        return PersistedPayload(payload, artifact)
