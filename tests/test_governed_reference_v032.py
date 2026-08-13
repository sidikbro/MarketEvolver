import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from market_evolver.archive.schemas import VintageClassification
from market_evolver.errors import GovernanceViolation, IntegrityViolation
from market_evolver.external.provider import DEEPSEEK_PROFILE, DeepSeekProvider
from market_evolver.research.governed import (
    EvidenceGateStatus,
    GovernedEvidence,
    GovernedRunStatus,
    GroundingStatus,
    ReviewerDisposition,
    ReviewerEvaluation,
    assess_evidence_sufficiency,
    audit_claim_grounding,
    seal_commitment,
)
from market_evolver.research.schemas import (
    ClaimType,
    ContextItem,
    ResearchClaim,
    ResearchContext,
    ResearchTask,
)

NOW = datetime(2026, 8, 13, 12, tzinfo=UTC)


def evidence(
    evidence_id: str,
    source_id: str,
    trust: str,
    *,
    observed: datetime = NOW,
    contradictions: tuple[str, ...] = (),
) -> GovernedEvidence:
    return GovernedEvidence(
        evidence_id,
        f"vintage:{evidence_id}",
        source_id,
        trust,
        observed,
        observed,
        VintageClassification.OBSERVED_LIVE_AT_TIME,
        f"Observed record {evidence_id}",
        contradictions,
        ("mechanism",),
    )


def claim(*support: str, contradict: tuple[str, ...] = ()) -> ResearchClaim:
    return ResearchClaim(
        ClaimType.HYPOTHESIS,
        "A measurable relationship may occur.",
        support,
        contradict,
        ("pair.usdils",),
        ("policy transmission",),
        "7 days",
        0.5,
        "deepseek-v4-flash",
        "governed-reference/1",
        NOW,
    )


@pytest.mark.unit
def test_live_evidence_sufficiency_gate() -> None:
    items = (
        evidence("official:1", "il.boi", "authoritative_official"),
        evidence("news:1", "uk.bbc.business", "reviewed_news"),
    )
    result = assess_evidence_sufficiency(items, NOW)
    assert result.status is EvidenceGateStatus.PASS
    blocked = assess_evidence_sufficiency(items[:1], NOW)
    assert blocked.status is EvidenceGateStatus.BLOCKED_EVIDENCE
    assert "reviewed news corroboration absent" in blocked.reasons


@pytest.mark.unit
def test_non_live_and_future_evidence_are_rejected() -> None:
    with pytest.raises(GovernanceViolation, match="live-observed"):
        replace(
            evidence("x", "il.boi", "authoritative_official"),
            classification=VintageClassification.RETROSPECTIVELY_AVAILABLE_CURRENT_COPY,
        )
    with pytest.raises(IntegrityViolation, match="future evidence"):
        assess_evidence_sufficiency(
            (evidence("future", "il.boi", "authoritative_official", observed=NOW + timedelta(seconds=1)),),
            NOW,
        )


@pytest.mark.unit
def test_grounding_rejects_fabricated_and_classifies_claims() -> None:
    items = (
        evidence("official:1", "il.boi", "authoritative_official"),
        evidence("news:1", "uk.bbc.business", "reviewed_news"),
    )
    assert audit_claim_grounding((claim("official:1", "news:1"),), items)[0].status is GroundingStatus.SUPPORTED
    assert audit_claim_grounding((claim("official:1"),), items)[0].status is GroundingStatus.PARTIALLY_SUPPORTED
    with pytest.raises(IntegrityViolation, match="fabricated"):
        audit_claim_grounding((claim("fabricated:1"),), items)
    rejected = claim("official:1")
    assert audit_claim_grounding(
        (rejected,), items, rejected_claim_ids=(rejected.claim_id,)
    )[0].status is GroundingStatus.UNSUPPORTED


@pytest.mark.unit
def test_reviewer_can_be_inconclusive_and_commitment_preserves_provenance() -> None:
    review = ReviewerEvaluation(ReviewerDisposition.INCONCLUSIVE, 0, 0, 0, 1, "wider", "unchanged")
    assert review.disposition is ReviewerDisposition.INCONCLUSIVE
    items = (
        evidence("official:1", "il.boi", "authoritative_official"),
        evidence("news:1", "uk.bbc.business", "reviewed_news"),
    )
    sealed = seal_commitment(
        subject_id="pair.usdils",
        cutoff=NOW,
        committed_at=NOW + timedelta(seconds=1),
        horizon="7 days",
        hypothesis=claim("official:1", "news:1"),
        evidence=items,
        uncertainty="material",
        provider="DeepSeek",
        model="deepseek-v4-flash",
        expert_mode="specialist_skeptical_reviewer",
    )
    assert sealed.evidence_ids == ("news:1", "official:1")
    assert sealed.vintage_ids == ("vintage:news:1", "vintage:official:1")


class Response:
    status = 200

    def __init__(self, body: dict) -> None:
        self.headers = {"Content-Type": "application/json", "x-request-id": "request-fixture"}
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def read(self, limit: int) -> bytes:
        return self.body


@pytest.mark.unit
def test_reasoning_exhaustion_preserves_usage() -> None:
    profile = replace(DEEPSEEK_PROFILE, max_tokens=64)
    response = Response(
        {
            "id": "completion-fixture",
            "choices": [{"finish_reason": "length", "message": {"content": ""}}],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 64,
                "completion_tokens_details": {"reasoning_tokens": 64},
            },
        }
    )
    provider = DeepSeekProvider(
        profile,
        api_key="fixture-key",
        opener=lambda *args, **kwargs: response,
        clock=lambda: NOW,
    )
    context = ResearchContext(
        NOW,
        "pair.usdils",
        (ContextItem("evidence", "official:1", NOW, "Observed evidence"),),
    )
    result = provider.invoke_accounted(
        ResearchTask.HYPOTHESIS_GENERATION,
        context,
        prompt_version="governed-reference/1",
        settings={"temperature": "0"},
    )
    assert result.status is GovernedRunStatus.MODEL_OUTPUT_EXHAUSTED
    assert result.usage.input_tokens == 20 and result.usage.output_tokens == 64
    assert result.reasoning_tokens == 64 and result.visible_output_tokens == 0
    assert result.request_id == "request-fixture"
    assert result.usage.estimated_cost is not None


@pytest.mark.unit
def test_truncated_visible_json_is_still_output_exhaustion() -> None:
    profile = replace(DEEPSEEK_PROFILE, max_tokens=64)
    response = Response(
        {
            "choices": [{"finish_reason": "length", "message": {"content": '{"claims":['}}],
            "usage": {
                "prompt_tokens": 20,
                "completion_tokens": 64,
                "completion_tokens_details": {"reasoning_tokens": 50},
            },
        }
    )
    provider = DeepSeekProvider(profile, api_key="fixture-key", opener=lambda *args, **kwargs: response)
    context = ResearchContext(
        NOW,
        "pair.usdils",
        (ContextItem("evidence", "official:1", NOW, "Observed evidence"),),
    )
    result = provider.invoke_accounted(
        ResearchTask.HYPOTHESIS_GENERATION,
        context,
        prompt_version="governed-reference/1",
        settings={"temperature": "0"},
    )
    assert result.status is GovernedRunStatus.MODEL_OUTPUT_EXHAUSTED
    assert result.reasoning_tokens == 50 and result.visible_output_tokens == 14
