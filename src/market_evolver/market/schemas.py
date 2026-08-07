"""Immutable market, instrument, corporate-action, and calendar schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import Enum

from market_evolver.errors import ValidationError
from market_evolver.provenance import content_id
from market_evolver.time import require_aware_utc


class AssetType(str, Enum):
    EQUITY = "equity"
    ETF = "etf"
    INDEX = "index"
    FX = "fx"


class ObservationType(str, Enum):
    OHLCV = "ohlcv"
    INDEX_LEVEL = "index_level"
    FX_RATE = "fx_rate"


class AdjustmentStatus(str, Enum):
    RAW = "raw"
    ADJUSTED = "adjusted"


class CorporateActionType(str, Enum):
    DIVIDEND = "dividend"
    SPLIT = "split"
    REVERSE_SPLIT = "reverse_split"
    SYMBOL_CHANGE = "symbol_change"
    MERGER = "merger"
    DELISTING = "delisting"


@dataclass(frozen=True, slots=True)
class Asset:
    asset_id: str
    symbol: str
    venue: str
    asset_type: AssetType
    currency: str
    company_id: str | None
    entity_id: str
    benchmark_asset_id: str | None
    valid_from: datetime
    valid_until: datetime | None
    observed_at: datetime
    provenance: tuple[str, ...]
    version: int = 1
    asset_version_id: str = field(init=False)

    def __post_init__(self) -> None:
        valid_from = require_aware_utc(self.valid_from, "valid_from")
        observed = require_aware_utc(self.observed_at, "observed_at")
        object.__setattr__(self, "valid_from", valid_from)
        object.__setattr__(self, "observed_at", observed)
        if self.valid_until is not None:
            valid_until = require_aware_utc(self.valid_until, "valid_until")
            if valid_until <= valid_from:
                raise ValidationError("asset valid_until must follow valid_from")
            object.__setattr__(self, "valid_until", valid_until)
        if not all((self.asset_id, self.symbol, self.venue, self.currency, self.entity_id)):
            raise ValidationError("asset identity and classification are required")
        if not self.provenance or self.version < 1:
            raise ValidationError("asset provenance and positive version are required")
        object.__setattr__(self, "asset_version_id", content_id("asset-version", self))


@dataclass(frozen=True, slots=True)
class MarketObservation:
    asset_id: str
    venue: str
    observation_type: ObservationType
    market_timestamp: datetime
    observed_at: datetime
    source_id: str
    adjustment_status: AdjustmentStatus
    currency: str
    parser_version: str
    provenance: tuple[str, ...]
    open: str | None = None
    high: str | None = None
    low: str | None = None
    close: str | None = None
    volume: str | None = None
    value: str | None = None
    observation_id: str = field(init=False)

    def __post_init__(self) -> None:
        market = require_aware_utc(self.market_timestamp, "market_timestamp")
        observed = require_aware_utc(self.observed_at, "observed_at")
        object.__setattr__(self, "market_timestamp", market)
        object.__setattr__(self, "observed_at", observed)
        if market > observed:
            raise ValidationError("market observation cannot be visible before market timestamp")
        if not all(
            (
                self.asset_id,
                self.venue,
                self.source_id,
                self.currency,
                self.parser_version,
                self.provenance,
            )
        ):
            raise ValidationError("market observation metadata and provenance are required")
        values = (self.open, self.high, self.low, self.close, self.volume, self.value)
        try:
            decimals = tuple(None if item is None else Decimal(item) for item in values)
        except (InvalidOperation, ValueError) as exc:
            raise ValidationError("market values must be decimal strings") from exc
        if self.observation_type is ObservationType.OHLCV:
            if any(item is None for item in decimals[:4]):
                raise ValidationError("OHLCV observation requires open, high, low, and close")
            assert decimals[1] is not None and decimals[2] is not None
            assert decimals[0] is not None and decimals[3] is not None
            if decimals[1] < max(decimals[0], decimals[3]) or decimals[2] > min(
                decimals[0], decimals[3]
            ):
                raise ValidationError("OHLC high/low ordering is invalid")
        elif self.value is None:
            raise ValidationError("index and FX observations require value")
        object.__setattr__(self, "observation_id", content_id("market-observation", self))

    @property
    def effective_close(self) -> str:
        if self.observation_type is ObservationType.OHLCV:
            assert self.close is not None
            return self.close
        assert self.value is not None
        return self.value


@dataclass(frozen=True, slots=True)
class CorporateAction:
    asset_id: str
    action_type: CorporateActionType
    effective_at: datetime
    announced_at: datetime | None
    observed_at: datetime
    source_id: str
    evidence_ids: tuple[str, ...]
    value: str | None = None
    currency: str | None = None
    old_symbol: str | None = None
    new_symbol: str | None = None
    action_id: str = field(init=False)

    def __post_init__(self) -> None:
        effective = require_aware_utc(self.effective_at, "effective_at")
        observed = require_aware_utc(self.observed_at, "observed_at")
        object.__setattr__(self, "effective_at", effective)
        object.__setattr__(self, "observed_at", observed)
        if self.announced_at is not None:
            announced = require_aware_utc(self.announced_at, "announced_at")
            if announced > observed:
                raise ValidationError("corporate action cannot be observed before announcement")
            object.__setattr__(self, "announced_at", announced)
        if not self.asset_id or not self.source_id or not self.evidence_ids:
            raise ValidationError("corporate action identity and evidence are required")
        if self.action_type is CorporateActionType.SYMBOL_CHANGE and not (
            self.old_symbol and self.new_symbol
        ):
            raise ValidationError("symbol change requires old and new symbols")
        object.__setattr__(self, "action_id", content_id("corporate-action", self))


@dataclass(frozen=True, slots=True)
class TradingSession:
    venue: str
    session_date: str
    opens_at: datetime | None
    closes_at: datetime | None
    is_trading_day: bool
    observed_at: datetime
    source_id: str
    parser_version: str
    session_id: str = field(init=False)

    def __post_init__(self) -> None:
        observed = require_aware_utc(self.observed_at, "observed_at")
        object.__setattr__(self, "observed_at", observed)
        for name in ("opens_at", "closes_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, require_aware_utc(value, name))
        if self.is_trading_day and (self.opens_at is None or self.closes_at is None):
            raise ValidationError("trading day requires session open and close")
        if self.opens_at and self.closes_at and self.closes_at <= self.opens_at:
            raise ValidationError("session close must follow open")
        object.__setattr__(self, "session_id", content_id("trading-session", self))


@dataclass(frozen=True, slots=True)
class MarketPartition:
    sha256: str
    relative_path: str
    size_bytes: int
    row_count: int
    created_at: datetime
    dataset_version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "created_at", require_aware_utc(self.created_at, "created_at"))
        if len(self.sha256) != 64 or self.size_bytes < 1 or self.row_count < 1:
            raise ValidationError("invalid immutable market partition metadata")
