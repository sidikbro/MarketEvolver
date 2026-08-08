from __future__ import annotations

from datetime import datetime

from market_evolver.expert.schemas import ExpertDefinition, ExpertStatus, RoutingDecision

ROUTES = {
    "technology": "expert.technology_ai",
    "software": "expert.technology_ai",
    "semiconductors": "expert.technology_ai",
    "cybersecurity": "expert.technology_ai",
    "real_estate": "expert.israel_real_estate",
    "housing": "expert.israel_real_estate",
    "rates": "expert.banking_macro",
    "inflation": "expert.banking_macro",
    "banking": "expert.banking_macro",
    "fx": "expert.banking_macro",
    "defense": "expert.defense_geopolitics",
    "geopolitics": "expert.defense_geopolitics",
    "sanctions": "expert.defense_geopolitics",
    "energy": "expert.energy",
    "oil": "expert.energy",
    "gas": "expert.energy",
}


def route(
    subject_id: str,
    cutoff: datetime,
    experts: tuple[ExpertDefinition, ...],
    *,
    tags: tuple[str, ...],
    geography: str,
) -> RoutingDecision:
    available = {item.expert_id: item for item in experts if item.status is ExpertStatus.APPROVED}
    selected: list[str] = []
    reasons: list[str] = []
    for tag in tags:
        expert_id = ROUTES.get(tag.casefold())
        expert = available.get(expert_id or "")
        if expert is not None and geography in expert.geography and expert_id not in selected:
            assert expert_id is not None
            selected.append(expert_id)
            reasons.append(f"{tag}->{expert_id}")
    fallback = "expert.general"
    if not selected:
        selected = [fallback]
        reasons = ["no approved specialist matched; generalist fallback"]
    return RoutingDecision(
        subject_id,
        cutoff,
        tuple(selected),
        "; ".join(reasons),
        1.0 if selected != [fallback] else 0.5,
        fallback,
        tags,
    )


def panel_route(
    subject_id: str,
    cutoff: datetime,
    experts: tuple[ExpertDefinition, ...],
    *,
    tags: tuple[str, ...],
    geography: str,
) -> RoutingDecision:
    routed = route(subject_id, cutoff, experts, tags=tags, geography=geography)
    members = tuple(dict.fromkeys((*routed.selected_expert_ids, routed.fallback_expert_id)))
    return RoutingDecision(
        subject_id,
        cutoff,
        members,
        routed.reason + "; skeptical reviewer required",
        routed.confidence,
        routed.fallback_expert_id,
        tags,
    )
