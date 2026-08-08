from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from market_evolver.errors import ValidationError
from market_evolver.news.schemas import EvidenceSecurityClass
from market_evolver.provenance import content_id
from market_evolver.time import require_aware_utc


class SocialSourceType(str, Enum):
    OFFICIAL_ACCOUNT = "official_account"
    JOURNALIST = "journalist"
    ANALYST = "analyst"
    COMPANY = "company"
    PUBLIC_CHANNEL = "public_channel"
    PUBLIC_GROUP = "public_group"
    FORUM = "forum"
    ANONYMOUS_ACCOUNT = "anonymous_account"
    UNKNOWN = "unknown"


class VerificationState(str, Enum):
    UNVERIFIED = "unverified"
    PLATFORM_VERIFIED = "platform_verified"
    IDENTITY_REVIEWED = "identity_reviewed"


class Accessibility(str, Enum):
    PUBLIC = "public"
    PRIVATE = "private"
    UNKNOWN = "unknown"


class NarrativeLifecycle(str, Enum):
    EMERGING = "emerging"
    ACTIVE = "active"
    FADING = "fading"
    EXPIRED = "expired"


class ClaimStatus(str, Enum):
    UNVERIFIED = "unverified"
    PARTIALLY_CONFIRMED = "partially_confirmed"
    CONFIRMED = "confirmed"
    CONTRADICTED = "contradicted"
    UNRESOLVED = "unresolved"
    EXPIRED = "expired"


class PropagationType(str, Enum):
    ORIGINAL = "original"
    REPLY = "reply"
    QUOTE = "quote"
    REPOST = "repost"
    FORWARDED_FROM = "forwarded_from"
    LIKELY_COPY_OF = "likely_copy_of"
    SAME_URL_CLUSTER = "same_url_cluster"
    SAME_TEXT_CLUSTER = "same_text_cluster"


class DuplicateClass(str, Enum):
    EXACT = "exact_duplicate"
    REPOST = "repost_forward"
    EDITED = "edited_copy"
    NEAR = "near_copy"
    INDEPENDENT = "independent_post"


class CoordinationStatus(str, Enum):
    CANDIDATE = "candidate"
    REVIEWED = "reviewed"
    DISMISSED = "dismissed"


@dataclass(frozen=True, slots=True)
class SocialSource:
    platform: str
    native_source_id: str
    display_name: str
    canonical_uri: str | None
    languages: tuple[str, ...]
    geography: tuple[str, ...]
    source_type: SocialSourceType
    created_at: datetime | None
    first_observed_at: datetime
    verification_state: VerificationState
    accessibility: Accessibility
    provenance: tuple[str, ...]
    active: bool = True
    source_id: str = field(init=False)

    def __post_init__(self) -> None:
        observed = require_aware_utc(self.first_observed_at, "first_observed_at")
        object.__setattr__(self, "first_observed_at", observed)
        if self.created_at is not None:
            object.__setattr__(self, "created_at", require_aware_utc(self.created_at, "created_at"))
        if self.accessibility is not Accessibility.PUBLIC:
            raise ValidationError("only public social sources may be registered")
        if (
            not self.platform
            or not self.native_source_id
            or not self.languages
            or not self.provenance
        ):
            raise ValidationError("social source identity and provenance required")
        object.__setattr__(self, "source_id", content_id("social-source", self))


