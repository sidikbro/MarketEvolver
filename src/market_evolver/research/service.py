"""Governed orchestration from context manifest to unaccepted research trace."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from market_evolver.errors import IntegrityViolation
from market_evolver.research.context import ResearchContextBuilder
from market_evolver.research.gates import validate_context, validate_provider_output
from market_evolver.research.providers import ResearchProvider
from market_evolver.research.repositories import SqlResearchRepository
from market_evolver.research.schemas import (
    ContextItem,
    ContextManifest,
    HypothesisStatus,
    ResearchContext,
    ResearchHypothesis,
    ResearchTask,
    ResearchTrace,
    ReviewerResult,
)


class ResearchService:
    prompt_version = "constrained-research/1"

    def __init__(self, session: Session, provider: ResearchProvider) -> None:
        self.session = session
        self.provider = provider
        self.repository = SqlResearchRepository(session)

    def build_context(self, company_id: str, cutoff: datetime) -> ResearchContext:
        context = ResearchContextBuilder(self.session).build(company_id, cutoff)
        validate_context(context)
        self.repository.add_context(context)
        self.session.commit()
        return context

    def hypothesize(self, context: ResearchContext) -> tuple[ResearchHypothesis, ResearchTrace]:
        validate_context(context)
        now = datetime.now(UTC)
        manifest = self._manifest(context, now)
        self.repository.add_context(context)
        self.repository.add_manifest(manifest)
        self.session.commit()  # reproducibility boundary exists before the provider call
        call = self.provider.invoke(
            ResearchTask.HYPOTHESIS_GENERATION,
            context,
            prompt_version=self.prompt_version,
            settings={"temperature": "0"},
        )
        validate_provider_output(context, call)
        if not call.structured_result:
            raise IntegrityViolation("provider produced no grounded hypothesis candidate")
        claim = call.structured_result[0]
        hypothesis = ResearchHypothesis(
            subject_entities=claim.entities or (context.subject_id,),
            mechanism_chain=claim.mechanisms,
            evidence_basis=claim.supporting_evidence_ids,
            counterevidence=claim.contradicting_evidence_ids,
            expected_horizon=claim.horizon,
            measurable_outcome=claim.text,
            falsification_criterion=f"The measurable outcome does not occur within {claim.horizon}.",
            confidence=claim.confidence,
            generated_by=call.model_id,
            generated_at=call.responded_at,
            cutoff=context.cutoff,
            status=HypothesisStatus.PROPOSED,
        )
        self.repository.add_call(call)
        for output in call.structured_result:
            self.repository.add_claim(output)
        self.repository.add_hypothesis(hypothesis)
        trace = ResearchTrace(
            manifest.manifest_id,
            call.call_id,
            tuple(item.claim_id for item in call.structured_result),
            hypothesis.hypothesis_id,
            None,
            "validated",
            False,
            call.responded_at,
        )
        self.repository.add_trace(trace)
        self.session.commit()
        return hypothesis, trace

    def review(self, hypothesis: ResearchHypothesis, context: ResearchContext) -> ReviewerResult:
        validate_context(context)
        review_context = ResearchContext(
            hypothesis.generated_at,
            context.subject_id,
            (
                ContextItem(
                    "hypothesis",
                    hypothesis.hypothesis_id,
                    hypothesis.generated_at,
                    (
                        f"Outcome: {hypothesis.measurable_outcome}; horizon: "
                        f"{hypothesis.expected_horizon}; falsification: "
                        f"{hypothesis.falsification_criterion}"
                    ),
                    hypothesis.evidence_basis,
                ),
                *(item for item in context.items if item.kind == "evidence"),
            ),
        )
        manifest = self._manifest(review_context, datetime.now(UTC))
        self.repository.add_context(review_context)
        self.repository.add_manifest(manifest)
        self.session.commit()
        call = self.provider.invoke(
            ResearchTask.CONTRADICTION_IDENTIFICATION,
            review_context,
            prompt_version="skeptical-reviewer/1",
            settings={"temperature": "0"},
        )
        validate_provider_output(review_context, call)
        self.repository.add_call(call)
        for output in call.structured_result:
            self.repository.add_claim(output)
        allowed = context.allowed_provenance_ids
        issues: list[str] = []
        if not set(hypothesis.evidence_basis) <= allowed:
            issues.append("missing provenance")
        if len(hypothesis.evidence_basis) < 2:
            issues.append("selection bias: evidence basis has fewer than two records")
        if hypothesis.counterevidence:
            issues.append("contradicting evidence requires resolution")
        if not hypothesis.mechanism_chain:
            issues.append("causal mechanism is unclear")
        if hypothesis.expected_horizon.casefold() in {"", "unspecified", "unknown"}:
            issues.append("unclear horizon")
        if not hypothesis.falsification_criterion:
            issues.append("untestable hypothesis")
        if "priced in" in hypothesis.measurable_outcome.casefold():
            issues.append("already-priced-in assumption is unsupported")
        stale = tuple(
            item.provenance_id
            for item in context.items
            if item.kind == "evidence"
            and (hypothesis.generated_at - item.first_observed_at).days > 730
        )
        if stale:
            issues.append("stale evidence")
        result = ReviewerResult(
            hypothesis.hypothesis_id,
            not issues,
            tuple(issues),
            ("Observed relationship may reflect an omitted common cause.",),
            stale,
            datetime.now(UTC),
            self.provider.model_id,
            "skeptical-reviewer/1",
        )
        self.repository.add_review(result)
        trace = ResearchTrace(
            manifest.manifest_id,
            call.call_id,
            tuple(item.claim_id for item in call.structured_result),
            hypothesis.hypothesis_id,
            result.reviewer_id,
            "validated",
            result.accepted,
            result.reviewed_at,
        )
        self.repository.add_trace(trace)
        self.session.commit()
        return result

    def _manifest(self, context: ResearchContext, created_at: datetime) -> ContextManifest:
        by_kind = {
            kind: tuple(sorted(item.provenance_id for item in context.items if item.kind == kind))
            for kind in ("evidence", "event", "policy", "filing", "fundamental")
        }
        return ContextManifest(
            context.research_context_id,
            context.cutoff,
            context.subject_id,
            by_kind["evidence"],
            by_kind["event"],
            by_kind["policy"],
            by_kind["filing"],
            by_kind["fundamental"],
            tuple(
                sorted(
                    item.provenance_id
                    for item in context.items
                    if item.kind == "graph_relationship"
                )
            ),
            self.provider.model_id,
            self.prompt_version,
            created_at,
        )
