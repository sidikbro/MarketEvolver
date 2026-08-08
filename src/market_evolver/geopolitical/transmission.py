"""Reviewed Israel-specific candidate transmission paths."""

from __future__ import annotations

from dataclasses import dataclass

from market_evolver.geopolitical.schemas import GeopoliticalEventType


@dataclass(frozen=True, slots=True)
class TransmissionTemplate:
    event_type: GeopoliticalEventType
    mechanisms: tuple[str, ...]
    affected_entities: tuple[str, ...]
    rationale: str


ISRAEL_TRANSMISSION_REGISTRY = (
    TransmissionTemplate(
        GeopoliticalEventType.AIRSPACE_DISRUPTION,
        ("airline_capacity", "tourism_demand"),
        ("country.israel", "sector.tourism"),
        "Airspace availability can constrain airline capacity and tourism access.",
    ),
    TransmissionTemplate(
        GeopoliticalEventType.SHIPPING_DISRUPTION,
        ("freight_delay", "shipping_cost", "import_cost"),
        ("country.israel", "sector.importers"),
        "Route disruption can delay freight and change import costs.",
    ),
    TransmissionTemplate(
        GeopoliticalEventType.MILITARY_ESCALATION,
        ("reserve_mobilization", "labor_availability", "construction_activity"),
        ("country.israel", "sector.real_estate"),
        "Explicit mobilization can alter available labor and construction activity.",
    ),
    TransmissionTemplate(
        GeopoliticalEventType.MILITARY_ESCALATION,
        ("government_spending", "defense_procurement"),
        ("country.israel", "sector.defense"),
        "Explicit appropriations or procurement decisions can transmit through public spending.",
    ),
    TransmissionTemplate(
        GeopoliticalEventType.ENERGY_SUPPLY_DISRUPTION,
        ("energy_cost", "import_availability"),
        ("country.israel", "sector.energy"),
        "Supply disruption can affect energy availability and cost.",
    ),
    TransmissionTemplate(
        GeopoliticalEventType.SOVEREIGN_RISK_EVENT,
        ("sovereign_risk_premium", "foreign_capital_flow", "currency_pressure"),
        ("country.israel", "currency.ils"),
        "Sovereign funding conditions can interact with capital flows and currency pressure.",
    ),
    TransmissionTemplate(
        GeopoliticalEventType.SANCTIONS,
        ("export_restriction", "supply_chain_disruption"),
        ("country.israel", "sector.exporters"),
        "Explicit restrictions can affect documented export and supply-chain exposures.",
    ),
)


def templates_for(event_type: GeopoliticalEventType) -> tuple[TransmissionTemplate, ...]:
    return tuple(item for item in ISRAEL_TRANSMISSION_REGISTRY if item.event_type is event_type)
