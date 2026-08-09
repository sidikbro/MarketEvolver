from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from market_evolver.errors import IntegrityViolation
from market_evolver.evolve.policy import EvolutionPolicy
from market_evolver.evolve.schemas import (
    BenchmarkManifest,
    ChallengerEvaluation,
    ChampionRegistryEvent,
    DatasetPartition,
    ErrorAttribution,
    ExpertVersion,
    HoldoutAccess,
    ImprovementProposal,
)
from market_evolver.storage.models import (
    ChallengerEvaluationModel,
    ChampionRegistryEventModel,
    EvolutionBenchmarkManifestModel,
    EvolutionErrorAttributionModel,
    EvolutionHoldoutAccessModel,
    EvolvableExpertVersionModel,
    ImprovementProposalModel,
)


class SqlEvolutionRepository:
    def __init__(self, session: Session):
        self.session = session

    def add_proposal(self, item: ImprovementProposal) -> bool:
        return self._add(
            ImprovementProposalModel,
            item.proposal_id,
            ImprovementProposalModel(
                proposal_id=item.proposal_id,
                expert_id=item.expert_id,
                parent_expert_version=item.parent_expert_version,
                status=item.status.value,
                created_at=item.created_at,
                payload=_jsonable(asdict(item)),
            ),
        )

    def add_version(self, item: ExpertVersion) -> bool:
        if (
            item.parent_version
            and self.session.get(EvolvableExpertVersionModel, item.parent_version) is None
        ):
            raise IntegrityViolation("challenger references unknown parent")
        if (
            item.proposal_id
            and self.session.get(ImprovementProposalModel, item.proposal_id) is None
        ):
            raise IntegrityViolation("challenger references unknown proposal")
        return self._add(
            EvolvableExpertVersionModel,
            item.expert_version_id,
            EvolvableExpertVersionModel(
                expert_version_id=item.expert_version_id,
                expert_id=item.expert_id,
                parent_version=item.parent_version,
                proposal_id=item.proposal_id,
                approval_state=item.approval_state.value,
                created_at=item.created_at,
                payload=_jsonable(asdict(item)),
            ),
        )

    def add_attribution(self, item: ErrorAttribution) -> bool:
        return self._add(
            EvolutionErrorAttributionModel,
            item.attribution_id,
            EvolutionErrorAttributionModel(
                attribution_id=item.attribution_id,
                expert_version_id=item.expert_version_id,
                category=item.category.value,
                attributed_at=item.attributed_at,
                critical=item.critical_safety_failure,
                payload=_jsonable(asdict(item)),
            ),
        )

    def add_manifest(self, item: BenchmarkManifest) -> bool:
        return self._add(
            EvolutionBenchmarkManifestModel,
            item.manifest_id,
            EvolutionBenchmarkManifestModel(
                manifest_id=item.manifest_id,
                dataset_version=item.dataset_version,
                created_at=item.created_at,
                payload=_jsonable(asdict(item)),
            ),
        )

    def audit_holdout(self, item: HoldoutAccess, policy: EvolutionPolicy) -> bool:
        if item.partition is DatasetPartition.FINAL_HOLDOUT:
            count = int(
                self.session.scalar(
                    select(func.count())
                    .select_from(EvolutionHoldoutAccessModel)
                    .where(
                        EvolutionHoldoutAccessModel.expert_version_id == item.expert_version_id,
                        EvolutionHoldoutAccessModel.manifest_id == item.manifest_id,
                        EvolutionHoldoutAccessModel.partition
                        == DatasetPartition.FINAL_HOLDOUT.value,
                    )
                )
                or 0
            )
            if count >= policy.maximum_final_holdout_accesses:
                raise IntegrityViolation("final holdout adaptive reuse limit exceeded")
        return self._add(
            EvolutionHoldoutAccessModel,
            item.access_id,
            EvolutionHoldoutAccessModel(
                access_id=item.access_id,
                expert_version_id=item.expert_version_id,
                manifest_id=item.manifest_id,
                partition=item.partition.value,
                accessed_at=item.accessed_at,
                payload=_jsonable(asdict(item)),
            ),
        )

    def add_evaluation(self, item: ChallengerEvaluation) -> bool:
        if self.session.get(EvolvableExpertVersionModel, item.challenger_version_id) is None:
            raise IntegrityViolation("evaluation references unknown challenger")
        if self.session.get(EvolutionBenchmarkManifestModel, item.manifest_id) is None:
            raise IntegrityViolation("evaluation references unknown benchmark manifest")
        return self._add(
            ChallengerEvaluationModel,
            item.evaluation_id,
            ChallengerEvaluationModel(
                evaluation_id=item.evaluation_id,
                challenger_version_id=item.challenger_version_id,
                manifest_id=item.manifest_id,
                decision=item.decision,
                safety_veto=item.safety_veto,
                evaluated_at=item.evaluated_at,
                payload=_jsonable(asdict(item)),
            ),
        )

    def add_registry_event(self, item: ChampionRegistryEvent) -> bool:
        if self.session.get(EvolvableExpertVersionModel, item.champion_version_id) is None:
            raise IntegrityViolation("champion event references unknown version")
        return self._add(
            ChampionRegistryEventModel,
            item.event_id,
            ChampionRegistryEventModel(
                event_id=item.event_id,
                expert_id=item.expert_id,
                champion_version_id=item.champion_version_id,
                action=item.action.value,
                occurred_at=item.occurred_at,
                payload=_jsonable(asdict(item)),
            ),
        )

    def current_champion_id(self, expert_id: str) -> str | None:
        row = self.session.scalar(
            select(ChampionRegistryEventModel)
            .where(ChampionRegistryEventModel.expert_id == expert_id)
            .order_by(
                ChampionRegistryEventModel.occurred_at.desc(),
                ChampionRegistryEventModel.event_id.desc(),
            )
            .limit(1)
        )
        return None if row is None else row.champion_version_id

    def history(self, expert_id: str) -> tuple[dict[str, Any], ...]:
        return tuple(
            row.payload
            for row in self.session.scalars(
                select(ChampionRegistryEventModel)
                .where(ChampionRegistryEventModel.expert_id == expert_id)
                .order_by(ChampionRegistryEventModel.occurred_at)
            )
        )

    def _add(self, model: type[object], key: str, row: object) -> bool:
        if self.session.get(model, key):
            return False
        self.session.add(row)
        return True


def _jsonable(value: dict[str, object]) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(
            json.dumps(
                value,
                default=lambda item: item.value if hasattr(item, "value") else item.isoformat(),
            )
        ),
    )
