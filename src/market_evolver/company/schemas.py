"""Immutable company identity, filing, fundamental, ratio, and exposure records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum

from market_evolver.errors import ValidationError
from market_evolver.provenance import content_id
from market_evolver.time import require_aware_utc


class CompanyStatus(str, Enum):
    ACTIVE = "active"
    DELISTED = "delisted"


class FilingType(str, Enum):
    ANNUAL_REPORT = "annual_report"
    QUARTERLY_REPORT = "quarterly_report"
    EARNINGS_RELEASE = "earnings_release"
    INVESTOR_PRESENTATION = "investor_presentation"
    REGULATORY_FILING = "regulatory_filing"


class FundamentalType(str, Enum):
    REVENUE = "revenue"
    OPERATING_INCOME = "operating_income"
    NET_INCOME = "net_income"
    CASH = "cash"
    DEBT = "debt"
    EQUITY = "equity"
    EPS = "eps"
    OPERATING_MARGIN = "operating_margin"
    NET_MARGIN = "net_margin"
    OPERATING_CASH_FLOW = "operating_cash_flow"
    CAPEX = "capex"
    SHARES_OUTSTANDING = "shares_outstanding"
    DIVIDENDS = "dividends"
    SEGMENT_REVENUE = "segment_revenue"
    GEOGRAPHIC_REVENUE = "geographic_revenue"


class RestatementStatus(str, Enum):
    ORIGINAL = "original"
    RESTATED = "restated"


class CompanyExposureType(str, Enum):
    FOREIGN_CURRENCY_REVENUE = "foreign_currency_revenue"
    IMPORT_DEPENDENCE = "import_dependence"
    DEBT_RATE_SENSITIVITY = "debt_rate_sensitivity"
    GOVERNMENT_CUSTOMER = "government_customer"
    DEFENSE_PROCUREMENT = "defense_procurement"
    GEOGRAPHIC_CONCENTRATION = "geographic_concentration"
    TOURISM_DEMAND = "tourism_demand"
    COMMODITY = "commodity"


@dataclass(frozen=True, slots=True)
class Listing:
    ticker: str
    exchange: str
    valid_from: datetime
    valid_until: datetime | None = None

    def __post_init__(self) -> None:
        start = require_aware_utc(self.valid_from, "listing.valid_from")
        object.__setattr__(self, "valid_from", start)
        if self.valid_until is not None:
            end = require_aware_utc(self.valid_until, "listing.valid_until")
            if end <= start:
                raise ValidationError("listing valid_until must follow valid_from")
            object.__setattr__(self, "valid_until", end)
        if not self.ticker.strip() or not self.exchange.strip():
            raise ValidationError("listing ticker and exchange are required")


@dataclass(frozen=True, slots=True)
class CompanyVersion:
    company_id: str
    legal_name: str
    hebrew_name: str | None
    english_name: str
    aliases: tuple[str, ...]
    listings: tuple[Listing, ...]
    isin: str | None
    sector_id: str
    industry_id: str | None
    domicile: str
    status: CompanyStatus
    dual_listed: bool
    identifiers: tuple[tuple[str, str], ...]
    provenance: tuple[str, ...]
    valid_from: datetime
    valid_until: datetime | None
    observed_at: datetime
    version: int
    company_version_id: str = field(init=False)

    def __post_init__(self) -> None:
        start = require_aware_utc(self.valid_from, "valid_from")
        observed = require_aware_utc(self.observed_at, "observed_at")
        object.__setattr__(self, "valid_from", start)
        object.__setattr__(self, "observed_at", observed)
        if self.valid_until is not None:
            end = require_aware_utc(self.valid_until, "valid_until")
            if end <= start:
                raise ValidationError("company valid_until must follow valid_from")
            object.__setattr__(self, "valid_until", end)
        if not self.company_id or not self.legal_name or not self.english_name:
            raise ValidationError("company identity and names are required")
        if not self.listings or not self.sector_id or not self.domicile or not self.provenance:
            raise ValidationError(
                "company listings, classification, domicile, and provenance required"
            )
        if self.dual_listed != (len({item.exchange for item in self.listings}) > 1):
            raise ValidationError("dual_listed must match listing history")
        if self.version < 1:
            raise ValidationError("company version must be positive")
        object.__setattr__(self, "company_version_id", content_id("company-version", self))


@dataclass(frozen=True, slots=True)
class Filing:
    company_id: str
    filing_type: FilingType
    form_type: str
    accession_number: str
    source_uri: str
    filed_at: datetime
    first_observed_at: datetime
    fiscal_period_start: date
    fiscal_period_end: date
    raw_artifact_sha256: str
    source_evidence_ids: tuple[str, ...]
    parser_version: str
    restates_filing_id: str | None = None
    filing_id: str = field(init=False)

    def __post_init__(self) -> None:
        filed = require_aware_utc(self.filed_at, "filed_at")
        observed = require_aware_utc(self.first_observed_at, "first_observed_at")
        object.__setattr__(self, "filed_at", filed)
        object.__setattr__(self, "first_observed_at", observed)
        if filed > observed:
            raise ValidationError("filing cannot be observed before filed_at")
        if self.fiscal_period_end < self.fiscal_period_start:
            raise ValidationError("fiscal period end cannot precede start")
        if self.fiscal_period_end > filed.date():
            raise ValidationError("filing cannot precede its fiscal period end")
        if not all(
            (
                self.company_id,
                self.form_type,
                self.accession_number,
                self.source_uri,
                self.raw_artifact_sha256,
                self.source_evidence_ids,
                self.parser_version,
            )
        ):
            raise ValidationError("filing metadata and provenance are required")
        object.__setattr__(self, "filing_id", content_id("filing", self))


@dataclass(frozen=True, slots=True)
class FundamentalObservation:
    company_id: str
    filing_id: str
    metric: FundamentalType
    value: str
    currency: str | None
    unit: str
    fiscal_period_start: date
    fiscal_period_end: date
    published_at: datetime
    first_observed_at: datetime
    source_evidence_ids: tuple[str, ...]
    parser_version: str
    restatement_status: RestatementStatus = RestatementStatus.ORIGINAL
    restates_observation_id: str | None = None
    dimensions: tuple[tuple[str, str], ...] = ()
    observation_id: str = field(init=False)

    def __post_init__(self) -> None:
        published = require_aware_utc(self.published_at, "published_at")
        observed = require_aware_utc(self.first_observed_at, "first_observed_at")
        object.__setattr__(self, "published_at", published)
        object.__setattr__(self, "first_observed_at", observed)
        if published > observed or self.fiscal_period_end < self.fiscal_period_start:
            raise ValidationError("invalid fundamental timeline or fiscal period")
        try:
            Decimal(self.value)
        except InvalidOperation as exc:
            raise ValidationError("fundamental value must be decimal") from exc
        if not self.unit or not self.source_evidence_ids or not self.parser_version:
            raise ValidationError("fundamental unit, evidence, and parser are required")
        restated = self.restatement_status is RestatementStatus.RESTATED
        if restated != (self.restates_observation_id is not None):
            raise ValidationError("restatement status must identify prior observation")
        object.__setattr__(self, "observation_id", content_id("fundamental", self))


@dataclass(frozen=True, slots=True)
class DerivedMetric:
    company_id: str
    metric: str
    value: str
    unit: str
    fiscal_period_end: date
    first_observed_at: datetime
    input_observation_ids: tuple[str, ...]
    formula_version: str
    derived_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "first_observed_at",
            require_aware_utc(self.first_observed_at, "first_observed_at"),
        )
        if len(self.input_observation_ids) < 1 or not self.formula_version:
            raise ValidationError("derived metric requires input provenance and formula")
        object.__setattr__(self, "derived_id", content_id("derived-fundamental", self))


@dataclass(frozen=True, slots=True)
class CompanyExposure:
    company_id: str
    exposure_type: CompanyExposureType
    target: str
    value: str | None
    unit: str | None
    valid_from: datetime
    valid_until: datetime | None
    first_observed_at: datetime
    source_evidence_ids: tuple[str, ...]
    version: int
    exposure_id: str = field(init=False)

    def __post_init__(self) -> None:
        start = require_aware_utc(self.valid_from, "valid_from")
        observed = require_aware_utc(self.first_observed_at, "first_observed_at")
        object.__setattr__(self, "valid_from", start)
        object.__setattr__(self, "first_observed_at", observed)
        if self.valid_until is not None:
            end = require_aware_utc(self.valid_until, "valid_until")
            if end <= start:
                raise ValidationError("exposure valid_until must follow valid_from")
            object.__setattr__(self, "valid_until", end)
        if (self.value is None) != (self.unit is None):
            raise ValidationError("exposure value and unit must appear together")
        if not self.target or not self.source_evidence_ids or self.version < 1:
            raise ValidationError("exposure target, evidence, and version required")
        object.__setattr__(self, "exposure_id", content_id("company-exposure", self))
