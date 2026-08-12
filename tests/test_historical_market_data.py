from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from market_evolver.errors import IntegrityViolation, ValidationError
from market_evolver.market.history import (
    BoiUsdIlsHistoryConnector,
    CompositionHistoryStatus,
    DatasetType,
    HistoricalBar,
    HistoricalCorporateAction,
    HistoricalDataset,
    HistoricalDatasetStore,
    HistoricalReplayEligibility,
    PriceAdjustmentPolicy,
    SourceClass,
    StooqDailyConnector,
    SurvivorshipStatus,
    compare_sources,
    measure_dataset,
    plumbing_baselines,
    storage_projections,
    validate_quality,
)

pytestmark = pytest.mark.integration
T0 = datetime(2025, 1, 10, tzinfo=UTC)


def bar(
    day: int,
    close: str,
    *,
    instrument: str = "asset.arcx.spy",
    currency: str = "USD",
    volume: str = "100",
    adjusted: str | None = None,
    source: str = "fixture.market",
) -> HistoricalBar:
    market_day = date(2025, 1, day)
    value = float(close)
    return HistoricalBar(
        instrument,
        "ARCX" if currency == "USD" else "BOI",
        market_day,
        datetime(2025, 1, day, 21, tzinfo=UTC),
        None,
        T0 + timedelta(days=day),
        currency,
        f"{value - 1:g}",
        f"{value + 1:g}",
        f"{value - 2:g}",
        close,
        volume,
        adjusted,
        None if adjusted is None else str(float(adjusted) / value),
        source,
        "sha256:" + "a" * 64,
        "fixture/1",
    )


def test_raw_adjusted_parquet_reproducibility_and_manifest(tmp_path: Path) -> None:
    store = HistoricalDatasetStore(tmp_path)
    bars = (bar(2, "100", adjusted="50"), bar(3, "102", adjusted="51"))
    paths, hashes, parquet_bytes = store.write_bars(bars, source_id="fixture", venue="ARCX")
    repeated_paths, repeated_hashes, _ = store.write_bars(
        tuple(reversed(bars)), source_id="fixture", venue="ARCX"
    )
    assert hashes == repeated_hashes and paths == repeated_paths
    assert store.read_bars(paths) == bars
    assert store.read_bars(paths)[0].raw_close == "100"
    assert store.read_bars(paths)[0].adjusted_close == "50"
    dataset = HistoricalDataset(
        "fixture",
        SourceClass.RESEARCH_QUALITY_PUBLIC,
        DatasetType.EQUITY_OHLCV,
        ("asset.arcx.spy",),
        "ARCX",
        "1d",
        date(2025, 1, 2),
        date(2025, 1, 3),
        T0,
        T0,
        ("sha256:" + "a" * 64,),
        ("sha256:" + "b" * 64,),
        hashes,
        tuple(path.relative_to(store.root / "parquet").as_posix() for path in paths),
        2,
        "America/New_York",
        PriceAdjustmentPolicy.RAW_AND_ADJUSTED_SEPARATE,
        "explicit actions only",
        SurvivorshipStatus.CURRENT_CONSTITUENTS_ONLY,
        CompositionHistoryStatus.UNAVAILABLE,
        "fixture/1",
        "historical-bars/1",
        ("source:fixture",),
        HistoricalReplayEligibility.OUTCOME_MEASUREMENT_ONLY,
        (("from", "2025-01-02"), ("to", "2025-01-03")),
        "sha256:" + "c" * 64,
        "commit:test",
    )
    manifest = store.write_manifest(dataset)
    assert store.write_manifest(dataset) == manifest
    assert parquet_bytes > 0
    assert storage_projections(parquet_bytes, 2)[0]["instruments"] == 18
    telemetry = measure_dataset(
        store,
        paths,
        raw_bytes=1000,
        normalized_bytes=500,
        elapsed_seconds=1,
    )
    assert telemetry.rows == 2 and telemetry.bytes_per_million_rows > 0
    assert set(plumbing_baselines(bars)) == {
        "cash",
        "buy_and_hold",
        "simple_momentum",
        "simple_mean_reversion",
    }


def test_split_dividend_and_composition_caveats() -> None:
    split = HistoricalCorporateAction(
        "asset.arcx.spy", "split", date(2025, 1, 3), "2", None, "fixture", "sha256:" + "a" * 64, T0
    )
    dividend = HistoricalCorporateAction(
        "asset.arcx.spy",
        "dividend",
        date(2025, 1, 4),
        "1.25",
        "USD",
        "fixture",
        "sha256:" + "a" * 64,
        T0,
    )
    assert split.action_id != dividend.action_id
    assert SurvivorshipStatus.CURRENT_CONSTITUENTS_ONLY.value == "current_constituents_only"
    assert CompositionHistoryStatus.UNAVAILABLE.value == "unavailable"


