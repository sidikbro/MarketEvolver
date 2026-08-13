from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field, is_dataclass
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from market_evolver.errors import GovernanceViolation, ValidationError
from market_evolver.external.pilot import NOT_AVAILABLE, PILOT_METRICS, PilotCostLimit
from market_evolver.external.schemas import UsageAccounting
from market_evolver.provenance import content_id
from market_evolver.time import require_aware_utc


class NativeResultLabel(str):
    NATIVE_ONLY = "NATIVE_ONLY"
    GOVERNED_REFERENCE = "GOVERNED_REFERENCE"
    SINGLE_RUN_INFRASTRUCTURE_VALIDATION = "SINGLE_RUN_INFRASTRUCTURE_VALIDATION"
    NON_EQUIVALENT = "NON_EQUIVALENT"
    BLOCKED = "BLOCKED"
    FAILED_EXTERNAL = "FAILED_EXTERNAL"


V031_NATIVE_COST_LIMIT = PilotCostLimit(100, 250_000, 100_000, "0.25", 900)


@dataclass(frozen=True, slots=True)
class ConsumedInput:
    path: str
    size: int
    sha256: str
    modified_at: datetime
    asset: str | None
    date_range: str | None
    category: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "modified_at", require_aware_utc(self.modified_at, "modified_at")
        )
        if self.size < 0 or not re.fullmatch(r"[0-9a-f]{64}", self.sha256):
            raise ValidationError("consumed inputs require size and SHA-256")
        if not self.path or not self.category:
            raise ValidationError("consumed input path and category are required")


@dataclass(frozen=True, slots=True)
class ConsumedCacheManifest:
    benchmark_id: str
    files: tuple[ConsumedInput, ...]
    historical_vintage_proof: bool = False
    manifest_id: str = field(init=False)

    def __post_init__(self) -> None:
        if self.historical_vintage_proof:
            raise ValidationError("retrospective cache manifests cannot assert causal vintage")
        if not self.benchmark_id:
            raise ValidationError("cache manifest requires benchmark ID")
        object.__setattr__(self, "manifest_id", content_id("consumed-cache-manifest", self))


@dataclass(frozen=True, slots=True)
class DynamicInputObservation:
    domain: str
    requested_at: datetime
    ticker: str
    requested_range: str
    response_sha256: str
    response_size: int
    category: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "requested_at", require_aware_utc(self.requested_at, "requested_at")
        )
        if "/" in self.domain or ":" in self.domain:
            raise ValidationError("dynamic input domain must be a bare hostname")
        if self.response_size < 0 or not re.fullmatch(r"[0-9a-f]{64}", self.response_sha256):
            raise ValidationError("dynamic input response metadata is invalid")
        if not all((self.domain, self.ticker, self.requested_range, self.category)):
            raise ValidationError("dynamic input observation is incomplete")


@dataclass(frozen=True, slots=True)
class NativeRunEnvelope:
    benchmark_id: str
    result_label: str
    external_sha: str
    market_evolver_sha: str
    provider: str
    model: str
    started_at: datetime
    finished_at: datetime
    environment_hash: str
    input_hashes: tuple[str, ...]
    network_domains: tuple[str, ...]
    agent_configuration: tuple[tuple[str, str], ...]
    decision: str
    financial_metrics: tuple[tuple[str, float | str], ...]
    log_hashes: tuple[str, ...]
    usage: UsageAccounting
    active_agents: int
    tool_calls: int
    failures: tuple[str, ...]
    envelope_id: str = field(init=False)

    def __post_init__(self) -> None:
        started = require_aware_utc(self.started_at, "started_at")
        finished = require_aware_utc(self.finished_at, "finished_at")
        object.__setattr__(self, "started_at", started)
        object.__setattr__(self, "finished_at", finished)
        allowed = {
            NativeResultLabel.NATIVE_ONLY,
            NativeResultLabel.GOVERNED_REFERENCE,
            NativeResultLabel.SINGLE_RUN_INFRASTRUCTURE_VALIDATION,
            NativeResultLabel.NON_EQUIVALENT,
            NativeResultLabel.BLOCKED,
            NativeResultLabel.FAILED_EXTERNAL,
        }
        if self.result_label not in allowed or finished < started:
            raise ValidationError("invalid native run result or time envelope")
        if min(self.active_agents, self.tool_calls) < 0:
            raise ValidationError("native run complexity cannot be negative")
        metric_names = {name for name, _ in self.financial_metrics}
        if metric_names != set(PILOT_METRICS):
            raise ValidationError("native run metrics must explicitly include every metric")
        if any("winner" == name.lower() for name, _ in self.agent_configuration):
            raise ValidationError("native run envelopes must not contain a winner field")
        object.__setattr__(self, "envelope_id", content_id("native-run-envelope", self))


