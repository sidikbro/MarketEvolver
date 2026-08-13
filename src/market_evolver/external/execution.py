from __future__ import annotations

import hashlib
import os
import statistics
from dataclasses import dataclass
from pathlib import Path

from market_evolver.external.comparison import ComparisonAssessment, assess_comparison
from market_evolver.external.inspection import inspect_repository
from market_evolver.external.provider import DEEPSEEK_PROFILE, usage_accounting
from market_evolver.external.schemas import (
    Comparability,
    ExecutionStatus,
    ExternalEnvironmentManifest,
    FairComparisonManifest,
    RepeatedRunSummary,
    UsageAccounting,
)


@dataclass(frozen=True, slots=True)
class FairnessAudit:
    classification: Comparability
    mismatches: tuple[str, ...]
    checks: tuple[tuple[str, bool], ...]


def fairness_audit(left: FairComparisonManifest, right: FairComparisonManifest) -> FairnessAudit:
    assessment: ComparisonAssessment = assess_comparison(left, right)
    differences = (*assessment.critical_differences, *assessment.model_differences)
    names = (
        "information_set",
        "asset_universe",
        "execution_timing",
        "transaction_costs",
        "initial_capital",
        "model_provider",
        "number_of_agent_calls",
    )
    return FairnessAudit(
        assessment.classification,
        differences,
        tuple((name, getattr(left, name) == getattr(right, name)) for name in names),
    )


def aggregate_repeats(
    metric_name: str,
    values: tuple[float, ...],
    requested: int,
    usage: tuple[UsageAccounting, ...],
    blocked_status: ExecutionStatus | None = None,
) -> RepeatedRunSummary:
    totals = UsageAccounting(
        sum(item.input_tokens for item in usage),
        sum(item.output_tokens for item in usage),
        sum(item.calls for item in usage),
        sum(item.latency_ms for item in usage),
        None,
    )
    status = blocked_status or (
        ExecutionStatus.PASS if len(values) == requested else ExecutionStatus.FAILED_EXTERNAL
    )
    return RepeatedRunSummary(
        status,
        requested,
        len(values),
        metric_name,
        statistics.fmean(values) if values else None,
        statistics.pvariance(values) if values else None,
        totals,
    )


def prepare_environment(benchmark_id: str, project_root: Path) -> ExternalEnvironmentManifest:
    repository = inspect_repository(benchmark_id, project_root)
    sibling = (
        project_root / f"../{'StockBench' if benchmark_id == 'stockbench' else 'TradingAgents'}"
    ).resolve()
    required_datasets: tuple[str, ...]
    expected: tuple[str, ...]
    dataset_paths: tuple[Path, ...]
    command: tuple[str, ...]
    outputs: tuple[str, ...]
    runtime: tuple[str, ...]
    if benchmark_id == "stockbench":
        requirements = sibling / "requirements.txt"
        config = sibling / "config.yaml"
        required_datasets = (
            "Polygon adjusted daily bars for selected asset/period",
            "Finnhub point-in-time news and fundamentals for selected asset/period",
        )
        expected = ("POLYGON_API_KEY", "FINNHUB_API_KEY", "DEEPSEEK_API_KEY")
        dataset_paths = (sibling / "storage/dataset-manifest.json",)
        command = (
            "python",
            "-m",
            "stockbench.apps.run_backtest",
            "--cfg",
            "config.yaml",
            "--start",
            "<start>",
            "--end",
            "<end>",
            "--llm-profile",
            "deepseek-v3.1",
        )
        outputs = ("storage/reports/backtest", "storage/logs")
        runtime = ("Python 3.10+", "provider access", "licensed/cached source data")
    else:
        requirements = sibling / "requirements.txt"
        config = sibling / "pyproject.toml"
        required_datasets = (
            "historical OHLCV visible at analysis cutoff",
            "historical news/fundamentals visible at analysis cutoff",
        )
        expected = ("DEEPSEEK_API_KEY",)
        dataset_paths = (sibling / "data/dataset-manifest.json",)
        command = ("tradingagents", "analyze", "--ticker", "<asset>", "--date", "<date>")
        outputs = ("decision", "portfolio path", "decision log", "reported metrics")
        runtime = ("Python 3.10+", "provider access", "market/news data access")
    missing = () if all(path.is_file() for path in dataset_paths) else required_datasets
    present = tuple(name for name in expected if os.environ.get(name))
    if "DEEPSEEK_API_KEY" not in present:
        status = ExecutionStatus.BLOCKED_PROVIDER
    elif missing:
        status = ExecutionStatus.BLOCKED_DATASET
    else:
        status = ExecutionStatus.PASS
    return ExternalEnvironmentManifest(
        benchmark_id,
        repository.manifest_id,
        DEEPSEEK_PROFILE.profile_id,
        repository.python_version,
        _sha(requirements),
        required_datasets,
        missing,
        expected,
        present,
        _sha(config),
        command,
        outputs,
        runtime,
        None,
        False,
        status,
    )


def empty_blocked_repeats(status: ExecutionStatus) -> RepeatedRunSummary:
    return aggregate_repeats(
        "cumulative_return", (), 3, (usage_accounting(0, 0, 0, 0, DEEPSEEK_PROFILE),), status
    )


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()
