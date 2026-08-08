from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_evolver.errors import IntegrityViolation
from market_evolver.experiment.schemas import (
    BacktestResult,
    CostBreakdown,
    CostModel,
    DatasetManifest,
    EntryRule,
    EvaluationWindow,
    ExitRule,
    ExperimentRegistrySnapshot,
    ExperimentSpecification,
    ExperimentStatus,
    PartitionKind,
    PositionPath,
    PositionPolicy,
    RebalanceFrequency,
    RuleOperator,
    SignalClause,
    SignalDefinition,
    SignalKind,
    TestSetAccess,
)
from market_evolver.storage.models import (
    BacktestDatasetModel,
    BacktestResultModel,
    ExperimentRegistryModel,
    ExperimentSpecificationModel,
    TestSetAccessModel,
)


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class SqlExperimentRepository:
    def __init__(self, session: Session):
        self.session = session

    def add_specification(self, spec: ExperimentSpecification) -> bool:
        if self.session.get(ExperimentSpecificationModel, spec.experiment_id):
            return False
        if spec.revision_of:
            prior = self.session.get(ExperimentSpecificationModel, spec.revision_of)
            if (
                prior is None
                or prior.version + 1 != spec.version
                or utc(prior.created_at) >= spec.created_at
            ):
                raise IntegrityViolation("invalid experiment revision")
            root_ids = {spec.revision_of, prior.experiment_id}
            if self.session.scalar(
                select(TestSetAccessModel).where(
                    TestSetAccessModel.experiment_id.in_(root_ids),
                    TestSetAccessModel.partition == PartitionKind.TEST.value,
                )
            ):
                raise IntegrityViolation("experiment cannot change after test-set access")
            if prior.status in {
                ExperimentStatus.VALIDATED.value,
                ExperimentStatus.RUNNING.value,
                ExperimentStatus.COMPLETED.value,
            }:
                raise IntegrityViolation("validated experiment specification is immutable")
        self.session.add(ExperimentSpecificationModel(**_spec_values(spec)))
        return True

    def add_dataset(self, item: DatasetManifest) -> bool:
        if self.session.get(BacktestDatasetModel, item.manifest_id):
            return False
        self.session.add(
            BacktestDatasetModel(
                manifest_id=item.manifest_id,
                dataset_version=item.dataset_version,
                parquet_hashes=list(item.parquet_hashes),
                source_versions=list(item.source_versions),
                parameter_hash=item.parameter_hash,
                seed=item.seed,
                rows_read=item.rows_read,
                bytes_read=item.bytes_read,
            )
        )
        return True

    def add_result(self, item: BacktestResult) -> bool:
        if self.session.get(BacktestResultModel, item.result_id):
            return False
        if not self.session.get(
            ExperimentSpecificationModel, item.experiment_id
        ) or not self.session.get(BacktestDatasetModel, item.dataset_manifest_id):
            raise IntegrityViolation("backtest result references missing immutable inputs")
        self.session.add(BacktestResultModel(**_result_values(item)))
        return True

    def add_test_access(self, item: TestSetAccess) -> bool:
        if self.session.get(TestSetAccessModel, item.audit_id):
            return False
        if not self.session.get(ExperimentSpecificationModel, item.experiment_id):
            raise IntegrityViolation("test access references unknown experiment")
        self.session.add(
            TestSetAccessModel(
                audit_id=item.audit_id,
                experiment_id=item.experiment_id,
                partition=item.partition.value,
                accessed_at=item.accessed_at,
                purpose=item.purpose,
                actor=item.actor,
            )
        )
        return True

    def add_registry_snapshot(self, item: ExperimentRegistrySnapshot) -> bool:
        if self.session.get(ExperimentRegistryModel, item.snapshot_id):
            return False
        self.session.add(ExperimentRegistryModel(**asdict(item)))
        return True

    def specification(self, experiment_id: str) -> ExperimentSpecification | None:
        row = self.session.get(ExperimentSpecificationModel, experiment_id)
        return None if row is None else _spec(row)

    def result(self, result_id: str) -> BacktestResult | None:
        row = self.session.get(BacktestResultModel, result_id)
        return None if row is None else _result(row)

    def results_for_experiment(self, experiment_id: str) -> tuple[BacktestResult, ...]:
        return tuple(
            _result(row)
            for row in self.session.scalars(
                select(BacktestResultModel)
                .where(BacktestResultModel.experiment_id == experiment_id)
                .order_by(BacktestResultModel.finished_at)
            )
        )

    def test_accesses(self, experiment_id: str) -> tuple[TestSetAccess, ...]:
        return tuple(
            TestSetAccess(
                row.experiment_id,
                PartitionKind(row.partition),
                utc(row.accessed_at),
                row.purpose,
                row.actor,
            )
            for row in self.session.scalars(
                select(TestSetAccessModel)
                .where(TestSetAccessModel.experiment_id == experiment_id)
                .order_by(TestSetAccessModel.accessed_at)
            )
        )


