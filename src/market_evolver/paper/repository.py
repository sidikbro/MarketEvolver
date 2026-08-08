from __future__ import annotations

import json
from dataclasses import asdict
from typing import cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_evolver.errors import IntegrityViolation
from market_evolver.paper.schemas import (
    AuditRecord,
    ExecutionDecision,
    PaperAccountSnapshot,
    PaperFill,
    PaperOrderCandidate,
    PaperPortfolio,
    PortfolioStatus,
    RiskEvaluation,
    RiskPolicy,
    SignalIntent,
)
from market_evolver.provenance import content_id
from market_evolver.storage.models import (
    PaperAccountSnapshotModel,
    PaperAuditModel,
    PaperExecutionDecisionModel,
    PaperFillModel,
    PaperOrderModel,
    PaperPortfolioModel,
    PaperRiskEvaluationModel,
    PaperRiskPolicyModel,
    PaperSignalModel,
)


class SqlPaperRepository:
    def __init__(self, session: Session):
        self.session = session

    def add_policy(self, item: RiskPolicy) -> bool:
        if self.session.get(PaperRiskPolicyModel, item.policy_id):
            return False
        values = _jsonable(asdict(item))
        values.pop("policy_id")
        self.session.add(
            PaperRiskPolicyModel(
                policy_id=item.policy_id,
                name=item.name,
                created_at=item.created_at,
                limits=values,
                provenance=list(item.provenance),
            )
        )
        return True

    def add_portfolio(self, item: PaperPortfolio) -> bool:
        version_id = f"{item.portfolio_id}:v{item.version}"
        if self.session.get(PaperPortfolioModel, version_id):
            return False
        prior = self.latest_portfolio_row(item.portfolio_id)
        if prior is not None:
            if prior.status != PortfolioStatus.CONFIGURED.value:
                raise IntegrityViolation("portfolio configuration is immutable once activated")
            if item.version != prior.version + 1 or item.revision_of != prior.portfolio_version_id:
                raise IntegrityViolation("invalid portfolio revision lineage")
        self.session.add(
            PaperPortfolioModel(
                portfolio_version_id=version_id,
                portfolio_id=item.portfolio_id,
                name=item.name,
                created_at=item.created_at,
                configuration=_jsonable(asdict(item)),
                status=item.status.value,
                version=item.version,
                revision_of=item.revision_of,
            )
        )
        return True

    def latest_portfolio_row(self, portfolio_id: str) -> PaperPortfolioModel | None:
        return self.session.scalar(
            select(PaperPortfolioModel)
            .where(PaperPortfolioModel.portfolio_id == portfolio_id)
            .order_by(PaperPortfolioModel.version.desc())
            .limit(1)
        )

    def transition(self, portfolio_id: str, status: PortfolioStatus, audit: AuditRecord) -> None:
        prior = self.latest_portfolio_row(portfolio_id)
        if prior is None:
            raise IntegrityViolation("unknown paper portfolio")
        allowed = {
            "configured": {"active", "stopped"},
            "active": {"paused", "stopped", "completed"},
            "paused": {"active", "stopped"},
            "stopped": set(),
            "completed": set(),
        }
        if status.value not in allowed[prior.status]:
            raise IntegrityViolation("invalid paper portfolio lifecycle transition")
        cfg = dict(prior.configuration)
        cfg["status"] = status.value
        self.session.add(
            PaperPortfolioModel(
                portfolio_version_id=f"{portfolio_id}:v{prior.version + 1}",
                portfolio_id=portfolio_id,
                name=prior.name,
                created_at=audit.timestamp,
                configuration=cfg,
                status=status.value,
                version=prior.version + 1,
                revision_of=prior.portfolio_version_id,
            )
        )
        self.add_audit(audit)

    def add_signal(self, item: SignalIntent) -> bool:
        return self._add(
            PaperSignalModel,
            item.signal_id,
            PaperSignalModel(
                signal_id=item.signal_id,
                portfolio_id=item.portfolio_id,
                generated_at=item.generated_at,
                payload=_jsonable(asdict(item)),
            ),
        )

    def add_order(self, item: PaperOrderCandidate) -> bool:
        if not self.session.get(PaperSignalModel, item.signal_id):
            raise IntegrityViolation("paper order requires persisted admitted signal")
        return self._add(
            PaperOrderModel,
            item.candidate_id,
            PaperOrderModel(
                candidate_id=item.candidate_id,
                signal_id=item.signal_id,
                portfolio_id=item.portfolio_id,
                generated_at=item.generated_at,
                payload=_jsonable(asdict(item)),
            ),
        )

    def add_evaluation(self, item: RiskEvaluation) -> bool:
        if not self.session.get(PaperOrderModel, item.candidate_id):
            raise IntegrityViolation("risk evaluation requires persisted candidate")
        return self._add(
            PaperRiskEvaluationModel,
            item.evaluation_id,
            PaperRiskEvaluationModel(
                evaluation_id=item.evaluation_id,
                candidate_id=item.candidate_id,
                portfolio_id=item.portfolio_id,
                evaluated_at=item.evaluated_at,
                action=item.action.value,
                payload=_jsonable(asdict(item)),
            ),
        )

    def add_decision(self, item: ExecutionDecision) -> bool:
        return self._add(
            PaperExecutionDecisionModel,
            item.decision_id,
            PaperExecutionDecisionModel(
                decision_id=item.decision_id,
                candidate_id=item.candidate_id,
                decided_at=item.decided_at,
                payload=_jsonable(asdict(item)),
            ),
        )

    def add_fill(self, item: PaperFill) -> bool:
        if not self.session.get(PaperExecutionDecisionModel, item.decision_id):
            raise IntegrityViolation("fill requires persisted execution decision")
        return self._add(
            PaperFillModel,
            item.fill_id,
            PaperFillModel(
                fill_id=item.fill_id,
                decision_id=item.decision_id,
                portfolio_id=item.portfolio_id,
                filled_at=item.filled_at,
                payload=_jsonable(asdict(item)),
            ),
        )

    def add_snapshot(self, item: PaperAccountSnapshot) -> bool:
        previous = self.session.scalar(
            select(PaperAccountSnapshotModel)
            .where(PaperAccountSnapshotModel.portfolio_id == item.portfolio_id)
            .order_by(PaperAccountSnapshotModel.timestamp.desc())
            .limit(1)
        )
        if previous is not None and previous.timestamp >= item.timestamp:
            raise IntegrityViolation("paper snapshots must advance monotonically")
        return self._add(
            PaperAccountSnapshotModel,
            item.snapshot_id,
            PaperAccountSnapshotModel(
                snapshot_id=item.snapshot_id,
                portfolio_id=item.portfolio_id,
                timestamp=item.timestamp,
                account=_jsonable(asdict(item)),
            ),
        )

    def add_audit(self, item: AuditRecord) -> bool:
        return self._add(
            PaperAuditModel,
            item.audit_id,
            PaperAuditModel(
                audit_id=item.audit_id,
                portfolio_id=item.portfolio_id,
                timestamp=item.timestamp,
                kind=item.kind,
                payload=_jsonable(asdict(item)),
            ),
        )

    def counts(self, portfolio_id: str) -> dict[str, int]:
        classes = (
            PaperSignalModel,
            PaperOrderModel,
            PaperRiskEvaluationModel,
            PaperFillModel,
            PaperAccountSnapshotModel,
            PaperAuditModel,
        )
        return {
            model.__tablename__: len(
                tuple(self.session.scalars(select(model).where(model.portfolio_id == portfolio_id)))
            )
            for model in classes
        }

    def _add(self, model: type[object], key: str, row: object) -> bool:
        if self.session.get(model, key):
            return False
        self.session.add(row)
        return True


def journal_id(parts: tuple[str, ...]) -> str:
    return content_id("paper-journal", parts)


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
