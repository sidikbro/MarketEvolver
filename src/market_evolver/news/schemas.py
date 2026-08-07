"""Immutable News Lab records and explicit trust-boundary types."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from urllib.parse import urlparse

from market_evolver.errors import ValidationError
from market_evolver.provenance import content_id
from market_evolver.sources.registry import SourceDefinition, TrustClass
from market_evolver.time import require_aware_utc


class EvidenceSecurityClass(str, Enum):
    TRUSTED_STRUCTURED = "trusted_structured"
    TRUSTED_UNSTRUCTURED = "trusted_unstructured"
    UNTRUSTED_UNSTRUCTURED = "untrusted_unstructured"
    QUARANTINED = "quarantined"


class ExtractionStatus(str, Enum):
    PENDING = "pending"
    EXTRACTED = "extracted"
    QUARANTINED = "quarantined"


class ReviewState(str, Enum):
    UNREVIEWED = "unreviewed"
    CORROBORATED = "corroborated"
    REJECTED = "rejected"
    PROMOTED = "promoted"


class DuplicateKind(str, Enum):
    ORIGINAL = "original"
    REINGESTED = "reingested"
    REVISION = "revision"
    SYNDICATED = "syndicated"
    INDEPENDENT = "independent"


class ContradictionStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"


def classify_evidence_security(
    source: SourceDefinition, *, structured: bool
) -> EvidenceSecurityClass:
    """Classify provenance, never factual correctness."""
    if source.trust_class is TrustClass.ANONYMOUS_OR_UNKNOWN:
        return EvidenceSecurityClass.QUARANTINED
    if source.trust_class is TrustClass.OFFICIAL:
        return (
            EvidenceSecurityClass.TRUSTED_STRUCTURED
            if structured and source.machine_readable
            else EvidenceSecurityClass.TRUSTED_UNSTRUCTURED
        )
    return EvidenceSecurityClass.UNTRUSTED_UNSTRUCTURED


@dataclass(frozen=True, slots=True)
class NewsItem:
    source_id: str
    title: str
    body: str
    language: str
    published_at: datetime
    first_observed_at: datetime
    canonical_uri: str
    content_hash: str
    raw_artifact_sha256: str
    parser_version: str
    trust_class: TrustClass
    evidence_security_class: EvidenceSecurityClass
    evidence_id: str
    updated_at: datetime | None = None
    last_modified_at: datetime | None = None
    revision_of: str | None = None
    extraction_status: ExtractionStatus = ExtractionStatus.PENDING
    quarantine_reason: str | None = None
    provenance: tuple[str, ...] = ()
    duplicate_kind: DuplicateKind = DuplicateKind.ORIGINAL
    normalized_fingerprint: str = ""
    news_id: str = field(init=False)

    def __post_init__(self) -> None:
        published = require_aware_utc(self.published_at, "published_at")
        observed = require_aware_utc(self.first_observed_at, "first_observed_at")
        if published > observed:
            raise ValidationError("news published_at cannot follow first_observed_at")
        object.__setattr__(self, "published_at", published)
        object.__setattr__(self, "first_observed_at", observed)
        for name in ("updated_at", "last_modified_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, require_aware_utc(value, name))
        if not self.source_id or not self.title.strip() or not self.body.strip():
            raise ValidationError("news source, title, and body are required")
        parsed = urlparse(self.canonical_uri)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValidationError("news canonical_uri must be an absolute HTTPS URI")
        if not self.content_hash.startswith("sha256:") or len(self.content_hash) != 71:
            raise ValidationError("news content_hash must be SHA-256")
        if len(self.raw_artifact_sha256) != 64:
            raise ValidationError("raw artifact SHA-256 is malformed")
        if not self.evidence_id or not self.parser_version or not self.provenance:
            raise ValidationError("news evidence, parser version, and provenance are required")
        quarantined = self.evidence_security_class is EvidenceSecurityClass.QUARANTINED
        expected_hash = (
            "sha256:" + hashlib.sha256(f"{self.title}\n{self.body}".encode()).hexdigest()
        )
        if not quarantined and self.content_hash != expected_hash:
            raise ValidationError("news content hash does not match title/body")
        if quarantined != (self.extraction_status is ExtractionStatus.QUARANTINED):
            raise ValidationError("quarantine security and extraction states must agree")
        if quarantined != bool(self.quarantine_reason):
            raise ValidationError("quarantined news requires exactly one quarantine reason")
        object.__setattr__(self, "news_id", content_id("news", self))


@dataclass(frozen=True, slots=True)
class NewsEventCandidate:
    news_id: str
    extracted_entities: tuple[str, ...]
    possible_event_type: str
    extraction_method: str
    confidence: float
    supporting_spans: tuple[str, ...]
    created_at: datetime
    review_state: ReviewState = ReviewState.UNREVIEWED
    candidate_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", require_aware_utc(self.created_at, "created_at"))
        if not self.news_id or not self.extraction_method or not self.possible_event_type:
            raise ValidationError("candidate identity and extraction metadata are required")
        if not 0 <= self.confidence <= 1:
            raise ValidationError("candidate confidence must be between zero and one")
        object.__setattr__(
            self,
            "candidate_id",
            content_id(
                "news-candidate",
                {
                    "news_id": self.news_id,
                    "extracted_entities": self.extracted_entities,
                    "possible_event_type": self.possible_event_type,
                    "extraction_method": self.extraction_method,
                    "confidence": self.confidence,
                    "supporting_spans": self.supporting_spans,
                    "created_at": self.created_at,
                },
            ),
        )


@dataclass(frozen=True, slots=True)
class CandidateReview:
    candidate_id: str
    state: ReviewState
    reviewed_at: datetime
    reviewer: str
    rationale: str
    review_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "reviewed_at", require_aware_utc(self.reviewed_at, "reviewed_at"))
        if not self.candidate_id or not self.reviewer or not self.rationale.strip():
            raise ValidationError("candidate review requires identity, reviewer, and rationale")
        if self.state is ReviewState.UNREVIEWED:
            raise ValidationError("unreviewed is an initial state, not a review action")
        object.__setattr__(self, "review_id", content_id("candidate-review", self))


@dataclass(frozen=True, slots=True)
class Corroboration:
    candidate_id: str
    evidence_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    independence_assumptions: tuple[str, ...]
    timestamp_ordering: tuple[str, ...]
    confidence: float
    contradictions: tuple[str, ...]
    created_at: datetime
    corroboration_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", require_aware_utc(self.created_at, "created_at"))
        if len(self.evidence_ids) < 2 or len(self.source_ids) < 2:
            raise ValidationError("corroboration requires at least two evidence sources")
        if len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValidationError("corroborating evidence must be distinct")
        if len(set(self.source_ids)) != len(self.source_ids):
            raise ValidationError("corroborating sources must be distinct")
        if not 0 <= self.confidence <= 1:
            raise ValidationError("corroboration confidence must be between zero and one")
        object.__setattr__(self, "corroboration_id", content_id("corroboration", self))


@dataclass(frozen=True, slots=True)
class EvidenceContradiction:
    evidence_a: str
    evidence_b: str
    contradiction_type: str
    detected_by: str
    confidence: float
    status: ContradictionStatus
    created_at: datetime
    contradiction_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", require_aware_utc(self.created_at, "created_at"))
        if (
            self.evidence_a == self.evidence_b
            or not self.contradiction_type
            or not self.detected_by
        ):
            raise ValidationError("contradiction requires two distinct evidence records")
        if not 0 <= self.confidence <= 1:
            raise ValidationError("contradiction confidence must be between zero and one")
        object.__setattr__(self, "contradiction_id", content_id("contradiction", self))
