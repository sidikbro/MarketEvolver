from __future__ import annotations

import statistics
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from market_evolver.errors import GovernanceViolation, ValidationError
from market_evolver.external.schemas import UsageAccounting

NOT_AVAILABLE = "NOT_AVAILABLE"


class ModelCompatibility(str, Enum):
    EXACT_MODEL = "EXACT_MODEL"
    COMPATIBLE_MODEL = "COMPATIBLE_MODEL"
    MODEL_MISMATCH = "MODEL_MISMATCH"
    BLOCKED = "BLOCKED"


class CompatibilityKind(str, Enum):
    NATIVE = "NATIVE"
    ENVIRONMENT_COMPATIBILITY = "ENVIRONMENT_COMPATIBILITY"
    PATCHED_BASELINE = "PATCHED_BASELINE"
    BLOCKED = "BLOCKED"


class ComparisonLayer(str, Enum):
    NATIVE = "NATIVE"
    CONTROLLED = "CONTROLLED"


class PilotComparability(str, Enum):
    EXACTLY_COMPARABLE = "EXACTLY_COMPARABLE"
    PARTIALLY_COMPARABLE = "PARTIALLY_COMPARABLE"
    NATIVE_ONLY = "NATIVE_ONLY"
    NON_EQUIVALENT = "NON_EQUIVALENT"


class TemporalDataClass(str, Enum):
    POINT_IN_TIME_SAFE = "point_in_time_safe"
    CURRENT_SNAPSHOT = "current_snapshot"
    TEMPORALLY_AMBIGUOUS = "temporally_ambiguous"
    PROVIDER_MANAGED = "provider_managed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class EnvironmentCompatibility:
    benchmark_id: str
    declared_typer: str | None
    resolved_typer: str
    declared_click: str | None
    resolved_click: str
    compatible_click: str | None
    kind: CompatibilityKind
    source_patch: bool
    failing_command: str | None
    failure: str | None

    def __post_init__(self) -> None:
        if self.kind is CompatibilityKind.PATCHED_BASELINE and not self.source_patch:
            raise ValidationError("patched baseline must be labeled")
        if self.source_patch and self.kind is not CompatibilityKind.PATCHED_BASELINE:
            raise ValidationError("source changes require PATCHED_BASELINE")


@dataclass(frozen=True, slots=True)
class TradingInputAudit:
    input_name: str
    implementations: tuple[str, ...]
    temporal_class: TemporalDataClass
    domains: tuple[str, ...]
    credential_variables: tuple[str, ...]
    bundled: bool
    rationale: str


@dataclass(frozen=True, slots=True)
class PilotCostLimit:
    maximum_calls: int
    maximum_input_tokens: int
    maximum_output_tokens: int
    maximum_estimated_cost: str
    maximum_wall_seconds: int

    def __post_init__(self) -> None:
        if (
            min(
                self.maximum_calls,
                self.maximum_input_tokens,
                self.maximum_output_tokens,
                self.maximum_wall_seconds,
            )
            < 1
            or Decimal(self.maximum_estimated_cost) <= 0
        ):
            raise ValidationError("pilot cost limits must be positive")


@dataclass(frozen=True, slots=True)
class ArchitectureComplexity:
    active_agents: int
    calls_per_decision: int
    tool_calls: int
    tokens_per_decision: int | str
    latency_per_decision_ms: int | str

    def __post_init__(self) -> None:
        integers = (self.active_agents, self.calls_per_decision, self.tool_calls)
        if min(integers) < 0:
            raise ValidationError("architecture complexity cannot be negative")
        for value in (self.tokens_per_decision, self.latency_per_decision_ms):
            if value != NOT_AVAILABLE and (not isinstance(value, int) or value < 0):
                raise ValidationError("complexity metrics require non-negative values")


@dataclass(frozen=True, slots=True)
class PilotRepeatSummary:
    individual_results: tuple[float, float, float]
    mean: float
    spread: float


PILOT_COST_LIMIT = PilotCostLimit(12, 24_000, 6_000, "0.25", 900)

PILOT_METRICS = (
    "cumulative_return",
    "benchmark_return",
    "excess_return",
    "max_drawdown",
    "sharpe",
    "sortino",
    "turnover",
    "trades",
    "fees",
    "model_calls",
    "input_tokens",
    "output_tokens",
    "provider_cost",
    "latency_ms",
    "unsupported_claims",
    "provenance_failures",
    "temporal_leakage",
    "reviewer_rejection",
    "capability_violations",
)


def classify_model(
    configured_model: str | None,
    returned_model: str | None,
    reference_model: str | None,
) -> ModelCompatibility:
    if not configured_model or not returned_model or not reference_model:
        return ModelCompatibility.BLOCKED
    if returned_model == reference_model == configured_model:
        return ModelCompatibility.EXACT_MODEL
    if returned_model == reference_model:
        return ModelCompatibility.COMPATIBLE_MODEL
    return ModelCompatibility.MODEL_MISMATCH


