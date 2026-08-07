"""Append-only persistence and replay for constrained research."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_evolver.errors import IntegrityViolation
from market_evolver.research.schemas import (
    AnonymizationMapping,
    ContextItem,
    ContextManifest,
    HypothesisStatus,
    ProviderCall,
    ResearchClaim,
    ResearchContext,
    ResearchHypothesis,
    ResearchTrace,
    ReviewerResult,
)
from market_evolver.storage.models import (
    AnonymizationMappingModel,
    ContextManifestModel,
    ProviderCallModel,
    ResearchClaimModel,
    ResearchContextModel,
    ResearchHypothesisModel,
    ResearchReviewModel,
    ResearchTraceModel,
)


class SqlResearchRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_context(self, context: ResearchContext) -> bool:
        if self.session.get(ResearchContextModel, context.research_context_id):
            return False
        self.session.add(
            ResearchContextModel(
                research_context_id=context.research_context_id,
                cutoff=context.cutoff,
                subject_id=context.subject_id,
                items=[
                    {
                        "kind": item.kind,
                        "provenance_id": item.provenance_id,
                        "first_observed_at": item.first_observed_at.isoformat(),
                        "text": item.text,
                        "evidence_ids": list(item.evidence_ids),
                    }
                    for item in context.items
                ],
                anonymized=context.anonymized,
            )
        )
        self.session.flush()
        return True

    def get_context(self, context_id: str) -> ResearchContext | None:
        model = self.session.get(ResearchContextModel, context_id)
        if model is None:
            return None
        return ResearchContext(
            _utc(model.cutoff),
            model.subject_id,
            tuple(
                ContextItem(
                    item["kind"],
                    item["provenance_id"],
                    datetime.fromisoformat(item["first_observed_at"]),
                    item["text"],
                    tuple(item["evidence_ids"]),
                )
                for item in model.items
            ),
            model.anonymized,
        )

    def add_manifest(self, item: ContextManifest) -> bool:
        if self.session.get(ContextManifestModel, item.manifest_id):
            return False
        if self.session.get(ResearchContextModel, item.research_context_id) is None:
            raise IntegrityViolation("manifest references unknown context")
        self.session.add(
            ContextManifestModel(
                manifest_id=item.manifest_id,
                research_context_id=item.research_context_id,
                cutoff=item.cutoff,
                subject_id=item.subject_id,
                evidence_ids=list(item.evidence_ids),
                event_ids=list(item.event_ids),
                policy_ids=list(item.policy_ids),
                filing_ids=list(item.filing_ids),
                fundamental_ids=list(item.fundamental_ids),
                graph_versions=list(item.graph_versions),
                model_id=item.model_id,
                prompt_version=item.prompt_version,
                created_at=item.created_at,
            )
        )
        self.session.flush()
        return True

    def add_anonymization_mapping(self, item: AnonymizationMapping) -> bool:
        if self.session.get(AnonymizationMappingModel, item.mapping_id):
            return False
        if self.session.get(ResearchContextModel, item.research_context_id) is None:
            raise IntegrityViolation("anonymization mapping references unknown context")
        self.session.add(
            AnonymizationMappingModel(
                mapping_id=item.mapping_id,
                research_context_id=item.research_context_id,
                values=[list(value) for value in item.values],
                created_at=item.created_at,
            )
        )
        self.session.flush()
        return True

    def get_anonymization_mapping(self, context_id: str) -> AnonymizationMapping | None:
        model = self.session.scalar(
            select(AnonymizationMappingModel)
            .where(AnonymizationMappingModel.research_context_id == context_id)
            .limit(1)
        )
        if model is None:
            return None
        return AnonymizationMapping(
            model.research_context_id,
            tuple((item[0], item[1]) for item in model.values),
            _utc(model.created_at),
        )

    def add_call(self, item: ProviderCall) -> bool:
        if self.session.get(ProviderCallModel, item.call_id):
            return False
        self.session.add(
            ProviderCallModel(
                call_id=item.call_id,
                provider_id=item.provider_id,
                model_id=item.model_id,
                requested_at=item.requested_at,
                responded_at=item.responded_at,
                settings=[list(value) for value in item.settings],
                prompt_version=item.prompt_version,
                token_usage=[list(value) for value in item.token_usage],
                raw_response_hash=item.raw_response_hash,
                structured_result=[_claim_json(claim) for claim in item.structured_result],
            )
        )
        self.session.flush()
        return True

    def add_claim(self, item: ResearchClaim) -> bool:
        if self.session.get(ResearchClaimModel, item.claim_id):
            return False
        self.session.add(ResearchClaimModel(claim_id=item.claim_id, **_claim_dict(item)))
        self.session.flush()
        return True

    def add_hypothesis(self, item: ResearchHypothesis) -> bool:
        if self.session.get(ResearchHypothesisModel, item.hypothesis_id):
            return False
        self.session.add(
            ResearchHypothesisModel(
                hypothesis_id=item.hypothesis_id,
                subject_entities=list(item.subject_entities),
                mechanism_chain=list(item.mechanism_chain),
                evidence_basis=list(item.evidence_basis),
                counterevidence=list(item.counterevidence),
                expected_horizon=item.expected_horizon,
                measurable_outcome=item.measurable_outcome,
                falsification_criterion=item.falsification_criterion,
                confidence=item.confidence,
                generated_by=item.generated_by,
                generated_at=item.generated_at,
                cutoff=item.cutoff,
                status=item.status.value,
            )
        )
        self.session.flush()
        return True

    def get_hypothesis(
        self, item_id: str, cutoff: datetime | None = None
    ) -> ResearchHypothesis | None:
        model = self.session.get(ResearchHypothesisModel, item_id)
        if model is None or (cutoff is not None and _utc(model.generated_at) > cutoff):
            return None
        return ResearchHypothesis(
            tuple(model.subject_entities),
            tuple(model.mechanism_chain),
            tuple(model.evidence_basis),
            tuple(model.counterevidence),
            model.expected_horizon,
            model.measurable_outcome,
            model.falsification_criterion,
            model.confidence,
            model.generated_by,
            _utc(model.generated_at),
            _utc(model.cutoff),
            HypothesisStatus(model.status),
        )

    def add_review(self, item: ReviewerResult) -> bool:
        if self.session.get(ResearchReviewModel, item.reviewer_id):
            return False
        if self.session.get(ResearchHypothesisModel, item.hypothesis_id) is None:
            raise IntegrityViolation("review references unknown hypothesis")
        self.session.add(
            ResearchReviewModel(
                reviewer_id=item.reviewer_id,
                hypothesis_id=item.hypothesis_id,
                accepted=item.accepted,
                issues=list(item.issues),
                alternative_explanations=list(item.alternative_explanations),
                stale_evidence_ids=list(item.stale_evidence_ids),
                reviewed_at=item.reviewed_at,
                model_id=item.model_id,
                prompt_version=item.prompt_version,
            )
        )
        self.session.flush()
        return True

    def add_trace(self, item: ResearchTrace) -> bool:
        if self.session.get(ResearchTraceModel, item.trace_id):
            return False
        if self.session.get(ContextManifestModel, item.manifest_id) is None:
            raise IntegrityViolation("trace references unknown manifest")
        if self.session.get(ProviderCallModel, item.provider_call_id) is None:
            raise IntegrityViolation("trace references unknown provider call")
        self.session.add(
            ResearchTraceModel(
                trace_id=item.trace_id,
                manifest_id=item.manifest_id,
                provider_call_id=item.provider_call_id,
                claim_ids=list(item.claim_ids),
                hypothesis_id=item.hypothesis_id,
                reviewer_id=item.reviewer_id,
                validation_state=item.validation_state,
                accepted=item.accepted,
                created_at=item.created_at,
            )
        )
        self.session.flush()
        return True

    def get_trace(self, trace_id: str) -> ResearchTrace | None:
        model = self.session.get(ResearchTraceModel, trace_id)
        if model is None:
            return None
        return ResearchTrace(
            model.manifest_id,
            model.provider_call_id,
            tuple(model.claim_ids),
            model.hypothesis_id,
            model.reviewer_id,
            model.validation_state,
            model.accepted,
            _utc(model.created_at),
        )

    def context_for_hypothesis(self, hypothesis_id: str) -> ResearchContext | None:
        trace = self.session.scalar(
            select(ResearchTraceModel)
            .where(
                ResearchTraceModel.hypothesis_id == hypothesis_id,
                ResearchTraceModel.reviewer_id.is_(None),
            )
            .order_by(ResearchTraceModel.created_at)
            .limit(1)
        )
        if trace is None:
            return None
        manifest = self.session.get(ContextManifestModel, trace.manifest_id)
        return None if manifest is None else self.get_context(manifest.research_context_id)


def _claim_dict(item: ResearchClaim) -> dict[str, object]:
    return {
        "claim_type": item.claim_type.value,
        "text": item.text,
        "supporting_evidence_ids": list(item.supporting_evidence_ids),
        "contradicting_evidence_ids": list(item.contradicting_evidence_ids),
        "entities": list(item.entities),
        "mechanisms": list(item.mechanisms),
        "horizon": item.horizon,
        "confidence": item.confidence,
        "model_id": item.model_id,
        "prompt_version": item.prompt_version,
        "created_at": item.created_at,
        "review_state": item.review_state.value,
    }


def _claim_json(item: ResearchClaim) -> dict[str, object]:
    value = _claim_dict(item)
    value["created_at"] = item.created_at.isoformat()
    return value


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