def _spec_values(item: ExperimentSpecification) -> dict[str, object]:
    return {
        "experiment_id": item.experiment_id,
        "hypothesis_id": item.hypothesis_id,
        "created_at": item.created_at,
        "cutoff": item.cutoff,
        "research_context_id": item.research_context_id,
        "asset_universe": list(item.asset_universe),
        "benchmark": item.benchmark,
        "signal_definition": {
            "require_all": item.signal_definition.require_all,
            "clauses": [
                {
                    "kind": clause.kind.value,
                    "field_name": clause.field_name,
                    "operator": clause.operator.value,
                    "value": clause.value,
                    "lookback_days": clause.lookback_days,
                }
                for clause in item.signal_definition.clauses
            ],
        },
        "entry_rule": item.entry_rule.value,
        "exit_rule": item.exit_rule.value,
        "holding_period": item.holding_period,
        "rebalance_frequency": item.rebalance_frequency.value,
        "position_policy": item.position_policy.value,
        "cost_model": asdict(item.cost_model),
        "evaluation_window": {
            key: getattr(item.evaluation_window, key).isoformat()
            for key in (
                "research_start",
                "research_end",
                "validation_start",
                "validation_end",
                "test_start",
                "test_end",
            )
        },
        "exclusion_rules": list(item.exclusion_rules),
        "parameter_manifest": [list(pair) for pair in item.parameter_manifest],
        "code_version_hash": item.code_version_hash,
        "provenance": list(item.provenance),
        "status": item.status.value,
        "version": item.version,
        "revision_of": item.revision_of,
    }


def _spec(row: ExperimentSpecificationModel) -> ExperimentSpecification:
    clauses = tuple(
        SignalClause(
            SignalKind(item["kind"]),
            item["field_name"],
            RuleOperator(item["operator"]),
            item["value"],
            item["lookback_days"],
        )
        for item in row.signal_definition["clauses"]
    )
    window = EvaluationWindow(
        *(
            datetime.fromisoformat(row.evaluation_window[key])
            for key in (
                "research_start",
                "research_end",
                "validation_start",
                "validation_end",
                "test_start",
                "test_end",
            )
        )
    )
    return ExperimentSpecification(
        row.hypothesis_id,
        utc(row.created_at),
        utc(row.cutoff),
        row.research_context_id,
        tuple(row.asset_universe),
        row.benchmark,
        SignalDefinition(clauses, row.signal_definition["require_all"]),
        EntryRule(row.entry_rule),
        ExitRule(row.exit_rule),
        row.holding_period,
        RebalanceFrequency(row.rebalance_frequency),
        PositionPolicy(row.position_policy),
        CostModel(**row.cost_model),
        window,
        tuple(row.exclusion_rules),
        tuple((str(pair[0]), str(pair[1])) for pair in row.parameter_manifest),
        row.code_version_hash,
        tuple(row.provenance),
        ExperimentStatus(row.status),
        row.version,
        row.revision_of,
    )


def _result_values(item: BacktestResult) -> dict[str, object]:
    metrics = {
        key: getattr(item, key)
        for key in (
            "gross_return",
            "net_return",
            "benchmark_return",
            "excess_return",
            "volatility",
            "max_drawdown",
            "sharpe",
            "sortino",
            "hit_rate",
            "turnover",
        )
    }
    return {
        "result_id": item.result_id,
        "experiment_id": item.experiment_id,
        "dataset_manifest_id": item.dataset_manifest_id,
        "reproducibility": [list(pair) for pair in item.reproducibility],
        "started_at": item.started_at,
        "finished_at": item.finished_at,
        "metrics": metrics,
        "transaction_costs": asdict(item.transaction_costs),
        "number_of_signals": item.number_of_signals,
        "executed_trades": item.executed_trades,
        "skipped_signals": item.skipped_signals,
        "rejection_reasons": list(item.rejection_reasons),
        "nav": [list(pair) for pair in item.nav],
        "position_paths": [_path_json(path) for path in item.position_paths],
        "runtime_ms": item.runtime_ms,
        "parquet_bytes_read": item.parquet_bytes_read,
    }


def _path_json(path: PositionPath) -> dict[str, object]:
    value = asdict(path)
    value["entry_at"] = path.entry_at.isoformat()
    value["exit_at"] = path.exit_at.isoformat()
    return value


def _result(row: BacktestResultModel) -> BacktestResult:
    paths = tuple(
        PositionPath(
            item["asset_id"],
            datetime.fromisoformat(item["entry_at"]),
            datetime.fromisoformat(item["exit_at"]),
            item["quantity"],
            item["entry_price"],
            item["exit_price"],
            item["maximum_favorable_excursion"],
            item["maximum_adverse_excursion"],
            item["holding_period"],
            item["realized_return"],
            item["benchmark_relative_return"],
            CostBreakdown(**item["costs"]),
        )
        for item in row.position_paths
    )
    return BacktestResult(
        row.experiment_id,
        row.dataset_manifest_id,
        tuple((str(pair[0]), str(pair[1])) for pair in row.reproducibility),
        utc(row.started_at),
        utc(row.finished_at),
        row.metrics["gross_return"],
        row.metrics["net_return"],
        row.metrics["benchmark_return"],
        row.metrics["excess_return"],
        row.metrics["volatility"],
        row.metrics["max_drawdown"],
        row.metrics["sharpe"],
        row.metrics["sortino"],
        row.metrics["hit_rate"],
        row.metrics["turnover"],
        CostBreakdown(**row.transaction_costs),
        row.number_of_signals,
        row.executed_trades,
        row.skipped_signals,
        tuple(row.rejection_reasons),
        tuple((str(pair[0]), str(pair[1])) for pair in row.nav),
        paths,
        row.runtime_ms,
        row.parquet_bytes_read,
    )
