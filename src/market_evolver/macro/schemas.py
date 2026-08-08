"""Immutable schemas for macro releases, surprises, trends, and divergences."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum

from market_evolver.errors import ValidationError
from market_evolver.provenance import content_id
from market_evolver.time import require_aware_utc


class MacroCategory(str, Enum):
    INFLATION = "inflation"
    INTEREST_RATES = "interest_rates"
    EMPLOYMENT = "employment"
    GDP_ACTIVITY = "gdp_activity"
    HOUSING = "housing_construction"
    CONSUMER = "consumer_activity"
    TRADE = "trade"
    TOURISM = "tourism"
    INDUSTRIAL_PRODUCTION = "industrial_production"
    CREDIT = "credit_conditions"
    GOVERNMENT_SPENDING = "government_spending"
    ENERGY = "energy_prices"
    FX = "fx_macro"
    TECHNOLOGY_CAPEX = "technology_capex"


class SeasonalAdjustment(str, Enum):
    NOT_APPLICABLE = "not_applicable"
    UNADJUSTED = "unadjusted"
    SEASONALLY_ADJUSTED = "seasonally_adjusted"


class ExpectationStatus(str, Enum):
    UNKNOWN = "unknown"
    AVAILABLE = "available"


class TrendState(str, Enum):
    RISING = "rising"
    FALLING = "falling"
    ACCELERATING = "accelerating"
    DECELERATING = "decelerating"
    REGIME_SHIFT_CANDIDATE = "regime_shift_candidate"
    ANOMALY = "anomaly"
    STABLE = "stable"


class TrendHorizon(str, Enum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


_VALID_UNITS = {
    "percent",
    "percentage_point",
    "index",
    "count",
    "currency",
    "currency_millions",
    "ratio",
    "rate",
    "barrel",
}


def _number(value: str, name: str) -> Decimal:
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValidationError(f"{name} must be numeric") from exc
    if not number.is_finite():
        raise ValidationError(f"{name} must be finite")
    return number


@dataclass(frozen=True, slots=True)
class MacroObservation:
    series_id: str
    source_id: str
    geography: str
    category: MacroCategory
    observation_period: str
    value: str
    unit: str
    published_at: datetime
    first_observed_at: datetime
    revision_of: str | None
    seasonal_adjustment: SeasonalAdjustment
    provenance: tuple[str, ...]
    parser_version: str
    name_en: str
    name_he: str | None = None
    prior_value: str | None = None
    expected_value: str | None = None
    expectation_source: str | None = None
    expectation_observed_at: datetime | None = None
    observation_id: str = field(init=False)

    def __post_init__(self) -> None:
        published = require_aware_utc(self.published_at, "published_at")
        observed = require_aware_utc(self.first_observed_at, "first_observed_at")
        object.__setattr__(self, "published_at", published)
        object.__setattr__(self, "first_observed_at", observed)
        if published > observed:
            raise ValidationError("macro release cannot be observed before publication")
        if self.unit not in _VALID_UNITS:
            raise ValidationError(f"unsupported macro unit: {self.unit}")
        _number(self.value, "value")
        if self.prior_value is not None:
            _number(self.prior_value, "prior_value")
        expectation_fields = (
            self.expected_value,
            self.expectation_source,
            self.expectation_observed_at,
        )
        if any(value is not None for value in expectation_fields) and not all(
            value is not None for value in expectation_fields
        ):
            raise ValidationError("expectation value, source, and observation time are atomic")
        if self.expected_value is not None:
            _number(self.expected_value, "expected_value")
            expectation_observed_at = self.expectation_observed_at
            assert expectation_observed_at is not None
            expected_at = require_aware_utc(expectation_observed_at, "expectation_observed_at")
            if expected_at > published:
                raise ValidationError("expectation must be known by release publication")
            object.__setattr__(self, "expectation_observed_at", expected_at)
        if not all(
            (
                self.series_id,
                self.source_id,
                self.geography,
                self.observation_period,
                self.provenance,
                self.parser_version,
                self.name_en,
            )
        ):
            raise ValidationError("macro identity, metadata, and provenance are required")
        object.__setattr__(self, "observation_id", content_id("macro-observation", self))

    @property
    def expectation_status(self) -> ExpectationStatus:
        return (
            ExpectationStatus.AVAILABLE
            if self.expected_value is not None
            else ExpectationStatus.UNKNOWN
        )

    @property
    def surprise(self) -> str | None:
        if self.expected_value is None:
            return None
        return format(_number(self.value, "value") - _number(self.expected_value, "expected"), "f")


@dataclass(frozen=True, slots=True)
class TrendSignal:
    series_id: str
    geography: str
    category: MacroCategory
    horizon: TrendHorizon
    state: TrendState
    as_of_period: str
    calculated_at: datetime
    calculation_version: str
    input_observation_ids: tuple[str, ...]
    slope: str | None = None
    rolling_mean: str | None = None
    z_score: str | None = None
    mechanism_ids: tuple[str, ...] = ()
    trend_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "calculated_at", require_aware_utc(self.calculated_at, "calculated_at")
        )
        if not self.input_observation_ids or not self.calculation_version:
            raise ValidationError("trend requires versioned observation provenance")
        for name in ("slope", "rolling_mean", "z_score"):
            value = getattr(self, name)
            if value is not None:
                _number(value, name)
        object.__setattr__(self, "trend_id", content_id("trend-signal", self))


@dataclass(frozen=True, slots=True)
class TrendDivergence:
    left_trend_id: str
    right_trend_id: str
    description: str
    observed_at: datetime
    provenance_ids: tuple[str, ...]
    divergence_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", require_aware_utc(self.observed_at, "observed_at"))
        if self.left_trend_id == self.right_trend_id or not self.provenance_ids:
            raise ValidationError("divergence requires two distinct provenanced trends")
        object.__setattr__(self, "divergence_id", content_id("trend-divergence", self))


@dataclass(frozen=True, slots=True)
class StructuralTrend:
    structural_id: str
    name: str
    description: str
    geography: str
    valid_from: datetime
    valid_until: datetime | None
    first_observed_at: datetime
    evidence_ids: tuple[str, ...]
    mechanism_ids: tuple[str, ...]
    curated: bool = True

    def __post_init__(self) -> None:
        start = require_aware_utc(self.valid_from, "valid_from")
        observed = require_aware_utc(self.first_observed_at, "first_observed_at")
        object.__setattr__(self, "valid_from", start)
        object.__setattr__(self, "first_observed_at", observed)
        if self.valid_until is not None:
            end = require_aware_utc(self.valid_until, "valid_until")
            object.__setattr__(self, "valid_until", end)
            if end <= start:
                raise ValidationError("structural trend validity interval is invalid")
        if not self.curated or not self.evidence_ids:
            raise ValidationError("v0.11 structural trends must be curated and evidenced")
