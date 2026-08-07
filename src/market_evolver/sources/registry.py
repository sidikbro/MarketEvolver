"""Validated registry of external data authorities."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from re import fullmatch
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from market_evolver.errors import ValidationError


class RegistrySourceType(str, Enum):
    CENTRAL_BANK = "central_bank"
    NATIONAL_STATISTICS = "national_statistics"
    EXCHANGE_DISCLOSURES = "exchange_disclosures"
    REGULATOR = "regulator"
    GOVERNMENT = "government"
    LEGISLATURE = "legislature"
    NEWS = "news"
    SOCIAL = "social"


class AuthorityTier(str, Enum):
    OFFICIAL_PRIMARY = "official_primary"
    OFFICIAL_SECONDARY = "official_secondary"
    LICENSED_PROVIDER = "licensed_provider"
    UNTRUSTED = "untrusted"


class IngestionMethod(str, Enum):
    JSON_API = "json_api"
    SDMX_API = "sdmx_api"
    DISCLOSURE_API = "disclosure_api"
    FILE_DOWNLOAD = "file_download"


@dataclass(frozen=True, slots=True)
class SourceDefinition:
    source_id: str
    name: str
    source_type: RegistrySourceType
    geography: str
    authority_tier: AuthorityTier
    base_uri: str
    expected_content_types: tuple[str, ...]
    timezone: str
    ingestion_method: IngestionMethod
    enabled: bool
    revision_notes: str

    def __post_init__(self) -> None:
        if fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*", self.source_id) is None:
            raise ValidationError("source_id must be a stable dotted or hyphenated identifier")
        if not self.name.strip() or not self.geography.strip():
            raise ValidationError("source name and geography are required")
        if not self.base_uri.startswith("https://"):
            raise ValidationError("source base_uri must use HTTPS")
        if not self.expected_content_types or any(
            "/" not in value for value in self.expected_content_types
        ):
            raise ValidationError("at least one valid expected content type is required")
        if not self.revision_notes.strip():
            raise ValidationError("source revision behavior must be documented")
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError as exc:
            raise ValidationError(f"unknown source timezone: {self.timezone}") from exc


class SourceRegistry:
    def __init__(self, definitions: tuple[SourceDefinition, ...]) -> None:
        by_id = {item.source_id: item for item in definitions}
        if len(by_id) != len(definitions):
            raise ValidationError("source registry contains duplicate source_id values")
        self._definitions = by_id

    def get(self, source_id: str) -> SourceDefinition:
        try:
            return self._definitions[source_id]
        except KeyError as exc:
            raise ValidationError(f"unknown registered source: {source_id}") from exc

    def list(self, *, enabled_only: bool = False) -> tuple[SourceDefinition, ...]:
        values = sorted(self._definitions.values(), key=lambda item: item.source_id)
        if enabled_only:
            values = [item for item in values if item.enabled]
        return tuple(values)


DEFAULT_REGISTRY = SourceRegistry(
    (
        SourceDefinition(
            source_id="il.boi",
            name="Bank of Israel",
            source_type=RegistrySourceType.CENTRAL_BANK,
            geography="IL",
            authority_tier=AuthorityTier.OFFICIAL_PRIMARY,
            base_uri="https://www.boi.org.il",
            expected_content_types=("application/json", "text/json"),
            timezone="Asia/Jerusalem",
            ingestion_method=IngestionMethod.JSON_API,
            enabled=True,
            revision_notes=(
                "Current representative rates may be followed by revised series-database "
                "values; each observed payload is retained independently."
            ),
        ),
        SourceDefinition(
            source_id="il.cbs",
            name="Israel Central Bureau of Statistics",
            source_type=RegistrySourceType.NATIONAL_STATISTICS,
            geography="IL",
            authority_tier=AuthorityTier.OFFICIAL_PRIMARY,
            base_uri="https://www.cbs.gov.il",
            expected_content_types=("application/json", "application/xml", "text/csv"),
            timezone="Asia/Jerusalem",
            ingestion_method=IngestionMethod.SDMX_API,
            enabled=False,
            revision_notes=(
                "Statistical releases may be preliminary, seasonally adjusted, or revised; "
                "release vintages must be retained."
            ),
        ),
        SourceDefinition(
            source_id="il.tase.maya",
            name="TASE MAYA",
            source_type=RegistrySourceType.EXCHANGE_DISCLOSURES,
            geography="IL",
            authority_tier=AuthorityTier.OFFICIAL_PRIMARY,
            base_uri="https://maya.tase.co.il",
            expected_content_types=("application/json", "application/pdf"),
            timezone="Asia/Jerusalem",
            ingestion_method=IngestionMethod.DISCLOSURE_API,
            enabled=False,
            revision_notes=(
                "Corporate filings can be corrected or superseded; disclosure versions and "
                "exchange publication times must remain distinct."
            ),
        ),
    )
)
