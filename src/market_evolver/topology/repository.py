from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import asdict
from datetime import datetime
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from market_evolver.errors import IntegrityViolation
from market_evolver.provenance import content_id
from market_evolver.storage.models import (
    ExpertTopologyVersionModel,
    TopologyEvaluationModel,
    TopologyGapSignalModel,
    TopologyHoldoutAccessModel,
    TopologyProposalModel,
    TopologyRegistryEventModel,
    TopologyRoutingTraceModel,
)
from market_evolver.time import require_aware_utc
from market_evolver.topology.policy import TopologyPolicy
from market_evolver.topology.schemas import (
    GapSignal,
    RelationshipType,
    TopologyEdge,
    TopologyEvaluation,
    TopologyHoldoutAccess,
    TopologyNode,
    TopologyProposal,
    TopologyRegistryEvent,
    TopologyState,
    TopologyVersion,
)


class SqlTopologyRepository:
    def __init__(self, session: Session):
        self.session = session

    def add_gap(self, item: GapSignal) -> bool:
        return self._add(
            TopologyGapSignalModel,
            item.signal_id,
            TopologyGapSignalModel(
                signal_id=item.signal_id,
                expert_id=item.expert_id,
                category=item.category.value,
                observed_at=item.observed_at,
                payload=_jsonable(asdict(item)),
            ),
        )

    def add_proposal(self, item: TopologyProposal) -> bool:
        return self._add(
            TopologyProposalModel,
            item.proposal_id,
            TopologyProposalModel(
                proposal_id=item.proposal_id,
                proposal_type=item.proposal_type.value,
                status=item.status.value,
                created_at=item.created_at,
                payload=_jsonable(asdict(item)),
            ),
        )

    def add_version(self, item: TopologyVersion) -> bool:
        if (
            item.parent_topology_version_id
            and self.session.get(ExpertTopologyVersionModel, item.parent_topology_version_id)
            is None
        ):
            raise IntegrityViolation("topology challenger references unknown parent")
        if item.proposal_id and self.session.get(TopologyProposalModel, item.proposal_id) is None:
            raise IntegrityViolation("topology challenger references unknown proposal")
        return self._add(
            ExpertTopologyVersionModel,
            item.topology_version_id,
            ExpertTopologyVersionModel(
                topology_version_id=item.topology_version_id,
                parent_topology_version_id=item.parent_topology_version_id,
                proposal_id=item.proposal_id,
                state=item.state.value,
                created_at=item.created_at,
                payload=_jsonable(asdict(item)),
            ),
        )

    def add_evaluation(self, item: TopologyEvaluation) -> bool:
        if (
            self.session.get(TopologyProposalModel, item.proposal_id) is None
            or self.session.get(ExpertTopologyVersionModel, item.challenger_topology_id) is None
        ):
            raise IntegrityViolation("topology evaluation references unpersisted benchmark inputs")
        return self._add(
            TopologyEvaluationModel,
            item.evaluation_id,
            TopologyEvaluationModel(
                evaluation_id=item.evaluation_id,
                proposal_id=item.proposal_id,
                challenger_topology_id=item.challenger_topology_id,
                decision=item.decision,
                safety_veto=item.safety_veto,
                evaluated_at=item.evaluated_at,
                payload=_jsonable(asdict(item)),
            ),
        )

    def add_registry_event(self, item: TopologyRegistryEvent) -> bool:
        if self.session.get(ExpertTopologyVersionModel, item.topology_version_id) is None:
            raise IntegrityViolation("topology activation references unknown version")
        return self._add(
            TopologyRegistryEventModel,
            item.event_id,
            TopologyRegistryEventModel(
                event_id=item.event_id,
                topology_version_id=item.topology_version_id,
                action=item.action.value,
                occurred_at=item.occurred_at,
                payload=_jsonable(asdict(item)),
            ),
        )

    def audit_holdout(self, item: TopologyHoldoutAccess, policy: TopologyPolicy) -> bool:
        count = int(
            self.session.scalar(
                select(func.count())
                .select_from(TopologyHoldoutAccessModel)
                .where(
                    TopologyHoldoutAccessModel.topology_version_id == item.topology_version_id,
                    TopologyHoldoutAccessModel.benchmark_manifest_id == item.benchmark_manifest_id,
                )
            )
            or 0
        )
        if count >= policy.maximum_final_holdout_accesses:
            raise IntegrityViolation("topology final holdout adaptive reuse limit exceeded")
        return self._add(
            TopologyHoldoutAccessModel,
            item.access_id,
            TopologyHoldoutAccessModel(
                access_id=item.access_id,
                topology_version_id=item.topology_version_id,
                benchmark_manifest_id=item.benchmark_manifest_id,
                accessed_at=item.accessed_at,
                payload=_jsonable(asdict(item)),
            ),
        )

    def add_routing_trace(
        self,
        topology_version_id: str,
        cutoff: datetime,
        subject_id: str,
        selected: tuple[str, ...],
        expected: tuple[str, ...],
        provenance: tuple[str, ...],
    ) -> str:
        cutoff = require_aware_utc(cutoff, "cutoff")
        payload = {
            "subject_id": subject_id,
            "selected": selected,
            "expected": expected,
            "provenance": provenance,
        }
        trace_id = content_id("topology-routing-trace", (topology_version_id, cutoff, payload))
        self._add(
            TopologyRoutingTraceModel,
            trace_id,
            TopologyRoutingTraceModel(
                trace_id=trace_id,
                topology_version_id=topology_version_id,
                cutoff=cutoff,
                correct=set(selected) == set(expected),
                payload=_jsonable(payload),
            ),
        )
        return trace_id

    def active_at(self, cutoff: datetime) -> TopologyVersion | None:
        cutoff = require_aware_utc(cutoff, "cutoff")
        event = self.session.scalar(
            select(TopologyRegistryEventModel)
            .where(TopologyRegistryEventModel.occurred_at <= cutoff)
            .order_by(
                TopologyRegistryEventModel.occurred_at.desc(),
                TopologyRegistryEventModel.event_id.desc(),
            )
            .limit(1)
        )
        if event is None:
            return None
        row = self.session.get(ExpertTopologyVersionModel, event.topology_version_id)
        return None if row is None else _topology(row.payload)

    def history(self) -> tuple[dict[str, Any], ...]:
        return tuple(
            row.payload
            for row in self.session.scalars(
                select(TopologyRegistryEventModel).order_by(TopologyRegistryEventModel.occurred_at)
            )
        )

    def _add(self, model: type[object], key: str, row: object) -> bool:
        if self.session.get(model, key):
            return False
        self.session.add(row)
        return True


