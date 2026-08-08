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
    RSS_FEED = "rss_feed"


class TrustClass(str, Enum):
    OFFICIAL = "official"
    PRIMARY_CORPORATE = "primary_corporate"
    ESTABLISHED_NEWS = "established_news"
    SPECIALIST_PUBLICATION = "specialist_publication"
    SOCIAL = "social"
    ANONYMOUS_OR_UNKNOWN = "anonymous_or_unknown"


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
    trust_class: TrustClass = TrustClass.OFFICIAL
    language: tuple[str, ...] = ("en",)
    publisher_identity: str = ""
    owner_organization: str | None = None
    machine_readable: bool = True
    publication_timestamp_semantics: str = "Publisher-supplied timestamp."
    access_notes: str = "Public endpoint; availability may change."
    storage_constraints: str = "Internal research retention only."

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
        if not self.language or any(not item.strip() for item in self.language):
            raise ValidationError("source languages are required")
        if not (self.publisher_identity or self.name).strip():
            raise ValidationError("publisher identity is required")
        if not self.publication_timestamp_semantics.strip():
            raise ValidationError("publication timestamp semantics are required")
        if not self.access_notes.strip() or not self.storage_constraints.strip():
            raise ValidationError("access and storage constraints must be documented")
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
            source_id="uk.bbc.business",
            name="BBC Business",
            source_type=RegistrySourceType.NEWS,
            geography="GLOBAL",
            authority_tier=AuthorityTier.UNTRUSTED,
            base_uri="https://feeds.bbci.co.uk/news/business/rss.xml",
            expected_content_types=(
                "application/rss+xml",
                "application/xml",
                "text/xml",
            ),
            timezone="Europe/London",
            ingestion_method=IngestionMethod.RSS_FEED,
            enabled=True,
            revision_notes=(
                "Feed entries may be edited or removed; every changed item is retained as "
                "a new locally observed revision."
            ),
            trust_class=TrustClass.ESTABLISHED_NEWS,
            language=("en",),
            publisher_identity="British Broadcasting Corporation",
            owner_organization="BBC",
            publication_timestamp_semantics="RSS pubDate supplied by the publisher.",
            access_notes="Public RSS feed; article pages may have regional access controls.",
            storage_constraints=(
                "Retain feed payloads for internal provenance; do not redistribute article text."
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
        SourceDefinition(
            source_id="il.mof",
            name="Israel Ministry of Finance",
            source_type=RegistrySourceType.GOVERNMENT,
            geography="IL",
            authority_tier=AuthorityTier.OFFICIAL_PRIMARY,
            base_uri="https://www.gov.il/en/departments/ministry_of_finance",
            expected_content_types=("application/json", "application/pdf", "text/html"),
            timezone="Asia/Jerusalem",
            ingestion_method=IngestionMethod.FILE_DOWNLOAD,
            enabled=False,
            revision_notes="Publication contracts vary by department and require review.",
        ),
        SourceDefinition(
            source_id="il.isa",
            name="Israel Securities Authority",
            source_type=RegistrySourceType.REGULATOR,
            geography="IL",
            authority_tier=AuthorityTier.OFFICIAL_PRIMARY,
            base_uri="https://www.new.isa.gov.il",
            expected_content_types=("application/json", "application/pdf", "text/html"),
            timezone="Asia/Jerusalem",
            ingestion_method=IngestionMethod.FILE_DOWNLOAD,
            enabled=False,
            revision_notes="Rules and circulars may be corrected or superseded.",
        ),
        SourceDefinition(
            source_id="il.knesset",
            name="Knesset",
            source_type=RegistrySourceType.LEGISLATURE,
            geography="IL",
            authority_tier=AuthorityTier.OFFICIAL_PRIMARY,
            base_uri="https://main.knesset.gov.il",
            expected_content_types=("application/json", "application/xml", "text/html"),
            timezone="Asia/Jerusalem",
            ingestion_method=IngestionMethod.JSON_API,
            enabled=False,
            revision_notes="Bills have stage-specific versions and committee records.",
        ),
        SourceDefinition(
            source_id="il.competition",
            name="Israel Competition Authority",
            source_type=RegistrySourceType.REGULATOR,
            geography="IL",
            authority_tier=AuthorityTier.OFFICIAL_PRIMARY,
            base_uri="https://www.gov.il/en/departments/competition_authority",
            expected_content_types=("application/pdf", "text/html"),
            timezone="Asia/Jerusalem",
            ingestion_method=IngestionMethod.FILE_DOWNLOAD,
            enabled=False,
            revision_notes="Decisions and guidance can be challenged or amended.",
        ),
        SourceDefinition(
            source_id="il.tax",
            name="Israel Tax Authority",
            source_type=RegistrySourceType.GOVERNMENT,
            geography="IL",
            authority_tier=AuthorityTier.OFFICIAL_PRIMARY,
            base_uri="https://www.gov.il/en/departments/israel_tax_authority",
            expected_content_types=("application/pdf", "text/html"),
            timezone="Asia/Jerusalem",
            ingestion_method=IngestionMethod.FILE_DOWNLOAD,
            enabled=False,
            revision_notes="Circulars and implementation dates may change.",
        ),
        SourceDefinition(
            source_id="us.sec.edgar",
            name="SEC EDGAR",
            source_type=RegistrySourceType.REGULATOR,
            geography="US",
            authority_tier=AuthorityTier.OFFICIAL_PRIMARY,
            base_uri="https://data.sec.gov",
            expected_content_types=("application/json",),
            timezone="America/New_York",
            ingestion_method=IngestionMethod.JSON_API,
            enabled=True,
            revision_notes=(
                "Amendments and corrected XBRL facts remain separate filing observations."
            ),
            language=("en",),
            publisher_identity="U.S. Securities and Exchange Commission",
            owner_organization="U.S. Government",
            publication_timestamp_semantics="SEC filing date and accession metadata.",
            access_notes="Requires a descriptive User-Agent with contact information.",
            storage_constraints="Retain official filing metadata and facts with provenance.",
        ),
        SourceDefinition(
            source_id="us.fred",
            name="Federal Reserve Economic Data",
            source_type=RegistrySourceType.CENTRAL_BANK,
            geography="US",
            authority_tier=AuthorityTier.OFFICIAL_SECONDARY,
            base_uri="https://api.stlouisfed.org",
            expected_content_types=("application/json",),
            timezone="America/Chicago",
            ingestion_method=IngestionMethod.JSON_API,
            enabled=False,
            revision_notes="FRED/ALFRED vintages and realtime periods must be captured before replay is enabled.",
        ),
        SourceDefinition(
            source_id="eu.ecb.data",
            name="ECB Data Portal",
            source_type=RegistrySourceType.CENTRAL_BANK,
            geography="EU",
            authority_tier=AuthorityTier.OFFICIAL_PRIMARY,
            base_uri="https://data-api.ecb.europa.eu",
            expected_content_types=("text/csv", "application/vnd.sdmx.data+csv"),
            timezone="Europe/Berlin",
            ingestion_method=IngestionMethod.SDMX_API,
            enabled=False,
            revision_notes="SDMX series can be revised; release-time vintages require local capture.",
        ),
        SourceDefinition(
            source_id="global.worldbank",
            name="World Bank Indicators",
            source_type=RegistrySourceType.NATIONAL_STATISTICS,
            geography="GLOBAL",
            authority_tier=AuthorityTier.OFFICIAL_SECONDARY,
            base_uri="https://api.worldbank.org",
            expected_content_types=("application/json", "application/xml"),
            timezone="UTC",
            ingestion_method=IngestionMethod.JSON_API,
            enabled=False,
            revision_notes="Indicator histories may be revised or rebenchmarked without vintage guarantees.",
        ),
        SourceDefinition(
            source_id="global.oecd.sdmx",
            name="OECD Data Explorer",
            source_type=RegistrySourceType.NATIONAL_STATISTICS,
            geography="GLOBAL",
            authority_tier=AuthorityTier.OFFICIAL_SECONDARY,
            base_uri="https://sdmx.oecd.org",
            expected_content_types=("text/csv", "application/vnd.sdmx.data+csv"),
            timezone="Europe/Paris",
            ingestion_method=IngestionMethod.SDMX_API,
            enabled=False,
            revision_notes="Dataset structures and observations may be revised; vintages must be retained.",
        ),
        SourceDefinition(
            source_id="us.eia",
            name="U.S. Energy Information Administration",
            source_type=RegistrySourceType.GOVERNMENT,
            geography="US",
            authority_tier=AuthorityTier.OFFICIAL_PRIMARY,
            base_uri="https://api.eia.gov",
            expected_content_types=("application/json",),
            timezone="America/New_York",
            ingestion_method=IngestionMethod.JSON_API,
            enabled=False,
            revision_notes="Energy series may be revised; API-key and vintage handling require review.",
        ),
        SourceDefinition(
            source_id="il.pmo.statements",
            name="Israel Prime Minister's Office Statements",
            source_type=RegistrySourceType.GOVERNMENT,
            geography="IL",
            authority_tier=AuthorityTier.OFFICIAL_PRIMARY,
            base_uri="https://www.gov.il/en/departments/prime_ministers_office",
            expected_content_types=("application/json", "text/html", "application/pdf"),
            timezone="Asia/Jerusalem",
            ingestion_method=IngestionMethod.FILE_DOWNLOAD,
            enabled=False,
            revision_notes="Statements may be corrected, withdrawn, translated, or superseded without a machine-readable revision feed.",
        ),
        SourceDefinition(
            source_id="il.idf.statements",
            name="Israel Defense Forces Statements",
            source_type=RegistrySourceType.GOVERNMENT,
            geography="IL",
            authority_tier=AuthorityTier.OFFICIAL_PRIMARY,
            base_uri="https://www.idf.il/en",
            expected_content_types=("text/html", "application/json"),
            timezone="Asia/Jerusalem",
            ingestion_method=IngestionMethod.FILE_DOWNLOAD,
            enabled=False,
            revision_notes="Operational statements can be updated or corrected; no reviewed immutable API contract is available.",
        ),
        SourceDefinition(
            source_id="us.state.statements",
            name="U.S. Department of State Statements",
            source_type=RegistrySourceType.GOVERNMENT,
            geography="US",
            authority_tier=AuthorityTier.OFFICIAL_PRIMARY,
            base_uri="https://www.state.gov",
            expected_content_types=("text/html", "application/xml"),
            timezone="America/New_York",
            ingestion_method=IngestionMethod.RSS_FEED,
            enabled=False,
            revision_notes="Statements may be corrected or removed; feed and page revision semantics require review.",
        ),
        SourceDefinition(
            source_id="global.un.press",
            name="United Nations Press",
            source_type=RegistrySourceType.GOVERNMENT,
            geography="GLOBAL",
            authority_tier=AuthorityTier.OFFICIAL_PRIMARY,
            base_uri="https://press.un.org",
            expected_content_types=("text/html", "application/xml"),
            timezone="America/New_York",
            ingestion_method=IngestionMethod.RSS_FEED,
            enabled=False,
            revision_notes="Press releases may be corrected; publication and update timestamps need contract review.",
        ),
        SourceDefinition(
            source_id="global.icao",
            name="International Civil Aviation Organization",
            source_type=RegistrySourceType.GOVERNMENT,
            geography="GLOBAL",
            authority_tier=AuthorityTier.OFFICIAL_PRIMARY,
            base_uri="https://www.icao.int",
            expected_content_types=("text/html", "application/pdf"),
            timezone="America/Montreal",
            ingestion_method=IngestionMethod.FILE_DOWNLOAD,
            enabled=False,
            revision_notes="No reviewed public capacity/cancellation API and vintage contract is enabled.",
        ),
        SourceDefinition(
            source_id="global.imo",
            name="International Maritime Organization",
            source_type=RegistrySourceType.GOVERNMENT,
            geography="GLOBAL",
            authority_tier=AuthorityTier.OFFICIAL_PRIMARY,
            base_uri="https://www.imo.org",
            expected_content_types=("text/html", "application/pdf"),
            timezone="Europe/London",
            ingestion_method=IngestionMethod.FILE_DOWNLOAD,
            enabled=False,
            revision_notes="No reviewed route-disruption API with historical visibility is enabled.",
        ),
        SourceDefinition(
            source_id="global.iea",
            name="International Energy Agency",
            source_type=RegistrySourceType.GOVERNMENT,
            geography="GLOBAL",
            authority_tier=AuthorityTier.OFFICIAL_SECONDARY,
            base_uri="https://www.iea.org",
            expected_content_types=("application/json", "text/csv", "application/pdf"),
            timezone="Europe/Paris",
            ingestion_method=IngestionMethod.FILE_DOWNLOAD,
            enabled=False,
            revision_notes="Dataset licensing, revisions, and release vintages require series-level review.",
        ),
    )
)
