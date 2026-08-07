"""Deterministic policy extraction and direction-neutral mechanism candidates."""

from __future__ import annotations

import re
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from market_evolver.government.schemas import (
    GovernmentActionCandidate,
    GovernmentActionStatus,
    GovernmentActionType,
)

_STATUS_WORDS = {
    "proposal": GovernmentActionStatus.PROPOSED,
    "proposed": GovernmentActionStatus.PROPOSED,
    "consultation": GovernmentActionStatus.CONSULTATION,
    "approved": GovernmentActionStatus.APPROVED,
    "published": GovernmentActionStatus.PUBLISHED,
    "effective": GovernmentActionStatus.EFFECTIVE,
    "amended": GovernmentActionStatus.AMENDED,
    "repealed": GovernmentActionStatus.REPEALED,
}


def extract_policy_candidate(
    *,
    evidence_id: str,
    text: str,
    created_at: datetime,
    issuing_body: str | None = None,
) -> GovernmentActionCandidate:
    folded = text.casefold()
    action_type: GovernmentActionType | None = None
    mechanisms: tuple[str, ...] = ()
    entities: set[str] = set()
    if "interest rate" in folded or "ריבית" in text:
        action_type = GovernmentActionType.MONETARY_POLICY
        mechanisms = ("financing_cost", "refinancing_cost", "credit_demand", "interest_margin")
        entities.update(("institution.boi", "sector.banks"))
    elif "housing" in folded or "דיור" in text:
        action_type = GovernmentActionType.HOUSING_POLICY
        mechanisms = ("financing_cost", "credit_demand", "construction_input_cost")
        entities.update(("sector.real_estate", "sector.construction"))
    elif "procurement" in folded or "tender" in folded:
        action_type = GovernmentActionType.PROCUREMENT
        mechanisms = ("government_spending", "defense_procurement")
    transition = next(
        (status for word, status in _STATUS_WORDS.items() if word in folded),
        None,
    )
    values = tuple(sorted(set(re.findall(r"\b\d+(?:\.\d+)?\s*%", text))))
    dates = tuple(
        sorted(
            {
                parsed
                for raw in re.findall(r"\b\d{4}-\d{2}-\d{2}\b", text)
                if (parsed := _date(raw)) is not None
            }
        )
    )
    return GovernmentActionCandidate(
        evidence_ids=(evidence_id,),
        issuing_body=issuing_body,
        possible_action_type=action_type,
        possible_transition=transition,
        explicit_dates=dates,
        explicit_values=values,
        entities=tuple(sorted(entities)),
        candidate_mechanisms=mechanisms,
        extraction_method="deterministic-policy-keywords/v1",
        confidence=1.0 if action_type is not None else 0.0,
        created_at=created_at,
    )


def normalize_rate(value: object) -> str:
    try:
        return format(Decimal(str(value)), "f")
    except InvalidOperation as exc:
        raise ValueError("policy rate is not numeric") from exc


def _date(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=UTC)
    except ValueError:
        return None
