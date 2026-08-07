"""Bank of Israel representative exchange-rate connector."""

from __future__ import annotations

import json
import urllib.request
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from market_evolver.errors import IntegrityViolation, ValidationError
from market_evolver.ingestion.connectors import (
    BaseConnector,
    FetchedPayload,
    ParsedItem,
    PersistedPayload,
)
from market_evolver.ingestion.schemas import NormalizedObservation
from market_evolver.schemas import Evidence, Source
from market_evolver.sources.registry import DEFAULT_REGISTRY


class BankOfIsraelConnector(BaseConnector):
    source_id = "il.boi"
    parser_version = "boi-exchange-rates/1"
    dataset_name = "representative-exchange-rates"
    endpoint = "https://www.boi.org.il/PublicApi/GetExchangeRates"

    def fetch(self, dataset: str) -> FetchedPayload:
        if dataset != self.dataset_name:
            raise ValidationError(f"unsupported Bank of Israel dataset: {dataset}")
        request = urllib.request.Request(
            self.endpoint,
            headers={
                "Accept": "application/json",
                "User-Agent": "MarketEvolver/0.3 (+research-only)",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return FetchedPayload(
                body=response.read(),
                source_uri=response.geturl(),
                content_type=response.headers.get_content_type(),
            )

    def normalize(self, payload: PersistedPayload) -> PersistedPayload:
        definition = DEFAULT_REGISTRY.get(self.source_id)
        if payload.observed.fetched.content_type not in definition.expected_content_types:
            raise IntegrityViolation(
                f"unexpected BOI content type: {payload.observed.fetched.content_type}"
            )
        return payload

    def parse(self, payload: PersistedPayload, dataset: str) -> tuple[ParsedItem, ...]:
        if dataset != self.dataset_name:
            raise ValidationError(f"unsupported Bank of Israel dataset: {dataset}")
        try:
            document = json.loads(payload.observed.fetched.body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IntegrityViolation("invalid Bank of Israel JSON payload") from exc
        rates = document.get("exchangeRates") if isinstance(document, dict) else None
        if not isinstance(rates, list) or not rates:
            raise IntegrityViolation("BOI payload has no exchangeRates")
        return tuple(self._parse_rate(item) for item in rates)

    def emit_evidence(
        self,
        item: ParsedItem,
        source: Source,
        observation: NormalizedObservation,
    ) -> Evidence:
        return Evidence(
            claim=(
                f"Bank of Israel representative rate {item.item_key} was "
                f"{item.value} {item.unit} for {item.period_start.isoformat()}"
            ),
            source_ids=(source.provenance_id,),
            observed_at=observation.first_observed_at,
            excerpt_digest=observation.provenance_id,
        )

    def _parse_rate(self, item: Any) -> ParsedItem:
        if not isinstance(item, dict):
            raise IntegrityViolation("BOI exchange-rate item must be an object")
        key = item.get("key")
        value = item.get("currentExchangeRate")
        unit = item.get("unit")
        last_update = item.get("lastUpdate")
        if (
            not isinstance(key, str)
            or not key
            or value is None
            or not isinstance(unit, int)
            or unit <= 0
            or not isinstance(last_update, str)
        ):
            raise IntegrityViolation("BOI exchange-rate item is missing required fields")
        try:
            normalized_value = format(Decimal(str(value)), "f")
        except InvalidOperation as exc:
            raise IntegrityViolation("BOI exchange rate is not numeric") from exc
        published = _parse_boi_timestamp(last_update)
        period = published.date()
        return ParsedItem(
            item_key=key,
            period_start=period,
            period_end=period,
            published_at=published,
            effective_at=published,
            superseded_at=None,
            value=normalized_value,
            unit=f"ILS per {unit} {key}",
        )


def _parse_boi_timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise IntegrityViolation("invalid BOI lastUpdate timestamp") from exc
    if parsed.tzinfo is None:
        raise IntegrityViolation("BOI lastUpdate timestamp must include a timezone")
    return parsed.astimezone(UTC)
