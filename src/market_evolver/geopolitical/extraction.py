"""Conservative phrase-based extraction of explicit geopolitical facts."""

from __future__ import annotations

import re
from datetime import datetime

from market_evolver.geopolitical.schemas import GeopoliticalEventCandidate, GeopoliticalEventType

_RULES: tuple[tuple[GeopoliticalEventType, tuple[str, ...], tuple[str, ...]], ...] = (
    (
        GeopoliticalEventType.AIRSPACE_DISRUPTION,
        (
            "airspace closed",
            "airport closed",
            "flights cancelled",
            "airspace reopened",
            "airport reopened",
        ),
        ("airline_capacity", "tourism_demand"),
    ),
    (
        GeopoliticalEventType.SHIPPING_DISRUPTION,
        ("port closed", "shipping disrupted", "route suspended", "port reopened"),
        ("freight_delay", "shipping_cost", "import_availability"),
    ),
    (
        GeopoliticalEventType.CEASEFIRE,
        ("ceasefire announced", "ceasefire entered into force", "ceasefire violated"),
        ("sovereign_risk_premium",),
    ),
    (
        GeopoliticalEventType.SANCTIONS,
        ("sanctions imposed", "sanctions amended", "sanctions lifted"),
        ("export_restriction", "foreign_capital_flow"),
    ),
    (
        GeopoliticalEventType.EXPORT_RESTRICTION,
        ("export ban", "export restriction"),
        ("export_restriction", "supply_chain_disruption"),
    ),
    (
        GeopoliticalEventType.BORDER_CLOSURE,
        ("border closed", "crossing closed", "border reopened"),
        ("labor_availability", "import_availability"),
    ),
    (
        GeopoliticalEventType.MILITARY_ESCALATION,
        ("reserve mobilization", "military escalation"),
        ("reserve_mobilization", "labor_availability", "government_spending"),
    ),
    (
        GeopoliticalEventType.ENERGY_SUPPLY_DISRUPTION,
        ("energy supply disrupted", "pipeline closed"),
        ("energy_cost", "supply_chain_disruption"),
    ),
)

_ACTORS = (
    "Israel",
    "United States",
    "European Union",
    "United Nations",
    "Iran",
    "Lebanon",
    "Egypt",
    "Jordan",
)
_GEOGRAPHY = ("Israel", "Gaza", "Lebanon", "Red Sea", "Mediterranean", "Middle East")


def extract_candidate(
    text: str, evidence_id: str, observed_at: datetime
) -> GeopoliticalEventCandidate:
    folded = " ".join(text.casefold().split())
    event_type = None
    mechanisms: tuple[str, ...] = ()
    spans: list[str] = []
    for candidate_type, phrases, candidate_mechanisms in _RULES:
        matches = [phrase for phrase in phrases if phrase in folded]
        if matches:
            event_type = candidate_type
            mechanisms = candidate_mechanisms
            spans.extend(matches)
            break
    actors = tuple(value for value in _ACTORS if value.casefold() in folded)
    geography = tuple(value for value in _GEOGRAPHY if value.casefold() in folded)
    explicit_times = tuple(_explicit_iso_times(text, observed_at))
    confidence = (
        1.0 if event_type is not None and (actors or geography) else 0.5 if event_type else 0.0
    )
    return GeopoliticalEventCandidate(
        (evidence_id,),
        event_type,
        actors,
        geography,
        explicit_times,
        mechanisms,
        "deterministic-explicit-phrases/1",
        confidence,
        observed_at,
        supporting_spans=tuple(spans),
    )


def _explicit_iso_times(text: str, observed_at: datetime) -> tuple[datetime, ...]:
    values: list[datetime] = []
    for match in re.findall(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:Z|[+-]\d{2}:\d{2})\b", text):
        parsed = datetime.fromisoformat(match)
        if parsed <= observed_at:
            values.append(parsed)
    return tuple(values)
