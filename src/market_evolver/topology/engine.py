from __future__ import annotations

from datetime import datetime

from market_evolver.errors import GovernanceViolation
from market_evolver.expert.schemas import ExpertDefinition
from market_evolver.topology.policy import TopologyPolicy
from market_evolver.topology.schemas import (
    GapCategory,
    GapSignal,
    ProposedExpert,
    RelationshipType,
    TopologyAction,
    TopologyEdge,
    TopologyEvaluation,
    TopologyMetrics,
    TopologyNode,
    TopologyProposal,
    TopologyProposalStatus,
    TopologyProposalType,
    TopologyRegistryEvent,
    TopologyState,
    TopologyVersion,
)


def detect_gaps(
    expert_id: str,
    domain: str,
    observed_at: datetime,
    measurements: dict[GapCategory, tuple[int, int, tuple[str, ...]]],
) -> tuple[GapSignal, ...]:
    return tuple(
        GapSignal(expert_id, domain, category, count, threshold, evidence, observed_at)
        for category, (count, threshold, evidence) in sorted(
            measurements.items(), key=lambda x: x[0].value
        )
        if count >= threshold
    )


def validate_capability_inheritance(
    proposed: ProposedExpert, parents: tuple[ExpertDefinition, ...]
) -> None:
    if {item.expert_id for item in parents} != set(proposed.parent_expert_ids):
        raise GovernanceViolation("proposed expert parent definitions are incomplete")
    tool_pool = set.intersection(*(set(item.allowed_tools) for item in parents))
    source_pool = set.union(*(set(item.allowed_source_classes) for item in parents))
    mechanism_pool = set.union(*(set(item.allowed_mechanisms) for item in parents))
    if not set(proposed.allowed_tools) <= tool_pool:
        raise GovernanceViolation("topology proposal escalates expert tool capability")
    if not set(proposed.allowed_sources) <= source_pool:
        raise GovernanceViolation("topology proposal admits unsupported source class")
    if not set(proposed.mechanisms) <= mechanism_pool:
        raise GovernanceViolation("topology proposal exceeds governed mechanism scope")


def propose_split(
    parent: ExpertDefinition,
    gaps: tuple[GapSignal, ...],
    children: tuple[ProposedExpert, ...],
    created_at: datetime,
    created_by: str,
) -> TopologyProposal:
    if not gaps or any(item.expert_id != parent.expert_id for item in gaps):
        raise GovernanceViolation("split proposal requires parent-specific deterministic gaps")
    for child in children:
        validate_capability_inheritance(child, (parent,))
    return TopologyProposal(
        TopologyProposalType.SPLIT_EXPERT,
        tuple(item.signal_id for item in gaps),
        (parent.expert_id,),
        children,
        (),
        "Repeated subdomain gaps motivate a bounded split evaluation.",
        "Improve domain coverage and routing precision.",
        tuple(item.category.value for item in gaps),
        tuple(case for child in children for case in child.benchmark_case_ids),
        created_by,
        created_at,
        TopologyProposalStatus.PROPOSED,
        tuple(item.signal_id for item in gaps),
    )


