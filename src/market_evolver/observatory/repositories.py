"""Canonical event persistence, lifecycle audit, replay, and reporting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_evolver.errors import IntegrityViolation
from market_evolver.observatory.entities import DEFAULT_ENTITY_REGISTRY, EntityRegistry
from market_evolver.observatory.mechanisms import (
    DEFAULT_MECHANISM_REGISTRY,
    MechanismRegistry,
)
from market_evolver.observatory.schemas import (
    CanonicalEvent,
    EventMechanismLink,
    EventStatus,
    EventTransition,
    EventType,
    ReviewerStatus,
    RevisionState,
)
from market_evolver.storage.models import (
    CanonicalEventModel,
    EventMechanismLinkModel,
    EventSupportModel,
    EventTransitionModel,
    EvidenceModel,
    SourceModel,
)
from market_evolver.time import require_aware_utc


@dataclass(frozen=True, slots=True)
class ObservatorySummary:
    events_by_source: dict[str, int]
    events_by_type: dict[str, int]
    revision_count: int
    entities_referenced: tuple[str, ...]
    mechanisms_referenced: tuple[str, ...]
    coverage_started_at: datetime | None
    coverage_ended_at: datetime | None


class SqlCanonicalEventRepository:
    def __init__(
        self,
        session: Session,
        *,
        entities: EntityRegistry = DEFAULT_ENTITY_REGISTRY,
        mechanisms: MechanismRegistry = DEFAULT_MECHANISM_REGISTRY,
    ) -> None:
        self.session = session
        self.entities = entities
        self.mechanisms = mechanisms

    def add(self, event: CanonicalEvent) -> tuple[CanonicalEvent, bool]:
        self._validate_registries(event)
        self._validate_provenance(event)
        existing = self.session.scalar(
            select(CanonicalEventModel).where(
                CanonicalEventModel.deduplication_key == event.deduplication_key,
                CanonicalEventModel.material_fingerprint == event.material_fingerprint,
            )
        )
        if existing is not None:
            restored = self._to_domain(existing)
            self._add_support(restored.event_id, event)
            self.session.flush()
            return restored, False

        same_identity = tuple(
            self.session.scalars(
                select(CanonicalEventModel).where(
                    CanonicalEventModel.deduplication_key == event.deduplication_key
                )
            )
        )
        if same_identity:
            if event.supersedes_event_id is None:
                raise IntegrityViolation(
                    "materially changed event must identify the superseded version"
                )
            superseded = self.session.get(CanonicalEventModel, event.supersedes_event_id)
            if superseded is None or superseded.deduplication_key != event.deduplication_key:
                raise IntegrityViolation("supersedes_event_id has a different canonical identity")

        model = self._to_model(event)
        self.session.add(model)
        self.session.flush()
        self._add_support(event.event_id, event)
        self._record_initial_lifecycle(event)
        if event.supersedes_event_id is not None:
            previous_status = self.current_status(
                event.supersedes_event_id, event.first_observed_at
            )
            self.transition(
                event.supersedes_event_id,
                from_status=previous_status,
                to_status=EventStatus.SUPERSEDED,
                transitioned_at=event.first_observed_at,
                rationale=f"Superseded by canonical revision {event.event_id}",
                evidence_ids=event.evidence_ids,
                reviewer_status=ReviewerStatus.RULE_VALIDATED,
            )
        self.session.flush()
        return event, True

    def get(self, event_id: str) -> CanonicalEvent | None:
        model = self.session.get(CanonicalEventModel, event_id)
        return None if model is None else self._to_domain(model)

    def latest_for_key_before(
        self, deduplication_key: str, cutoff: datetime
    ) -> CanonicalEvent | None:
        normalized = require_aware_utc(cutoff, "cutoff")
        model = self.session.scalar(
            select(CanonicalEventModel)
            .where(
                CanonicalEventModel.deduplication_key == deduplication_key,
                CanonicalEventModel.first_observed_at < normalized,
            )
            .order_by(
                CanonicalEventModel.first_observed_at.desc(),
                CanonicalEventModel.event_id.desc(),
            )
            .limit(1)
        )
        return None if model is None else self._to_domain(model)

    def get_events_visible_at(self, cutoff: datetime) -> list[CanonicalEvent]:
        normalized = require_aware_utc(cutoff, "cutoff")
        models = self.session.scalars(
            select(CanonicalEventModel)
            .where(CanonicalEventModel.first_observed_at <= normalized)
            .order_by(CanonicalEventModel.first_observed_at, CanonicalEventModel.event_id)
        )
        visible: list[CanonicalEvent] = []
        for model in models:
            evidence = [
                self.session.get(EvidenceModel, evidence_id) for evidence_id in model.evidence_ids
            ]
            if evidence and all(
                item is not None and _utc(item.observed_at) <= normalized for item in evidence
            ):
                visible.append(self._to_domain(model))
        return visible

    def transition(
        self,
        event_id: str,
        *,
        from_status: EventStatus | None,
        to_status: EventStatus,
        transitioned_at: datetime,
        rationale: str,
        evidence_ids: tuple[str, ...],
        reviewer_status: ReviewerStatus,
    ) -> EventTransition:
        if self.session.get(CanonicalEventModel, event_id) is None:
            raise IntegrityViolation("transition references an unknown event")
        self._require_evidence(evidence_ids, transitioned_at)
        current = self.current_status(event_id, transitioned_at)
        if current != from_status:
            raise IntegrityViolation(
                f"transition expected {from_status}, but current status is {current}"
            )
        transition = EventTransition(
            event_id=event_id,
            from_status=from_status,
            to_status=to_status,
            transitioned_at=transitioned_at,
            rationale=rationale,
            evidence_ids=evidence_ids,
            reviewer_status=reviewer_status,
            sequence=len(self.transitions(event_id)),
        )
        if self.session.get(EventTransitionModel, transition.transition_id) is None:
            self.session.add(
                EventTransitionModel(
                    transition_id=transition.transition_id,
                    event_id=transition.event_id,
                    from_status=(
                        None if transition.from_status is None else transition.from_status.value
                    ),
                    to_status=transition.to_status.value,
                    transitioned_at=transition.transitioned_at,
                    rationale=transition.rationale,
                    evidence_ids=list(transition.evidence_ids),
                    reviewer_status=transition.reviewer_status.value,
                    sequence=transition.sequence,
                )
            )
            self.session.flush()
        return transition

    def current_status(self, event_id: str, cutoff: datetime) -> EventStatus | None:
        normalized = require_aware_utc(cutoff, "cutoff")
        model = self.session.scalar(
            select(EventTransitionModel)
            .where(
                EventTransitionModel.event_id == event_id,
                EventTransitionModel.transitioned_at <= normalized,
            )
            .order_by(
                EventTransitionModel.transitioned_at.desc(),
                EventTransitionModel.sequence.desc(),
            )
            .limit(1)
        )
        return None if model is None else EventStatus(model.to_status)

    def transitions(self, event_id: str) -> list[EventTransition]:
        models = self.session.scalars(
            select(EventTransitionModel)
            .where(EventTransitionModel.event_id == event_id)
            .order_by(EventTransitionModel.transitioned_at, EventTransitionModel.sequence)
        )
        return [
            EventTransition(
                event_id=model.event_id,
                from_status=(None if model.from_status is None else EventStatus(model.from_status)),
                to_status=EventStatus(model.to_status),
                transitioned_at=_utc(model.transitioned_at),
                rationale=model.rationale,
                evidence_ids=tuple(model.evidence_ids),
                reviewer_status=ReviewerStatus(model.reviewer_status),
                sequence=model.sequence,
            )
            for model in models
        ]

    def _record_initial_lifecycle(self, event: CanonicalEvent) -> None:
        if event.event_status is EventStatus.PROPOSED:
            self.transition(
                event.event_id,
                from_status=None,
                to_status=EventStatus.PROPOSED,
                transitioned_at=event.first_observed_at,
                rationale="Event proposed by deterministic extraction",
                evidence_ids=event.evidence_ids,
                reviewer_status=ReviewerStatus.RULE_VALIDATED,
            )
            return
        self.transition(
            event.event_id,
            from_status=None,
            to_status=EventStatus.OBSERVED,
            transitioned_at=event.first_observed_at,
            rationale="Event observed in trusted evidence",
            evidence_ids=event.evidence_ids,
            reviewer_status=ReviewerStatus.RULE_VALIDATED,
        )
        if event.event_status is not EventStatus.OBSERVED:
            self.transition(
                event.event_id,
                from_status=EventStatus.OBSERVED,
                to_status=event.event_status,
                transitioned_at=event.first_observed_at,
                rationale=f"Deterministic rule assigned {event.event_status.value}",
                evidence_ids=event.evidence_ids,
                reviewer_status=ReviewerStatus.RULE_VALIDATED,
            )

    def _add_support(self, event_id: str, event: CanonicalEvent) -> None:
        for evidence_id in event.evidence_ids:
            evidence = self.session.get(EvidenceModel, evidence_id)
            assert evidence is not None
            supporting_sources = set(evidence.source_ids).intersection(event.source_ids)
            if not supporting_sources:
                raise IntegrityViolation("event source/evidence provenance does not intersect")
            for source_id in sorted(supporting_sources):
                key = {
                    "event_id": event_id,
                    "evidence_id": evidence_id,
                    "source_id": source_id,
                }
                if self.session.get(EventSupportModel, key) is None:
                    self.session.add(
                        EventSupportModel(
                            **key,
                            first_observed_at=event.first_observed_at,
                        )
                    )

    def _validate_registries(self, event: CanonicalEvent) -> None:
        for entity_id in event.entities:
            self.entities.get(entity_id)
        for mechanism_id in event.causal_mechanisms:
            self.mechanisms.get(mechanism_id)

    def _validate_provenance(self, event: CanonicalEvent) -> None:
        if any(self.session.get(SourceModel, item) is None for item in event.source_ids):
            raise IntegrityViolation("event references an unknown source")
        self._require_evidence(event.evidence_ids, event.first_observed_at)

    def _require_evidence(self, evidence_ids: tuple[str, ...], available_at: datetime) -> None:
        normalized = require_aware_utc(available_at, "available_at")
        evidence = [self.session.get(EvidenceModel, item) for item in evidence_ids]
        if any(item is None for item in evidence):
            raise IntegrityViolation("unknown event evidence provenance")
        if any(_utc(item.observed_at) > normalized for item in evidence if item is not None):
            raise IntegrityViolation("event or transition predates supporting evidence")

    @staticmethod
    def _to_model(event: CanonicalEvent) -> CanonicalEventModel:
        return CanonicalEventModel(
            event_id=event.event_id,
            event_type=event.event_type.value,
            source_ids=list(event.source_ids),
            evidence_ids=list(event.evidence_ids),
            geography=list(event.geography),
            entities=list(event.entities),
            sectors=list(event.sectors),
            affected_asset_classes=list(event.affected_asset_classes),
            published_at=event.published_at,
            first_observed_at=event.first_observed_at,
            effective_at=event.effective_at,
            event_status=event.event_status.value,
            confidence=event.confidence,
            novelty=event.novelty,
            revision_state=event.revision_state.value,
            supersedes_event_id=event.supersedes_event_id,
            causal_mechanisms=list(event.causal_mechanisms),
            tags=list(event.tags),
            attributes=[list(item) for item in event.attributes],
            deduplication_key=event.deduplication_key,
            material_fingerprint=event.material_fingerprint,
        )

    @staticmethod
    def _to_domain(model: CanonicalEventModel) -> CanonicalEvent:
        event = CanonicalEvent(
            event_type=EventType(model.event_type),
            source_ids=tuple(model.source_ids),
            evidence_ids=tuple(model.evidence_ids),
            geography=tuple(model.geography),
            entities=tuple(model.entities),
            sectors=tuple(model.sectors),
            affected_asset_classes=tuple(model.affected_asset_classes),
            published_at=_utc_optional(model.published_at),
            first_observed_at=_utc(model.first_observed_at),
            effective_at=_utc_optional(model.effective_at),
            event_status=EventStatus(model.event_status),
            confidence=model.confidence,
            novelty=model.novelty,
            revision_state=RevisionState(model.revision_state),
            supersedes_event_id=model.supersedes_event_id,
            causal_mechanisms=tuple(model.causal_mechanisms),
            tags=tuple(model.tags),
            attributes=tuple((str(item[0]), str(item[1])) for item in model.attributes),
            deduplication_key=model.deduplication_key,
        )
        if (
            event.event_id != model.event_id
            or event.material_fingerprint != model.material_fingerprint
        ):
            raise IntegrityViolation("stored event failed deterministic identity verification")
        return event


class SqlEventMechanismRepository:
    def __init__(
        self,
        session: Session,
        *,
        mechanisms: MechanismRegistry = DEFAULT_MECHANISM_REGISTRY,
    ) -> None:
        self.session = session
        self.mechanisms = mechanisms

    def add(self, link: EventMechanismLink) -> tuple[EventMechanismLink, bool]:
        self.mechanisms.get(link.mechanism_id)
        event = self.session.get(CanonicalEventModel, link.event_id)
        if event is None:
            raise IntegrityViolation("mechanism link references an unknown event")
        evidence = [self.session.get(EvidenceModel, item) for item in link.evidence_ids]
        if any(item is None for item in evidence):
            raise IntegrityViolation("mechanism link references unknown evidence")
        if any(_utc(item.observed_at) > link.linked_at for item in evidence if item is not None):
            raise IntegrityViolation("mechanism link predates its evidence")
        existing = self.session.get(EventMechanismLinkModel, link.link_id)
        if existing is not None:
            return link, False
        self.session.add(
            EventMechanismLinkModel(
                link_id=link.link_id,
                event_id=link.event_id,
                mechanism_id=link.mechanism_id,
                confidence=link.confidence,
                expected_horizon=link.expected_horizon.value,
                rationale=link.rationale,
                evidence_ids=list(link.evidence_ids),
                reviewer_status=link.reviewer_status.value,
                linked_at=link.linked_at,
            )
        )
        self.session.flush()
        return link, True


def observatory_summary(session: Session, cutoff: datetime | None = None) -> ObservatorySummary:
    normalized = datetime.max.replace(tzinfo=UTC) if cutoff is None else require_aware_utc(cutoff)
    repository = SqlCanonicalEventRepository(session)
    events = repository.get_events_visible_at(normalized)
    event_ids = {item.event_id for item in events}
    source_counts: dict[str, int] = {}
    type_counts: dict[str, int] = {}
    entities: set[str] = set()
    for event in events:
        type_counts[event.event_type.value] = type_counts.get(event.event_type.value, 0) + 1
        entities.update(event.entities)
        support_sources = set(event.source_ids)
        support_sources.update(
            session.scalars(
                select(EventSupportModel.source_id).where(
                    EventSupportModel.event_id == event.event_id,
                    EventSupportModel.first_observed_at <= normalized,
                )
            )
        )
        for source_id in support_sources:
            source_counts[source_id] = source_counts.get(source_id, 0) + 1
    mechanism_ids = set(
        session.scalars(
            select(EventMechanismLinkModel.mechanism_id).where(
                EventMechanismLinkModel.event_id.in_(event_ids),
                EventMechanismLinkModel.linked_at <= normalized,
            )
        )
    )
    observed = [item.first_observed_at for item in events]
    return ObservatorySummary(
        events_by_source=dict(sorted(source_counts.items())),
        events_by_type=dict(sorted(type_counts.items())),
        revision_count=sum(item.supersedes_event_id is not None for item in events),
        entities_referenced=tuple(sorted(entities)),
        mechanisms_referenced=tuple(sorted(mechanism_ids)),
        coverage_started_at=min(observed) if observed else None,
        coverage_ended_at=max(observed) if observed else None,
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _utc_optional(value: datetime | None) -> datetime | None:
    return None if value is None else _utc(value)
