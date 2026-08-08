"""Immutable schemas for uncertain geopolitical observations and mechanisms."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from market_evolver.errors import ValidationError
from market_evolver.provenance import content_id
from market_evolver.time import require_aware_utc


class GeopoliticalEventType(str, Enum):
    MILITARY_ESCALATION = "military_escalation"
    MILITARY_DEESCALATION = "military_deescalation"
    CEASEFIRE = "ceasefire"
    SANCTIONS = "sanctions"
    EXPORT_RESTRICTION = "export_restriction"
    TRADE_RESTRICTION = "trade_restriction"
    BORDER_CLOSURE = "border_closure"
    AIRSPACE_DISRUPTION = "airspace_disruption"
    SHIPPING_DISRUPTION = "shipping_disruption"
    ENERGY_SUPPLY_DISRUPTION = "energy_supply_disruption"
    DIPLOMATIC_CHANGE = "diplomatic_change"
    ELECTION_OR_GOVERNMENT_CHANGE = "election_or_government_change"
    SOVEREIGN_RISK_EVENT = "sovereign_risk_event"
    CYBER_GEOPOLITICAL_EVENT = "cyber_geopolitical_event"


class GeopoliticalStatus(str, Enum):
    REPORTED = "reported"
    ANNOUNCED = "announced"
    ONGOING = "ongoing"
    ENDED = "ended"
    AMENDED = "amended"
    WITHDRAWN = "withdrawn"


class ConfirmationState(str, Enum):
    UNVERIFIED = "unverified"
    PARTIALLY_CONFIRMED = "partially_confirmed"
    CONFIRMED = "confirmed"
    DISPUTED = "disputed"
    CONTRADICTED = "contradicted"
    RESOLVED = "resolved"


class CandidateReviewState(str, Enum):
    UNREVIEWED = "unreviewed"
    CORROBORATED = "corroborated"
    REJECTED = "rejected"
    PROMOTED = "promoted"


class TransmissionHorizon(str, Enum):
    IMMEDIATE = "immediate"
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class CorroborationKind(str, Enum):
    INDEPENDENT = "independent_sources"
    SYNDICATED = "syndicated_copy"
    OFFICIAL_CONFIRMATION = "official_confirmation"
    OFFICIAL_CONTRADICTION = "official_contradiction"
    UNRESOLVED_CONFLICT = "unresolved_conflict"


@dataclass(frozen=True, slots=True)
class GeopoliticalEvent:
    event_type: GeopoliticalEventType
    geography: tuple[str, ...]
    actors: tuple[str, ...]
    source_evidence_ids: tuple[str, ...]
    status: GeopoliticalStatus
    started_at: datetime | None
    announced_at: datetime | None
    first_observed_at: datetime
    ended_at: datetime | None
    confidence: float
    confirmation_state: ConfirmationState
    revision_of: str | None
    provenance: tuple[str, ...]
    version: int
    event_id: str = field(init=False)

    def __post_init__(self) -> None:
        observed = require_aware_utc(self.first_observed_at, "first_observed_at")
        object.__setattr__(self, "first_observed_at", observed)
        for name in ("started_at", "announced_at", "ended_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, require_aware_utc(value, name))
        if self.announced_at is not None and self.announced_at > observed:
            raise ValidationError(
                "geopolitical announcement cannot be observed before announcement"
            )
        if (
            self.ended_at is not None
            and self.started_at is not None
            and self.ended_at < self.started_at
        ):
            raise ValidationError("geopolitical event cannot end before it starts")
        if (
            not self.geography
            or not self.actors
            or not self.source_evidence_ids
            or not self.provenance
        ):
            raise ValidationError(
                "geopolitical event requires geography, actors, evidence, and provenance"
            )
        if not 0 <= self.confidence <= 1 or self.version < 1:
            raise ValidationError("invalid geopolitical confidence or version")
        if (self.version == 1) != (self.revision_of is None):
            raise ValidationError("only later geopolitical versions may identify a revision")
        object.__setattr__(self, "event_id", content_id("geopolitical-event", self))


@dataclass(frozen=True, slots=True)
class GeopoliticalEventCandidate:
    source_evidence_ids: tuple[str, ...]
    event_type: GeopoliticalEventType | None
    actors: tuple[str, ...]
    geography: tuple[str, ...]
    explicit_timestamps: tuple[datetime, ...]
    mechanism_candidates: tuple[str, ...]
    extraction_method: str
    confidence: float
    created_at: datetime
    review_state: CandidateReviewState = CandidateReviewState.UNREVIEWED
    supporting_spans: tuple[str, ...] = ()
    candidate_id: str = field(init=False)

    def __post_init__(self) -> None:
        created = require_aware_utc(self.created_at, "created_at")
        object.__setattr__(self, "created_at", created)
        timestamps = tuple(
            require_aware_utc(value, "explicit_timestamp") for value in self.explicit_timestamps
        )
        object.__setattr__(self, "explicit_timestamps", timestamps)
        if any(value > created for value in timestamps):
            raise ValidationError("candidate cannot contain a future explicit timestamp")
        if not self.source_evidence_ids or not self.extraction_method:
            raise ValidationError("geopolitical candidate requires evidence and extraction method")
        if not 0 <= self.confidence <= 1:
            raise ValidationError("candidate confidence must be between zero and one")
        object.__setattr__(self, "candidate_id", content_id("geopolitical-candidate", self))


@dataclass(frozen=True, slots=True)
class GeopoliticalCandidateReview:
    candidate_id: str
    state: CandidateReviewState
    reviewed_at: datetime
    reviewer: str
    rationale: str
    review_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "reviewed_at", require_aware_utc(self.reviewed_at, "reviewed_at"))
        if self.state is CandidateReviewState.UNREVIEWED or not self.reviewer or not self.rationale:
            raise ValidationError("candidate review must be an explicit governed decision")
        object.__setattr__(self, "review_id", content_id("geopolitical-review", self))


@dataclass(frozen=True, slots=True)
class TransmissionPath:
    event_id: str
    mechanisms: tuple[str, ...]
    affected_entities: tuple[str, ...]
    horizon: TransmissionHorizon
    confidence: float
    rationale: str
    provenance_ids: tuple[str, ...]
    observed_at: datetime
    valid_until: datetime | None = None
    path_id: str = field(init=False)

    def __post_init__(self) -> None:
        observed = require_aware_utc(self.observed_at, "observed_at")
        object.__setattr__(self, "observed_at", observed)
        if self.valid_until is not None:
            end = require_aware_utc(self.valid_until, "valid_until")
            object.__setattr__(self, "valid_until", end)
            if end <= observed:
                raise ValidationError("transmission validity must end after observation")
        if not self.mechanisms or not self.provenance_ids or not self.rationale.strip():
            raise ValidationError(
                "transmission path requires mechanisms, rationale, and provenance"
            )
        if not 0 <= self.confidence <= 1:
            raise ValidationError("transmission confidence must be between zero and one")
        if re.search(
            r"\b(buy|sell|long position|short position|price target|market will (rise|fall))\b",
            self.rationale.casefold(),
        ):
            raise ValidationError("transmission path cannot encode investment direction")
        object.__setattr__(self, "path_id", content_id("geopolitical-transmission", self))


@dataclass(frozen=True, slots=True)
class GeopoliticalCorroboration:
    candidate_id: str
    evidence_ids: tuple[str, ...]
    source_ids: tuple[str, ...]
    kind: CorroborationKind
    observed_at: datetime
    rationale: str
    confidence: float
    corroboration_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", require_aware_utc(self.observed_at, "observed_at"))
        if len(self.evidence_ids) < 2 or len(self.source_ids) < 2 or not self.rationale:
            raise ValidationError("geopolitical corroboration requires two sourced records")
        if self.kind is not CorroborationKind.SYNDICATED and (
            len(set(self.evidence_ids)) != len(self.evidence_ids)
            or len(set(self.source_ids)) != len(self.source_ids)
        ):
            raise ValidationError("independent or official corroboration requires distinct sources")
        if not 0 <= self.confidence <= 1:
            raise ValidationError("corroboration confidence must be between zero and one")
        object.__setattr__(self, "corroboration_id", content_id("geopolitical-corroboration", self))