@dataclass(frozen=True, slots=True)
class SocialPost:
    platform: str
    source_id: str
    native_post_id: str
    thread_parent_id: str | None
    reply_parent_id: str | None
    posted_at: datetime
    first_observed_at: datetime
    edited_at: datetime | None
    deleted_at: datetime | None
    original_text: str
    normalized_text: str
    language: str
    urls: tuple[str, ...]
    mentions: tuple[str, ...]
    quoted_source_id: str | None
    metrics: tuple[tuple[str, int], ...]
    raw_artifact_sha256: str
    content_hash: str
    media_references: tuple[str, ...]
    provenance: tuple[str, ...]
    revision_of: str | None = None
    post_id: str = field(init=False)
    security_class: EvidenceSecurityClass = field(
        init=False, default=EvidenceSecurityClass.UNTRUSTED_UNSTRUCTURED
    )

    def __post_init__(self) -> None:
        posted = require_aware_utc(self.posted_at, "posted_at")
        observed = require_aware_utc(self.first_observed_at, "first_observed_at")
        object.__setattr__(self, "posted_at", posted)
        object.__setattr__(self, "first_observed_at", observed)
        if posted > observed:
            raise ValidationError("social post cannot be observed before posting")
        for name in ("edited_at", "deleted_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, require_aware_utc(value, name))
        expected = "sha256:" + hashlib.sha256(self.original_text.encode()).hexdigest()
        if self.content_hash != expected or len(self.raw_artifact_sha256) != 64:
            raise ValidationError("social content or artifact hash mismatch")
        if not self.original_text or not self.provenance:
            raise ValidationError("social text and provenance required")
        object.__setattr__(self, "post_id", content_id("social-post", self))


@dataclass(frozen=True, slots=True)
class NarrativeCandidate:
    topics: tuple[str, ...]
    entities: tuple[str, ...]
    supporting_post_ids: tuple[str, ...]
    earliest_observed_at: datetime
    proposition: str
    language: str
    extraction_method: str
    confidence: float
    corroboration_state: str
    contradiction_state: str
    lifecycle_state: NarrativeLifecycle
    reviewed: bool = False
    candidate_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "earliest_observed_at",
            require_aware_utc(self.earliest_observed_at, "earliest_observed_at"),
        )
        if not self.supporting_post_ids or not self.proposition or not 0 <= self.confidence <= 1:
            raise ValidationError("invalid narrative candidate")
        object.__setattr__(self, "candidate_id", content_id("narrative-candidate", self))


@dataclass(frozen=True, slots=True)
class RumorClaim:
    proposition: str
    entities: tuple[str, ...]
    origin_post_id: str
    first_observed_at: datetime
    supporting_post_ids: tuple[str, ...]
    contradicting_post_ids: tuple[str, ...]
    official_evidence_ids: tuple[str, ...]
    news_evidence_ids: tuple[str, ...]
    status: ClaimStatus
    revision_of: str | None
    version: int
    claim_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "first_observed_at",
            require_aware_utc(self.first_observed_at, "first_observed_at"),
        )
        if (
            not self.proposition
            or self.version < 1
            or (self.version == 1) != (self.revision_of is None)
        ):
            raise ValidationError("invalid rumor version")
        object.__setattr__(self, "claim_id", content_id("rumor-claim", self))


@dataclass(frozen=True, slots=True)
class PropagationEdge:
    source_post_id: str
    target_post_id: str
    relation: PropagationType
    observed_at: datetime
    provenance: tuple[str, ...]
    edge_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", require_aware_utc(self.observed_at, "observed_at"))
        if self.source_post_id == self.target_post_id:
            raise ValidationError("propagation edge must connect distinct posts")
        object.__setattr__(self, "edge_id", content_id("social-propagation", self))


@dataclass(frozen=True, slots=True)
class CoordinationCandidate:
    post_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    features: tuple[tuple[str, str], ...]
    confidence: float
    status: CoordinationStatus
    observed_at: datetime
    provenance: tuple[str, ...]
    coordination_candidate_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", require_aware_utc(self.observed_at, "observed_at"))
        if len(self.post_ids) < 2 or not 0 <= self.confidence <= 1:
            raise ValidationError("coordination candidate needs a cluster")
        object.__setattr__(
            self, "coordination_candidate_id", content_id("coordination-candidate", self)
        )


@dataclass(frozen=True, slots=True)
class ReputationSnapshot:
    source_id: str
    domain: str
    window_start: datetime
    window_end: datetime
    computed_at: datetime
    claims_originated: int
    confirmed: int
    contradicted: int
    unresolved: int
    median_confirmation_lead_seconds: int | None
    copy_rate: float
    original_content_rate: float
    sample_size: int
    uncertainty: str
    snapshot_id: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("window_start", "window_end", "computed_at"):
            object.__setattr__(self, name, require_aware_utc(getattr(self, name), name))
        if (
            self.window_end > self.computed_at
            or self.window_start > self.window_end
            or self.sample_size < 0
        ):
            raise ValidationError("invalid reputation cutoff window")
        object.__setattr__(self, "snapshot_id", content_id("social-reputation", self))
