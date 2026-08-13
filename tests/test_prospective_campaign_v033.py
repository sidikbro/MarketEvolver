from dataclasses import FrozenInstanceError, replace
from datetime import UTC, date, datetime, timedelta

import pytest

from market_evolver.errors import GovernanceViolation, ValidationError
from market_evolver.external.schemas import UsageAccounting
from market_evolver.research.governed import GroundingStatus
from market_evolver.research.prospective import (
    CampaignDefinition,
    CanonicalEntity,
    CaseEligibility,
    CaseReason,
    CommitmentLedger,
    ComparisonOperator,
    EvaluationRule,
    LedgerEntry,
    LedgerState,
    ModeEfficiency,
    OutcomeStatus,
    ProspectiveCommitment,
    ReviewerClaimAudit,
    ScheduledCase,
    audit_entity_integrity,
    deterministic_schedule,
    reviewer_metrics,
)
from market_evolver.research.schemas import ClaimType, ResearchClaim

NOW = datetime(2026, 8, 13, 12, tzinfo=UTC)


def rule() -> EvaluationRule:
    return EvaluationRule("usdils_close_change", ComparisonOperator.GREATER_THAN_OR_EQUAL, 0.01, -0.01, "ratio")


def campaign() -> CampaignDefinition:
    return CampaignDefinition(
        "v033-prospective-2026q3",
        date(2026, 8, 17),
        date(2026, 8, 20),
        ("pair.usdils",),
        (7,),
        ("authoritative official", "reviewed-news corroboration"),
        ("generalist", "specialist", "specialist_skeptical_reviewer"),
        "DeepSeek",
        "deepseek-v4-flash",
        ("Monday quiet control", "Tuesday/Thursday scheduled"),
        (rule(),),
        ("claim grounding", "reviewer recall", "cost per accepted claim"),
        NOW,
    )


def claim(text: str = "BOI policy transmission may affect USD/ILS.") -> ResearchClaim:
    return ResearchClaim(
        ClaimType.HYPOTHESIS,
        text,
        ("official:1", "news:1"),
        (),
        ("pair.usdils",),
        ("policy transmission",),
        "7 days",
        0.5,
        "deepseek-v4-flash",
        "prospective-v033/1",
        NOW,
    )


@pytest.mark.unit
def test_campaign_sealing_and_immutability() -> None:
    first = campaign()
    assert first.definition_hash == campaign().definition_hash
    with pytest.raises(FrozenInstanceError):
        first.model = "changed"  # type: ignore[misc]


@pytest.mark.unit
def test_deterministic_sampling_and_quiet_control() -> None:
    first = deterministic_schedule(campaign())
    assert first == deterministic_schedule(campaign())
    assert [row.reason for row in first] == [
        CaseReason.QUIET_CONTROL,
        CaseReason.SCHEDULED,
        CaseReason.SCHEDULED,
    ]


@pytest.mark.unit
def test_blocked_and_negative_control_cases_are_retained() -> None:
    blocked = ScheduledCase(
        campaign().campaign_id,
        "pair.usdils",
        date(2026, 8, 17),
        CaseReason.NEGATIVE_CONTROL,
        7,
        CaseEligibility.BLOCKED_EVIDENCE,
        ("reviewed news corroboration absent",),
    )
    assert blocked.eligibility is CaseEligibility.BLOCKED_EVIDENCE
    with pytest.raises(ValidationError, match="retain evidence"):
        replace(blocked, evidence_gate_reasons=())


@pytest.mark.unit
def test_entity_resolution_rejects_boi_bank_of_ireland_expansion() -> None:
    registry = {
        "il.boi": CanonicalEntity(
            "il.boi", "Bank of Israel", ("BOI",), ("Bank of Ireland",)
        )
    }
    assert audit_entity_integrity((claim("Bank of Israel policy may affect USD/ILS."),), ("il.boi",), registry)[0].accepted
    rejected = audit_entity_integrity(
        (claim("Bank of Ireland policy may affect USD/ILS."),), ("il.boi",), registry
    )[0]
    assert not rejected.accepted and rejected.conflicts == ("il.boi:Bank of Ireland",)


