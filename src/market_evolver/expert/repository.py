from __future__ import annotations

import json
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_evolver.errors import IntegrityViolation
from market_evolver.expert.evaluation import ExpertComparison
from market_evolver.expert.schemas import (
    ExpertAssessment,
    ExpertDefinition,
    ExpertResearchSession,
    ExpertScorecard,
    ExpertStatus,
    Horizon,
    RoutingDecision,
    ToolRequestAudit,
)
from market_evolver.provenance import content_id
from market_evolver.storage.models import (
    ExpertAssessmentModel,
    ExpertComparisonModel,
    ExpertDefinitionModel,
    ExpertRoutingModel,
    ExpertScorecardModel,
    ExpertSessionModel,
    ExpertToolAuditModel,
)


class SqlExpertRepository:
    def __init__(self, session: Session):
        self.session = session

    def add_definition(self, item: ExpertDefinition) -> bool:
        if self.session.get(ExpertDefinitionModel, item.definition_id):
            return False
        previous = self.latest_row(item.expert_id)
        if previous is not None and (
            item.version != previous.version + 1 or item.revision_of != previous.definition_id
        ):
            raise IntegrityViolation("invalid expert definition lineage")
        self.session.add(
            ExpertDefinitionModel(
                definition_id=item.definition_id,
                expert_id=item.expert_id,
                created_at=item.created_at,
                status=item.status.value,
                version=item.version,
                revision_of=item.revision_of,
                payload=_jsonable(asdict(item)),
            )
        )
        return True

    def latest_row(self, expert_id: str) -> ExpertDefinitionModel | None:
        return self.session.scalar(
            select(ExpertDefinitionModel)
            .where(ExpertDefinitionModel.expert_id == expert_id)
            .order_by(ExpertDefinitionModel.version.desc())
            .limit(1)
        )

    def latest(self, expert_id: str) -> ExpertDefinition | None:
        row = self.latest_row(expert_id)
        return None if row is None else _definition(row.payload)

    def list_latest(self) -> tuple[ExpertDefinition, ...]:
        ids = tuple(self.session.scalars(select(ExpertDefinitionModel.expert_id).distinct()))
        return tuple(
            item for expert_id in sorted(ids) if (item := self.latest(expert_id)) is not None
        )

    def add_tool_audit(self, item: ToolRequestAudit) -> bool:
        return self._add(
            ExpertToolAuditModel,
            item.audit_id,
            ExpertToolAuditModel(
                audit_id=item.audit_id,
                expert_definition_id=item.expert_definition_id,
                session_id=item.session_id,
                requested_at=item.requested_at,
                decision=item.decision.value,
                payload=_jsonable(asdict(item)),
            ),
        )

    def add_session(self, item: ExpertResearchSession) -> bool:
        if self.session.get(ExpertDefinitionModel, item.expert_definition_id) is None:
            raise IntegrityViolation("expert session references unknown definition")
        return self._add(
            ExpertSessionModel,
            item.session_id,
            ExpertSessionModel(
                session_id=item.session_id,
                expert_definition_id=item.expert_definition_id,
                cutoff=item.cutoff,
                started_at=item.started_at,
                status=item.status.value,
                domain=item.domain,
                payload=_jsonable(asdict(item)),
            ),
        )

    def add_assessment(self, item: ExpertAssessment, allowed_evidence: frozenset[str]) -> bool:
        if not set(item.evidence_ids) <= allowed_evidence:
            raise IntegrityViolation("expert assessment contains fabricated provenance")
        if self.session.get(ExpertSessionModel, item.session_id) is None:
            raise IntegrityViolation("assessment references unknown expert session")
        return self._add(
            ExpertAssessmentModel,
            item.assessment_id,
            ExpertAssessmentModel(
                assessment_id=item.assessment_id,
                session_id=item.session_id,
                created_at=item.created_at,
                payload=_jsonable(asdict(item)),
            ),
        )

    def add_routing(self, item: RoutingDecision) -> bool:
        return self._add(
            ExpertRoutingModel,
            item.routing_id,
            ExpertRoutingModel(
                routing_id=item.routing_id, cutoff=item.cutoff, payload=_jsonable(asdict(item))
            ),
        )

    def add_scorecard(self, item: ExpertScorecard) -> bool:
        return self._add(
            ExpertScorecardModel,
            item.scorecard_id,
            ExpertScorecardModel(
                scorecard_id=item.scorecard_id,
                expert_definition_id=item.expert_definition_id,
                cutoff=item.cutoff,
                payload=_jsonable(asdict(item)),
            ),
        )

    def add_comparison(self, item: ExpertComparison, created_at: datetime) -> str:
        created = created_at.astimezone(UTC)
        item_id = content_id("expert-comparison", (item, created))
        self._add(
            ExpertComparisonModel,
            item_id,
            ExpertComparisonModel(
                comparison_id=item_id, created_at=created, payload=_jsonable(asdict(item))
            ),
        )
        return item_id

    def _add(self, model: type[object], key: str, row: object) -> bool:
        if self.session.get(model, key):
            return False
        self.session.add(row)
        return True


def _jsonable(value: dict[str, object]) -> dict[str, object]:
    return cast(
        dict[str, object],
        json.loads(
            json.dumps(
                value,
                default=lambda item: item.value if hasattr(item, "value") else item.isoformat(),
            )
        ),
    )


def _definition(value: dict[str, Any]) -> ExpertDefinition:
    return ExpertDefinition(
        str(value["expert_id"]),
        str(value["name"]),
        str(value["domain"]),
        tuple(value["geography"]),
        tuple(Horizon(v) for v in value["supported_horizons"]),
        tuple(value["allowed_entity_types"]),
        tuple(value["allowed_source_classes"]),
        tuple(value["allowed_tools"]),
        tuple(value["allowed_research_tasks"]),
        tuple(value["allowed_mechanisms"]),
        tuple(value["forbidden_capabilities"]),
        str(value["prompt_version"]),
        str(value["model_policy"]),
        datetime.fromisoformat(str(value["created_at"])),
        ExpertStatus(str(value["status"])),
        tuple(value["provenance"]),
        int(value["version"]),
        None if value["revision_of"] is None else str(value["revision_of"]),
    )
