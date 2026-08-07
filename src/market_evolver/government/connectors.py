"""Reviewed and skeleton government source adapters."""

from __future__ import annotations

import json
import urllib.request
from datetime import UTC, datetime
from typing import Any

from market_evolver.errors import IntegrityViolation, ValidationError
from market_evolver.government.extraction import normalize_rate
from market_evolver.ingestion.connectors import (
    BaseConnector,
    FetchedPayload,
    ParsedItem,
    PersistedPayload,
)
from market_evolver.ingestion.schemas import NormalizedObservation
from market_evolver.schemas import Evidence, Source
from market_evolver.sources.registry import DEFAULT_REGISTRY


class BankOfIsraelPolicyConnector(BaseConnector):
    source_id = "il.boi"
    parser_version = "boi-policy-interest/1"
    dataset_name = "policy-interest-rate"
    endpoint = "https://www.boi.org.il/PublicApi/GetInterest"

    def fetch(self, dataset: str) -> FetchedPayload:
        if dataset != self.dataset_name:
            raise ValidationError(f"unsupported BOI policy dataset: {dataset}")
        request = urllib.request.Request(
            self.endpoint,
            headers={"Accept": "application/json", "User-Agent": "MarketEvolver/0.7"},
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return FetchedPayload(
                response.read(),
                response.geturl(),
                response.headers.get_content_type(),
            )

    def normalize(self, payload: PersistedPayload) -> PersistedPayload:
        if (
            payload.observed.fetched.content_type
            not in DEFAULT_REGISTRY.get(self.source_id).expected_content_types
        ):
            raise IntegrityViolation("unexpected BOI policy content type")
        return payload

    def parse(self, payload: PersistedPayload, dataset: str) -> tuple[ParsedItem, ...]:
        if dataset != self.dataset_name:
            raise ValidationError(f"unsupported BOI policy dataset: {dataset}")
        try:
            document = json.loads(payload.observed.fetched.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IntegrityViolation("invalid BOI policy JSON") from exc
        if not isinstance(document, dict) or "currentInterest" not in document:
            raise IntegrityViolation("BOI policy payload lacks currentInterest")
        published = _optional_timestamp(document.get("lastUpdate"))
        observed = payload.observed.first_observed_at
        period = (published or observed).date()
        next_decision = _optional_timestamp(document.get("nextInterestDate"))
        return (
            ParsedItem(
                item_key="boi-policy-rate",
                period_start=period,
                period_end=period,
                published_at=published,
                effective_at=published,
                superseded_at=None,
                value=normalize_rate(document["currentInterest"]),
                unit="percent",
            ),
            ParsedItem(
                item_key="boi-next-rate-decision",
                period_start=(next_decision or observed).date(),
                period_end=(next_decision or observed).date(),
                published_at=published,
                effective_at=next_decision,
                superseded_at=None,
                value=(next_decision.isoformat() if next_decision else "unknown"),
                unit="scheduled decision timestamp",
            ),
        )

    def emit_evidence(
        self, item: ParsedItem, source: Source, observation: NormalizedObservation
    ) -> Evidence:
        if item.item_key == "boi-policy-rate":
            claim = f"Bank of Israel published current policy interest rate {item.value}%"
        else:
            claim = f"Bank of Israel published next rate decision date {item.value}"
        return Evidence(
            claim=claim,
            source_ids=(source.provenance_id,),
            observed_at=observation.first_observed_at,
            excerpt_digest=observation.provenance_id,
        )


class DisabledGovernmentConnector:
    parser_version = "disabled/0"

    def __init__(self, source_id: str) -> None:
        self.source_id = source_id

    def fetch(self, dataset: str) -> FetchedPayload:
        raise ValidationError(
            f"government connector is disabled pending contract review: {dataset}"
        )


def _optional_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise IntegrityViolation("BOI policy timestamp must be a string")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise IntegrityViolation("malformed BOI policy timestamp") from exc
    if parsed.tzinfo is None:
        raise IntegrityViolation("BOI policy timestamp must include timezone")
    return parsed.astimezone(UTC)