@pytest.mark.unit
def test_reviewer_miss_accounting() -> None:
    metrics = reviewer_metrics(
        (
            ReviewerClaimAudit("bad-missed", GroundingStatus.UNSUPPORTED, True, False),
            ReviewerClaimAudit("bad-caught", GroundingStatus.CONTRADICTED, False, False),
            ReviewerClaimAudit("good-rejected", GroundingStatus.SUPPORTED, False, True),
        )
    )
    assert metrics.unsupported_claims_caught == 1
    assert metrics.unsupported_claims_missed == 1
    assert metrics.supported_claims_incorrectly_rejected == 1
    assert metrics.contradictions_caught == 1
    assert metrics.precision == 0.5 and metrics.recall == 0.5


def commitment() -> ProspectiveCommitment:
    return ProspectiveCommitment(
        campaign().campaign_id,
        "case:1",
        NOW,
        "pair.usdils",
        7,
        "USD/ILS closes at least 1% above its cutoff close.",
        "close-to-close USD/ILS change over seven calendar days",
        rule(),
        0.5,
        "direction and magnitude uncertain",
        ("official:1", "news:1"),
        "specialist",
        "DeepSeek",
        "deepseek-v4-flash",
        NOW + timedelta(days=7),
        NOW + timedelta(days=8),
        NOW + timedelta(seconds=1),
    )


@pytest.mark.unit
def test_commitment_is_immutable_and_has_predeclared_maturity() -> None:
    sealed = commitment()
    assert sealed.evaluation_start == NOW + timedelta(days=7)
    with pytest.raises(FrozenInstanceError):
        sealed.prediction = "retrofitted"  # type: ignore[misc]


@pytest.mark.unit
def test_outcome_isolation_and_append_only_transitions() -> None:
    sealed = commitment()
    ledger = CommitmentLedger()
    base = {
        "campaign_id": sealed.campaign_id,
        "case_id": sealed.case_id,
        "commitment_id": sealed.commitment_id,
        "maturity_date": sealed.evaluation_start,
    }
    ledger.append(LedgerEntry(**base, state=LedgerState.SEALED, recorded_at=sealed.created_at))
    ledger.append(
        LedgerEntry(
            **base,
            state=LedgerState.AWAITING_OUTCOME,
            recorded_at=sealed.created_at + timedelta(seconds=1),
        )
    )
    with pytest.raises(GovernanceViolation, match="before maturity"):
        ledger.append(LedgerEntry(**base, state=LedgerState.MATURED, recorded_at=NOW + timedelta(days=1)))
    with pytest.raises(GovernanceViolation, match="future outcome"):
        LedgerEntry(
            **base,
            state=LedgerState.AWAITING_OUTCOME,
            recorded_at=NOW + timedelta(days=1),
            outcome_status=OutcomeStatus.SUPPORTED,
        )
    assert len(ledger.entries) == 2


@pytest.mark.unit
def test_predeclared_evaluation_thresholds() -> None:
    threshold = rule()
    assert threshold.evaluate(0.02) is OutcomeStatus.SUPPORTED
    assert threshold.evaluate(-0.02) is OutcomeStatus.FALSIFIED
    assert threshold.evaluate(0) is OutcomeStatus.INCONCLUSIVE
    assert threshold.evaluate(None) is OutcomeStatus.INCONCLUSIVE


@pytest.mark.unit
def test_efficiency_metrics() -> None:
    result = ModeEfficiency.from_usage(
        (UsageAccounting(100, 50, 1, 900, "0.003"),),
        reasoning_tokens=30,
        visible_tokens=20,
        accepted_claims=2,
    )
    assert result.calls == 1
    assert result.cost_per_accepted_claim == 0.0015
    assert result.tokens_per_accepted_claim == 75
    assert result.reasoning_visible_ratio == 1.5
    assert result.latency_per_accepted_claim_ms == 450