def _jsonable(value: Mapping[str, object]) -> dict[str, Any]:
    return cast(
        dict[str, Any],
        json.loads(
            json.dumps(
                value,
                default=lambda item: item.value if hasattr(item, "value") else item.isoformat(),
            )
        ),
    )


def _topology(value: dict[str, Any]) -> TopologyVersion:
    return TopologyVersion(
        value["parent_topology_version_id"],
        value["proposal_id"],
        tuple(
            TopologyNode(
                item["expert_id"],
                item["expert_version_id"],
                item["domain"],
                datetime.fromisoformat(item["active_from"]),
                None
                if item["active_until"] is None
                else datetime.fromisoformat(item["active_until"]),
            )
            for item in value["nodes"]
        ),
        tuple(
            TopologyEdge(
                item["source_id"],
                item["target_id"],
                RelationshipType(item["relationship"]),
                tuple(tuple(pair) for pair in item["conditions"]),
                int(item["priority"]),
            )
            for item in value["edges"]
        ),
        tuple((item[0], tuple(item[1])) for item in value["panel_rules"]),
        value["router_version"],
        datetime.fromisoformat(value["created_at"]),
        value["created_by"],
        TopologyState(value["state"]),
        value["benchmark_manifest_id"],
        value["safety_status"],
        tuple(value["provenance"]),
    )
