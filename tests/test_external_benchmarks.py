import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from market_evolver.errors import GovernanceViolation, ValidationError
from market_evolver.external.benchmark_plan import common_v028_manifests
from market_evolver.external.comparison import assess_comparison, normalize_metrics
from market_evolver.external.execution import aggregate_repeats, fairness_audit
from market_evolver.external.inspection import inspection_summary, verify_runnable
from market_evolver.external.provider import DEEPSEEK_PROFILE, DeepSeekProvider, usage_accounting
from market_evolver.external.registry import EXTERNAL_BENCHMARKS
from market_evolver.external.schemas import (
    Comparability,
    ComparisonMode,
    ExecutionStatus,
    ExternalActionProposal,
    ExternalBenchmarkDefinition,
    ExternalBenchmarkStatus,
    ExternalEnvironmentManifest,
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


@pytest.mark.unit
def test_provider_profile_and_blocked_validation(monkeypatch) -> None:
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    assert DEEPSEEK_PROFILE.temperature == 0
    assert DEEPSEEK_PROFILE.structured_output
    result = DeepSeekProvider().validate()
    assert result.status is ExecutionStatus.BLOCKED_PROVIDER
    assert result.input_tokens == result.output_tokens == 0


@pytest.mark.unit
def test_deepseek_validation_accounts_for_bounded_structured_response() -> None:
    class Response:
        def __init__(self) -> None:
            self.headers = {"x-request-id": "request-fixture"}

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self, limit):
            assert limit == 1_000_001
            return json.dumps(
                {
                    "id": "completion-fixture",
                    "model": "deepseek-v4-flash-202608",
                    "system_fingerprint": "fp-fixture",
                    "choices": [{"message": {"content": '{"ok":true}'}}],
                    "usage": {"prompt_tokens": 5, "completion_tokens": 3},
                }
            ).encode()

    provider = DeepSeekProvider(
        api_key="fixture-not-a-secret", opener=lambda *args, **kwargs: Response()
    )
    result = provider.validate()
    assert result.status is ExecutionStatus.PASS
    assert result.input_tokens == 5 and result.output_tokens == 3
    assert result.provider_request_id == "request-fixture"
    assert result.returned_model_id == "deepseek-v4-flash-202608"
    assert ("system_fingerprint", "fp-fixture") in result.response_metadata


@pytest.mark.unit
def test_deepseek_retries_are_bounded() -> None:
    attempts = 0
    delays = []

    def fail(*args, **kwargs):
        nonlocal attempts
        attempts += 1
        raise OSError("fixture failure")

    provider = DeepSeekProvider(api_key="fixture-not-a-secret", opener=fail, sleeper=delays.append)
    result = provider.validate()
    assert result.status is ExecutionStatus.FAILED_EXTERNAL
    assert attempts == 3 and delays == [0.5, 1.0]


@pytest.mark.unit
def test_cost_accounting_and_repeat_aggregation() -> None:
    priced = replace(
        DEEPSEEK_PROFILE,
        input_price_per_million_tokens="1.0",
        output_price_per_million_tokens="2.0",
    )
    usage = usage_accounting(1000, 500, 1, 20, priced)
    assert usage.estimated_cost == "0.002000"
    summary = aggregate_repeats("cumulative_return", (0.1, 0.2, 0.3), 3, (usage,) * 3)
    assert summary.status is ExecutionStatus.PASS
    assert summary.mean == pytest.approx(0.2)
    assert summary.population_variance == pytest.approx(0.0066666667)


@pytest.mark.unit
def test_blocked_repeats_never_become_synthetic_results() -> None:
    summary = aggregate_repeats("cumulative_return", (), 3, (), ExecutionStatus.BLOCKED_DATASET)
    assert summary.mean is None and summary.population_variance is None
    assert summary.repeats_completed == 0


@pytest.mark.unit
def test_fairness_audit_lists_model_and_information_mismatches() -> None:
    audit = fairness_audit(
        comparison(), comparison(information_set="bars only", model_provider="different/model")
    )
    assert audit.classification is Comparability.NON_EQUIVALENT
    assert "information_set" in audit.mismatches and "model_provider" in audit.mismatches


@pytest.mark.unit
def test_patched_baseline_requires_patch_hash() -> None:
    with pytest.raises(ValidationError, match="patch"):
        ExternalEnvironmentManifest(
            "stockbench",
            "repo",
            "provider",
            "3.11",
            HASH,
            (),
            (),
            (),
            (),
            HASH,
            ("python",),
            ("report",),
            ("Python",),
            None,
            True,
            ExecutionStatus.BLOCKED_DATASET,
        )


@pytest.mark.unit
def test_common_case_is_bounded_and_mode_differences_are_explicit() -> None:
    manifests = common_v028_manifests()
    assert len(manifests) == 5
    audit = fairness_audit(manifests[0], manifests[1])
    assert audit.classification is Comparability.PARTIALLY_COMPARABLE
    assert audit.mismatches == ("mode",)
