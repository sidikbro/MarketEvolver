from __future__ import annotations

import hashlib
import json
import platform
import subprocess
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from market_evolver.errors import GovernanceViolation, IntegrityViolation
from market_evolver.external.schemas import (
    BenchmarkDecision,
    DatasetAudit,
    DatasetClassification,
    EnvironmentSetupManifest,
    NetworkDomainManifest,
    ProviderCostLimit,
    ReadinessRow,
    ReadinessState,
    UsageAccounting,
)

EXPECTED_REPOSITORIES = {
    "stockbench": (
        "StockBench",
        "ce8b2b3483590646ad3b650ac8221f43f76fd091",
        "https://github.com/ChenYXxxx/stockbench.git",
    ),
    "tradingagents": (
        "TradingAgents",
        "a33fd4c0f134485a43553a2c23a63cb14adbd88f",
        "https://github.com/tauricresearch/tradingagents.git",
    ),
}

MINIMAL_LIVE_COST_LIMIT = ProviderCostLimit(2, 1_024, 512, "0.01")


def verify_external_integrity(benchmark_id: str, project_root: Path) -> Path:
    directory, expected_sha, expected_remote = EXPECTED_REPOSITORIES[benchmark_id]
    path = (project_root / ".." / directory).resolve()
    sha = _git(path, "rev-parse", "HEAD")
    remote = _git(path, "remote", "get-url", "origin")
    dirty = _git(path, "status", "--porcelain")
    if sha != expected_sha or remote != expected_remote or dirty:
        raise GovernanceViolation("external repository integrity gate failed")
    return path


def environment_manifest(
    benchmark_id: str,
    project_root: Path,
    interpreter: Path,
    *,
    setup_at: datetime,
    install_succeeded: bool,
    smoke_outcome: str,
) -> EnvironmentSetupManifest:
    repository = verify_external_integrity(benchmark_id, project_root)
    dependency = repository / (
        "requirements.txt" if benchmark_id == "stockbench" else "pyproject.toml"
    )
    freeze = subprocess.run(
        (str(interpreter), "-m", "pip", "freeze", "--all"),
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    ).stdout
    python_version = subprocess.run(
        (str(interpreter), "--version"), check=True, capture_output=True, text=True, timeout=10
    ).stdout.strip()
    command = (
        ("pip", "install", "-r", "requirements.txt")
        if benchmark_id == "stockbench"
        else ("pip", "install", ".[dev]")
    )
    return EnvironmentSetupManifest(
        benchmark_id,
        EXPECTED_REPOSITORIES[benchmark_id][1],
        python_version,
        hashlib.sha256(freeze.encode()).hexdigest(),
        dependency.name,
        hashlib.sha256(dependency.read_bytes()).hexdigest(),
        platform.platform(),
        setup_at,
        command,
        install_succeeded,
        smoke_outcome,
    )


def stockbench_dataset_audit(cache_root: Path) -> DatasetAudit:
    files = tuple(path for path in cache_root.rglob("*") if path.is_file())
    asset_dates: list[tuple[str, str]] = []
    schemas: set[str] = set()
    assets: set[str] = set()
    provenance: set[str] = set()
    for path in files:
        relative = path.relative_to(cache_root)
        schemas.add(relative.parts[0])
        if relative.parts[0] in {"stock_indicators", "news_by_day"}:
            name = path.stem
            if "_" in name:
                asset, date = name.rsplit("_", 1)
                if len(date) == 10:
                    assets.add(asset)
                    asset_dates.append((asset, date))
        if relative.parts[0] in {"financials", "corporate_actions"}:
            assets.add(path.name.split(".", 1)[0])
    for path in files:
        if path.suffix != ".json":
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            continue
        text = json.dumps(document)
        for field in (
            "published_utc",
            "api_source",
            "data_source",
            "cached_at",
            "start_date",
            "end_date",
        ):
            if f'"{field}"' in text:
                provenance.add(field)
    dates = sorted(date for _, date in asset_dates)
    return DatasetAudit(
        "stockbench",
        DatasetClassification.PARTIALLY_REPRODUCIBLE
        if files
        else DatasetClassification.BLOCKED_DATASET,
        len(files),
        tuple(sorted(assets)),
        dates[0] if dates else None,
        dates[-1] if dates else None,
        tuple(sorted(schemas)),
        tuple(sorted(provenance)),
        False,
        (
            "cache has no immutable retrieval manifest or content-hash catalog",
            "publication times do not prove first observation or historical API visibility",
            "fundamental filing availability and revision history are absent",
            "adjusted indicators do not retain auditable raw price observations",
        ),
    )