def consumed_cache_manifest(
    benchmark_id: str, cache_root: Path, consumed_paths: tuple[Path, ...]
) -> ConsumedCacheManifest:
    root = cache_root.resolve()
    records = []
    for supplied in sorted({path.resolve() for path in consumed_paths}, key=str):
        if not supplied.is_file() or not supplied.is_relative_to(root):
            raise GovernanceViolation("consumed cache input must be a file beneath cache root")
        relative = supplied.relative_to(root).as_posix()
        stat = supplied.stat()
        records.append(
            ConsumedInput(
                relative,
                stat.st_size,
                hashlib.sha256(supplied.read_bytes()).hexdigest(),
                datetime.fromtimestamp(stat.st_mtime).astimezone(),
                _infer_asset(relative),
                _infer_date_range(relative),
                _infer_category(relative),
            )
        )
    return ConsumedCacheManifest(benchmark_id, tuple(records))


def observe_dynamic_input(
    url: str,
    *,
    requested_at: datetime,
    ticker: str,
    requested_range: str,
    response: bytes,
    category: str,
    allowed_domains: tuple[str, ...],
) -> DynamicInputObservation:
    domain = (urlsplit(url).hostname or "").lower()
    if domain not in allowed_domains:
        raise GovernanceViolation(f"unexpected external domain: {domain or 'missing'}")
    return DynamicInputObservation(
        domain,
        requested_at,
        ticker,
        requested_range,
        hashlib.sha256(response).hexdigest(),
        len(response),
        category,
    )


def enforce_native_cost_limit(limit: PilotCostLimit, usage: UsageAccounting) -> None:
    checks = (
        (usage.calls, limit.maximum_calls, "calls"),
        (usage.input_tokens, limit.maximum_input_tokens, "input tokens"),
        (usage.output_tokens, limit.maximum_output_tokens, "output tokens"),
    )
    for actual, maximum, name in checks:
        if actual > maximum:
            raise GovernanceViolation(f"native cost guard rejected {name}")
    if usage.estimated_cost is None:
        raise GovernanceViolation("native cost guard requires priced usage")
    from decimal import Decimal

    if Decimal(usage.estimated_cost) > Decimal(limit.maximum_estimated_cost):
        raise GovernanceViolation("native cost guard rejected estimated cost")


def native_run_label(completed_runs: int, requested_runs: int = 3) -> str:
    if completed_runs < 0 or requested_runs < 1 or completed_runs > requested_runs:
        raise ValidationError("invalid native repeat counts")
    if completed_runs == 1 and requested_runs > 1:
        return NativeResultLabel.SINGLE_RUN_INFRASTRUCTURE_VALIDATION
    if completed_runs == 0:
        return NativeResultLabel.BLOCKED
    return NativeResultLabel.NATIVE_ONLY


def explicit_metrics(values: dict[str, float]) -> tuple[tuple[str, float | str], ...]:
    unknown = set(values) - set(PILOT_METRICS)
    if unknown:
        raise ValidationError(f"unknown native metrics: {sorted(unknown)}")
    return tuple((name, float(values[name]) if name in values else NOT_AVAILABLE) for name in PILOT_METRICS)


def write_manifest(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(value) if is_dataclass(value) and not isinstance(value, type) else value
    path.write_text(json.dumps(payload, default=str, sort_keys=True, indent=2) + "\n", encoding="utf-8")


def _infer_asset(path: str) -> str | None:
    match = re.search(r"(?:^|[/_.-])([A-Z]{1,5})(?:[/_.-]|$)", path)
    return match.group(1) if match else None


def _infer_date_range(path: str) -> str | None:
    dates = re.findall(r"20\d{2}[-_]\d{2}[-_]\d{2}", path)
    normalized = tuple(item.replace("_", "-") for item in dates)
    return "/".join((normalized[0], normalized[-1])) if normalized else None


def _infer_category(path: str) -> str:
    lowered = path.lower()
    for category in ("news", "financials", "fundamentals", "corporate_actions", "stock_indicators", "prices", "ohlcv"):
        if category in lowered:
            return category
    return "unknown"
