"""Small curated, deterministic Israel market graph seed."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from market_evolver.knowledge.repositories import SqlKnowledgeGraph
from market_evolver.knowledge.schemas import (
    EntityVersion,
    Exposure,
    ExposureDirection,
    ExposureStrength,
    ExposureType,
    ExternalIdentifier,
    KnowledgeEntityType,
    RecordStatus,
    Relationship,
    RelationType,
)
from market_evolver.observatory.mechanisms import DEFAULT_MECHANISM_REGISTRY

SEED_OBSERVED_AT = datetime(2025, 1, 1, tzinfo=UTC)
SEED_ACTIVE_FROM = datetime(1948, 5, 14, tzinfo=UTC)
SEED_PROVENANCE = ("seed:marketevolver:v0.5",)


def seed_knowledge_graph(
    session: Session, *, observed_at: datetime = SEED_OBSERVED_AT
) -> tuple[int, int, int]:
    graph = SqlKnowledgeGraph(session)
    entity_count = 0
    relationship_count = 0
    exposure_count = 0
    for entity in _entities(observed_at):
        _, created = graph.add_entity(entity)
        entity_count += int(created)
    for relationship in _relationships(observed_at):
        _, created = graph.add_relationship(relationship)
        relationship_count += int(created)
    for exposure in _exposures(observed_at):
        _, created = graph.add_exposure(exposure)
        exposure_count += int(created)
    session.flush()
    return entity_count, relationship_count, exposure_count


def _entities(observed_at: datetime) -> tuple[EntityVersion, ...]:
    entities = [
        _entity(
            "country.il",
            "Israel",
            KnowledgeEntityType.COUNTRY,
            observed_at,
            hebrew_name="ישראל",
            aliases=("State of Israel", "IL"),
            geography=("IL",),
            identifiers=(ExternalIdentifier("ISO-3166-1-alpha-2", "IL"),),
        ),
        _entity(
            "institution.boi",
            "Bank of Israel",
            KnowledgeEntityType.CENTRAL_BANK,
            observed_at,
            hebrew_name="בנק ישראל",
            aliases=("BOI",),
            geography=("IL",),
        ),
        _entity(
            "currency.ils",
            "Israeli new shekel",
            KnowledgeEntityType.CURRENCY,
            observed_at,
            hebrew_name="שקל חדש",
            aliases=("ILS", "NIS", "שקל"),
            geography=("IL",),
            identifiers=(ExternalIdentifier("ISO-4217", "ILS"),),
        ),
        _entity(
            "currency.usd",
            "United States dollar",
            KnowledgeEntityType.CURRENCY,
            observed_at,
            aliases=("USD", "US dollar", "דולר"),
            geography=("US",),
            identifiers=(ExternalIdentifier("ISO-4217", "USD"),),
        ),
        _entity(
            "currency.eur",
            "Euro",
            KnowledgeEntityType.CURRENCY,
            observed_at,
            aliases=("EUR", "אירו"),
            geography=("EU",),
            identifiers=(ExternalIdentifier("ISO-4217", "EUR"),),
        ),
        _entity(
            "asset.fx.usdils",
            "USD/ILS",
            KnowledgeEntityType.CURRENCY_PAIR,
            observed_at,
            aliases=("USDILS", "USD ILS", "דולר שקל"),
            geography=("IL", "US"),
        ),
        _entity(
            "exchange.tase",
            "Tel Aviv Stock Exchange",
            KnowledgeEntityType.EXCHANGE,
            observed_at,
            hebrew_name="הבורסה לניירות ערך בתל אביב",
            aliases=("TASE", "בורסת תל אביב"),
            geography=("IL",),
            identifiers=(ExternalIdentifier("MIC", "XTAE"),),
        ),
    ]
    sector_names = {
        "technology": "Technology",
        "semiconductors": "Semiconductors",
        "cybersecurity": "Cybersecurity",
        "software": "Software",
        "financial": "Financial sector",
        "banks": "Banks",
        "insurance": "Insurance",
        "real_estate": "Real estate",
        "residential": "Residential real estate",
        "commercial": "Commercial real estate",
        "construction": "Construction",
        "defense": "Defense",
        "energy": "Energy",
        "retail": "Retail",
        "healthcare": "Healthcare",
        "pharmaceuticals": "Pharmaceuticals",
        "tourism": "Tourism",
        "transportation": "Transportation",
        "industrials": "Industrials",
    }
    entities.extend(
        _entity(
            f"sector.{key}",
            name,
            KnowledgeEntityType.SECTOR,
            observed_at,
            aliases=(key.replace("_", " "),),
            geography=("IL",),
        )
        for key, name in sector_names.items()
    )
    entities.extend(
        _entity(
            f"mechanism.{item.mechanism_id}",
            item.name,
            KnowledgeEntityType.MECHANISM,
            observed_at,
            aliases=(item.mechanism_id,),
            geography=("IL",),
        )
        for item in DEFAULT_MECHANISM_REGISTRY.list()
    )
    return tuple(entities)


def _relationships(observed_at: datetime) -> tuple[Relationship, ...]:
    taxonomy = (
        ("sector.cybersecurity", "sector.technology"),
        ("sector.semiconductors", "sector.technology"),
        ("sector.software", "sector.technology"),
        ("sector.banks", "sector.financial"),
        ("sector.insurance", "sector.financial"),
        ("sector.residential", "sector.real_estate"),
        ("sector.commercial", "sector.real_estate"),
        ("sector.construction", "sector.real_estate"),
        ("sector.pharmaceuticals", "sector.healthcare"),
    )
    mechanism_effects = (
        ("mechanism.import_cost", "sector.retail"),
        ("mechanism.import_cost", "sector.industrials"),
        ("mechanism.import_cost", "sector.construction"),
        ("mechanism.export_competitiveness", "sector.technology"),
        ("mechanism.financing_cost", "sector.real_estate"),
        ("mechanism.financing_cost", "sector.construction"),
        ("mechanism.interest_margin", "sector.banks"),
        ("mechanism.defense_procurement", "sector.defense"),
        ("mechanism.tourism_demand", "sector.tourism"),
        ("mechanism.energy_cost", "sector.transportation"),
        ("mechanism.energy_cost", "sector.industrials"),
        ("mechanism.regulation_cost", "sector.banks"),
    )
    chains = (
        ("mechanism.risk_premium", "mechanism.financing_cost"),
        ("mechanism.financing_cost", "mechanism.credit_demand"),
        ("mechanism.government_spending", "mechanism.defense_procurement"),
        ("mechanism.supply_chain_disruption", "mechanism.import_cost"),
        ("mechanism.import_cost", "mechanism.construction_input_cost"),
        ("mechanism.energy_cost", "mechanism.import_cost"),
    )
    relationships = [
        _relationship(RelationType.CHILD_OF, source, target, observed_at)
        for source, target in taxonomy
    ]
    relationships.extend(
        _relationship(RelationType.AFFECTS, source, target, observed_at)
        for source, target in mechanism_effects
    )
    relationships.extend(
        _relationship(RelationType.LEADS_TO, source, target, observed_at)
        for source, target in chains
    )
    relationships.extend(
        (
            _relationship(
                RelationType.OPERATES_IN,
                "institution.boi",
                "country.il",
                observed_at,
            ),
            _relationship(
                RelationType.OPERATES_IN,
                "exchange.tase",
                "country.il",
                observed_at,
            ),
        )
    )
    return tuple(relationships)


def _exposures(observed_at: datetime) -> tuple[Exposure, ...]:
    return (
        Exposure(
            exposure_type=ExposureType.MECHANISM_SENSITIVITY,
            subject_entity="sector.banks",
            target_entity="mechanism.interest_margin",
            direction=ExposureDirection.NON_DIRECTIONAL,
            strength=ExposureStrength.UNKNOWN,
            unit=None,
            value=None,
            effective_from=SEED_ACTIVE_FROM,
            effective_until=None,
            observed_at=observed_at,
            confidence=0.8,
            source_evidence=SEED_PROVENANCE,
            status=RecordStatus.ACTIVE,
            version=1,
        ),
        Exposure(
            exposure_type=ExposureType.HOUSING_MARKET,
            subject_entity="sector.real_estate",
            target_entity="mechanism.financing_cost",
            direction=ExposureDirection.NON_DIRECTIONAL,
            strength=ExposureStrength.UNKNOWN,
            unit=None,
            value=None,
            effective_from=SEED_ACTIVE_FROM,
            effective_until=None,
            observed_at=observed_at,
            confidence=0.75,
            source_evidence=SEED_PROVENANCE,
            status=RecordStatus.ACTIVE,
            version=1,
        ),
        Exposure(
            exposure_type=ExposureType.DEFENSE_PROCUREMENT,
            subject_entity="sector.defense",
            target_entity="mechanism.defense_procurement",
            direction=ExposureDirection.DEMAND,
            strength=ExposureStrength.UNKNOWN,
            unit=None,
            value=None,
            effective_from=SEED_ACTIVE_FROM,
            effective_until=None,
            observed_at=observed_at,
            confidence=0.8,
            source_evidence=SEED_PROVENANCE,
            status=RecordStatus.ACTIVE,
            version=1,
        ),
    )


def _entity(
    entity_id: str,
    name: str,
    entity_type: KnowledgeEntityType,
    observed_at: datetime,
    *,
    hebrew_name: str | None = None,
    aliases: tuple[str, ...] = (),
    geography: tuple[str, ...] = (),
    identifiers: tuple[ExternalIdentifier, ...] = (),
) -> EntityVersion:
    return EntityVersion(
        entity_id=entity_id,
        canonical_name=name,
        aliases=aliases,
        hebrew_name=hebrew_name,
        english_name=name,
        entity_type=entity_type,
        geography=geography,
        identifiers=identifiers,
        active_from=SEED_ACTIVE_FROM,
        active_until=None,
        observed_at=observed_at,
        provenance=SEED_PROVENANCE,
        confidence=1.0,
        version=1,
    )


def _relationship(
    relation_type: RelationType,
    source: str,
    target: str,
    observed_at: datetime,
) -> Relationship:
    return Relationship(
        relation_type=relation_type,
        source_entity=source,
        target_entity=target,
        valid_from=SEED_ACTIVE_FROM,
        valid_until=None,
        observed_at=observed_at,
        confidence=0.9,
        provenance=SEED_PROVENANCE,
        status=RecordStatus.ACTIVE,
        version=1,
    )
