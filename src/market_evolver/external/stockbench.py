from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from market_evolver.errors import GovernanceViolation, ValidationError
from market_evolver.external.schemas import ExternalActionProposal
from market_evolver.provenance import content_id
from market_evolver.research.schemas import ContextItem, ResearchContext
from market_evolver.time import require_aware_utc


def stockbench_context(
    observation: dict[str, object], cutoff: datetime, *, anonymized: bool = False
) -> ResearchContext:
    at = require_aware_utc(cutoff, "cutoff")
    symbol = observation.get("symbol")
    observed_at = observation.get("observed_at")
    if not isinstance(symbol, str) or not isinstance(observed_at, datetime):
        raise ValidationError("StockBench observation requires symbol and observed_at")
    seen = require_aware_utc(observed_at, "observed_at")
    if seen > at:
        raise GovernanceViolation("StockBench observation leaks beyond research cutoff")
    items = []
    for key in sorted(observation):
        if key in {"symbol", "observed_at"}:
            continue
        value = observation[key]
        identifier = content_id(
            "external-stockbench-input", {"key": key, "value": value, "at": seen}
        )
        items.append(ContextItem("external_unproven_input", identifier, seen, f"{key}={value}"))
    subject = "ANONYMIZED_ASSET" if anonymized else symbol
    return ResearchContext(at, subject, tuple(items), anonymized)


def to_stockbench_action(proposal: ExternalActionProposal) -> dict[str, str]:
    quantity = Decimal(proposal.quantity)
    if quantity < 0:
        raise ValidationError("external action quantity cannot be negative")
    if proposal.reviewer_decision == "rejected":
        return {"symbol": proposal.symbol, "action": "HOLD", "quantity": "0"}
    return {"symbol": proposal.symbol, "action": proposal.action, "quantity": str(quantity)}
