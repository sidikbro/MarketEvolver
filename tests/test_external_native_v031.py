from datetime import UTC, datetime

import pytest

from market_evolver.errors import GovernanceViolation
from market_evolver.external.native import (
    V031_NATIVE_COST_LIMIT,
    NativeResultLabel,
    consumed_cache_manifest,
    enforce_native_cost_limit,
    explicit_metrics,
    native_run_label,
    observe_dynamic_input,
)
from market_evolver.external.pilot import NOT_AVAILABLE
from market_evolver.external.schemas import UsageAccounting


@pytest.mark.unit
def test_consumed_cache_manifest_is_retrospective_and_exact(tmp_path) -> None:
    cached = tmp_path / "news" / "AAPL_2025-04-01.json"
    cached.parent.mkdir()
    cached.write_bytes(b'{"headline":"fixture"}')
    result = consumed_cache_manifest("stockbench", tmp_path, (cached,))
    assert result.historical_vintage_proof is False
    assert len(result.files) == 1
    assert result.files[0].path == "news/AAPL_2025-04-01.json"
    assert result.files[0].asset == "AAPL"
    assert result.files[0].date_range == "2025-04-01/2025-04-01"
    assert result.files[0].category == "news"
    assert len(result.files[0].sha256) == 64


@pytest.mark.unit
def test_consumed_cache_manifest_rejects_files_outside_root(tmp_path) -> None:
    outside = tmp_path.parent / "outside-v031"
    outside.write_bytes(b"fixture")
    try:
        with pytest.raises(GovernanceViolation, match="beneath cache root"):
            consumed_cache_manifest("stockbench", tmp_path, (outside,))
    finally:
        outside.unlink()


@pytest.mark.unit
def test_dynamic_input_and_network_domain_capture() -> None:
    result = observe_dynamic_input(
        "https://query1.finance.yahoo.com/v8/chart/AAPL?token=secret",
        requested_at=datetime(2026, 8, 13, tzinfo=UTC),
        ticker="AAPL",
        requested_range="2025-04-01/2025-04-03",
        response=b"response fixture",
        category="market_prices",
        allowed_domains=("query1.finance.yahoo.com",),
    )
    assert result.domain == "query1.finance.yahoo.com"
    assert result.response_size == 16
    assert "secret" not in repr(result)
    with pytest.raises(GovernanceViolation, match="unexpected external domain"):
        observe_dynamic_input(
            "https://unexpected.example/data",
            requested_at=datetime(2026, 8, 13, tzinfo=UTC),
            ticker="AAPL",
            requested_range="one-day",
            response=b"x",
            category="news",
            allowed_domains=("query1.finance.yahoo.com",),
        )


@pytest.mark.unit
def test_native_cost_guards_and_single_run_label() -> None:
    enforce_native_cost_limit(
        V031_NATIVE_COST_LIMIT, UsageAccounting(10, 5, 1, 20, "0.0001")
    )
    with pytest.raises(GovernanceViolation, match="calls"):
        enforce_native_cost_limit(
            V031_NATIVE_COST_LIMIT, UsageAccounting(10, 5, 101, 20, "0.01")
        )
    assert native_run_label(1) == NativeResultLabel.SINGLE_RUN_INFRASTRUCTURE_VALIDATION
    assert native_run_label(3) == NativeResultLabel.NATIVE_ONLY


@pytest.mark.unit
def test_native_metrics_use_not_available_and_no_winner() -> None:
    metrics = dict(explicit_metrics({"cumulative_return": 0.0}))
    assert metrics["cumulative_return"] == 0.0
    assert metrics["benchmark_return"] == NOT_AVAILABLE
    assert "winner" not in metrics
