"""Cross-component validation manifests; contains no research or execution capability."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from market_evolver.errors import IntegrityViolation, ValidationError
from market_evolver.provenance import content_id
from market_evolver.time import require_aware_utc

PIPELINE_STAGES = (
    "official_source",
    "evidence",
    "event",
    "knowledge_graph",
    "company_fundamentals",
    "macro_policy_news",
    "fused_claim",
    "research_context",
    "expert_routing",
    "hypothesis",
    "experiment",
    "backtest",
    "paper_signal",
    "risk_governor",
    "simulated_fill",
    "portfolio_snapshot",
)


@dataclass(frozen=True, slots=True)
class IntegrationCheckpoint:
    stage: str
    observed_at: datetime
    provenance_ids: tuple[str, ...]
    payload_hash: str
    checkpoint_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "observed_at", require_aware_utc(self.observed_at, "observed_at"))
        if self.stage not in PIPELINE_STAGES or not self.provenance_ids:
            raise ValidationError("integration checkpoint lacks stage or provenance")
        if not self.payload_hash.startswith("sha256:"):
            raise ValidationError("integration checkpoint payload hash is invalid")
        object.__setattr__(self, "checkpoint_id", content_id("integration-checkpoint", self))


@dataclass(frozen=True, slots=True)
class IntegrationManifest:
    cutoff: datetime
    checkpoints: tuple[IntegrationCheckpoint, ...]
    manifest_id: str = field(init=False)

    def __post_init__(self) -> None:
        cutoff = require_aware_utc(self.cutoff, "cutoff")
        object.__setattr__(self, "cutoff", cutoff)
        if tuple(item.stage for item in self.checkpoints) != PIPELINE_STAGES:
            raise IntegrityViolation("integration pipeline is incomplete or out of order")
        previous: str | None = None
        for item in self.checkpoints:
            if item.observed_at > cutoff:
                raise IntegrityViolation("future checkpoint leaked into integration manifest")
            if previous is not None and previous not in item.provenance_ids:
                raise IntegrityViolation("integration provenance chain is broken")
            previous = item.checkpoint_id
        object.__setattr__(self, "manifest_id", content_id("integration-manifest", self))


def visible_checkpoints(
    records: tuple[IntegrationCheckpoint, ...], cutoff: datetime
) -> tuple[IntegrationCheckpoint, ...]:
    at = require_aware_utc(cutoff, "cutoff")
    return tuple(item for item in records if item.observed_at <= at)
