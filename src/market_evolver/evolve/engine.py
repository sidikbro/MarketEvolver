from __future__ import annotations

import random
from dataclasses import replace
from datetime import datetime
from statistics import mean

from market_evolver.errors import GovernanceViolation
from market_evolver.evolve.policy import EvolutionPolicy
from market_evolver.evolve.schemas import (
    ApprovalState,
    ChallengerEvaluation,
    ChampionRegistryEvent,
    ExpertVersion,
    ImprovementProposal,
    RegistryAction,
    VersionMetrics,
)


def construct_challenger(
    parent: ExpertVersion, proposal: ImprovementProposal, created_at: datetime, actor: str
) -> ExpertVersion:
    if (
        proposal.parent_expert_version != parent.expert_version_id
        or proposal.expert_id != parent.expert_id
    ):
        raise GovernanceViolation("proposal does not target parent expert version")
    prompt_version = parent.prompt_version
    retrieval = parent.retrieval_configuration
    reasoning = parent.reasoning_template
    sources = parent.source_preferences
    tool_policy = parent.tool_policy
    diff: list[tuple[str, str, str]] = []
    for key, value in proposal.proposed_change:
        if key == "tool_policy":
            requested = tuple(part for part in value.split(",") if part)
            if not set(requested) <= set(parent.tool_policy):
                raise GovernanceViolation("challenger cannot expand expert capabilities")
            old: object = parent.tool_policy
            new: object = requested
            tool_policy = requested
        elif key == "prompt_version":
            old = prompt_version
            new = prompt_version = value
        elif key == "retrieval_configuration":
            old = retrieval
            parsed: list[tuple[str, str]] = []
            for part in (item for item in value.split("|") if item):
                if "=" not in part:
                    raise GovernanceViolation("retrieval configuration must use key=value")
                name, setting = part.split("=", 1)
                parsed.append((name, setting))
            retrieval = tuple(parsed)
            new = retrieval
        elif key == "reasoning_template":
            old = reasoning
            new = reasoning = tuple(part for part in value.split("|") if part)
        elif key == "source_preferences":
            old = sources
            new = sources = tuple(part for part in value.split("|") if part)
        else:
            raise GovernanceViolation("proposal change is not supported by bounded constructor")
        diff.append((key, repr(old), repr(new)))
    return ExpertVersion(
        parent.expert_id,
        parent.expert_version_id,
        proposal.proposal_id,
        prompt_version,
        retrieval,
        tool_policy,
        reasoning,
        sources,
        parent.model_policy,
        created_at,
        actor,
        ApprovalState.CHALLENGER,
        None,
        tuple(diff),
        (*parent.provenance, proposal.proposal_id),
    )


def evaluate_challenger(
    champion: ExpertVersion,
    challenger: ExpertVersion,
    manifest_id: str,
    champion_metrics: VersionMetrics,
    challenger_metrics: VersionMetrics,
    case_deltas: tuple[float, ...],
    evaluated_at: datetime,
    policy: EvolutionPolicy,
) -> ChallengerEvaluation:
    if challenger.parent_version != champion.expert_version_id:
        raise GovernanceViolation("challenger is not paired with supplied champion")
    safety = (
        challenger_metrics.safety_violations
        + challenger_metrics.temporal_leakage
        + challenger_metrics.fabricated_provenance
        + challenger_metrics.action_attempts
    )
    reasons: list[str] = []
    if safety:
        reasons.append("CRITICAL_SAFETY_REGRESSION")
    if len(case_deltas) < policy.minimum_cases:
        reasons.append("INSUFFICIENT_CASES")
    if (
        challenger_metrics.grounded_claim_rate + policy.grounded_noninferiority_margin
        < champion_metrics.grounded_claim_rate
    ):
        reasons.append("GROUNDED_CLAIM_REGRESSION")
    if (
        challenger_metrics.domain_quality - champion_metrics.domain_quality
        < policy.minimum_domain_improvement
    ):
        reasons.append("DOMAIN_IMPROVEMENT_INSUFFICIENT")
    if (
        challenger_metrics.reviewer_acceptance + policy.reviewer_regression_tolerance
        < champion_metrics.reviewer_acceptance
    ):
        reasons.append("REVIEWER_ACCEPTANCE_REGRESSION")
    allowed_cost = champion_metrics.operational_cost * (1 + policy.cost_increase_tolerance)
    if challenger_metrics.operational_cost > allowed_cost:
        reasons.append("COST_TOLERANCE_EXCEEDED")
    wins = sum(value > 0 for value in case_deltas)
    losses = sum(value < 0 for value in case_deltas)
    ties = len(case_deltas) - wins - losses
    adequate = len(case_deltas) >= 10
    interval = paired_bootstrap_interval(case_deltas) if adequate else None
    decision = "quarantined" if safety else "eligible_for_promotion" if not reasons else "rejected"
    return ChallengerEvaluation(
        champion.expert_version_id,
        challenger.expert_version_id,
        manifest_id,
        case_deltas,
        champion_metrics,
        challenger_metrics,
        wins,
        ties,
        losses,
        mean(case_deltas) if case_deltas else 0.0,
        interval,
        adequate,
        bool(safety),
        decision,
        tuple(reasons),
        evaluated_at,
    )


def paired_bootstrap_interval(
    deltas: tuple[float, ...], iterations: int = 1000, seed: int = 0
) -> tuple[float, float]:
    if len(deltas) < 10:
        raise GovernanceViolation("sample is inadequate for confidence interval")
    generator = random.Random(seed)
    samples = sorted(mean(generator.choice(deltas) for _ in deltas) for _ in range(iterations))
    return samples[int(iterations * 0.025)], samples[int(iterations * 0.975)]


def promotion_event(
    challenger: ExpertVersion,
    previous: ExpertVersion,
    evaluation: ChallengerEvaluation,
    actor: str,
    reason: str,
    occurred_at: datetime,
) -> ChampionRegistryEvent:
    if evaluation.decision != "eligible_for_promotion" or evaluation.safety_veto:
        raise GovernanceViolation("challenger is not eligible for governed promotion")
    return ChampionRegistryEvent(
        challenger.expert_id,
        challenger.expert_version_id,
        previous.expert_version_id,
        RegistryAction.PROMOTION,
        actor,
        reason,
        occurred_at,
        (),
        evaluation.evaluation_id,
    )


def rollback_event(
    expert_id: str,
    prior_version_id: str,
    current_version_id: str,
    actor: str,
    reason: str,
    occurred_at: datetime,
    affected_sessions: tuple[str, ...],
) -> ChampionRegistryEvent:
    return ChampionRegistryEvent(
        expert_id,
        prior_version_id,
        current_version_id,
        RegistryAction.ROLLBACK,
        actor,
        reason,
        occurred_at,
        affected_sessions,
        None,
    )


def eligible_version(challenger: ExpertVersion, evaluation: ChallengerEvaluation) -> ExpertVersion:
    state = (
        ApprovalState.QUARANTINED
        if evaluation.safety_veto
        else (
            ApprovalState.ELIGIBLE
            if evaluation.decision == "eligible_for_promotion"
            else ApprovalState.REJECTED
        )
    )
    return replace(challenger, approval_state=state, benchmark_manifest_id=evaluation.manifest_id)
