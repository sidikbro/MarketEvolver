"""Disabled connector skeletons for CBS and TASE MAYA."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Never

from market_evolver.errors import GovernanceViolation
from market_evolver.ingestion.connectors import (
    BaseConnector,
    FetchedPayload,
    ParsedItem,
    PersistedPayload,
)
from market_evolver.ingestion.schemas import NormalizedObservation
from market_evolver.schemas import Evidence, Source
from market_evolver.time import require_aware_utc


class _DisabledConnector(BaseConnector):
    source_id: str
    parser_version = "skeleton/0"

    def fetch(self, dataset: str) -> FetchedPayload:
        self._disabled()

    def normalize(self, payload: PersistedPayload) -> PersistedPayload:
        self._disabled()

    def parse(self, payload: PersistedPayload, dataset: str) -> tuple[ParsedItem, ...]:
        self._disabled()

    def emit_evidence(
        self,
        item: ParsedItem,
        source: Source,
        observation: NormalizedObservation,
    ) -> Evidence:
        self._disabled()

    def _disabled(self) -> Never:
        raise GovernanceViolation(
            f"{self.source_id} ingestion is disabled until its official API contract is fixed"
        )


class IsraelCbsConnector(_DisabledConnector):
    source_id = "il.cbs"


class TaseMayaConnector(_DisabledConnector):
    source_id = "il.tase.maya"


@dataclass(frozen=True, slots=True)
class CorporateDisclosureMetadata:
    """Future MAYA disclosure envelope; no download behavior is enabled."""

    disclosure_id: str
    issuer_id: str
    published_at: datetime
    effective_at: datetime | None
    superseded_at: datetime | None
    source_uri: str
    mime_type: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "published_at", require_aware_utc(self.published_at, "published_at")
        )
        for name in ("effective_at", "superseded_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, require_aware_utc(value, name))
