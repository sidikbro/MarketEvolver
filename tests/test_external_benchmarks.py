from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from market_evolver.errors import GovernanceViolation, ValidationError
from market_evolver.external.comparison import assess_comparison, normalize_metrics
from market_evolver.external.inspection import inspection_summary, verify_runnable
from market_evolver.external.registry import EXTERNAL_BENCHMARKS
from market_evolver.external.schemas import (
    Comparability,
    ComparisonMode,
    ExternalActionProposal,
    ExternalBenchmarkDefinition,
    ExternalBenchmarkStatus,
    ExternalRepositoryManifest,
    ExternalRunImport,
    FairComparisonManifest,
)
from market_evolver.external.stockbench import stockbench_context, to_stockbench_action
from market_evolver.external.tradingagents import import_tradingagents_result

NOW = datetime(2025, 1, 2, tzinfo=UTC)
SHA = "1" * 40
HASH = "2" * 64


def comparison(**changes) -> FairComparisonManifest:
    values = {
        "asset_universe": ("AAPL",),
        "time_period": "2024-01-01/2024-12-31",
        "initial_capital": "100000 USD",
        "transaction_costs": "10 bps",
        "execution_timing": "next open",
        "information_set": "bars+news through prior close",
        "model_provider": "provider/model",
        "model_settings": "temperature=0 seed=7",
        "number_of_agent_calls": 2,
        "benchmark": "SPY total return",
        "currency": "USD",
        "fractional_share_policy": "disabled",
        "mode": ComparisonMode.GENERALIST,
        "provenance": ("config:fixture",),
    }
    values.update(changes)
    return FairComparisonManifest(**values)


def repository_manifest(*, dirty: bool = False) -> ExternalRepositoryManifest:
    return ExternalRepositoryManifest(
        "stockbench", SHA, "https://example.test/repo.git", dirty, "3.12.0", HASH, HASH, (), NOW
    )


@pytest.mark.unit
def test_registry_pins_and_placeholder_statuses() -> None:
    stockbench = EXTERNAL_BENCHMARKS.get("stockbench")
    assert stockbench.pinned_git_sha == "ce8b2b3483590646ad3b650ac8221f43f76fd091"
    assert stockbench.license == "Apache-2.0"
    assert EXTERNAL_BENCHMARKS.get("ktd-fin").status is ExternalBenchmarkStatus.REGISTERED
    with pytest.raises(ValidationError, match="full Git SHA"):
        replace(stockbench, pinned_git_sha="main")


@pytest.mark.unit
def test_missing_benchmark_metadata_and_contamination_annotation() -> None:
    with pytest.raises(ValidationError, match="metadata"):
        ExternalBenchmarkDefinition(
            "missing",
            "",
            "https://example.test/repo",
            None,
            None,
            "unknown",
            "",
            "",
            (),
            "",
            (),
            (),
            "",
            (),
            ExternalBenchmarkStatus.REGISTERED,
            (),
        )
    for item in EXTERNAL_BENCHMARKS.list():
        assert item.contamination_notes and item.provenance


@pytest.mark.unit
def test_dirty_external_repository_is_not_runnable() -> None:
    clean = replace(
        repository_manifest(), git_sha=EXTERNAL_BENCHMARKS.get("stockbench").pinned_git_sha
    )
    verify_runnable(clean)
    with pytest.raises(GovernanceViolation, match="dirty"):
        verify_runnable(replace(clean, dirty=True))


@pytest.mark.unit
def test_comparison_detects_incompatible_and_partial_setups() -> None:
    base = comparison()
    assert assess_comparison(base, base).classification is Comparability.EXACTLY_COMPARABLE
    partial = comparison(model_provider="other/model")
    assert assess_comparison(base, partial).classification is Comparability.PARTIALLY_COMPARABLE
    assert (
        assess_comparison(base, comparison(mode=ComparisonMode.SPECIALIST)).classification
        is Comparability.PARTIALLY_COMPARABLE
    )
    incompatible = comparison(transaction_costs="zero")
    result = assess_comparison(base, incompatible)
    assert result.classification is Comparability.NON_EQUIVALENT
    assert result.critical_differences == ("transaction_costs",)