def test_quality_duplicate_missing_extreme_zero_and_currency() -> None:
    bars = (bar(2, "100"), bar(2, "100"), bar(4, "50", volume="0", currency="ILS"))
    report = validate_quality(
        "dataset:test",
        bars,
        expected_sessions=(date(2025, 1, 2), date(2025, 1, 3), date(2025, 1, 4)),
        expected_currency="USD",
    )
    codes = {item.code for item in report.issues}
    assert report.status == "failed"
    assert {
        "DUPLICATE_BAR",
        "MISSING_SESSION",
        "EXTREME_MOVE",
        "ZERO_VOLUME",
        "CURRENCY_MISMATCH",
    } <= codes


def test_impossible_negative_and_naive_bars_fail_closed() -> None:
    with pytest.raises(ValidationError):
        HistoricalBar(
            "asset",
            "ARCX",
            date(2025, 1, 2),
            datetime(2025, 1, 2),  # noqa: DTZ001 - malformed boundary input
            None,
            T0,
            "USD",
            "10",
            "9",
            "8",
            "10",
            "1",
            None,
            None,
            "fixture",
            "sha256:" + "a" * 64,
            "fixture/1",
        )
    with pytest.raises(ValidationError):
        bar(2, "100", volume="-1")


def test_source_disagreement_benchmark_and_fx_joins(tmp_path: Path) -> None:
    left = (bar(2, "100"), bar(3, "101"))
    right = (bar(2, "100", source="other"), bar(3, "102", source="other"))
    assert len(compare_sources(left, right)) == 1
    fx = (
        bar(2, "3.5", instrument="asset.fx.usdils", currency="ILS"),
        bar(3, "3.6", instrument="asset.fx.usdils", currency="ILS"),
    )
    store = HistoricalDatasetStore(tmp_path)
    equity_paths, _, _ = store.write_bars(left, source_id="fixture", venue="ARCX")
    fx_paths, _, _ = store.write_bars(fx, source_id="fixture", venue="BOI")
    assert (
        len(store.aligned_join((*equity_paths, *fx_paths), "asset.arcx.spy", "asset.fx.usdils"))
        == 2
    )


def test_corrupt_parquet_and_immutable_partition_fail_closed(tmp_path: Path) -> None:
    store = HistoricalDatasetStore(tmp_path)
    paths, hashes, _ = store.write_bars((bar(2, "100"),), source_id="fixture", venue="ARCX")
    paths[0].write_bytes(paths[0].read_bytes() + b"corrupt")
    with pytest.raises(IntegrityViolation):
        store.verify_parquet(paths[0], hashes[0])
    with pytest.raises(IntegrityViolation):
        store.write_bars((bar(2, "100"),), source_id="fixture", venue="ARCX")


def test_boi_contract_and_stooq_schema_and_bounds(tmp_path: Path) -> None:
    store = HistoricalDatasetStore(tmp_path)
    boi_payload = (
        b"SERIES_CODE,FREQ,BASE_CURRENCY,COUNTER_CURRENCY,UNIT_MEASURE,DATA_TYPE,DATA_SOURCE,TIME_COLLECT,CONF_STATUS,PUB_WEBSITE,UNIT_MULT,COMMENTS,TIME_PERIOD,OBS_VALUE,RELEASE_STATUS\n"
        b"RER_USD_ILS,D,USD,ILS,ILS,OF00,BOI_MRKT,V,F,Y,0,,2025-01-02,3.618,YP\n"
    )
    artifact = store.persist_raw(boi_payload, "text/csv")
    parsed = BoiUsdIlsHistoryConnector().parse(boi_payload, retrieved_at=T0, artifact=artifact)
    assert parsed[0].raw_close == "3.618" and parsed[0].volume == "0"
    stooq_payload = b"Date,Open,High,Low,Close,Volume\n2025-01-02,100,102,99,101,1000\n"
    stooq_artifact = store.persist_raw(stooq_payload, "text/csv")
    assert (
        len(
            StooqDailyConnector().parse(
                stooq_payload,
                instrument_id="asset.arcx.spy",
                venue="ARCX",
                currency="USD",
                retrieved_at=T0,
                artifact=stooq_artifact,
            )
        )
        == 1
    )
    with pytest.raises(IntegrityViolation):
        StooqDailyConnector().parse(
            b"changed,schema\n",
            instrument_id="asset.arcx.spy",
            venue="ARCX",
            currency="USD",
            retrieved_at=T0,
            artifact=stooq_artifact,
        )
    with pytest.raises(ValidationError):
        StooqDailyConnector().fetch("spy.us", date(2000, 1, 1), date(2025, 1, 1))