def stockbench_click_resolution(
    *, resolved_typer: str, resolved_click: str, source_patch: bool = False
) -> EnvironmentCompatibility:
    if source_patch:
        return EnvironmentCompatibility(
            "stockbench",
            ">=0.9.0,<0.13.0",
            resolved_typer,
            None,
            resolved_click,
            None,
            CompatibilityKind.PATCHED_BASELINE,
            True,
            "python -m stockbench.apps.run_backtest --help",
            "source patch supplied",
        )
    click_parts = tuple(int(part) for part in resolved_click.split(".")[:2])
    incompatible = resolved_typer == "0.12.5" and click_parts >= (8, 2)
    return EnvironmentCompatibility(
        "stockbench",
        ">=0.9.0,<0.13.0",
        resolved_typer,
        None,
        resolved_click,
        "8.1.8" if incompatible else None,
        CompatibilityKind.ENVIRONMENT_COMPATIBILITY if incompatible else CompatibilityKind.NATIVE,
        False,
        "python -m stockbench.apps.run_backtest --help" if incompatible else None,
        "Typer 0.12.5 is incompatible with resolved Click >=8.2" if incompatible else None,
    )


def tradingagents_data_audit() -> tuple[TradingInputAudit, ...]:
    yahoo = ("query1.finance.yahoo.com", "query2.finance.yahoo.com", "fc.yahoo.com")
    return (
        TradingInputAudit(
            "market_prices",
            ("yfinance", "alpha_vantage"),
            TemporalDataClass.PROVIDER_MANAGED,
            (*yahoo, "www.alphavantage.co"),
            ("ALPHA_VANTAGE_API_KEY",),
            False,
            "date-bounded request; retrieval vintage is not preserved",
        ),
        TradingInputAudit(
            "fundamentals",
            ("yfinance", "alpha_vantage"),
            TemporalDataClass.CURRENT_SNAPSHOT,
            (*yahoo, "www.alphavantage.co"),
            ("ALPHA_VANTAGE_API_KEY",),
            False,
            "current vendor statement sets can expose later restatements",
        ),
        TradingInputAudit(
            "news",
            ("yfinance", "alpha_vantage"),
            TemporalDataClass.TEMPORALLY_AMBIGUOUS,
            (*yahoo, "www.alphavantage.co"),
            ("ALPHA_VANTAGE_API_KEY",),
            False,
            "publication time does not prove historical retrieval visibility or edits",
        ),
        TradingInputAudit(
            "sentiment_social",
            ("reddit", "stocktwits"),
            TemporalDataClass.CURRENT_SNAPSHOT,
            ("www.reddit.com", "api.stocktwits.com"),
            (),
            False,
            "public live feeds are fetched during analysis",
        ),
        TradingInputAudit(
            "technical_indicators",
            ("yfinance-derived", "alpha_vantage"),
            TemporalDataClass.PROVIDER_MANAGED,
            (*yahoo, "www.alphavantage.co"),
            ("ALPHA_VANTAGE_API_KEY",),
            False,
            "derived from vendor market history without a retrieval-vintage manifest",
        ),
    )


def enforce_pilot_cost_limit(
    limit: PilotCostLimit, usage: UsageAccounting, elapsed_seconds: int
) -> None:
    checks = (
        (usage.calls, limit.maximum_calls, "calls"),
        (usage.input_tokens, limit.maximum_input_tokens, "input tokens"),
        (usage.output_tokens, limit.maximum_output_tokens, "output tokens"),
        (elapsed_seconds, limit.maximum_wall_seconds, "wall clock"),
    )
    for actual, maximum, name in checks:
        if actual > maximum:
            raise GovernanceViolation(f"pilot cost guard rejected {name}")
    if usage.estimated_cost is None:
        raise GovernanceViolation("pilot cost guard requires priced usage")
    if Decimal(usage.estimated_cost) > Decimal(limit.maximum_estimated_cost):
        raise GovernanceViolation("pilot cost guard rejected estimated cost")


def normalize_pilot_metrics(values: dict[str, float]) -> dict[str, float | str]:
    unknown = set(values) - set(PILOT_METRICS)
    if unknown:
        raise ValidationError(f"unknown pilot metrics: {sorted(unknown)}")
    return {
        name: float(values[name]) if name in values else NOT_AVAILABLE for name in PILOT_METRICS
    }


def aggregate_three_runs(values: tuple[float, ...]) -> PilotRepeatSummary:
    if len(values) != 3:
        raise ValidationError("pilot aggregation requires exactly three runs")
    return PilotRepeatSummary(
        (values[0], values[1], values[2]),
        statistics.fmean(values),
        max(values) - min(values),
    )


def classify_fairness(
    layer: ComparisonLayer,
    *,
    critical_mismatches: tuple[str, ...],
    remaining_mismatches: tuple[str, ...],
) -> PilotComparability:
    if layer is ComparisonLayer.NATIVE:
        return PilotComparability.NATIVE_ONLY
    if critical_mismatches:
        return PilotComparability.NON_EQUIVALENT
    if remaining_mismatches:
        return PilotComparability.PARTIALLY_COMPARABLE
    return PilotComparability.EXACTLY_COMPARABLE
