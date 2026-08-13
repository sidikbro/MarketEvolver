import pytest

from market_evolver.errors import GovernanceViolation, ValidationError
from market_evolver.external.pilot import (
    NOT_AVAILABLE,
    PILOT_COST_LIMIT,
    ArchitectureComplexity,
    ComparisonLayer,
    CompatibilityKind,
    ModelCompatibility,
    PilotComparability,
    TemporalDataClass,
    aggregate_three_runs,
    classify_fairness,
    classify_model,
    enforce_pilot_cost_limit,
    normalize_pilot_metrics,
    stockbench_click_resolution,
    tradingagents_data_audit,
)
from market_evolver.external.schemas import UsageAccounting


@pytest.mark.unit
def test_stockbench_environment_only_resolution() -> None:
    result = stockbench_click_resolution(resolved_typer="0.12.5", resolved_click="8.4.2")
    assert result.kind is CompatibilityKind.ENVIRONMENT_COMPATIBILITY
    assert result.compatible_click == "8.1.8" and not result.source_patch
    assert (
        stockbench_click_resolution(resolved_typer="0.12.5", resolved_click="8.1.8").kind
        is CompatibilityKind.NATIVE
    )


@pytest.mark.unit
def test_patched_baseline_is_explicit() -> None:
    result = stockbench_click_resolution(
        resolved_typer="0.12.5", resolved_click="8.4.2", source_patch=True
    )
    assert result.kind is CompatibilityKind.PATCHED_BASELINE and result.source_patch


@pytest.mark.unit
def test_two_comparison_layers_are_not_merged() -> None:
    assert (
        classify_fairness(ComparisonLayer.NATIVE, critical_mismatches=(), remaining_mismatches=())
        is PilotComparability.NATIVE_ONLY
    )
    assert (
        classify_fairness(
            ComparisonLayer.CONTROLLED,
            critical_mismatches=(),
            remaining_mismatches=("agent_calls",),
        )
        is PilotComparability.PARTIALLY_COMPARABLE
    )


@pytest.mark.unit
def test_missing_metrics_are_not_zero() -> None:
    metrics = normalize_pilot_metrics({"cumulative_return": 0.0})
    assert metrics["cumulative_return"] == 0.0
    assert metrics["sharpe"] == NOT_AVAILABLE
    with pytest.raises(ValidationError, match="unknown"):
        normalize_pilot_metrics({"profit": 1.0})


@pytest.mark.unit
def test_pilot_cost_guard_includes_wall_clock() -> None:
    usage = UsageAccounting(100, 20, 1, 10, "0.001")
    enforce_pilot_cost_limit(PILOT_COST_LIMIT, usage, 10)
    with pytest.raises(GovernanceViolation, match="wall clock"):
        enforce_pilot_cost_limit(PILOT_COST_LIMIT, usage, 901)


@pytest.mark.unit
def test_three_run_aggregation_preserves_individuals() -> None:
    result = aggregate_three_runs((1.0, 2.0, 4.0))
    assert result.individual_results == (1.0, 2.0, 4.0)
    assert result.mean == pytest.approx(7 / 3) and result.spread == 3.0
    with pytest.raises(ValidationError, match="exactly three"):
        aggregate_three_runs((1.0, 2.0))


@pytest.mark.unit
def test_model_and_fairness_classification() -> None:
    assert classify_model("m", "m", "m") is ModelCompatibility.EXACT_MODEL
    assert classify_model("alias", "m", "m") is ModelCompatibility.COMPATIBLE_MODEL
    assert classify_model("m", "other", "m") is ModelCompatibility.MODEL_MISMATCH
    assert classify_model("m", None, "m") is ModelCompatibility.BLOCKED
    assert (
        classify_fairness(
            ComparisonLayer.CONTROLLED,
            critical_mismatches=("point_in_time",),
            remaining_mismatches=(),
        )
        is PilotComparability.NON_EQUIVALENT
    )


@pytest.mark.unit
def test_architecture_complexity_and_trading_data_audit() -> None:
    complexity = ArchitectureComplexity(2, 2, 0, NOT_AVAILABLE, NOT_AVAILABLE)
    assert complexity.active_agents == 2
    audit = {item.input_name: item for item in tradingagents_data_audit()}
    assert audit["fundamentals"].temporal_class is TemporalDataClass.CURRENT_SNAPSHOT
    assert audit["news"].temporal_class is TemporalDataClass.TEMPORALLY_AMBIGUOUS
    assert all(not item.bundled for item in audit.values())
