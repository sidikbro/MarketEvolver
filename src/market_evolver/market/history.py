"""Governed historical datasets, deterministic quality checks, and analytics."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import tempfile
import time
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from datetime import time as datetime_time
from decimal import Decimal, InvalidOperation
from enum import Enum
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb

from market_evolver.errors import IntegrityViolation, ValidationError
from market_evolver.provenance import content_id
from market_evolver.storage.artifacts import Artifact, LocalArtifactStore
from market_evolver.time import require_aware_utc


class DatasetType(str, Enum):
    EQUITY_OHLCV = "equity_ohlcv"
    INDEX_OHLCV = "index_ohlcv"
    FX = "fx"
    CORPORATE_ACTIONS = "corporate_actions"
    INDEX_COMPOSITION = "index_composition"
    TRADING_CALENDAR = "trading_calendar"


class SourceClass(str, Enum):
    AUTHORITATIVE_OFFICIAL = "authoritative_official"
    RESEARCH_QUALITY_PUBLIC = "research_quality_public"
    CONVENIENCE_EXPERIMENTAL = "convenience_experimental"


class PriceAdjustmentPolicy(str, Enum):
    RAW_AND_ADJUSTED_SEPARATE = "raw_and_adjusted_separate"
    RAW_ONLY = "raw_only"
    NOT_APPLICABLE = "not_applicable"


class SurvivorshipStatus(str, Enum):
    CURRENT_CONSTITUENTS_ONLY = "current_constituents_only"
    HISTORICAL_CONSTITUENTS_AVAILABLE = "historical_constituents_available"
    PARTIAL_HISTORY = "partial_history"
    UNKNOWN = "unknown"


class CompositionHistoryStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    PARTIAL = "partial"
    NOT_APPLICABLE = "not_applicable"


class HistoricalReplayEligibility(str, Enum):
    OUTCOME_MEASUREMENT_ONLY = "outcome_measurement_only"
    SAFE_FOR_HISTORICAL_REPLAY = "safe_for_historical_replay"
    FORWARD_OBSERVATION_ONLY = "forward_observation_only"
    TEMPORALLY_AMBIGUOUS = "temporally_ambiguous"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class HistoricalBar:
    instrument_id: str
    venue: str
    market_date: date
    market_timestamp: datetime
    historical_record_at: datetime | None
    retrieved_at: datetime
    currency: str
    raw_open: str
    raw_high: str
    raw_low: str
    raw_close: str
    volume: str
    adjusted_close: str | None
    adjustment_factor: str | None
    source_id: str
    raw_artifact_id: str
    parser_version: str
    bar_id: str = field(init=False)

    def __post_init__(self) -> None:
        market = require_aware_utc(self.market_timestamp, "market_timestamp")
        retrieved = require_aware_utc(self.retrieved_at, "retrieved_at")
        object.__setattr__(self, "market_timestamp", market)
        object.__setattr__(self, "retrieved_at", retrieved)
        if self.historical_record_at is not None:
            object.__setattr__(
                self,
                "historical_record_at",
                require_aware_utc(self.historical_record_at, "historical_record_at"),
            )
        if market.date() != self.market_date:
            raise ValidationError("bar market date and timestamp disagree")
        if market > retrieved:
            raise ValidationError("historical bar cannot be retrieved before its market timestamp")
        try:
            values = tuple(
                Decimal(value)
                for value in (
                    self.raw_open,
                    self.raw_high,
                    self.raw_low,
                    self.raw_close,
                    self.volume,
                )
            )
            adjusted = None if self.adjusted_close is None else Decimal(self.adjusted_close)
            factor = None if self.adjustment_factor is None else Decimal(self.adjustment_factor)
        except (InvalidOperation, ValueError) as exc:
            raise ValidationError("historical bar values must be decimal strings") from exc
        if any(value < 0 for value in values) or adjusted is not None and adjusted < 0:
            raise ValidationError("historical prices and volume cannot be negative")
        if values[1] < max(values[0], values[3]) or values[2] > min(values[0], values[3]):
            raise ValidationError("historical OHLC relationship is impossible")
        if factor is not None and factor <= 0:
            raise ValidationError("adjustment factor must be positive")
        if not self.raw_artifact_id.startswith("sha256:"):
            raise ValidationError("historical bar requires raw artifact provenance")
        object.__setattr__(self, "bar_id", content_id("historical-bar", self))


@dataclass(frozen=True, slots=True)
class HistoricalCorporateAction:
    instrument_id: str
    action_type: str
    effective_date: date
    value: str
    currency: str | None
    source_id: str
    raw_artifact_id: str
    observed_at: datetime
    action_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", require_aware_utc(self.observed_at, "observed_at"))
        if self.action_type not in {"dividend", "split", "reverse_split"}:
            raise ValidationError("unsupported historical corporate action")
        if Decimal(self.value) <= 0 or not self.raw_artifact_id.startswith("sha256:"):
            raise ValidationError("corporate action requires positive value and raw provenance")
        object.__setattr__(self, "action_id", content_id("historical-action", self))


@dataclass(frozen=True, slots=True)
class HistoricalDataset:
    source_id: str
    source_class: SourceClass
    dataset_type: DatasetType
    instruments: tuple[str, ...]
    venue: str
    frequency: str
    date_start: date
    date_end: date
    retrieval_started_at: datetime
    retrieval_completed_at: datetime
    raw_artifact_ids: tuple[str, ...]
    normalized_artifact_ids: tuple[str, ...]
    parquet_hashes: tuple[str, ...]
    parquet_paths: tuple[str, ...]
    row_count: int
    timezone: str
    price_adjustment_policy: PriceAdjustmentPolicy
    corporate_action_policy: str
    survivorship_status: SurvivorshipStatus
    composition_history_status: CompositionHistoryStatus
    parser_version: str
    schema_version: str
    provenance: tuple[str, ...]
    replay_eligibility: HistoricalReplayEligibility
    request_parameters: tuple[tuple[str, str], ...]
    source_contract_fingerprint: str
    code_commit: str
    dataset_id: str = field(init=False)

    def __post_init__(self) -> None:
        started = require_aware_utc(self.retrieval_started_at, "retrieval_started_at")
        completed = require_aware_utc(self.retrieval_completed_at, "retrieval_completed_at")
        object.__setattr__(self, "retrieval_started_at", started)
        object.__setattr__(self, "retrieval_completed_at", completed)
        if completed < started or self.date_end < self.date_start:
            raise ValidationError("historical dataset time range is invalid")
        if (
            not self.instruments
            or self.row_count < 1
            or not self.parquet_hashes
            or len(self.parquet_hashes) != len(self.parquet_paths)
        ):
            raise ValidationError("historical dataset requires instruments, rows, and Parquet")
        if not self.raw_artifact_ids or not self.normalized_artifact_ids or not self.provenance:
            raise ValidationError("historical dataset requires complete provenance")
        ZoneInfo(self.timezone)
        object.__setattr__(self, "dataset_id", content_id("historical-dataset", self))


@dataclass(frozen=True, slots=True)
class QualityIssue:
    code: str
    severity: str
    instrument_id: str
    market_date: str | None
    detail: str


@dataclass(frozen=True, slots=True)
class DatasetQualityReport:
    dataset_id: str
    status: str
    issues: tuple[QualityIssue, ...]
    rows: int
    duplicate_bars: int
    missing_sessions: int


@dataclass(frozen=True, slots=True)
class DatasetTelemetry:
    raw_bytes: int
    normalized_bytes: int
    parquet_bytes: int
    duckdb_metadata_bytes: int
    rows: int
    compression_ratio: float
    bytes_per_million_rows: int
    ingest_rows_per_second: float
    parquet_write_bytes_per_second: float
    duckdb_scan_ms: float


def measure_dataset(
    store: HistoricalDatasetStore,
    paths: tuple[Path, ...],
    *,
    raw_bytes: int,
    normalized_bytes: int,
    elapsed_seconds: float,
) -> DatasetTelemetry:
    diagnostics = store.diagnostics(paths)
    rows = int(diagnostics["rows"])
    parquet_bytes = sum(path.stat().st_size for path in paths)
    if rows < 1 or elapsed_seconds <= 0:
        raise ValidationError("dataset telemetry requires rows and positive elapsed time")
    return DatasetTelemetry(
        raw_bytes,
        normalized_bytes,
        parquet_bytes,
        0,
        rows,
        normalized_bytes / parquet_bytes if parquet_bytes else 0,
        round(parquet_bytes * 1_000_000 / rows),
        rows / elapsed_seconds,
        parquet_bytes / elapsed_seconds,
        float(diagnostics["scan_ms"]),
    )


def plumbing_baselines(bars: tuple[HistoricalBar, ...]) -> dict[str, str]:
    """Fixed diagnostics only; these are not optimized strategies or recommendations."""
    if len(bars) < 2:
        raise ValidationError("baseline plumbing requires at least two bars")
    ordered = tuple(sorted(bars, key=lambda item: item.market_timestamp))
    first = Decimal(ordered[0].raw_close)
    last = Decimal(ordered[-1].raw_close)
    prior = Decimal(ordered[-2].raw_close)
    return {
        "cash": "0",
        "buy_and_hold": str(last / first - 1),
        "simple_momentum": "up" if last > prior else "down" if last < prior else "flat",
        "simple_mean_reversion": "below_prior" if last < prior else "not_below_prior",
    }


class HistoricalDatasetStore:
    COLUMNS = (
        "bar_id",
        "instrument_id",
        "venue",
        "market_date",
        "market_timestamp",
        "historical_record_at",
        "retrieved_at",
        "currency",
        "raw_open",
        "raw_high",
        "raw_low",
        "raw_close",
        "volume",
        "adjusted_close",
        "adjustment_factor",
        "source_id",
        "raw_artifact_id",
        "parser_version",
    )

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.artifacts = LocalArtifactStore(self.root / "raw")

    def persist_raw(self, content: bytes, mime_type: str) -> Artifact:
        return self.artifacts.put(content, mime_type=mime_type)

    def write_bars(
        self, bars: tuple[HistoricalBar, ...], *, source_id: str, venue: str
    ) -> tuple[tuple[Path, ...], tuple[str, ...], int]:
        if not bars:
            raise IntegrityViolation("cannot write empty historical dataset")
        ordered = tuple(sorted(bars, key=lambda item: (item.instrument_id, item.market_timestamp)))
        groups: dict[tuple[str, int], list[HistoricalBar]] = {}
        for bar in ordered:
            groups.setdefault((bar.instrument_id, bar.market_date.year), []).append(bar)
        paths: list[Path] = []
        hashes: list[str] = []
        total_bytes = 0
        for (instrument, year), values in groups.items():
            relative = (
                Path(f"source={source_id}")
                / f"venue={venue}"
                / "frequency=1d"
                / f"instrument={instrument}"
                / f"year={year}"
                / "bars.parquet"
            )
            destination = self.root / "parquet" / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            descriptor, name = tempfile.mkstemp(suffix=".parquet", dir=destination.parent)
            os.close(descriptor)
            temporary = Path(name)
            try:
                self._write_parquet(temporary, tuple(values))
                digest = hashlib.sha256(temporary.read_bytes()).hexdigest()
                if destination.exists():
                    if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                        raise IntegrityViolation("immutable historical partition already differs")
                else:
                    os.link(temporary, destination)
                paths.append(destination)
                hashes.append(digest)
                total_bytes += destination.stat().st_size
            finally:
                temporary.unlink(missing_ok=True)
        return tuple(paths), tuple(hashes), total_bytes

    def write_manifest(self, dataset: HistoricalDataset) -> Path:
        path = self.root / "manifests" / f"{dataset.dataset_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(_jsonable(asdict(dataset)), sort_keys=True, separators=(",", ":"))
        if path.exists() and path.read_text(encoding="utf-8") != payload:
            raise IntegrityViolation("immutable dataset manifest mismatch")
        if not path.exists():
            path.write_text(payload, encoding="utf-8")
        return path

    def read_bars(self, paths: tuple[Path, ...]) -> tuple[HistoricalBar, ...]:
        if not paths:
            return ()
        connection = duckdb.connect(":memory:")
        try:
            rows = connection.execute(
                f"SELECT {', '.join(self.COLUMNS)} FROM read_parquet(?) ORDER BY instrument_id, market_timestamp",
                [[str(path) for path in paths]],
            ).fetchall()
        finally:
            connection.close()
        result = []
        for row in rows:
            values = dict(zip(self.COLUMNS, row, strict=True))
            item = HistoricalBar(**{key: values[key] for key in self.COLUMNS if key != "bar_id"})
            if item.bar_id != values["bar_id"]:
                raise IntegrityViolation("Parquet normalized-row hash mismatch")
            result.append(item)
        return tuple(result)

    def verify_parquet(self, path: Path, expected_hash: str) -> None:
        if hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
            raise IntegrityViolation("historical Parquet hash mismatch")

    def diagnostics(self, paths: tuple[Path, ...]) -> dict[str, Any]:
        connection = duckdb.connect(":memory:")
        started = time.perf_counter()
        try:
            row = connection.execute(
                "SELECT count(*), count(DISTINCT instrument_id), min(market_date), max(market_date) FROM read_parquet(?)",
                [[str(path) for path in paths]],
            ).fetchone()
        finally:
            connection.close()
        assert row is not None
        return {
            "rows": int(row[0]),
            "instruments": int(row[1]),
            "date_start": str(row[2]),
            "date_end": str(row[3]),
            "scan_ms": (time.perf_counter() - started) * 1000,
        }

    def aligned_join(
        self, paths: tuple[Path, ...], left_instrument: str, right_instrument: str
    ) -> tuple[tuple[str, str, str], ...]:
        connection = duckdb.connect(":memory:")
        try:
            rows = connection.execute(
                """SELECT CAST(a.market_date AS VARCHAR), a.raw_close, b.raw_close
                FROM read_parquet(?) a JOIN read_parquet(?) b USING (market_date)
                WHERE a.instrument_id = ? AND b.instrument_id = ? ORDER BY a.market_date""",
                [
                    [str(path) for path in paths],
                    [str(path) for path in paths],
                    left_instrument,
                    right_instrument,
                ],
            ).fetchall()
        finally:
            connection.close()
        return tuple((str(day), str(left), str(right)) for day, left, right in rows)

    @classmethod
    def _write_parquet(cls, path: Path, bars: tuple[HistoricalBar, ...]) -> None:
        connection = duckdb.connect(":memory:")
        try:
            connection.execute(
                """CREATE TABLE bars (
                bar_id VARCHAR, instrument_id VARCHAR, venue VARCHAR, market_date DATE,
                market_timestamp TIMESTAMPTZ, historical_record_at TIMESTAMPTZ,
                retrieved_at TIMESTAMPTZ, currency VARCHAR, raw_open VARCHAR,
                raw_high VARCHAR, raw_low VARCHAR, raw_close VARCHAR, volume VARCHAR,
                adjusted_close VARCHAR, adjustment_factor VARCHAR, source_id VARCHAR,
                raw_artifact_id VARCHAR, parser_version VARCHAR)"""
            )
            connection.executemany(
                f"INSERT INTO bars VALUES ({', '.join('?' for _ in cls.COLUMNS)})",
                [tuple(getattr(item, column) for column in cls.COLUMNS) for item in bars],
            )
            escaped = str(path).replace("'", "''")
            connection.execute(f"COPY bars TO '{escaped}' (FORMAT PARQUET, COMPRESSION ZSTD)")
        finally:
            connection.close()


def validate_quality(
    dataset_id: str,
    bars: tuple[HistoricalBar, ...],
    *,
    expected_sessions: tuple[date, ...] = (),
    expected_currency: str | None = None,
) -> DatasetQualityReport:
    issues: list[QualityIssue] = []
    seen: set[tuple[str, datetime]] = set()
    duplicate_count = 0
    prior: dict[str, HistoricalBar] = {}
    dates_by_instrument: dict[str, set[date]] = {}
    original_order = tuple((item.instrument_id, item.market_timestamp) for item in bars)
    if original_order != tuple(sorted(original_order)):
        issues.append(
            QualityIssue("OUT_OF_ORDER", "error", "*", None, "bars are not stably ordered")
        )
    for bar in bars:
        key = (bar.instrument_id, bar.market_timestamp)
        if key in seen:
            duplicate_count += 1
            issues.append(
                QualityIssue(
                    "DUPLICATE_BAR",
                    "error",
                    bar.instrument_id,
                    bar.market_date.isoformat(),
                    "duplicate market timestamp",
                )
            )
        seen.add(key)
        dates_by_instrument.setdefault(bar.instrument_id, set()).add(bar.market_date)
        if expected_currency and bar.currency != expected_currency:
            issues.append(
                QualityIssue(
                    "CURRENCY_MISMATCH",
                    "error",
                    bar.instrument_id,
                    bar.market_date.isoformat(),
                    f"expected {expected_currency}, received {bar.currency}",
                )
            )
        if Decimal(bar.volume) == 0 and not bar.instrument_id.startswith("asset.fx."):
            issues.append(
                QualityIssue(
                    "ZERO_VOLUME",
                    "warning",
                    bar.instrument_id,
                    bar.market_date.isoformat(),
                    "zero volume requires review",
                )
            )
        previous = prior.get(bar.instrument_id)
        if previous and Decimal(previous.raw_close) > 0:
            change = abs(Decimal(bar.raw_close) / Decimal(previous.raw_close) - 1)
            if change >= Decimal("0.20"):
                issues.append(
                    QualityIssue(
                        "EXTREME_MOVE",
                        "warning",
                        bar.instrument_id,
                        bar.market_date.isoformat(),
                        f"absolute close move {change}",
                    )
                )
            if change >= Decimal("0.45"):
                issues.append(
                    QualityIssue(
                        "SPLIT_LIKE_DISCONTINUITY",
                        "warning",
                        bar.instrument_id,
                        bar.market_date.isoformat(),
                        "requires explicit corporate-action review",
                    )
                )
        prior[bar.instrument_id] = bar
    missing = 0
    for instrument, present in dates_by_instrument.items():
        for session in expected_sessions:
            if session not in present:
                missing += 1
                issues.append(
                    QualityIssue(
                        "MISSING_SESSION",
                        "warning",
                        instrument,
                        session.isoformat(),
                        "expected calendar session has no bar",
                    )
                )
    status = (
        "failed"
        if any(item.severity == "error" for item in issues)
        else "degraded"
        if issues
        else "passed"
    )
    return DatasetQualityReport(
        dataset_id, status, tuple(issues), len(bars), duplicate_count, missing
    )


def compare_sources(
    left: tuple[HistoricalBar, ...], right: tuple[HistoricalBar, ...]
) -> tuple[dict[str, str], ...]:
    right_by_key = {(item.instrument_id, item.market_date): item for item in right}
    differences = []
    for item in left:
        other = right_by_key.get((item.instrument_id, item.market_date))
        if other is None:
            continue
        if (item.raw_close, item.adjusted_close, item.volume) != (
            other.raw_close,
            other.adjusted_close,
            other.volume,
        ):
            differences.append(
                {
                    "instrument_id": item.instrument_id,
                    "date": item.market_date.isoformat(),
                    "left_close": item.raw_close,
                    "right_close": other.raw_close,
                    "left_adjusted": str(item.adjusted_close),
                    "right_adjusted": str(other.adjusted_close),
                    "left_volume": item.volume,
                    "right_volume": other.volume,
                }
            )
    return tuple(differences)


class StooqDailyConnector:
    """Replaceable convenience source; explicitly not official exchange data."""

    source_id = "global.stooq.experimental"
    parser_version = "stooq-daily-csv/1"
    max_days = 3660
    max_bytes = 5_000_000

    def fetch(self, symbol: str, start: date, end: date) -> bytes:
        _bounded_range(start, end, self.max_days)
        query = urllib.parse.urlencode(
            {
                "s": symbol.casefold(),
                "d1": start.strftime("%Y%m%d"),
                "d2": end.strftime("%Y%m%d"),
                "i": "d",
            }
        )
        request = urllib.request.Request(
            f"https://stooq.com/q/d/l/?{query}",
            headers={"User-Agent": "MarketEvolver/0.23 bounded-research"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            body = bytes(response.read(self.max_bytes + 1))
        if len(body) > self.max_bytes:
            raise IntegrityViolation("historical response exceeds byte limit")
        return body

    def parse(
        self,
        body: bytes,
        *,
        instrument_id: str,
        venue: str,
        currency: str,
        retrieved_at: datetime,
        artifact: Artifact,
    ) -> tuple[HistoricalBar, ...]:
        try:
            rows = csv.DictReader(io.StringIO(body.decode("utf-8")))
        except UnicodeDecodeError as exc:
            raise IntegrityViolation("historical CSV encoding is invalid") from exc
        required = {"Date", "Open", "High", "Low", "Close", "Volume"}
        if rows.fieldnames is None or not required.issubset(rows.fieldnames):
            raise IntegrityViolation("historical CSV schema changed")
        output = []
        try:
            for row in rows:
                day = date.fromisoformat(row["Date"])
                output.append(
                    HistoricalBar(
                        instrument_id,
                        venue,
                        day,
                        datetime.combine(day, datetime_time(21), UTC),
                        None,
                        retrieved_at,
                        currency,
                        row["Open"],
                        row["High"],
                        row["Low"],
                        row["Close"],
                        row["Volume"],
                        None,
                        None,
                        self.source_id,
                        f"sha256:{artifact.sha256}",
                        self.parser_version,
                    )
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise IntegrityViolation("malformed historical CSV row") from exc
        if not output:
            raise IntegrityViolation("historical CSV contains no rows")
        return tuple(output)


class BoiUsdIlsHistoryConnector:
    """Official bounded BOI SDMX daily USD/ILS representative-rate series."""

    source_id = "il.boi.sdmx.exr"
    parser_version = "boi-sdmx-usdils-csv/1"
    series_code = "RER_USD_ILS"
    max_days = 3660
    max_bytes = 5_000_000
    endpoint = (
        "https://edge.boi.org.il/FusionEdgeServer/sdmx/v2/data/dataflow/"
        "BOI.STATISTICS/EXR/1.0/RER_USD_ILS"
    )

    def fetch(self, start: date, end: date) -> tuple[bytes, str]:
        _bounded_range(start, end, self.max_days)
        query = urllib.parse.urlencode(
            {
                "startperiod": start.isoformat(),
                "endperiod": end.isoformat(),
                "format": "csv",
            }
        )
        uri = f"{self.endpoint}?{query}"
        request = urllib.request.Request(
            uri,
            headers={"Accept": "text/csv", "User-Agent": "MarketEvolver/0.23 bounded-research"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            body = bytes(response.read(self.max_bytes + 1))
        if len(body) > self.max_bytes:
            raise IntegrityViolation("BOI historical response exceeds byte limit")
        return body, uri

    def parse(
        self, body: bytes, *, retrieved_at: datetime, artifact: Artifact
    ) -> tuple[HistoricalBar, ...]:
        try:
            reader = csv.DictReader(io.StringIO(body.decode("utf-8-sig")))
        except UnicodeDecodeError as exc:
            raise IntegrityViolation("BOI historical CSV encoding is invalid") from exc
        required = {
            "SERIES_CODE",
            "FREQ",
            "BASE_CURRENCY",
            "COUNTER_CURRENCY",
            "UNIT_MEASURE",
            "DATA_TYPE",
            "TIME_PERIOD",
            "OBS_VALUE",
            "RELEASE_STATUS",
        }
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            raise IntegrityViolation("BOI historical CSV schema changed")
        output = []
        try:
            for row in reader:
                if (
                    row["SERIES_CODE"] != self.series_code
                    or row["FREQ"] != "D"
                    or row["BASE_CURRENCY"] != "USD"
                    or row["COUNTER_CURRENCY"] != "ILS"
                    or row["DATA_TYPE"] != "OF00"
                ):
                    raise IntegrityViolation("BOI historical row violates fixed series contract")
                day = date.fromisoformat(row["TIME_PERIOD"])
                value = row["OBS_VALUE"]
                output.append(
                    HistoricalBar(
                        "asset.fx.usdils",
                        "BOI",
                        day,
                        datetime.combine(day, datetime_time(13, 15), ZoneInfo("Asia/Jerusalem")),
                        None,
                        retrieved_at,
                        "ILS",
                        value,
                        value,
                        value,
                        value,
                        "0",
                        None,
                        None,
                        self.source_id,
                        f"sha256:{artifact.sha256}",
                        self.parser_version,
                    )
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise IntegrityViolation("malformed BOI historical row") from exc
        if not output:
            raise IntegrityViolation("BOI historical response contains no observations")
        return tuple(output)


def storage_projections(parquet_bytes: int, rows: int) -> tuple[dict[str, int], ...]:
    if parquet_bytes < 0 or rows < 1:
        raise ValidationError("projection requires observed rows")
    bytes_per_row = parquet_bytes / rows
    values = []
    for instruments in (18, 100, 1000):
        for years in (5, 10, 20):
            estimated_rows = instruments * years * 252
            values.append(
                {
                    "instruments": instruments,
                    "years": years,
                    "estimated_rows": estimated_rows,
                    "estimated_parquet_bytes": round(estimated_rows * bytes_per_row),
                }
            )
    return tuple(values)


def _bounded_range(start: date, end: date, max_days: int) -> None:
    if end < start or (end - start).days > max_days:
        raise ValidationError(f"historical request must span 0..{max_days} days")


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value