def network_manifests() -> tuple[NetworkDomainManifest, ...]:
    return (
        NetworkDomainManifest(
            "marketevolver",
            ("api.deepseek.com",),
            ("DEEPSEEK_API_KEY",),
            ("bounded structured model response",),
        ),
        NetworkDomainManifest(
            "stockbench",
            ("api.deepseek.com", "api.finnhub.io", "api.polygon.io"),
            ("DEEPSEEK_API_KEY", "FINNHUB_API_KEY", "POLYGON_API_KEY"),
            ("model response", "news", "fundamentals", "market bars", "corporate actions"),
        ),
        NetworkDomainManifest(
            "tradingagents",
            (
                "api.deepseek.com",
                "query1.finance.yahoo.com",
                "query2.finance.yahoo.com",
                "fc.yahoo.com",
                "www.alphavantage.co",
                "api.stlouisfed.org",
                "gamma-api.polymarket.com",
                "api.stocktwits.com",
                "www.reddit.com",
            ),
            ("DEEPSEEK_API_KEY", "ALPHA_VANTAGE_API_KEY", "FRED_API_KEY"),
            (
                "model response",
                "prices",
                "fundamentals",
                "news",
                "macro",
                "prediction markets",
                "sentiment",
            ),
        ),
    )


def enforce_cost_limit(
    limit: ProviderCostLimit, used: UsageAccounting, proposed: UsageAccounting
) -> None:
    values = (
        (used.calls + proposed.calls, limit.maximum_calls, "calls"),
        (used.input_tokens + proposed.input_tokens, limit.maximum_input_tokens, "input tokens"),
        (used.output_tokens + proposed.output_tokens, limit.maximum_output_tokens, "output tokens"),
    )
    for actual, maximum, label in values:
        if actual > maximum:
            raise GovernanceViolation(f"provider cost guard rejected {label}")
    costs = (used.estimated_cost, proposed.estimated_cost)
    if any(value is None for value in costs):
        raise GovernanceViolation("provider cost guard requires priced usage")
    if sum(Decimal(value) for value in costs if value is not None) > Decimal(
        limit.maximum_estimated_cost
    ):
        raise GovernanceViolation("provider cost guard rejected estimated cost")


def readiness_matrix(provider_available: bool) -> tuple[ReadinessRow, ...]:
    ready = ReadinessState.READY
    blocked = ReadinessState.BLOCKED
    mismatch = ReadinessState.MISMATCH
    unknown = ReadinessState.UNKNOWN
    provider = ready if provider_available else blocked
    return (
        ReadinessRow("Provider", provider, provider, provider, "DeepSeek credential is shared"),
        ReadinessRow(
            "Model", ready, mismatch, ready, "StockBench pins retired deepseek-v3.1 profile"
        ),
        ReadinessRow("Asset universe", ready, ready, ready, "AAPL common case is supported"),
        ReadinessRow(
            "Historical period", ready, ready, unknown, "TradingAgents coverage is dynamic"
        ),
        ReadinessRow("Market data", ready, mismatch, unknown, "native datasets differ"),
        ReadinessRow("News", ready, mismatch, unknown, "vintage proof is not equivalent"),
        ReadinessRow("Fundamentals", ready, mismatch, unknown, "filing availability differs"),
        ReadinessRow("Costs", ready, unknown, unknown, "external native costs are not fixed"),
        ReadinessRow(
            "Execution timing", ready, mismatch, mismatch, "decision/fill contracts differ"
        ),
        ReadinessRow("Capital", ready, ready, unknown, "TradingAgents has no fixed capital"),
        ReadinessRow("Anonymization", ready, blocked, blocked, "external baselines lack masking"),
        ReadinessRow(
            "Point-in-time evidence", ready, blocked, blocked, "native proof is insufficient"
        ),
    )


def benchmark_decisions(provider_available: bool) -> tuple[tuple[str, BenchmarkDecision], ...]:
    if not provider_available:
        return (
            ("marketevolver-vs-stockbench", BenchmarkDecision.BLOCKED_PROVIDER),
            ("marketevolver-vs-tradingagents", BenchmarkDecision.BLOCKED_PROVIDER),
        )
    return (
        ("marketevolver-vs-stockbench", BenchmarkDecision.BLOCKED_DEPENDENCY),
        ("marketevolver-vs-tradingagents", BenchmarkDecision.BLOCKED_DATASET),
    )


def _git(path: Path, *args: str) -> str:
    try:
        return subprocess.run(
            ("git", "-C", str(path), *args),
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError) as exc:
        raise IntegrityViolation("external Git inspection failed") from exc
