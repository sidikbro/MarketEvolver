"""Immutable knowledge-graph records with bitemporal visibility."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Protocol

from market_evolver.errors import ValidationError
from market_evolver.provenance import content_id
from market_evolver.time import require_aware_utc


class KnowledgeEntityType(str, Enum):
    COUNTRY = "country"
    CURRENCY = "currency"
    CURRENCY_PAIR = "currency_pair"
    CENTRAL_BANK = "central_bank"
    GOVERNMENT_BODY = "government_body"
    REGULATOR = "regulator"
    EXCHANGE = "exchange"
    COMPANY = "company"
    SECTOR = "sector"
    INDUSTRY = "industry"
    INDEX = "index"
    ETF = "etf"
    COMMODITY = "commodity"
    ECONOMIC_INDICATOR = "economic_indicator"
    MECHANISM = "mechanism"


class RelationType(str, Enum):
    BELONGS_TO = "belongs_to"
    CHILD_OF = "child_of"
    EXPOSED_TO = "exposed_to"
    SENSITIVE_TO = "sensitive_to"
    REGULATED_BY = "regulated_by"
    LISTED_ON = "listed_on"
    OPERATES_IN = "operates_in"
    IMPORTS_FROM = "imports_from"
    EXPORTS_TO = "exports_to"
    CONTAINS = "contains"
    AFFECTS = "affects"
    LEADS_TO = "leads_to"


class RecordStatus(str, Enum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"


class ExposureType(str, Enum):
    CURRENCY_REVENUE = "currency_revenue"
    CURRENCY_COST = "currency_cost"
    FLOATING_RATE_DEBT = "floating_rate_debt"
    HOUSING_MARKET = "housing_market"
    DEFENSE_PROCUREMENT = "defense_procurement"
    TOURISM_DEMAND = "tourism_demand"
    MECHANISM_SENSITIVITY = "mechanism_sensitivity"


class ExposureDirection(str, Enum):
    REVENUE = "revenue"
    COST = "cost"
    ASSET = "asset"
    LIABILITY = "liability"
    DEMAND = "demand"
    SUPPLY = "supply"
    NON_DIRECTIONAL = "non_directional"


class ExposureStrength(str, Enum):
    UNKNOWN = "unknown"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ResolutionStatus(str, Enum):
    RESOLVED = "resolved"
    AMBIGUOUS = "ambiguous"
    NOT_FOUND = "not_found"


@dataclass(frozen=True, slots=True)
class ExternalIdentifier:
    scheme: str
    value: str

    def __post_init__(self) -> None:
        if not self.scheme.strip() or not self.value.strip():
            raise ValidationError("identifier scheme and value are required")


@dataclass(frozen=True, slots=True)
class EntityVersion:
    entity_id: str
    canonical_name: str
    aliases: tuple[str, ...]
    hebrew_name: str | None
    english_name: str
    entity_type: KnowledgeEntityType
    geography: tuple[str, ...]
    identifiers: tuple[ExternalIdentifier, ...]
    active_from: datetime
    active_until: datetime | None
    observed_at: datetime
    provenance: tuple[str, ...]
    confidence: float
    version: int
    entity_version_id: str = field(init=False)

    def __post_init__(self) -> None:
        active_from = require_aware_utc(self.active_from, "active_from")
        observed = require_aware_utc(self.observed_at, "observed_at")
        object.__setattr__(self, "active_from", active_from)
        object.__setattr__(self, "observed_at", observed)
        if self.active_until is not None:
            active_until = require_aware_utc(self.active_until, "active_until")
            if active_until <= active_from:
                raise ValidationError("entity active_until must follow active_from")
            object.__setattr__(self, "active_until", active_until)
        if not self.entity_id or not self.canonical_name or not self.english_name:
            raise ValidationError("entity identity and names are required")
        if self.version < 1:
            raise ValidationError("entity version must be positive")
        if not self.provenance:
            raise ValidationError("entity provenance is required")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValidationError("entity confidence must be between 0 and 1")
        if len(set(self.aliases)) != len(self.aliases):
            raise ValidationError("entity aliases must be unique")
        if len(set(self.identifiers)) != len(self.identifiers):
            raise ValidationError("entity identifiers must be unique")
        object.__setattr__(self, "entity_version_id", content_id("entity-version", self))


@dataclass(frozen=True, slots=True)
class AliasRecord:
    alias: str
    entity_version_id: str
    valid_from: datetime
    valid_until: datetime | None
    observed_at: datetime
    provenance: tuple[str, ...]
    alias_id: str = field(init=False)
    normalized_alias: str = field(init=False)

    def __post_init__(self) -> None:
        normalized = normalize_alias(self.alias)
        if not normalized:
            raise ValidationError("alias must contain letters or digits")
        object.__setattr__(self, "normalized_alias", normalized)
        valid_from = require_aware_utc(self.valid_from, "valid_from")
        object.__setattr__(self, "valid_from", valid_from)
        object.__setattr__(self, "observed_at", require_aware_utc(self.observed_at, "observed_at"))
        if self.valid_until is not None:
            valid_until = require_aware_utc(self.valid_until, "valid_until")
            if valid_until <= valid_from:
                raise ValidationError("alias valid_until must follow valid_from")
            object.__setattr__(self, "valid_until", valid_until)
        if not self.entity_version_id or not self.provenance:
            raise ValidationError("alias entity and provenance are required")
        object.__setattr__(self, "alias_id", content_id("entity-alias", self))


@dataclass(frozen=True, slots=True)
class Relationship:
    relation_type: RelationType
    source_entity: str
    target_entity: str
    valid_from: datetime
    valid_until: datetime | None
    observed_at: datetime
    confidence: float
    provenance: tuple[str, ...]
    status: RecordStatus
    version: int
    relationship_id: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_versioned_interval(self)
        if self.source_entity == self.target_entity:
            raise ValidationError("self-relationships are not allowed")
        if not self.source_entity or not self.target_entity or not self.provenance:
            raise ValidationError("relationship endpoints and provenance are required")
        object.__setattr__(self, "relationship_id", content_id("relationship", self))


@dataclass(frozen=True, slots=True)
class Exposure:
    exposure_type: ExposureType
    subject_entity: str
    target_entity: str
    direction: ExposureDirection
    strength: ExposureStrength
    unit: str | None
    value: str | None
    effective_from: datetime
    effective_until: datetime | None
    observed_at: datetime
    confidence: float
    source_evidence: tuple[str, ...]
    status: RecordStatus
    version: int
    exposure_id: str = field(init=False)

    def __post_init__(self) -> None:
        _validate_versioned_interval(
            self,
            from_name="effective_from",
            until_name="effective_until",
        )
        if not self.subject_entity or not self.target_entity or not self.source_evidence:
            raise ValidationError("exposure endpoints and source evidence are required")
        if (self.value is None) != (self.unit is None):
            raise ValidationError("quantitative exposure value and unit must appear together")
        object.__setattr__(self, "exposure_id", content_id("exposure", self))


@dataclass(frozen=True, slots=True)
class AliasResolution:
    status: ResolutionStatus
    candidates: tuple[EntityVersion, ...]


@dataclass(frozen=True, slots=True)
class GraphPath:
    entity_ids: tuple[str, ...]
    relationship_ids: tuple[str, ...]
    relationship_versions: tuple[int, ...]
    provenance: tuple[str, ...]
    confidence: float
    cutoff_validated: bool


@dataclass(frozen=True, slots=True)
class EventTrace:
    event_id: str
    cutoff: datetime
    direct_entities: tuple[str, ...]
    candidate_mechanisms: tuple[str, ...]
    paths: tuple[GraphPath, ...]


def normalize_alias(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return "".join(re.findall(r"[\w]+", normalized, flags=re.UNICODE))


class _VersionedInterval(Protocol):
    @property
    def observed_at(self) -> datetime: ...

    @property
    def confidence(self) -> float: ...

    @property
    def version(self) -> int: ...


def _validate_versioned_interval(
    record: _VersionedInterval,
    *,
    from_name: str = "valid_from",
    until_name: str = "valid_until",
) -> None:
    start = require_aware_utc(getattr(record, from_name), from_name)
    observed = require_aware_utc(record.observed_at, "observed_at")
    object.__setattr__(record, from_name, start)
    object.__setattr__(record, "observed_at", observed)
    end = getattr(record, until_name)
    if end is not None:
        normalized_end = require_aware_utc(end, until_name)
        if normalized_end <= start:
            raise ValidationError(f"{until_name} must follow {from_name}")
        object.__setattr__(record, until_name, normalized_end)
    if not 0.0 <= record.confidence <= 1.0:
        raise ValidationError("confidence must be between 0 and 1")
    if record.version < 1:
        raise ValidationError("version must be positive")
