"""Government action persistence and point-in-time lifecycle replay."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_evolver.errors import IntegrityViolation
from market_evolver.government.schemas import (
    ExpectationStatus,
    GovernmentAction,
    GovernmentActionCandidate,
    GovernmentActionStatus,
    GovernmentActionType,
    GovernmentTransition,
    PolicyReviewState,
    validate_transition,
)
from market_evolver.observatory.mechanisms import DEFAULT_MECHANISM_REGISTRY
from market_evolver.storage.models import (
    EvidenceModel,
    GovernmentActionModel,
    GovernmentCandidateModel,
    GovernmentTransitionModel,
    KnowledgeEntityModel,
)
from market_evolver.time import require_aware_utc


class SqlGovernmentRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_action(self, action: GovernmentAction) -> tuple[GovernmentAction, bool]:
        existing = self.session.get(GovernmentActionModel, action.action_id)
        if existing is not None:
            restored = self._action(existing)
            if restored != action:
                raise IntegrityViolation("immutable government action identity collision")
            return restored, False
        self._require_evidence(action.source_evidence_ids, action.first_observed_at)
        if action.supersedes_action_id is not None:
            previous = self.session.get(GovernmentActionModel, action.supersedes_action_id)
            if previous is None:
                raise IntegrityViolation("government revision references unknown action")
            if action.version != previous.version + 1:
                raise IntegrityViolation("government action versions must be sequential")
        for entity_id in (
            action.issuing_body,
            *action.affected_entities,
            *action.affected_sectors,
        ):
            if not self.session.scalar(
                select(KnowledgeEntityModel).where(
                    KnowledgeEntityModel.entity_id == entity_id,
                    KnowledgeEntityModel.observed_at <= action.first_observed_at,
                )
            ):
                raise IntegrityViolation(
                    f"government action references unknown entity: {entity_id}"
                )
        for mechanism in action.candidate_mechanisms:
            DEFAULT_MECHANISM_REGISTRY.get(mechanism)
        self.session.add(
            GovernmentActionModel(
                action_id=action.action_id,
                jurisdiction=action.jurisdiction,
                issuing_body=action.issuing_body,
                action_type=action.action_type.value,
                title=action.title,
                description_reference=action.description_reference,
                status=action.status.value,
                announced_at=action.announced_at,
                published_at=action.published_at,
                effective_at=action.effective_at,
                first_observed_at=action.first_observed_at,
                expires_at=action.expires_at,
                supersedes_action_id=action.supersedes_action_id,
                source_evidence_ids=list(action.source_evidence_ids),
                affected_entities=list(action.affected_entities),
                affected_sectors=list(action.affected_sectors),
                candidate_mechanisms=list(action.candidate_mechanisms),
                confidence=action.confidence,
                provenance=list(action.provenance),
                version=action.version,
                expectation_status=action.expectation_status.value,
            )
        )
        self.session.flush()
        self.transition(
            action.action_id,
            from_status=None,
            to_status=action.status,
            transitioned_at=action.first_observed_at,
            evidence_ids=action.source_evidence_ids,
            rationale="Initial government action observation",
        )
        return action, True

    def transition(
        self,
        action_id: str,
        *,
        from_status: GovernmentActionStatus | None,
        to_status: GovernmentActionStatus,
        transitioned_at: datetime,
        evidence_ids: tuple[str, ...],
        rationale: str,
    ) -> GovernmentTransition:
        at = require_aware_utc(transitioned_at, "transitioned_at")
        if self.session.get(GovernmentActionModel, action_id) is None:
            raise IntegrityViolation("transition references unknown government action")
        current = self.current_status(action_id, at)
        if current is not from_status:
            raise IntegrityViolation(f"transition expected {from_status}, current is {current}")
        validate_transition(from_status, to_status)
        self._require_evidence(evidence_ids, at)
        transition = GovernmentTransition(
            action_id=action_id,
            from_status=from_status,
            to_status=to_status,
            transitioned_at=at,
            evidence_ids=evidence_ids,
            rationale=rationale,
            sequence=len(self.transitions(action_id)),
        )
        if self.session.get(GovernmentTransitionModel, transition.transition_id) is None:
            self.session.add(
                GovernmentTransitionModel(
                    transition_id=transition.transition_id,
                    action_id=action_id,
                    from_status=None if from_status is None else from_status.value,
                    to_status=to_status.value,
                    transitioned_at=at,
                    evidence_ids=list(evidence_ids),
                    rationale=rationale,
                    sequence=transition.sequence,
                )
            )
            self.session.flush()
        return transition

    def add_candidate(
        self, candidate: GovernmentActionCandidate
    ) -> tuple[GovernmentActionCandidate, bool]:
        self._require_evidence(candidate.evidence_ids, candidate.created_at)
        existing = self.session.get(GovernmentCandidateModel, candidate.candidate_id)
        if existing is not None:
            return self._candidate(existing), False
        self.session.add(
            GovernmentCandidateModel(
                candidate_id=candidate.candidate_id,
                evidence_ids=list(candidate.evidence_ids),
                issuing_body=candidate.issuing_body,
                possible_action_type=(
                    None
                    if candidate.possible_action_type is None
                    else candidate.possible_action_type.value
                ),
                possible_transition=(
                    None
                    if candidate.possible_transition is None
                    else candidate.possible_transition.value
                ),
                explicit_dates=[item.isoformat() for item in candidate.explicit_dates],
                explicit_values=list(candidate.explicit_values),
                entities=list(candidate.entities),
                candidate_mechanisms=list(candidate.candidate_mechanisms),
                extraction_method=candidate.extraction_method,
                confidence=candidate.confidence,
                created_at=candidate.created_at,
                review_state=candidate.review_state.value,
                expectation_status=candidate.expectation_status.value,
            )
        )
        self.session.flush()
        return candidate, True

    def get(self, action_id: str) -> GovernmentAction | None:
        model = self.session.get(GovernmentActionModel, action_id)
        return None if model is None else self._action(model)

    def get_actions_visible_at(self, cutoff: datetime) -> list[GovernmentAction]:
        at = require_aware_utc(cutoff, "cutoff")
        models = self.session.scalars(
            select(GovernmentActionModel)
            .where(GovernmentActionModel.first_observed_at <= at)
            .order_by(GovernmentActionModel.first_observed_at, GovernmentActionModel.action_id)
        )
        return [
            self._action(model)
            for model in models
            if all(
                (evidence := self.session.get(EvidenceModel, evidence_id)) is not None
                and _utc(evidence.observed_at) <= at
                for evidence_id in model.source_evidence_ids
            )
        ]

    def get_candidates_visible_at(self, cutoff: datetime) -> list[GovernmentActionCandidate]:
        at = require_aware_utc(cutoff, "cutoff")
        models = self.session.scalars(
            select(GovernmentCandidateModel)
            .where(GovernmentCandidateModel.created_at <= at)
            .order_by(GovernmentCandidateModel.created_at)
        )
        return [self._candidate(model) for model in models]

    def current_status(self, action_id: str, cutoff: datetime) -> GovernmentActionStatus | None:
        at = require_aware_utc(cutoff, "cutoff")
        model = self.session.scalar(
            select(GovernmentTransitionModel)
            .where(
                GovernmentTransitionModel.action_id == action_id,
                GovernmentTransitionModel.transitioned_at <= at,
            )
            .order_by(
                GovernmentTransitionModel.transitioned_at.desc(),
                GovernmentTransitionModel.sequence.desc(),
            )
            .limit(1)
        )
        return None if model is None else GovernmentActionStatus(model.to_status)

    def transitions(
        self, action_id: str, cutoff: datetime | None = None
    ) -> list[GovernmentTransition]:
        statement = select(GovernmentTransitionModel).where(
            GovernmentTransitionModel.action_id == action_id
        )
        if cutoff is not None:
            statement = statement.where(
                GovernmentTransitionModel.transitioned_at <= require_aware_utc(cutoff, "cutoff")
            )
        models = self.session.scalars(
            statement.order_by(
                GovernmentTransitionModel.transitioned_at,
                GovernmentTransitionModel.sequence,
            )
        )
        return [
            GovernmentTransition(
                action_id=model.action_id,
                from_status=(
                    None if model.from_status is None else GovernmentActionStatus(model.from_status)
                ),
                to_status=GovernmentActionStatus(model.to_status),
                transitioned_at=_utc(model.transitioned_at),
                evidence_ids=tuple(model.evidence_ids),
                rationale=model.rationale,
                sequence=model.sequence,
            )
            for model in models
        ]

    def _require_evidence(self, evidence_ids: tuple[str, ...], at: datetime) -> None:
        evidence = [self.session.get(EvidenceModel, item) for item in evidence_ids]
        if any(item is None for item in evidence):
            raise IntegrityViolation("unknown government evidence")
        if any(_utc(item.observed_at) > at for item in evidence if item is not None):
            raise IntegrityViolation("government record predates supporting evidence")

    @staticmethod
    def _action(model: GovernmentActionModel) -> GovernmentAction:
        action = GovernmentAction(
            jurisdiction=model.jurisdiction,
            issuing_body=model.issuing_body,
            action_type=GovernmentActionType(model.action_type),
            title=model.title,
            description_reference=model.description_reference,
            status=GovernmentActionStatus(model.status),
            announced_at=_utc_optional(model.announced_at),
            published_at=_utc_optional(model.published_at),
            effective_at=_utc_optional(model.effective_at),
            first_observed_at=_utc(model.first_observed_at),
            expires_at=_utc_optional(model.expires_at),
            supersedes_action_id=model.supersedes_action_id,
            source_evidence_ids=tuple(model.source_evidence_ids),
            affected_entities=tuple(model.affected_entities),
            affected_sectors=tuple(model.affected_sectors),
            candidate_mechanisms=tuple(model.candidate_mechanisms),
            confidence=model.confidence,
            provenance=tuple(model.provenance),
            version=model.version,
            expectation_status=ExpectationStatus(model.expectation_status),
        )
        if action.action_id != model.action_id:
            raise IntegrityViolation("stored government action failed identity verification")
        return action

    @staticmethod
    def _candidate(model: GovernmentCandidateModel) -> GovernmentActionCandidate:
        candidate = GovernmentActionCandidate(
            evidence_ids=tuple(model.evidence_ids),
            issuing_body=model.issuing_body,
            possible_action_type=(
                None
                if model.possible_action_type is None
                else GovernmentActionType(model.possible_action_type)
            ),
            possible_transition=(
                None
                if model.possible_transition is None
                else GovernmentActionStatus(model.possible_transition)
            ),
            explicit_dates=tuple(datetime.fromisoformat(item) for item in model.explicit_dates),
            explicit_values=tuple(model.explicit_values),
            entities=tuple(model.entities),
            candidate_mechanisms=tuple(model.candidate_mechanisms),
            extraction_method=model.extraction_method,
            confidence=model.confidence,
            created_at=_utc(model.created_at),
            review_state=PolicyReviewState(model.review_state),
            expectation_status=ExpectationStatus(model.expectation_status),
        )
        if candidate.candidate_id != model.candidate_id:
            raise IntegrityViolation("stored government candidate failed identity verification")
        return candidate


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _utc_optional(value: datetime | None) -> datetime | None:
    return None if value is None else _utc(value)
