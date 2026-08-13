import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from market_evolver.errors import GovernanceViolation, ValidationError
from market_evolver.external.bringup import (
    MINIMAL_LIVE_COST_LIMIT,
    benchmark_decisions,
    enforce_cost_limit,
    network_manifests,
    readiness_matrix,
    stockbench_dataset_audit,
    verify_external_integrity,
)
from market_evolver.external.schemas import (
    BenchmarkDecision,
    DatasetClassification,
    EnvironmentSetupManifest,
    ProviderCostLimit,
    ReadinessState,
    UsageAccounting,
)

HASH = "a" * 64
SHA = "b" * 40


@pytest.mark.unit
def test_environment_manifest_requires_dependency_and_freeze_hashes() -> None:
    manifest = EnvironmentSetupManifest(
        "stockbench",
        SHA,
        "Python 3.12.13",
        HASH,
        "requirements.txt",
        HASH,
        "Linux-test",
        datetime(2026, 8, 13, tzinfo=UTC),
        ("pip", "install", "-r", "requirements.txt"),
        True,
        "imports pass; CLI blocked by native dependency resolution",
    )
    assert manifest.manifest_id and manifest.install_succeeded
    with pytest.raises(ValidationError, match="SHA-256"):
        EnvironmentSetupManifest(
            "stockbench",
            SHA,
            "3.12",
            "bad",
            "requirements.txt",
            HASH,
            "Linux",
            datetime(2026, 8, 13, tzinfo=UTC),
            ("pip",),
            True,
            "pass",
        )


@pytest.mark.unit
def test_dirty_repository_is_rejected(monkeypatch, tmp_path: Path) -> None:
    values = iter((SHA, "https://example.test/repo.git", "dirty"))
    monkeypatch.setitem(
        __import__(
            "market_evolver.external.bringup", fromlist=["EXPECTED_REPOSITORIES"]
        ).EXPECTED_REPOSITORIES,
        "fixture",
        ("Fixture", SHA, "https://example.test/repo.git"),
    )
    monkeypatch.setattr("market_evolver.external.bringup._git", lambda *args: next(values))
    with pytest.raises(GovernanceViolation, match="integrity"):
        verify_external_integrity("fixture", tmp_path)


@pytest.mark.unit
def test_dataset_audit_is_noncausal_without_retrieval_proof(tmp_path: Path) -> None:
    indicator = tmp_path / "stock_indicators"
    indicator.mkdir()
    (indicator / "AAPL_2025-04-03.json").write_text('{"date":"2025-04-03"}')
    news = tmp_path / "news"
    news.mkdir()
    (news / "one.json").write_text(
        '{"items":[{"published_utc":"2025-04-02T10:00:00Z","api_source":"finnhub"}]}'
    )
    audit = stockbench_dataset_audit(tmp_path)
    assert audit.classification is DatasetClassification.PARTIALLY_REPRODUCIBLE
    assert audit.assets == ("AAPL",) and not audit.information_timestamps
    assert "published_utc" in audit.provenance_metadata


@pytest.mark.unit
def test_network_domains_are_explicit_and_never_broad() -> None:
    manifests = network_manifests()
    assert {item.benchmark_id for item in manifests} == {
        "marketevolver",
        "stockbench",
        "tradingagents",
    }
    assert all(not item.broad_network_allowed for item in manifests)
    assert "api.deepseek.com" in manifests[0].domains


@pytest.mark.unit
def test_cost_guard_fails_closed() -> None:
    assert MINIMAL_LIVE_COST_LIMIT.maximum_estimated_cost == "0.01"
    limit = ProviderCostLimit(2, 100, 50, "0.01")
    used = UsageAccounting(50, 10, 1, 100, "0.003")
    enforce_cost_limit(limit, used, UsageAccounting(40, 20, 1, 100, "0.004"))
    with pytest.raises(GovernanceViolation, match="calls"):
        enforce_cost_limit(limit, used, UsageAccounting(40, 20, 2, 100, "0.004"))
    with pytest.raises(GovernanceViolation, match="priced"):
        enforce_cost_limit(limit, used, UsageAccounting(1, 1, 1, 1, None))


@pytest.mark.unit
def test_readiness_matrix_and_blocked_decisions() -> None:
    matrix = {item.dimension: item for item in readiness_matrix(False)}
    assert matrix["Provider"].market_evolver is ReadinessState.BLOCKED
    assert matrix["Model"].stockbench is ReadinessState.MISMATCH
    assert matrix["Point-in-time evidence"].tradingagents is ReadinessState.BLOCKED
    assert benchmark_decisions(False) == (
        ("marketevolver-vs-stockbench", BenchmarkDecision.BLOCKED_PROVIDER),
        ("marketevolver-vs-tradingagents", BenchmarkDecision.BLOCKED_PROVIDER),
    )


@pytest.mark.unit
def test_recorded_environment_freeze_hashes_match() -> None:
    root = Path(__file__).parents[1]
    manifest = json.loads(
        (root / "config/external/v029-environments.json").read_text(encoding="utf-8")
    )
    for item in manifest["environments"]:
        path = root / f"config/external/{item['benchmark_id']}-v029.freeze.txt"
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["pip_freeze_sha256"]