def build_challenger(
    champion: TopologyVersion,
    proposal: TopologyProposal,
    expert_version_ids: dict[str, str],
    created_at: datetime,
    actor: str,
) -> TopologyVersion:
    nodes = {item.expert_id: item for item in champion.nodes}
    edges = list(champion.edges)
    if proposal.proposal_type is TopologyProposalType.SPLIT_EXPERT:
        for child in proposal.proposed_experts:
            version_id = expert_version_ids.get(child.expert_id)
            if version_id is None:
                raise GovernanceViolation("proposed expert lacks certified version")
            nodes[child.expert_id] = TopologyNode(
                child.expert_id, version_id, child.domain, created_at
            )
            for parent in child.parent_expert_ids:
                edges.append(
                    TopologyEdge(
                        parent,
                        child.expert_id,
                        RelationshipType.PARENT_CHILD,
                        child.routing_conditions,
                        10,
                    )
                )
    elif proposal.proposal_type is TopologyProposalType.MERGE_EXPERTS:
        for source in proposal.source_expert_ids:
            old = nodes.pop(source, None)
            if old is None:
                raise GovernanceViolation("merge source is not active")
        for merged in proposal.proposed_experts:
            version_id = expert_version_ids.get(merged.expert_id)
            if version_id is None:
                raise GovernanceViolation("merged expert lacks certified version")
            nodes[merged.expert_id] = TopologyNode(
                merged.expert_id, version_id, merged.domain, created_at
            )
        edges = [edge for edge in edges if edge.source_id in nodes and edge.target_id in nodes]
    elif proposal.proposal_type is TopologyProposalType.RETIRE_EXPERT:
        for source in proposal.source_expert_ids:
            nodes.pop(source, None)
        edges = [edge for edge in edges if edge.source_id in nodes and edge.target_id in nodes]
    elif proposal.proposal_type in {
        TopologyProposalType.CHANGE_ROUTING,
        TopologyProposalType.CHANGE_DOMAIN_SCOPE,
        TopologyProposalType.FORM_PANEL,
        TopologyProposalType.CREATE_EXPERT,
    }:
        for child in proposal.proposed_experts:
            version_id = expert_version_ids.get(child.expert_id)
            if version_id:
                nodes[child.expert_id] = TopologyNode(
                    child.expert_id, version_id, child.domain, created_at
                )
    return TopologyVersion(
        champion.topology_version_id,
        proposal.proposal_id,
        tuple(sorted(nodes.values(), key=lambda item: item.expert_id)),
        tuple(edges),
        champion.panel_rules,
        f"router:{proposal.proposal_id}",
        created_at,
        actor,
        TopologyState.CHALLENGER,
        None,
        "pending",
        (*champion.provenance, proposal.proposal_id),
    )


def evaluate_topology(
    proposal: TopologyProposal,
    champion: TopologyVersion,
    challenger: TopologyVersion,
    manifest_id: str,
    champion_metrics: TopologyMetrics,
    challenger_metrics: TopologyMetrics,
    route_results: tuple[tuple[str, str], ...],
    certification_checks: tuple[tuple[str, bool], ...],
    evaluated_at: datetime,
    policy: TopologyPolicy,
) -> TopologyEvaluation:
    safety = challenger_metrics.safety_violations > 0 or not all(
        dict(certification_checks).values()
    )
    reasons: list[str] = []
    if safety:
        reasons.append("SAFETY_OR_CERTIFICATION_VETO")
    if challenger_metrics.routing_accuracy < policy.minimum_routing_accuracy:
        reasons.append("ROUTING_ACCURACY")
    if (
        challenger_metrics.benchmark_quality + policy.quality_noninferiority_margin
        < champion_metrics.benchmark_quality
    ):
        reasons.append("QUALITY_REGRESSION")
    if challenger_metrics.provider_cost > champion_metrics.provider_cost * (
        1 + policy.maximum_cost_increase
    ):
        reasons.append("COST_INCREASE")
    if challenger_metrics.latency_ms > champion_metrics.latency_ms * (
        1 + policy.maximum_latency_increase
    ):
        reasons.append("LATENCY_INCREASE")
    if challenger_metrics.average_panel_size > policy.maximum_panel_size:
        reasons.append("PANEL_TOO_LARGE")
    decision = (
        "quarantined" if safety else "certified_pending_approval" if not reasons else "rejected"
    )
    return TopologyEvaluation(
        proposal.proposal_id,
        champion.topology_version_id,
        challenger.topology_version_id,
        manifest_id,
        champion_metrics,
        challenger_metrics,
        route_results,
        certification_checks,
        safety,
        decision,
        tuple(reasons),
        evaluated_at,
    )


def activation_event(
    challenger: TopologyVersion,
    champion: TopologyVersion,
    evaluation: TopologyEvaluation,
    actor: str,
    reason: str,
    occurred_at: datetime,
) -> TopologyRegistryEvent:
    if evaluation.decision != "certified_pending_approval" or evaluation.safety_veto:
        raise GovernanceViolation("topology challenger is not certified for activation")
    return TopologyRegistryEvent(
        challenger.topology_version_id,
        champion.topology_version_id,
        TopologyAction.ACTIVATION,
        actor,
        reason,
        occurred_at,
    )


def rollback_event(
    prior_id: str, current_id: str, actor: str, reason: str, occurred_at: datetime
) -> TopologyRegistryEvent:
    return TopologyRegistryEvent(
        prior_id, current_id, TopologyAction.ROLLBACK, actor, reason, occurred_at
    )
