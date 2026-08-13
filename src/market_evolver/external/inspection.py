from __future__ import annotations

import hashlib
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from market_evolver.errors import GovernanceViolation, IntegrityViolation
from market_evolver.external.registry import EXTERNAL_BENCHMARKS
from market_evolver.external.schemas import ExternalRepositoryManifest


@dataclass(frozen=True, slots=True)
class InspectionSummary:
    benchmark_id: str
    architecture: tuple[str, ...]
    observation_schema: tuple[str, ...]
    action_schema: tuple[str, ...]
    timeline: str
    initial_capital: str
    assets: tuple[str, ...]
    inputs: tuple[str, ...]
    costs: str
    metrics: tuple[str, ...]
    contamination_controls: tuple[str, ...]
    limitations: tuple[str, ...]

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def inspect_repository(benchmark_id: str, project_root: Path) -> ExternalRepositoryManifest:
    definition = EXTERNAL_BENCHMARKS.get(benchmark_id)
    if definition.local_path is None or definition.pinned_git_sha is None:
        raise GovernanceViolation("external benchmark has no inspected local pinned checkout")
    path = (project_root / definition.local_path).resolve()
    if not (path / ".git").exists():
        raise IntegrityViolation(f"external sibling repository is absent: {path}")
    sha = _git(path, "rev-parse", "HEAD")
    if sha != definition.pinned_git_sha:
        raise IntegrityViolation("external checkout SHA differs from immutable registry pin")
    remote = _git(path, "remote", "get-url", "origin")
    dirty = bool(_git(path, "status", "--porcelain"))
    dependencies = _combined_hash(path, ("requirements.txt", "pyproject.toml"))
    license_hash = _file_hash(path / "LICENSE")
    config_names = ("config.yaml", "config.yml", "pyproject.toml")
    configs = tuple(
        (name, _file_hash(path / name)) for name in config_names if (path / name).is_file()
    )
    return ExternalRepositoryManifest(
        benchmark_id,
        sha,
        remote,
        dirty,
        f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        dependencies,
        license_hash,
        configs,
        datetime.now(UTC),
    )


def verify_runnable(manifest: ExternalRepositoryManifest) -> None:
    definition = EXTERNAL_BENCHMARKS.get(manifest.benchmark_id)
    if definition.pinned_git_sha != manifest.git_sha:
        raise IntegrityViolation("external repository is not at its pinned SHA")
    if manifest.dirty:
        raise GovernanceViolation("dirty external repository cannot be evaluated")


def inspection_summary(benchmark_id: str) -> InspectionSummary:
    if benchmark_id == "stockbench":
        return InspectionSummary(
            benchmark_id,
            ("portfolio state", "fundamental filter", "decision agent", "simulated execution"),
            ("symbol", "adjusted daily history", "fundamentals", "news", "cash/positions"),
            ("symbol", "direction/action", "quantity/allocation", "rationale"),
            "daily sequential decisions after a 15-day warmup; exact interval is run-configured",
            "USD 100,000 in inspected config",
            (
                "GS",
                "MSFT",
                "HD",
                "V",
                "SHW",
                "CAT",
                "MCD",
                "UNH",
                "AXP",
                "AMGN",
                "TRV",
                "CRM",
                "JPM",
                "IBM",
                "HON",
                "BA",
                "AMZN",
                "AAPL",
                "PG",
                "JNJ",
            ),
            ("adjusted daily bars", "7-day history", "fundamentals", "2-day news", "portfolio"),
            "not established by inspected config; comparison must state it explicitly",
            ("cumulative return", "max drawdown", "Sharpe", "Sortino", "benchmark comparison"),
            ("historical sequential evaluation", "offline cache mode available"),
            (
                "native inputs lack MarketEvolver evidence IDs",
                "historical names/news may be pretrained",
            ),
        )
    if benchmark_id == "tradingagents":
        return InspectionSummary(
            benchmark_id,
            (
                "market/news/social/fundamentals analysts",
                "bull/bear researchers",
                "research manager",
                "trader",
                "aggressive/conservative/neutral risk managers",
                "portfolio manager",
                "persistent decision memory and reflection",
                "provider abstraction",
            ),
            ("ticker", "analysis date", "market", "fundamentals", "news", "sentiment"),
            ("buy/sell/hold decision", "structured manager/trader outputs"),
            "single-date analysis and optional backtest workflow; operator-configured",
            "not fixed by the framework inspection",
            ("provider-supported ticker",),
            ("market", "fundamentals", "news", "sentiment", "prior decision memory"),
            "must be supplied by the comparison run",
            ("return", "SPY-relative return", "decision history"),
            ("verified data snapshot described upstream",),
            (
                "memory can cross evaluation boundaries",
                "provider data vintages require independent audit",
            ),
        )
    raise GovernanceViolation("placeholder benchmark has no inspection adapter")


def _git(path: Path, *args: str) -> str:
    result = subprocess.run(
        ("git", "-C", str(path), *args),
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return result.stdout.strip()


def _file_hash(path: Path) -> str:
    if not path.is_file():
        raise IntegrityViolation(f"required external manifest file is absent: {path.name}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _combined_hash(path: Path, names: tuple[str, ...]) -> str:
    present = [name for name in names if (path / name).is_file()]
    if not present:
        raise IntegrityViolation("external dependency manifest is absent")
    digest = hashlib.sha256()
    for name in sorted(present):
        digest.update(name.encode())
        digest.update(b"\0")
        digest.update((path / name).read_bytes())
    return digest.hexdigest()
