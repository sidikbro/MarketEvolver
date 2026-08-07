"""Narrow official SEC submissions/companyfacts connector for seeded companies."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

from market_evolver.errors import IntegrityViolation, ValidationError
from market_evolver.ingestion.connectors import FetchedPayload

_ALLOWED_CIKS = {"0001003935", "0001027664", "0000818686", "0000941221"}


@dataclass(frozen=True, slots=True)
class SecFilingMetadata:
    accession_number: str
    form_type: str
    filed_at: datetime
    report_date: date
    primary_document: str


@dataclass(frozen=True, slots=True)
class SecFact:
    concept: str
    value: str
    unit: str
    fiscal_period_end: date
    filed_at: datetime
    accession_number: str
    form_type: str


class SecEdgarConnector:
    source_id = "us.sec.edgar"
    parser_version = "sec-edgar-json/1"
    max_bytes = 20_000_000

    def __init__(self, user_agent: str) -> None:
        if "@" not in user_agent or len(user_agent.strip()) < 8:
            raise ValidationError("SEC user agent must identify an organization and contact")
        self.user_agent = user_agent

    def fetch_submissions(self, cik: str) -> FetchedPayload:
        normalized = self._cik(cik)
        return self._fetch(f"https://data.sec.gov/submissions/CIK{normalized}.json")

    def fetch_companyfacts(self, cik: str) -> FetchedPayload:
        normalized = self._cik(cik)
        return self._fetch(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{normalized}.json")

    def parse_filings(self, payload: bytes) -> tuple[SecFilingMetadata, ...]:
        document = _json(payload)
        recent = document.get("filings", {}).get("recent", {})
        required = ("accessionNumber", "filingDate", "reportDate", "form", "primaryDocument")
        if not all(isinstance(recent.get(name), list) for name in required):
            raise IntegrityViolation("malformed SEC submissions metadata")
        lengths = {len(recent[name]) for name in required}
        if len(lengths) != 1:
            raise IntegrityViolation("inconsistent SEC submissions columns")
        filings = []
        try:
            for accession, filed, report, form, document_name in zip(
                *(recent[name] for name in required), strict=True
            ):
                if form not in {"10-K", "10-Q", "20-F", "6-K", "40-F"}:
                    continue
                filings.append(
                    SecFilingMetadata(
                        str(accession),
                        str(form),
                        datetime.combine(date.fromisoformat(str(filed)), datetime.min.time(), UTC),
                        date.fromisoformat(str(report)),
                        str(document_name),
                    )
                )
        except (TypeError, ValueError) as exc:
            raise IntegrityViolation("malformed SEC filing metadata value") from exc
        return tuple(filings)

    def parse_facts(self, payload: bytes) -> tuple[SecFact, ...]:
        document = _json(payload)
        us_gaap = document.get("facts", {}).get("us-gaap", {})
        if not isinstance(us_gaap, dict):
            raise IntegrityViolation("malformed SEC companyfacts")
        output: list[SecFact] = []
        try:
            for concept in (
                "Revenues",
                "SalesRevenueNet",
                "OperatingIncomeLoss",
                "NetIncomeLoss",
                "CashAndCashEquivalentsAtCarryingValue",
                "Assets",
                "Liabilities",
                "StockholdersEquity",
                "EarningsPerShareDiluted",
                "NetCashProvidedByUsedInOperatingActivities",
                "PaymentsToAcquirePropertyPlantAndEquipment",
                "CommonStocksIncludingAdditionalPaidInCapital",
            ):
                fact = us_gaap.get(concept)
                if not isinstance(fact, dict) or not isinstance(fact.get("units"), dict):
                    continue
                for unit, rows in fact["units"].items():
                    if not isinstance(rows, list):
                        continue
                    for row in rows:
                        if not isinstance(row, dict) or not all(
                            key in row for key in ("val", "end", "filed", "accn", "form")
                        ):
                            continue
                        output.append(
                            SecFact(
                                concept=concept,
                                value=str(row["val"]),
                                unit=str(unit),
                                fiscal_period_end=date.fromisoformat(str(row["end"])),
                                filed_at=datetime.combine(
                                    date.fromisoformat(str(row["filed"])),
                                    datetime.min.time(),
                                    UTC,
                                ),
                                accession_number=str(row["accn"]),
                                form_type=str(row["form"]),
                            )
                        )
        except (TypeError, ValueError) as exc:
            raise IntegrityViolation("malformed SEC fact value") from exc
        return tuple(output)

    def _fetch(self, uri: str) -> FetchedPayload:
        request = urllib.request.Request(
            uri,
            headers={
                "Accept": "application/json",
                "User-Agent": self.user_agent,
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read(self.max_bytes + 1)
            if len(body) > self.max_bytes:
                raise IntegrityViolation("SEC payload exceeds configured size limit")
            return FetchedPayload(body, response.geturl(), response.headers.get_content_type())

    @staticmethod
    def _cik(value: str) -> str:
        normalized = value.zfill(10)
        if normalized not in _ALLOWED_CIKS:
            raise ValidationError("SEC connector is restricted to the curated CIK allowlist")
        return normalized


def _json(payload: bytes) -> dict[str, Any]:
    try:
        document = json.loads(payload)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegrityViolation("malformed SEC JSON") from exc
    if not isinstance(document, dict):
        raise IntegrityViolation("SEC JSON root must be an object")
    return document
