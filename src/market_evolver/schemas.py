"""Typed, immutable research records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from market_evolver.errors import ValidationError
from market_evolver.provenance import content_id
from market_evolver.time import ensure_available_at, require_aware_utc, validate_source_timeline


class SourceKind(str, Enum):
    NEWS = "news"
    SOCIAL = "social"
    TRENDS = "trends"
    GOVERNMENT = "government"
    GEOPOLITICAL = "geopolitical"
    MARKET_DATA = "market_data"
    RESEARCH = "research"


class TrustLevel(str, Enum):
    UNTRUSTED = "untrusted"
    CORROBORATED = "corroborated"
    AUTHORITATIVE = "authoritative"


class DecisionRecommendation(str, Enum):
    REJECT = "reject"
    WATCH = "watch"
    INVESTIGATE = "investigate"
    ACCEPT_FOR_RESEARCH = "accept_for_research"


@dataclass(frozen=True, slots=True)
class Source:
    uri: str
    kind: SourceKind
    publisher: str
    published_at: datetime
    observed_at: datetime
    ingested_at: datetime
    effective_at: datetime | None = None
    trust: TrustLevel = TrustLevel.UNTRUSTED
    content_digest: str = ""
    mime_type: str = "application/octet-stream"
    provenance_id: str = field(init=False)

    def __post_init__(self) -> None:
        if not self.uri or not self.publisher:
            raise ValidationError("source uri and publisher are required")
        validate_source_timeline(
            published_at=self.published_at,
            observed_at=self.observed_at,
            ingested_at=self.ingested_at,
        )
        object.__setattr__(
            self, "published_at", require_aware_utc(self.published_at, "published_at")
        )
        object.__setattr__(self, "observed_at", require_aware_utc(self.observed_at, "observed_at"))
        object.__setattr__(self, "ingested_at", require_aware_utc(self.ingested_at, "ingested_at"))
        if self.effective_at is not None:
            object.__setattr__(
                self, "effective_at", require_aware_utc(self.effective_at, "effective_at")
            )
        if not self.content_digest:
            raise ValidationError("content_digest is required")
        if not self.mime_type:
            raise ValidationError("mime_type is required")
        object.__setattr__(self, "provenance_id", content_id("source", self))

    @property
    def available_at(self) -> datetime:
        return require_aware_utc(self.observed_at, "observed_at")


@dataclass(frozen=True, slots=True)
class Evidence:
    claim: str
    source_ids: tuple[str, ...]
    observed_at: datetime
    excerpt_digest: str
    provenance_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", require_aware_utc(self.observed_at, "observed_at"))
        if not self.claim.strip():
            raise ValidationError("evidence claim is required")
        if not self.source_ids or any(not item for item in self.source_ids):
            raise ValidationError("every evidence claim requires source provenance")
        if not self.excerpt_digest:
            raise ValidationError("excerpt_digest is required")
        object.__setattr__(self, "provenance_id", content_id("evidence", self))

    @property
    def available_at(self) -> datetime:
        return require_aware_utc(self.observed_at, "observed_at")


@dataclass(frozen=True, slots=True)
class Event:
    title: str
    occurred_at: datetime
    known_at: datetime
    evidence_ids: tuple[str, ...]
    provenance_id: str = field(init=False)

    def __post_init__(self) -> None:
        occurred = require_aware_utc(self.occurred_at, "occurred_at")
        known = require_aware_utc(self.known_at, "known_at")
        if occurred > known:
            raise ValidationError("occurred_at cannot be after known_at")
        if not self.title.strip() or not self.evidence_ids:
            raise ValidationError("event title and evidence provenance are required")
        object.__setattr__(self, "occurred_at", occurred)
        object.__setattr__(self, "known_at", known)
        object.__setattr__(self, "provenance_id", content_id("event", self))

    @property
    def available_at(self) -> datetime:
        return require_aware_utc(self.known_at, "known_at")


@dataclass(frozen=True, slots=True)
class Hypothesis:
    statement: str
    as_of: datetime
    evidence_ids: tuple[str, ...]
    event_ids: tuple[str, ...] = ()
    confidence: float = 0.5
    provenance_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "as_of", require_aware_utc(self.as_of, "as_of"))
        if not self.statement.strip() or not self.evidence_ids:
            raise ValidationError("hypothesis statement and evidence provenance are required")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValidationError("confidence must be between 0 and 1")
        object.__setattr__(self, "provenance_id", content_id("hypothesis", self))

    @property
    def available_at(self) -> datetime:
        return require_aware_utc(self.as_of, "as_of")


@dataclass(frozen=True, slots=True)
class ResearchDecision:
    recommendation: DecisionRecommendation
    rationale: str
    decided_at: datetime
    knowledge_cutoff: datetime
    hypothesis_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    provenance_id: str = field(init=False)

    def __post_init__(self) -> None:
        decided = require_aware_utc(self.decided_at, "decided_at")
        cutoff = require_aware_utc(self.knowledge_cutoff, "knowledge_cutoff")
        if cutoff > decided:
            raise ValidationError("knowledge_cutoff cannot be after decided_at")
        if not self.rationale.strip() or not self.hypothesis_ids or not self.evidence_ids:
            raise ValidationError("decision requires rationale and complete provenance")
        object.__setattr__(self, "decided_at", decided)
        object.__setattr__(self, "knowledge_cutoff", cutoff)
        object.__setattr__(self, "provenance_id", content_id("decision", self))

    def validate_inputs(self, *records: Evidence | Event | Hypothesis | Source) -> None:
        """Validate that supplied inputs existed by this decision's cutoff."""
        for record in records:
            ensure_available_at(record.available_at, self.knowledge_cutoff)
