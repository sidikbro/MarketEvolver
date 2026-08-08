"""Host-controlled, read-only expert tool registry."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from market_evolver.errors import GovernanceViolation
from market_evolver.expert.schemas import (
    AuditDecision,
    ExpertDefinition,
    ExpertStatus,
    ToolRequestAudit,
)
from market_evolver.time import require_aware_utc


@dataclass(frozen=True, slots=True)
class ToolResult:
    tool_name: str
    cutoff: datetime
    records: tuple[dict[str, Any], ...]
    provenance_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        require_aware_utc(self.cutoff, "cutoff")
        if any(
            "first_observed_at" in row
            and require_aware_utc(row["first_observed_at"], "first_observed_at") > self.cutoff
            for row in self.records
        ):
            raise GovernanceViolation("tool returned future evidence")


ReadOnlyHandler = Callable[[str | None, datetime], ToolResult]


class ResearchToolRegistry:
    TOOL_NAMES = frozenset(
        (
            "get_company_context",
            "get_fundamentals",
            "get_filings",
            "get_events",
            "get_policy_actions",
            "get_macro_trends",
            "get_fused_claims",
            "get_source_reputation",
            "get_geopolitical_events",
            "get_market_history",
            "get_mechanism_paths",
            "get_backtest_results",
        )
    )

    def __init__(self, handlers: dict[str, ReadOnlyHandler] | None = None) -> None:
        self._handlers = dict(handlers or {})
        if not set(self._handlers) <= self.TOOL_NAMES:
            raise GovernanceViolation("unknown tool cannot enter expert registry")

    def authorize(
        self,
        expert: ExpertDefinition,
        session_id: str,
        tool_name: str,
        *,
        requested_at: datetime,
        cutoff: datetime,
        entity_id: str | None,
        entity_type: str | None,
        source_class: str | None,
    ) -> ToolRequestAudit:
        requested_at = require_aware_utc(requested_at, "requested_at")
        cutoff = require_aware_utc(cutoff, "cutoff")
        reason = "ALLOWED"
        if cutoff > requested_at:
            reason = "FUTURE_CUTOFF"
        elif expert.status is not ExpertStatus.APPROVED:
            reason = "EXPERT_NOT_APPROVED"
        elif tool_name not in self.TOOL_NAMES or tool_name not in expert.allowed_tools:
            reason = "FORBIDDEN_TOOL"
        elif entity_type is not None and entity_type not in expert.allowed_entity_types:
            reason = "CROSS_DOMAIN_ENTITY"
        elif source_class is not None and source_class not in expert.allowed_source_classes:
            reason = "FORBIDDEN_SOURCE_CLASS"
        return ToolRequestAudit(
            expert.definition_id,
            session_id,
            tool_name,
            requested_at,
            cutoff,
            entity_id,
            entity_type,
            source_class,
            AuditDecision.ALLOWED if reason == "ALLOWED" else AuditDecision.DENIED,
            reason,
        )

    def call(self, audit: ToolRequestAudit) -> ToolResult:
        if audit.decision is not AuditDecision.ALLOWED:
            raise GovernanceViolation(f"expert tool denied: {audit.reason_code}")
        handler = self._handlers.get(audit.tool_name)
        if handler is None:
            raise GovernanceViolation("host did not grant requested tool capability")
        return handler(audit.entity_id, audit.cutoff)