@pytest.mark.unit
def test_metric_normalization_is_explicit() -> None:
    assert normalize_metrics({"cum_return": 0.1, "sharpe_ratio": 1.2, "unknown": 3}) == {
        "cumulative_return": 0.1,
        "sharpe": 1.2,
    }
    with pytest.raises(ValidationError, match="conflicting"):
        normalize_metrics({"cum_return": 0.1, "cumulative_return": 0.2})


@pytest.mark.unit
def test_stockbench_context_marks_missing_native_provenance_and_cutoff() -> None:
    context = stockbench_context(
        {"symbol": "AAPL", "observed_at": NOW, "price_history": [100, 101], "news": ["x"]},
        NOW,
    )
    assert context.subject_id == "AAPL"
    assert {item.kind for item in context.items} == {"external_unproven_input"}
    with pytest.raises(GovernanceViolation, match="cutoff"):
        stockbench_context({"symbol": "AAPL", "observed_at": NOW + timedelta(days=1)}, NOW)


@pytest.mark.unit
def test_action_schema_adapter_respects_reviewer() -> None:
    proposal = ExternalActionProposal(
        "AAPL", "BUY", "3", "bounded fixture", "context-1", "expert-v1", "approved", ("p1",)
    )
    assert to_stockbench_action(proposal) == {"symbol": "AAPL", "action": "BUY", "quantity": "3"}
    rejected = replace(proposal, reviewer_decision="rejected")
    assert to_stockbench_action(rejected)["action"] == "HOLD"


@pytest.mark.unit
def test_external_run_requires_reproducibility_provenance() -> None:
    run = ExternalRunImport(
        "tradingagents",
        "repo-manifest",
        SHA,
        (HASH,),
        (HASH,),
        "provider/model",
        (HASH,),
        (7,),
        (("python", "3.12"),),
        NOW,
        NOW + timedelta(seconds=1),
        ("HOLD",),
        HASH,
        (("cumulative_return", 0.0),),
        1000,
        HASH,
    )
    assert run.run_id and run.market_evolver_sha == SHA
    with pytest.raises(ValidationError, match="provenance"):
        replace(run, repository_manifest_id="")


@pytest.mark.unit
def test_tradingagents_import_rejects_non_manifest_material() -> None:
    payload = {
        "benchmark_id": "tradingagents",
        "repository_manifest_id": "repo-manifest",
        "market_evolver_sha": SHA,
        "dataset_hashes": [HASH],
        "config_hashes": [HASH],
        "model_provider": "provider/model",
        "prompt_hashes": [HASH],
        "seeds": [7],
        "environment": [["python", "3.12"]],
        "started_at": NOW.isoformat(),
        "finished_at": (NOW + timedelta(seconds=1)).isoformat(),
        "decisions": ["HOLD"],
        "portfolio_path_hash": HASH,
        "reported_metrics": [["cumulative_return", 0.0]],
        "runtime_ms": 1000,
        "reproducibility_log_hash": HASH,
    }
    assert import_tradingagents_result(payload).benchmark_id == "tradingagents"
    payload["external_source_tree"] = "forbidden"
    with pytest.raises(ValidationError, match="unsupported"):
        import_tradingagents_result(payload)


@pytest.mark.unit
def test_inspection_documents_architecture_and_limitations() -> None:
    stockbench = inspection_summary("stockbench")
    tradingagents = inspection_summary("tradingagents")
    assert stockbench.initial_capital == "USD 100,000 in inspected config"
    assert "bull/bear researchers" in tradingagents.architecture
    assert stockbench.limitations and tradingagents.contamination_controls
