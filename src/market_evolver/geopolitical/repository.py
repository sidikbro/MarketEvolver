"""Append-only geopolitical persistence and historical visibility queries."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_evolver.errors import IntegrityViolation
from market_evolver.geopolitical.schemas import (
    CandidateReviewState,
    ConfirmationState,
    CorroborationKind,
    GeopoliticalCandidateReview,
    GeopoliticalCorroboration,
    GeopoliticalEvent,
    GeopoliticalEventCandidate,
    GeopoliticalEventType,
    GeopoliticalStatus,
    TransmissionHorizon,
    TransmissionPath,
)
from market_evolver.observatory.mechanisms import DEFAULT_MECHANISM_REGISTRY
from market_evolver.storage.models import (
    EvidenceModel,
    GeopoliticalCandidateModel,
    GeopoliticalCandidateReviewModel,
    GeopoliticalCorroborationModel,
    GeopoliticalEventModel,
    GeopoliticalTransmissionModel,
)
from market_evolver.time import require_aware_utc


class SqlGeopoliticalRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_candidate(self, item: GeopoliticalEventCandidate) -> bool:
        if self.session.get(GeopoliticalCandidateModel, item.candidate_id) is not None:
            return False
        self._require_evidence(item.source_evidence_ids, item.created_at)
        for mechanism in item.mechanism_candidates:
            DEFAULT_MECHANISM_REGISTRY.get(mechanism)
        self.session.add(
            GeopoliticalCandidateModel(
                candidate_id=item.candidate_id,
                source_evidence_ids=list(item.source_evidence_ids),
                event_type=None if item.event_type is None else item.event_type.value,
                actors=list(item.actors),
                geography=list(item.geography),
                explicit_timestamps=[value.isoformat() for value in item.explicit_timestamps],
                mechanism_candidates=list(item.mechanism_candidates),
                extraction_method=item.extraction_method,
                confidence=item.confidence,
                created_at=item.created_at,
                review_state=item.review_state.value,
                supporting_spans=list(item.supporting_spans),
            )
        )
        return True

    def review_candidate(self, item: GeopoliticalCandidateReview) -> bool:
        candidate = self.session.get(GeopoliticalCandidateModel, item.candidate_id)
        if candidate is None or _utc(candidate.created_at) > item.reviewed_at:
            raise IntegrityViolation("candidate review references unavailable candidate")
        if self.session.get(GeopoliticalCandidateReviewModel, item.review_id) is not None:
            return False
        self.session.add(
            GeopoliticalCandidateReviewModel(
                review_id=item.review_id,
                candidate_id=item.candidate_id,
                state=item.state.value,
                reviewed_at=item.reviewed_at,
                reviewer=item.reviewer,
                rationale=item.rationale,
            )
        )
        return True

    def candidate_review_state(self, candidate_id: str, cutoff: datetime) -> CandidateReviewState:
        at = require_aware_utc(cutoff, "cutoff")
        row = self.session.scalar(
            select(GeopoliticalCandidateReviewModel)
            .where(
                GeopoliticalCandidateReviewModel.candidate_id == candidate_id,
                GeopoliticalCandidateReviewModel.reviewed_at <= at,
            )
            .order_by(GeopoliticalCandidateReviewModel.reviewed_at.desc())
            .limit(1)
        )
        return CandidateReviewState.UNREVIEWED if row is None else CandidateReviewState(row.state)

    def add_event(self, item: GeopoliticalEvent, *, candidate_id: str | None = None) -> bool:
        if self.session.get(GeopoliticalEventModel, item.event_id) is not None:
            return False
        self._require_evidence(item.source_evidence_ids, item.first_observed_at)
        if (
            candidate_id is not None
            and self.candidate_review_state(candidate_id, item.first_observed_at)
            is not CandidateReviewState.PROMOTED
        ):
            raise IntegrityViolation(
                "candidate must be explicitly promoted before canonicalization"
            )
        if item.revision_of is not None:
            previous = self.session.get(GeopoliticalEventModel, item.revision_of)
            if previous is None or item.version != previous.version + 1:
                raise IntegrityViolation(
                    "geopolitical revision must reference the preceding version"
                )
            if previous.event_type != item.event_type.value:
                raise IntegrityViolation("geopolitical revision cannot change event type")
            if _utc(previous.first_observed_at) >= item.first_observed_at:
                raise IntegrityViolation("geopolitical revision violates causal ordering")
        self.session.add(
            GeopoliticalEventModel(
                event_id=item.event_id,
                event_type=item.event_type.value,
                geography=list(item.geography),
                actors=list(item.actors),
                source_evidence_ids=list(item.source_evidence_ids),
                status=item.status.value,
                started_at=item.started_at,
                announced_at=item.announced_at,
                first_observed_at=item.first_observed_at,
                ended_at=item.ended_at,
                confidence=item.confidence,
                confirmation_state=item.confirmation_state.value,
                revision_of=item.revision_of,
                provenance=list(item.provenance),
                version=item.version,
            )
        )
        return True

    def get(self, event_id: str) -> GeopoliticalEvent | None:
        row = self.session.get(GeopoliticalEventModel, event_id)
        return None if row is None else self._event(row)

    def events_visible_at(self, cutoff: datetime) -> tuple[GeopoliticalEvent, ...]:
        at = require_aware_utc(cutoff, "cutoff")
        rows = tuple(
            self.session.scalars(
                select(GeopoliticalEventModel).where(GeopoliticalEventModel.first_observed_at <= at)
            )
        )
        supported = tuple(
            row for row in rows if self._evidence_visible(tuple(row.source_evidence_ids), at)
        )
        revised = {row.revision_of for row in supported if row.revision_of is not None}
        return tuple(
            self._event(row)
            for row in sorted(
                supported, key=lambda value: (_utc(value.first_observed_at), value.event_id)
            )
            if row.event_id not in revised
        )

    def add_path(self, item: TransmissionPath) -> bool:
        event = self.session.get(GeopoliticalEventModel, item.event_id)
        if event is None or _utc(event.first_observed_at) > item.observed_at:
            raise IntegrityViolation("transmission references unavailable event")
        for mechanism in item.mechanisms:
            DEFAULT_MECHANISM_REGISTRY.get(mechanism)
        if self.session.get(GeopoliticalTransmissionModel, item.path_id) is not None:
            return False
        self.session.add(
            GeopoliticalTransmissionModel(
                path_id=item.path_id,
                event_id=item.event_id,
                mechanisms=list(item.mechanisms),
                affected_entities=list(item.affected_entities),
                horizon=item.horizon.value,
                confidence=item.confidence,
                rationale=item.rationale,
                provenance_ids=list(item.provenance_ids),
                observed_at=item.observed_at,
                valid_until=item.valid_until,
            )
        )
        return True

    def paths_visible_at(
        self, cutoff: datetime, *, event_ids: tuple[str, ...] | None = None
    ) -> tuple[TransmissionPath, ...]:
        at = require_aware_utc(cutoff, "cutoff")
        statement = select(GeopoliticalTransmissionModel).where(
            GeopoliticalTransmissionModel.observed_at <= at
        )
        if event_ids is not None:
            if not event_ids:
                return ()
            statement = statement.where(GeopoliticalTransmissionModel.event_id.in_(event_ids))
        return tuple(
            self._path(row)
            for row in self.session.scalars(statement)
            if row.valid_until is None or _utc(row.valid_until) > at
        )

    def add_corroboration(self, item: GeopoliticalCorroboration) -> bool:
        if self.session.get(GeopoliticalCandidateModel, item.candidate_id) is None:
            raise IntegrityViolation("corroboration references unknown candidate")
        self._require_evidence(item.evidence_ids, item.observed_at)
        if self.session.get(GeopoliticalCorroborationModel, item.corroboration_id) is not None:
            return False
        self.session.add(
            GeopoliticalCorroborationModel(
                corroboration_id=item.corroboration_id,
                candidate_id=item.candidate_id,
                evidence_ids=list(item.evidence_ids),
                source_ids=list(item.source_ids),
                kind=item.kind.value,
                observed_at=item.observed_at,
                rationale=item.rationale,
                confidence=item.confidence,
            )
        )
        return True

    def corroborations_visible_at(self, cutoff: datetime) -> tuple[GeopoliticalCorroboration, ...]:
        at = require_aware_utc(cutoff, "cutoff")
        rows = self.session.scalars(
            select(GeopoliticalCorroborationModel).where(
                GeopoliticalCorroborationModel.observed_at <= at
            )
        )
        return tuple(
            GeopoliticalCorroboration(
                row.candidate_id,
                tuple(row.evidence_ids),
                tuple(row.source_ids),
                CorroborationKind(row.kind),
                _utc(row.observed_at),
                row.rationale,
                row.confidence,
            )
            for row in rows
        )

    def candidates_visible_at(self, cutoff: datetime) -> tuple[GeopoliticalEventCandidate, ...]:
        at = require_aware_utc(cutoff, "cutoff")
        return tuple(
            self._candidate(row)
            for row in self.session.scalars(
                select(GeopoliticalCandidateModel).where(
                    GeopoliticalCandidateModel.created_at <= at
                )
            )
        )

    def _require_evidence(self, ids: tuple[str, ...], cutoff: datetime) -> None:
        if not ids or not self._evidence_visible(ids, cutoff):
            raise IntegrityViolation("geopolitical record references unavailable evidence")

    def _evidence_visible(self, ids: tuple[str, ...], cutoff: datetime) -> bool:
        return all(
            (row := self.session.get(EvidenceModel, key)) is not None
            and _utc(row.observed_at) <= cutoff
            for key in ids
        )

    @staticmethod
    def _event(row: GeopoliticalEventModel) -> GeopoliticalEvent:
        return GeopoliticalEvent(
            GeopoliticalEventType(row.event_type),
            tuple(row.geography),
            tuple(row.actors),
            tuple(row.source_evidence_ids),
            GeopoliticalStatus(row.status),
            None if row.started_at is None else _utc(row.started_at),
            None if row.announced_at is None else _utc(row.announced_at),
            _utc(row.first_observed_at),
            None if row.ended_at is None else _utc(row.ended_at),
            row.confidence,
            ConfirmationState(row.confirmation_state),
            row.revision_of,
            tuple(row.provenance),
            row.version,
        )

    @staticmethod
    def _candidate(row: GeopoliticalCandidateModel) -> GeopoliticalEventCandidate:
        return GeopoliticalEventCandidate(
            tuple(row.source_evidence_ids),
            None if row.event_type is None else GeopoliticalEventType(row.event_type),
            tuple(row.actors),
            tuple(row.geography),
            tuple(datetime.fromisoformat(value) for value in row.explicit_timestamps),
            tuple(row.mechanism_candidates),
            row.extraction_method,
            row.confidence,
            _utc(row.created_at),
            CandidateReviewState(row.review_state),
            tuple(row.supporting_spans),
        )

    @staticmethod
    def _path(row: GeopoliticalTransmissionModel) -> TransmissionPath:
        return TransmissionPath(
            row.event_id,
            tuple(row.mechanisms),
            tuple(row.affected_entities),
            TransmissionHorizon(row.horizon),
            row.confidence,
            row.rationale,
            tuple(row.provenance_ids),
            _utc(row.observed_at),
            None if row.valid_until is None else _utc(row.valid_until),
        )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
