"""Append-only replay cases, commitments, runs, outcomes, and paired results."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_evolver.errors import IntegrityViolation
from market_evolver.replay.schemas import (
    BenchmarkPair,
    OutcomeEvaluation,
    ReplayCase,
    ReplayCaseType,
    ReplayRun,
    ResearchCommitment,
    ResearchMode,
)
from market_evolver.storage.models import (
    BenchmarkPairModel,
    OutcomeEvaluationModel,
    ReplayCaseModel,
    ReplayCommitmentModel,
    ReplayRunModel,
)


class SqlReplayRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_case(self, item: ReplayCase) -> bool:
        if self.session.get(ReplayCaseModel, item.case_id):
            return False
        self.session.add(
            ReplayCaseModel(
                case_id=item.case_id,
                case_type=item.case_type.value,
                entity_ids=list(item.entity_ids),
                asset_ids=list(item.asset_ids),
                cutoff=item.cutoff,
                horizon=item.horizon,
                available_evidence_manifest_id=item.available_evidence_manifest_id,
                benchmark_asset_id=item.benchmark_asset_id,
                expected_output_schema=item.expected_output_schema,
                evaluation_protocol=item.evaluation_protocol,
                dataset_version=item.dataset_version,
                created_at=item.created_at,
            )
        )
        self.session.flush()
        return True

    def get_case(self, case_id: str) -> ReplayCase | None:
        model = self.session.get(ReplayCaseModel, case_id)
        return None if model is None else self._case(model)

    def list_cases(self) -> list[ReplayCase]:
        return [
            self._case(item)
            for item in self.session.scalars(
                select(ReplayCaseModel).order_by(ReplayCaseModel.case_type)
            )
        ]

    def add_commitment(self, item: ResearchCommitment) -> bool:
        if self.session.get(ReplayCommitmentModel, item.commitment_id):
            return False
        if self.session.get(ReplayCaseModel, item.case_id) is None:
            raise IntegrityViolation("commitment references unknown replay case")
        self.session.add(
            ReplayCommitmentModel(
                commitment_id=item.commitment_id,
                case_id=item.case_id,
                replay_timestamp=item.replay_timestamp,
                context_manifest_id=item.context_manifest_id,
                hypothesis_id=item.hypothesis_id,
                expected_horizon=item.expected_horizon,
                measurable_outcome=item.measurable_outcome,
                falsification_criterion=item.falsification_criterion,
                confidence=item.confidence,
                reviewer_decision=item.reviewer_decision,
                research_mode=item.research_mode.value,
                committed_at=item.committed_at,
            )
        )
        self.session.flush()
        return True

    def get_commitment(self, commitment_id: str) -> ResearchCommitment | None:
        model = self.session.get(ReplayCommitmentModel, commitment_id)
        if model is None:
            return None
        return ResearchCommitment(
            model.case_id,
            _utc(model.replay_timestamp),
            model.context_manifest_id,
            model.hypothesis_id,
            model.expected_horizon,
            model.measurable_outcome,
            model.falsification_criterion,
            model.confidence,
            model.reviewer_decision,
            ResearchMode(model.research_mode),
            _utc(model.committed_at),
        )

    def add_run(self, item: ReplayRun) -> bool:
        if self.session.get(ReplayRunModel, item.run_id):
            return False
        if self.session.get(ReplayCommitmentModel, item.commitment_id) is None:
            raise IntegrityViolation("run references unknown commitment")
        self.session.add(
            ReplayRunModel(
                run_id=item.run_id,
                case_id=item.case_id,
                commitment_id=item.commitment_id,
                named=item.named,
                started_at=item.started_at,
                finished_at=item.finished_at,
                runtime_ms=item.runtime_ms,
                status=item.status,
            )
        )
        self.session.flush()
        return True

    def get_run(self, run_id: str) -> ReplayRun | None:
        model = self.session.get(ReplayRunModel, run_id)
        if model is None:
            return None
        return ReplayRun(
            model.case_id,
            model.commitment_id,
            model.named,
            _utc(model.started_at),
            _utc(model.finished_at),
            model.runtime_ms,
            model.status,
        )

    def list_runs(self) -> list[ReplayRun]:
        return [
            run
            for item in self.session.scalars(
                select(ReplayRunModel).order_by(ReplayRunModel.started_at)
            )
            if (run := self.get_run(item.run_id)) is not None
        ]

    def add_evaluation(self, item: OutcomeEvaluation) -> bool:
        if self.session.get(OutcomeEvaluationModel, item.evaluation_id):
            return False
        if self.session.get(ReplayRunModel, item.run_id) is None:
            raise IntegrityViolation("outcome references unknown replay run")
        self.session.add(
            OutcomeEvaluationModel(
                evaluation_id=item.evaluation_id,
                run_id=item.run_id,
                evaluated_at=item.evaluated_at,
                horizon_end=item.horizon_end,
                forward_return=item.forward_return,
                benchmark_relative_return=item.benchmark_relative_return,
                maximum_adverse_excursion=item.maximum_adverse_excursion,
                maximum_favorable_excursion=item.maximum_favorable_excursion,
                volatility=item.volatility,
                drawdown=item.drawdown,
                direction=item.direction,
                provenance_observation_ids=list(item.provenance_observation_ids),
            )
        )
        self.session.flush()
        return True

    def list_evaluations(self) -> list[OutcomeEvaluation]:
        return [
            self._evaluation(item) for item in self.session.scalars(select(OutcomeEvaluationModel))
        ]

    def add_pair(self, item: BenchmarkPair) -> bool:
        if self.session.get(BenchmarkPairModel, item.pair_id):
            return False
        self.session.add(
            BenchmarkPairModel(
                pair_id=item.pair_id,
                case_id=item.case_id,
                named_run_id=item.named_run_id,
                anonymized_run_id=item.anonymized_run_id,
                created_at=item.created_at,
            )
        )
        self.session.flush()
        return True

    @staticmethod
    def _case(model: ReplayCaseModel) -> ReplayCase:
        return ReplayCase(
            ReplayCaseType(model.case_type),
            tuple(model.entity_ids),
            tuple(model.asset_ids),
            _utc(model.cutoff),
            model.horizon,
            model.available_evidence_manifest_id,
            model.benchmark_asset_id,
            model.expected_output_schema,
            model.evaluation_protocol,
            model.dataset_version,
            _utc(model.created_at),
        )

    @staticmethod
    def _evaluation(model: OutcomeEvaluationModel) -> OutcomeEvaluation:
        return OutcomeEvaluation(
            model.run_id,
            _utc(model.evaluated_at),
            _utc(model.horizon_end),
            model.forward_return,
            model.benchmark_relative_return,
            model.maximum_adverse_excursion,
            model.maximum_favorable_excursion,
            model.volatility,
            model.drawdown,
            model.direction,
            tuple(model.provenance_observation_ids),
        )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
