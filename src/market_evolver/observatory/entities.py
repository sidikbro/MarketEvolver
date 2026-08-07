"""Canonical entity identifiers used by deterministic event rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from market_evolver.errors import ValidationError


class EntityType(str, Enum):
    INSTITUTION = "institution"
    CURRENCY = "currency"
    COUNTRY = "country"
    SECTOR = "sector"
    ECONOMIC_COHORT = "economic_cohort"
    COMPANY = "company"
    MINISTRY = "ministry"
    FOREIGN_GOVERNMENT = "foreign_government"
    COMMODITY = "commodity"
    INDUSTRY = "industry"


@dataclass(frozen=True, slots=True)
class Entity:
    entity_id: str
    name: str
    entity_type: EntityType
    geography: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()


class EntityRegistry:
    def __init__(self, entities: tuple[Entity, ...]) -> None:
        self._entities = {item.entity_id: item for item in entities}
        if len(self._entities) != len(entities):
            raise ValidationError("entity registry has duplicate identifiers")

    def get(self, entity_id: str) -> Entity:
        try:
            return self._entities[entity_id]
        except KeyError as exc:
            raise ValidationError(f"unknown entity: {entity_id}") from exc

    def list(self) -> tuple[Entity, ...]:
        return tuple(sorted(self._entities.values(), key=lambda item: item.entity_id))

    def contains(self, entity_id: str) -> bool:
        return entity_id in self._entities


DEFAULT_ENTITY_REGISTRY = EntityRegistry(
    (
        Entity("institution.boi", "Bank of Israel", EntityType.INSTITUTION, ("IL",)),
        Entity("currency.ils", "Israeli new shekel", EntityType.CURRENCY, ("IL",), ("ILS",)),
        Entity("currency.usd", "United States dollar", EntityType.CURRENCY, ("US",), ("USD",)),
        Entity("currency.eur", "Euro", EntityType.CURRENCY, ("EU",), ("EUR",)),
        Entity("country.il", "Israel", EntityType.COUNTRY, ("IL",)),
        Entity("sector.financial", "Financial sector", EntityType.SECTOR, ("IL",)),
        Entity("sector.real_estate", "Real-estate sector", EntityType.SECTOR, ("IL",)),
        Entity("cohort.exporters", "Exporters", EntityType.ECONOMIC_COHORT),
        Entity("cohort.importers", "Importers", EntityType.ECONOMIC_COHORT),
    )
)
