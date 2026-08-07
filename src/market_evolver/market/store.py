"""Immutable Parquet partitions with PostgreSQL metadata and DuckDB queries."""

from __future__ import annotations

import hashlib
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import duckdb
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from market_evolver.errors import IntegrityViolation
from market_evolver.market.schemas import (
    AdjustmentStatus,
    Asset,
    AssetType,
    CorporateAction,
    CorporateActionType,
    MarketObservation,
    MarketPartition,
    ObservationType,
    TradingSession,
)
from market_evolver.storage.models import (
    AssetModel,
    CorporateActionModel,
    MarketObservationModel,
    MarketPartitionModel,
    TradingSessionModel,
)
from market_evolver.time import require_aware_utc

_COLUMNS = (
    "observation_id",
    "asset_id",
    "venue",
    "observation_type",
    "market_timestamp",
    "observed_at",
    "source_id",
    "adjustment_status",
    "currency",
    "parser_version",
    "provenance",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "value",
)


class MarketDataStore:
    def __init__(self, session: Session, root: Path) -> None:
        self.session = session
        self.root = root.resolve()

    def add_asset(self, asset: Asset) -> tuple[Asset, bool]:
        existing = self.session.get(AssetModel, asset.asset_version_id)
        if existing is not None:
            restored = self._asset(existing)
            if restored != asset:
                raise IntegrityViolation("immutable asset identity collision")
            return restored, False
        latest = self.session.scalar(
            select(AssetModel)
            .where(AssetModel.asset_id == asset.asset_id)
            .order_by(AssetModel.version.desc())
            .limit(1)
        )
        if latest is not None and asset.version != latest.version + 1:
            raise IntegrityViolation("asset versions must be sequential")
        self.session.add(
            AssetModel(
                asset_version_id=asset.asset_version_id,
                asset_id=asset.asset_id,
                symbol=asset.symbol,
                venue=asset.venue,
                asset_type=asset.asset_type.value,
                currency=asset.currency,
                company_id=asset.company_id,
                entity_id=asset.entity_id,
                benchmark_asset_id=asset.benchmark_asset_id,
                valid_from=asset.valid_from,
                valid_until=asset.valid_until,
                observed_at=asset.observed_at,
                provenance=list(asset.provenance),
                version=asset.version,
            )
        )
        self.session.flush()
        return asset, True

    def get_asset_at(self, asset_id: str, cutoff: datetime) -> Asset | None:
        at = require_aware_utc(cutoff, "cutoff")
        model = self.session.scalar(
            select(AssetModel)
            .where(
                AssetModel.asset_id == asset_id,
                AssetModel.observed_at <= at,
                AssetModel.valid_from <= at,
                or_(AssetModel.valid_until.is_(None), AssetModel.valid_until > at),
            )
            .order_by(AssetModel.version.desc())
            .limit(1)
        )
        return None if model is None else self._asset(model)

    def list_assets(self, cutoff: datetime) -> list[Asset]:
        asset_ids = self.session.scalars(select(AssetModel.asset_id).distinct())
        return [
            asset
            for asset_id in sorted(asset_ids)
            if (asset := self.get_asset_at(asset_id, cutoff)) is not None
        ]

    def add_corporate_action(self, item: CorporateAction) -> bool:
        if self.session.get(CorporateActionModel, item.action_id):
            return False
        if self.get_asset_at(item.asset_id, item.observed_at) is None:
            raise IntegrityViolation("corporate action references unknown asset")
        self.session.add(
            CorporateActionModel(
                action_id=item.action_id,
                asset_id=item.asset_id,
                action_type=item.action_type.value,
                effective_at=item.effective_at,
                announced_at=item.announced_at,
                observed_at=item.observed_at,
                source_id=item.source_id,
                evidence_ids=list(item.evidence_ids),
                value=item.value,
                currency=item.currency,
                old_symbol=item.old_symbol,
                new_symbol=item.new_symbol,
            )
        )
        self.session.flush()
        return True

    def corporate_actions(self, asset_id: str, cutoff: datetime) -> list[CorporateAction]:
        at = require_aware_utc(cutoff, "cutoff")
        return [
            CorporateAction(
                model.asset_id,
                CorporateActionType(model.action_type),
                _utc(model.effective_at),
                None if model.announced_at is None else _utc(model.announced_at),
                _utc(model.observed_at),
                model.source_id,
                tuple(model.evidence_ids),
                model.value,
                model.currency,
                model.old_symbol,
                model.new_symbol,
            )
            for model in self.session.scalars(
                select(CorporateActionModel)
                .where(
                    CorporateActionModel.asset_id == asset_id,
                    CorporateActionModel.observed_at <= at,
                )
                .order_by(CorporateActionModel.effective_at)
            )
        ]

    def add_session(self, item: TradingSession) -> bool:
        if self.session.get(TradingSessionModel, item.session_id):
            return False
        self.session.add(
            TradingSessionModel(
                session_id=item.session_id,
                venue=item.venue,
                session_date=item.session_date,
                opens_at=item.opens_at,
                closes_at=item.closes_at,
                is_trading_day=item.is_trading_day,
                observed_at=item.observed_at,
                source_id=item.source_id,
                parser_version=item.parser_version,
            )
        )
        self.session.flush()
        return True

    def write_observations(
        self,
        observations: tuple[MarketObservation, ...],
        *,
        dataset_version: str,
        created_at: datetime | None = None,
    ) -> tuple[MarketPartition, int, int]:
        if not observations:
            raise IntegrityViolation("cannot write an empty market partition")
        for item in observations:
            if self.get_asset_at(item.asset_id, item.observed_at) is None:
                raise IntegrityViolation(
                    f"market observation references unknown asset {item.asset_id}"
                )
        created = (
            datetime.now(UTC) if created_at is None else require_aware_utc(created_at, "created_at")
        )
        self.root.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix="market-", suffix=".parquet", dir=self.root
        )
        os.close(descriptor)
        temporary = Path(temporary_name)
        try:
            self._write_parquet(temporary, observations)
            body = temporary.read_bytes()
            digest = hashlib.sha256(body).hexdigest()
            relative = Path("sha256") / digest[:2] / digest[2:4] / f"{digest}.parquet"
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(temporary, destination)
            except FileExistsError:
                if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                    raise IntegrityViolation("immutable Parquet path contains mismatched content")
            partition = MarketPartition(
                digest,
                relative.as_posix(),
                len(body),
                len(observations),
                created,
                dataset_version,
            )
        finally:
            temporary.unlink(missing_ok=True)
        existing_partition = self.session.get(MarketPartitionModel, partition.sha256)
        if existing_partition is None:
            self.session.add(
                MarketPartitionModel(
                    sha256=partition.sha256,
                    relative_path=partition.relative_path,
                    size_bytes=partition.size_bytes,
                    row_count=partition.row_count,
                    created_at=partition.created_at,
                    dataset_version=partition.dataset_version,
                )
            )
            self.session.flush()
        inserted = 0
        duplicates = 0
        for item in observations:
            existing = self.session.get(MarketObservationModel, item.observation_id)
            if existing is not None:
                duplicates += 1
                continue
            self.session.add(
                MarketObservationModel(
                    observation_id=item.observation_id,
                    asset_id=item.asset_id,
                    venue=item.venue,
                    observation_type=item.observation_type.value,
                    market_timestamp=item.market_timestamp,
                    observed_at=item.observed_at,
                    source_id=item.source_id,
                    adjustment_status=item.adjustment_status.value,
                    currency=item.currency,
                    parser_version=item.parser_version,
                    provenance=list(item.provenance),
                    partition_sha256=partition.sha256,
                )
            )
            inserted += 1
        self.session.flush()
        return partition, inserted, duplicates

    def get_market_data(
        self,
        asset_id: str,
        start: datetime,
        end: datetime,
        cutoff: datetime,
        *,
        adjustment_status: AdjustmentStatus = AdjustmentStatus.RAW,
    ) -> list[MarketObservation]:
        start_at = require_aware_utc(start, "start")
        end_at = require_aware_utc(end, "end")
        cutoff_at = require_aware_utc(cutoff, "cutoff")
        if end_at < start_at:
            raise IntegrityViolation("market query end precedes start")
        models = tuple(
            self.session.scalars(
                select(MarketObservationModel).where(
                    MarketObservationModel.asset_id == asset_id,
                    MarketObservationModel.market_timestamp >= start_at,
                    MarketObservationModel.market_timestamp <= end_at,
                    MarketObservationModel.observed_at <= cutoff_at,
                    MarketObservationModel.adjustment_status == adjustment_status.value,
                )
            )
        )
        latest: dict[tuple[datetime, str], MarketObservationModel] = {}
        for model in models:
            key = (_utc(model.market_timestamp), model.observation_type)
            if key not in latest or _utc(latest[key].observed_at) < _utc(model.observed_at):
                latest[key] = model
        if not latest:
            return []
        partition_paths = {
            model.partition_sha256: self._partition_path(model.partition_sha256)
            for model in latest.values()
        }
        by_id = self._read_parquet(tuple(partition_paths.values()))
        return [
            by_id[model.observation_id]
            for _, model in sorted(latest.items())
            if model.observation_id in by_id
        ]

    def get_close_visible_at(
        self, asset_id: str, timestamp: datetime, cutoff: datetime
    ) -> MarketObservation | None:
        values = self.get_market_data(asset_id, timestamp, timestamp, cutoff)
        return None if not values else values[-1]

    def get_benchmark_series(
        self, asset_id: str, start: datetime, end: datetime, cutoff: datetime
    ) -> list[MarketObservation]:
        asset = self.get_asset_at(asset_id, cutoff)
        if asset is None or asset.benchmark_asset_id is None:
            raise IntegrityViolation("asset has no visible benchmark")
        return self.get_market_data(asset.benchmark_asset_id, start, end, cutoff)

    def _partition_path(self, sha256: str) -> Path:
        model = self.session.get(MarketPartitionModel, sha256)
        if model is None:
            raise IntegrityViolation("market catalog references unknown partition")
        path = (self.root / model.relative_path).resolve()
        if not path.is_relative_to(self.root) or not path.is_file():
            raise IntegrityViolation("market partition path is missing or escapes root")
        if hashlib.sha256(path.read_bytes()).hexdigest() != sha256:
            raise IntegrityViolation("market partition hash mismatch")
        return path

    @staticmethod
    def _write_parquet(path: Path, observations: tuple[MarketObservation, ...]) -> None:
        connection = duckdb.connect(":memory:")
        try:
            connection.execute(
                """
                CREATE TABLE observations (
                    observation_id VARCHAR, asset_id VARCHAR, venue VARCHAR,
                    observation_type VARCHAR, market_timestamp TIMESTAMPTZ,
                    observed_at TIMESTAMPTZ, source_id VARCHAR,
                    adjustment_status VARCHAR, currency VARCHAR, parser_version VARCHAR,
                    provenance VARCHAR, open VARCHAR, high VARCHAR, low VARCHAR,
                    close VARCHAR, volume VARCHAR, value VARCHAR
                )
                """
            )
            connection.executemany(
                "INSERT INTO observations VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        item.observation_id,
                        item.asset_id,
                        item.venue,
                        item.observation_type.value,
                        item.market_timestamp,
                        item.observed_at,
                        item.source_id,
                        item.adjustment_status.value,
                        item.currency,
                        item.parser_version,
                        "\u001f".join(item.provenance),
                        item.open,
                        item.high,
                        item.low,
                        item.close,
                        item.volume,
                        item.value,
                    )
                    for item in observations
                ],
            )
            escaped = str(path).replace("'", "''")
            connection.execute(
                f"COPY observations TO '{escaped}' (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
        finally:
            connection.close()

    @staticmethod
    def _read_parquet(paths: tuple[Path, ...]) -> dict[str, MarketObservation]:
        connection = duckdb.connect(":memory:")
        try:
            rows = connection.execute(
                f"SELECT {', '.join(_COLUMNS)} FROM read_parquet(?)",
                [[str(path) for path in paths]],
            ).fetchall()
        finally:
            connection.close()
        output: dict[str, MarketObservation] = {}
        for row in rows:
            values = dict(zip(_COLUMNS, row, strict=True))
            item = MarketObservation(
                asset_id=values["asset_id"],
                venue=values["venue"],
                observation_type=ObservationType(values["observation_type"]),
                market_timestamp=_utc(values["market_timestamp"]),
                observed_at=_utc(values["observed_at"]),
                source_id=values["source_id"],
                adjustment_status=AdjustmentStatus(values["adjustment_status"]),
                currency=values["currency"],
                parser_version=values["parser_version"],
                provenance=tuple(values["provenance"].split("\u001f")),
                open=values["open"],
                high=values["high"],
                low=values["low"],
                close=values["close"],
                volume=values["volume"],
                value=values["value"],
            )
            if item.observation_id == values["observation_id"]:
                output[item.observation_id] = item
        return output

    @staticmethod
    def _asset(model: AssetModel) -> Asset:
        return Asset(
            model.asset_id,
            model.symbol,
            model.venue,
            AssetType(model.asset_type),
            model.currency,
            model.company_id,
            model.entity_id,
            model.benchmark_asset_id,
            _utc(model.valid_from),
            None if model.valid_until is None else _utc(model.valid_until),
            _utc(model.observed_at),
            tuple(model.provenance),
            model.version,
        )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
