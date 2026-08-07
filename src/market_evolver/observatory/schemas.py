"""Immutable canonical events, lifecycle transitions, and mechanism links."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from market_evolver.errors import ValidationError
from market_evolver.provenance import content_id
from market_evolver.time import require_aware_utc


class EventType(str, Enum):
    REPRESENTATIVE_EXCHANGE_RATE_UPDATE = "representative_exchange_rate_update"
    RATE_MOVEMENT = "rate_movement"
    UNUSUAL_FX_MOVE = "unusual_fx_move"
    BOI_POLICY_EVENT = "boi_policy_event"


class EventStatus(str, Enum):
    OBSERVED = "observed"
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    REVISED = "revised"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"


class RevisionState(str, Enum):
    ORIGINAL = "original"
    CORRECTED = "corrected"
    RESTATED = "restated"
    RETRACTED = "retracted"


class ReviewerStatus(str, Enum):
    UNREVIEWED = "unreviewed"
    RULE_VALIDATED = "rule_validated"
    HUMAN_APPROVED = "human_approved"
    REJECTED = "rejected"


class ExpectedHorizon(str, Enum):
    IMMEDIATE = "immediate"
    DAYS = "days"
    WEEKS = "weeks"
    MONTHS = "months"
    LONG_TERM = "long_term"


@dataclass(frozen=True, slots=True)
class CanonicalEvent:
    event_type: EventType
    source_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    geography: tuple[str, ...]
    entities: tuple[str, ...]
    sectors: tuple[str, ...]
    affected_asset_classes: tuple[str, ...]
    published_at: datetime | None
    first_observed_at: datetime
    effective_at: datetime | None
    event_status: EventStatus
    confidence: float
    novelty: float
    revision_state: RevisionState
    supersedes_event_id: str | None
    causal_mechanisms: tuple[str, ...]
    tags: tuple[str, ...]
    attributes: tuple[tuple[str, str], ...]
    deduplication_key: str
    material_fingerprint: str = field(init=False)
    event_id: str = field(init=False)

    def __post_init__(self) -> None:
        observed = require_aware_utc(self.first_observed_at, "first_observed_at")
        object.__setattr__(self, "first_observed_at", observed)
        for name in ("published_at", "effective_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, require_aware_utc(value, name))
        if self.published_at is not None and self.published_at > observed:
            raise ValidationError("event published_at cannot be after first_observed_at")
        if not self.source_ids or not self.evidence_ids:
            raise ValidationError("canonical events require source and evidence provenance")
        if not self.geography or not self.entities:
            raise ValidationError("canonical events require geography and entities")
        if not self.deduplication_key.strip():
            raise ValidationError("deduplication_key is required")
        if not 0.0 <= self.confidence <= 1.0 or not 0.0 <= self.novelty <= 1.0:
            raise ValidationError("confidence and novelty must be between 0 and 1")
        if self.revision_state is RevisionState.ORIGINAL and self.supersedes_event_id is not None:
            raise ValidationError("an original event cannot supersede another event")
        if self.revision_state is not RevisionState.ORIGINAL and not self.supersedes_event_id:
            raise ValidationError("a revised event must identify the superseded event")
        for values, label in (
            (self.source_ids, "source_ids"),
            (self.evidence_ids, "evidence_ids"),
            (self.geography, "geography"),
            (self.entities, "entities"),
            (self.affected_asset_classes, "affected_asset_classes"),
        ):
            if len(set(values)) != len(values) or any(not value for value in values):
                raise ValidationError(f"{label} must contain unique non-empty values")
        if tuple(sorted(self.attributes)) != self.attributes:
            raise ValidationError("event attributes must be sorted by key and value")

        material = {
            "event_type": self.event_type,
            "geography": self.geography,
            "entities": self.entities,
            "sectors": self.sectors,
            "affected_asset_classes": self.affected_asset_classes,
            "effective_at": self.effective_at,
            "revision_state": self.revision_state,
            "causal_mechanisms": self.causal_mechanisms,
            "tags": self.tags,
            "attributes": self.attributes,
            "deduplication_key": self.deduplication_key,
        }
        fingerprint = content_id("event-material", material)
        object.__setattr__(self, "material_fingerprint", fingerprint)
        object.__setattr__(
            self,
            "event_id",
            content_id(
                "canonical-event",
                {
                    **material,
                    "source_ids": self.source_ids,
                    "evidence_ids": self.evidence_ids,
                    "published_at": self.published_at,
                    "first_observed_at": self.first_observed_at,
                    "event_status": self.event_status,
                    "confidence": self.confidence,
                    "novelty": self.novelty,
                    "supersedes_event_id": self.supersedes_event_id,
                },
            ),
        )


@dataclass(frozen=True, slots=True)
class EventTransition:
    event_id: str
    from_status: EventStatus | None
    to_status: EventStatus
    transitioned_at: datetime
    rationale: str
    evidence_ids: tuple[str, ...]
    reviewer_status: ReviewerStatus
    sequence: int
    transition_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "transitioned_at",
            require_aware_utc(self.transitioned_at, "transitioned_at"),
        )
        if not self.event_id or not self.rationale.strip() or not self.evidence_ids:
            raise ValidationError("transition requires event, rationale, and evidence")
        if self.sequence < 0:
            raise ValidationError("transition sequence cannot be negative")
        validate_transition(self.from_status, self.to_status)
        object.__setattr__(self, "transition_id", content_id("event-transition", self))


@dataclass(frozen=True, slots=True)
class EventMechanismLink:
    event_id: str
    mechanism_id: str
    confidence: float
    expected_horizon: ExpectedHorizon
    rationale: str
    evidence_ids: tuple[str, ...]
    reviewer_status: ReviewerStatus
    linked_at: datetime
    link_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "linked_at", require_aware_utc(self.linked_at, "linked_at"))
        if not self.event_id or not self.mechanism_id or not self.rationale.strip():
            raise ValidationError("mechanism link requires event, mechanism, and rationale")
        if not self.evidence_ids:
            raise ValidationError("mechanism link requires evidence provenance")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValidationError("mechanism confidence must be between 0 and 1")
        object.__setattr__(self, "link_id", content_id("event-mechanism-link", self))


_TRANSITIONS: dict[EventStatus | None, frozenset[EventStatus]] = {
    None: frozenset((EventStatus.OBSERVED, EventStatus.PROPOSED)),
    EventStatus.OBSERVED: frozenset(
        (
            EventStatus.PROPOSED,
            EventStatus.CONFIRMED,
            EventStatus.REVISED,
            EventStatus.SUPERSEDED,
            EventStatus.RETRACTED,
        )
    ),
    EventStatus.PROPOSED: frozenset(
        (EventStatus.CONFIRMED, EventStatus.REVISED, EventStatus.RETRACTED)
    ),
    EventStatus.CONFIRMED: frozenset(
        (EventStatus.REVISED, EventStatus.SUPERSEDED, EventStatus.RETRACTED)
    ),
    EventStatus.REVISED: frozenset(
        (
            EventStatus.CONFIRMED,
            EventStatus.REVISED,
            EventStatus.SUPERSEDED,
            EventStatus.RETRACTED,
        )
    ),
    EventStatus.SUPERSEDED: frozenset(),
    EventStatus.RETRACTED: frozenset(),
}


def validate_transition(from_status: EventStatus | None, to_status: EventStatus) -> None:
    if to_status not in _TRANSITIONS[from_status]:
        before = "initial" if from_status is None else from_status.value
        raise ValidationError(f"invalid event transition: {before} -> {to_status.value}")
