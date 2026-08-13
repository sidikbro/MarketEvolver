from __future__ import annotations

from dataclasses import dataclass

from market_evolver.errors import ValidationError
from market_evolver.external.schemas import Comparability, FairComparisonManifest

CRITICAL_FIELDS = (
    "asset_universe",
    "time_period",
    "initial_capital",
    "transaction_costs",
    "execution_timing",
    "information_set",
    "benchmark",
    "currency",
    "fractional_share_policy",
)
MODEL_FIELDS = ("model_provider", "model_settings", "number_of_agent_calls", "mode")


@dataclass(frozen=True, slots=True)
class ComparisonAssessment:
    classification: Comparability
    critical_differences: tuple[str, ...]
    model_differences: tuple[str, ...]


def assess_comparison(
    left: FairComparisonManifest, right: FairComparisonManifest
) -> ComparisonAssessment:
    critical = tuple(
        name for name in CRITICAL_FIELDS if getattr(left, name) != getattr(right, name)
    )
    model = tuple(name for name in MODEL_FIELDS if getattr(left, name) != getattr(right, name))
    if critical:
        classification = Comparability.NON_EQUIVALENT
    elif model:
        classification = Comparability.PARTIALLY_COMPARABLE
    else:
        classification = Comparability.EXACTLY_COMPARABLE
    return ComparisonAssessment(classification, critical, model)


METRIC_ALIASES = {
    "cum_return": "cumulative_return",
    "cumulative_return": "cumulative_return",
    "benchmark_relative_return": "benchmark_relative_return",
    "alpha": "benchmark_relative_return",
    "max_drawdown": "max_drawdown",
    "volatility": "volatility",
    "sharpe": "sharpe",
    "sharpe_ratio": "sharpe",
    "sortino": "sortino",
    "turnover": "turnover",
    "trades": "number_of_trades",
    "number_of_trades": "number_of_trades",
    "decisions": "number_of_decisions",
    "transaction_costs": "transaction_costs",
    "token_usage": "token_usage",
    "provider_cost": "provider_cost",
    "latency_ms": "latency_ms",
    "grounded_claim_rate": "grounded_claim_rate",
    "unsupported_claim_rate": "unsupported_claim_rate",
    "temporal_leakage_failures": "temporal_leakage_failures",
    "provenance_failures": "provenance_failures",
    "reviewer_rejection": "reviewer_rejection",
    "safety_violations": "safety_violations",
}


def normalize_metrics(values: dict[str, float]) -> dict[str, float]:
    output: dict[str, float] = {}
    for name, value in values.items():
        canonical = METRIC_ALIASES.get(name.casefold())
        if canonical is None:
            continue
        if canonical in output and output[canonical] != value:
            raise ValidationError(f"conflicting values for normalized metric {canonical}")
        output[canonical] = float(value)
    return output
