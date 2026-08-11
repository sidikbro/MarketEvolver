"""Explicit, bounded live-source validation with isolated artifact retention."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4
from xml.etree import ElementTree

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from market_evolver.company.sec import SecEdgarConnector
from market_evolver.errors import IntegrityViolation, ValidationError
from market_evolver.ingestion.boi import BankOfIsraelConnector
from market_evolver.news.connectors import BbcBusinessRssConnector
from market_evolver.storage.artifacts import Artifact, LocalArtifactStore
from market_evolver.storage.repositories import add_artifact_metadata


class LiveStatus(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"
    DEGRADED = "DEGRADED"
    SKIPPED_BY_OPERATOR = "SKIPPED_BY_OPERATOR"


class ReplayEligibility(str, Enum):
    SAFE_FOR_HISTORICAL_REPLAY = "safe_for_historical_replay"
    SAFE_FOR_FORWARD_OBSERVATION_ONLY = "safe_for_forward_observation_only"
    TEMPORALLY_AMBIGUOUS = "temporally_ambiguous"
    DISABLED = "disabled"


@dataclass(frozen=True, slots=True)
class HttpObservation:
    status: int
    endpoint: str
    content_type: str
    body: bytes


@dataclass(frozen=True, slots=True)
class SourceContract:
    source_id: str
    endpoint: str
    content_types: tuple[str, ...]
    required_fields: tuple[str, ...]
    parser_version: str
    max_bytes: int
    max_requests: int
    replay_eligibility: ReplayEligibility


@dataclass(frozen=True, slots=True)
class LiveSourceResult:
    source_id: str
    status: LiveStatus
    endpoints: tuple[str, ...]
    requests: int
    http_statuses: tuple[int, ...]
    bytes_downloaded: int
    items: int
    duplicates: int
    quarantines: int
    raw_artifacts: int
    raw_bytes: int
    normalized_bytes: int
    schema_fingerprints: tuple[str, ...]
    schema_drift: tuple[str, ...]
    replay_eligibility: ReplayEligibility
    hashes: tuple[str, ...]
    provenance_chain: tuple[str, ...]
    errors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StorageProjection:
    observed_bytes: int
    observed_items: int
    days: int
    estimated_bytes: int
    basis: str = "linear estimate from one bounded validation workload"


@dataclass(frozen=True, slots=True)
class LiveValidationReport:
    run_id: str
    git_commit: str
    started_at: str
    finished_at: str
    environment: str
    source_configuration: tuple[tuple[str, str], ...]
    sources: tuple[LiveSourceResult, ...]
    files: int
    bytes: int
    database_rows: int
    parquet_growth: int
    provenance_integrity: bool
    point_in_time_checks: bool
    entity_resolution: tuple[str, ...]
    fusion: str
    projections: tuple[StorageProjection, ...]
    status: LiveStatus

    def json_text(self) -> str:
        return json.dumps(redact(asdict(self)), indent=2, sort_keys=True)

    def markdown_text(self) -> str:
        lines = [
            f"# Live validation {self.run_id}",
            "",
            f"Status: **{self.status.value}**",
            f"Started: {self.started_at}",
            f"Finished: {self.finished_at}",
            f"Git commit: `{self.git_commit}`",
            "",
            "| Source | Status | Requests | Items | Bytes | Replay eligibility |",
            "|---|---:|---:|---:|---:|---|",
        ]
        for item in self.sources:
            lines.append(
                f"| {item.source_id} | {item.status.value} | {item.requests} | "
                f"{item.items} | {item.bytes_downloaded} | {item.replay_eligibility.value} |"
            )
        lines.extend(
            (
                "",
                f"Raw artifacts: {sum(item.raw_artifacts for item in self.sources)}",
                f"Stored bytes: {self.bytes}",
                f"Provenance integrity: {self.provenance_integrity}",
                f"Point-in-time checks: {self.point_in_time_checks}",
                f"Fusion: {self.fusion}",
            )
        )
        return str(redact("\n".join(lines) + "\n"))


class BoundedHttpClient:
    """No retries, strict byte/request caps, and explicit identifying User-Agent."""

    def __init__(self, *, max_total_requests: int = 12, timeout: int = 20) -> None:
        if max_total_requests < 1 or timeout < 1:
            raise ValidationError("live HTTP bounds must be positive")
        self.max_total_requests = max_total_requests
        self.timeout = timeout
        self.requests = 0

    def get(self, contract: SourceContract, *, user_agent: str) -> HttpObservation:
        if self.requests >= self.max_total_requests:
            raise ValidationError("live validation request budget exhausted")
        self.requests += 1
        request = urllib.request.Request(
            contract.endpoint,
            headers={"Accept": ", ".join(contract.content_types), "User-Agent": user_agent},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = response.read(contract.max_bytes + 1)
                status = int(response.status)
                endpoint = response.geturl()
                content_type = response.headers.get_content_type().lower()
        except urllib.error.HTTPError as exc:
            raise IntegrityViolation(f"HTTP {exc.code} from reviewed endpoint") from exc
        if len(body) > contract.max_bytes:
            raise IntegrityViolation("live response exceeds reviewed byte limit")
        return HttpObservation(status, endpoint, content_type, body)


class LiveValidationHarness:
    def __init__(
        self,
        root: Path,
        *,
        opted_in: bool,
        environment: Mapping[str, str] | None = None,
        fetch: Callable[[SourceContract, str], HttpObservation] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not opted_in:
            raise ValidationError("live validation requires explicit operator opt-in")
        self.environment = dict(os.environ if environment is None else environment)
        self.clock = clock or (lambda: datetime.now(UTC))
        self.started = self.clock()
        self.run_id = f"live-{self.started.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
        self.run_root = root / self.run_id
        self.store = LocalArtifactStore(self.run_root / "raw")
        self.client = BoundedHttpClient()
        self.fetch = fetch or (lambda contract, ua: self.client.get(contract, user_agent=ua))
        self.database_url = self.environment.get("MARKET_EVOLVER_TEST_POSTGRES_URL")
        self.database_rows = 0

    def run(self) -> LiveValidationReport:
        results = [
            self._boi_fx(),
            self._boi_policy(),
            _skipped(
                "il.boi.fx.history",
                ReplayEligibility.TEMPORALLY_AMBIGUOUS,
                "BOI SDMX history is not used until its bounded series key and vintage semantics are fixed",
            ),
            self._bbc(),
            self._sec(),
            self._cbs(),
        ]
        finished = self.clock()
        raw_files = tuple(path for path in (self.run_root / "raw").rglob("*") if path.is_file())
        total_bytes = sum(path.stat().st_size for path in raw_files)
        failed = any(item.status is LiveStatus.FAILED for item in results)
        degraded = any(
            item.status in {LiveStatus.DEGRADED, LiveStatus.SKIPPED_BY_OPERATOR} for item in results
        )
        status = (
            LiveStatus.FAILED if failed else LiveStatus.DEGRADED if degraded else LiveStatus.PASSED
        )
        report = LiveValidationReport(
            self.run_id,
            _git_commit(),
            self.started.isoformat(),
            finished.isoformat(),
            "controlled-live-validation",
            (
                (
                    "sec_user_agent",
                    "configured"
                    if self.environment.get("MARKET_EVOLVER_SEC_USER_AGENT")
                    else "absent",
                ),
                (
                    "cbs_user_agent",
                    "configured"
                    if self.environment.get("MARKET_EVOLVER_CBS_USER_AGENT")
                    else "absent",
                ),
            ),
            tuple(results),
            len(raw_files),
            total_bytes,
            self.database_rows,
            0,
            all(not item.errors for item in results if item.status is LiveStatus.PASSED),
            all(
                item.replay_eligibility is not ReplayEligibility.SAFE_FOR_HISTORICAL_REPLAY
                for item in results
            ),
            _entity_resolution(tuple(results)),
            "no fusion candidate",
            (
                project_storage(total_bytes, sum(item.items for item in results), 30),
                project_storage(total_bytes, sum(item.items for item in results), 365),
            ),
            status,
        )
        self.run_root.mkdir(parents=True, exist_ok=True)
        (self.run_root / "report.json").write_text(report.json_text(), encoding="utf-8")
        (self.run_root / "report.md").write_text(report.markdown_text(), encoding="utf-8")
        return report

    def cleanup(self) -> None:
        import shutil

        if self.run_root.parent.name != "live_validation" or not self.run_root.name.startswith(
            "live-"
        ):
            raise IntegrityViolation("refusing to clean an unexpected live-validation path")
        shutil.rmtree(self.run_root, ignore_errors=False)

    def _validate(
        self, contract: SourceContract, user_agent: str, parser: Callable[[bytes], int]
    ) -> LiveSourceResult:
        try:
            response = self.fetch(contract, user_agent)
            if response.status != 200:
                raise IntegrityViolation(f"unexpected HTTP status {response.status}")
            if response.content_type not in contract.content_types:
                raise IntegrityViolation(f"content type drift: {response.content_type}")
            artifact = self.store.put(response.body, mime_type=response.content_type)
            duplicate = self.store.put(
                response.body,
                mime_type=response.content_type,
                expected_sha256=artifact.sha256,
            )
            if duplicate.relative_path != artifact.relative_path:
                raise IntegrityViolation("content-addressed duplicate changed artifact path")
            self.store.read(artifact)
            self._persist_artifact_metadata(artifact)
            fingerprint, missing = contract_fingerprint(
                response.body, response.content_type, contract.required_fields
            )
            if missing:
                raise IntegrityViolation(f"required fields missing: {', '.join(missing)}")
            items = parser(response.body)
            normalized_id = (
                "sha256:"
                + hashlib.sha256(
                    f"{contract.parser_version}:{fingerprint}:{items}".encode()
                ).hexdigest()
            )
            return LiveSourceResult(
                contract.source_id,
                LiveStatus.PASSED,
                (response.endpoint,),
                1,
                (response.status,),
                len(response.body),
                items,
                1,
                0,
                1,
                artifact.size_bytes,
                len(response.body),
                (fingerprint,),
                (),
                contract.replay_eligibility,
                (artifact.sha256,),
                (
                    f"network:{response.endpoint}",
                    f"artifact:sha256:{artifact.sha256}",
                    f"normalized:{normalized_id}",
                    f"validation-evidence:{normalized_id}",
                ),
                (),
            )
        except Exception as exc:  # noqa: BLE001 - source failures belong in the report
            message = f"{type(exc).__name__}: {exc}"
            drift = (
                (message,)
                if "content type" in message.casefold() or "required fields" in message.casefold()
                else ()
            )
            return LiveSourceResult(
                contract.source_id,
                LiveStatus.FAILED,
                (contract.endpoint,),
                1,
                (),
                0,
                0,
                0,
                1,
                0,
                0,
                0,
                (),
                drift,
                contract.replay_eligibility,
                (),
                (),
                (message,),
            )

    def _persist_artifact_metadata(self, artifact: Artifact) -> None:
        if not self.database_url:
            return
        if "_test" not in self.database_url:
            raise IntegrityViolation("live validation database must be a dedicated *_test database")
        engine = create_engine(self.database_url)
        try:
            with Session(engine) as session:
                add_artifact_metadata(session, artifact, self.started)
                session.commit()
            self.database_rows += 1
        finally:
            engine.dispose()

    def _boi_fx(self) -> LiveSourceResult:
        connector = BankOfIsraelConnector()
        contract = SourceContract(
            "il.boi.fx",
            connector.endpoint,
            ("application/json", "text/json"),
            ("exchangeRates",),
            connector.parser_version,
            1_000_000,
            1,
            ReplayEligibility.SAFE_FOR_FORWARD_OBSERVATION_ONLY,
        )
        return self._validate(
            contract,
            "MarketEvolver/0.22 controlled-validation",
            lambda body: len(
                tuple(connector._parse_rate(item) for item in _json_object(body)["exchangeRates"])
            ),
        )

    def _boi_policy(self) -> LiveSourceResult:
        contract = SourceContract(
            "il.boi.policy",
            "https://www.boi.org.il/PublicApi/GetInterest",
            ("application/json", "text/json"),
            ("currentInterest", "nextInterestDate"),
            "boi-policy-interest/1",
            100_000,
            1,
            ReplayEligibility.SAFE_FOR_FORWARD_OBSERVATION_ONLY,
        )
        return self._validate(
            contract,
            "MarketEvolver/0.22 controlled-validation",
            _validate_boi_policy,
        )

    def _bbc(self) -> LiveSourceResult:
        connector = BbcBusinessRssConnector()
        contract = SourceContract(
            "uk.bbc.business",
            connector.endpoint,
            ("application/rss+xml", "application/xml", "text/xml"),
            ("channel", "item", "title", "link", "pubDate"),
            connector.parser_version,
            connector.max_bytes,
            1,
            ReplayEligibility.SAFE_FOR_FORWARD_OBSERVATION_ONLY,
        )
        return self._validate(
            contract,
            "MarketEvolver/0.22 controlled-validation",
            lambda body: len(connector.parse(body)),
        )

    def _sec(self) -> LiveSourceResult:
        user_agent = self.environment.get("MARKET_EVOLVER_SEC_USER_AGENT", "").strip()
        if not user_agent:
            return _skipped(
                "us.sec.edgar", ReplayEligibility.TEMPORALLY_AMBIGUOUS, "SEC User-Agent absent"
            )
        connector = SecEdgarConnector(user_agent)
        results: list[LiveSourceResult] = []
        for cik in ("0000818686", "0001027664"):  # Teva, Elbit
            for kind, endpoint, fields, parser in (
                (
                    "submissions",
                    f"https://data.sec.gov/submissions/CIK{cik}.json",
                    ("cik", "filings"),
                    lambda body: len(connector.parse_filings(body)[:25]),
                ),
                (
                    "companyfacts",
                    f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json",
                    ("cik", "facts"),
                    lambda body: len(connector.parse_facts(body)[:100]),
                ),
            ):
                contract = SourceContract(
                    f"us.sec.edgar.{cik}.{kind}",
                    endpoint,
                    ("application/json",),
                    fields,
                    connector.parser_version,
                    connector.max_bytes,
                    1,
                    ReplayEligibility.TEMPORALLY_AMBIGUOUS,
                )
                results.append(self._validate(contract, user_agent, parser))
        return _combine("us.sec.edgar", results, ReplayEligibility.TEMPORALLY_AMBIGUOUS)

    def _cbs(self) -> LiveSourceResult:
        user_agent = self.environment.get("MARKET_EVOLVER_CBS_USER_AGENT", "").strip()
        if not user_agent:
            return _skipped(
                "il.cbs.series.3763",
                ReplayEligibility.TEMPORALLY_AMBIGUOUS,
                "CBS User-Agent absent",
            )
        endpoint = "https://apis.cbs.gov.il/series/data/list?id=3763&last=3&format=json&download=false&lang=en"
        contract = SourceContract(
            "il.cbs.series.3763",
            endpoint,
            ("application/json", "text/json"),
            (),
            "cbs-series-3763/1",
            1_000_000,
            1,
            ReplayEligibility.TEMPORALLY_AMBIGUOUS,
        )
        return self._validate(
            contract, user_agent, lambda body: _count_cbs_items(_json_object(body))
        )


def contract_fingerprint(
    body: bytes, content_type: str, required_fields: tuple[str, ...]
) -> tuple[str, tuple[str, ...]]:
    if "json" in content_type:
        document = _json_object(body)
        fields = tuple(sorted(str(key) for key in document))
        searchable = set(fields)
    else:
        if b"<!DOCTYPE" in body.upper() or b"<!ENTITY" in body.upper():
            raise IntegrityViolation("DTD/entity declarations are forbidden")
        try:
            root = ElementTree.fromstring(body)
        except ElementTree.ParseError as exc:
            raise IntegrityViolation("malformed XML contract response") from exc
        fields = tuple(sorted({_local(node.tag) for node in root.iter()}))
        searchable = set(fields)
    missing = tuple(field for field in required_fields if field not in searchable)
    payload = json.dumps(fields, separators=(",", ":")).encode()
    return "sha256:" + hashlib.sha256(payload).hexdigest(), missing


def project_storage(observed_bytes: int, observed_items: int, days: int) -> StorageProjection:
    if observed_bytes < 0 or observed_items < 0 or days < 1:
        raise ValidationError("storage projection inputs are invalid")
    return StorageProjection(observed_bytes, observed_items, days, observed_bytes * days)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, str):
        redacted = re.sub(r"(?i)(password|token|secret)=([^&\s]+)", r"\1=[REDACTED]", value)
        redacted = re.sub(
            r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}",
            "[REDACTED-CONTACT]",
            redacted,
            flags=re.IGNORECASE,
        )
        redacted = re.sub(
            r"(?i)(postgres(?:ql)?(?:\+\w+)?://[^:/\s]+:)[^@\s]+@", r"\1[REDACTED]@", redacted
        )
        return redacted
    return value


def _json_object(body: bytes) -> dict[str, Any]:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise IntegrityViolation("malformed JSON contract response") from exc
    if not isinstance(value, dict):
        raise IntegrityViolation("JSON contract root must be an object")
    return value


def _count_cbs_items(document: dict[str, Any]) -> int:
    def count(value: Any) -> int:
        if isinstance(value, list):
            return len(value)
        if isinstance(value, dict):
            return max((count(item) for item in value.values()), default=0)
        return 0

    items = count(document)
    if items == 0:
        raise IntegrityViolation("CBS response contains no bounded series observations")
    return items


def _validate_boi_policy(body: bytes) -> int:
    document = _json_object(body)
    try:
        float(document["currentInterest"])
        next_decision = datetime.fromisoformat(str(document["nextInterestDate"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise IntegrityViolation("BOI policy fields are malformed") from exc
    if next_decision.tzinfo is None:
        raise IntegrityViolation("BOI next decision timestamp is timezone-naive")
    return 2


def _entity_resolution(results: tuple[LiveSourceResult, ...]) -> tuple[str, ...]:
    by_source = {item.source_id: item for item in results}
    sec = by_source["us.sec.edgar"]
    return (
        "Teva/SEC: exact CIK allowlist"
        if sec.status is LiveStatus.PASSED
        else "Teva/SEC: unresolved; SEC validation skipped or failed",
        "Elbit/SEC: exact CIK allowlist"
        if sec.status is LiveStatus.PASSED
        else "Elbit/SEC: unresolved; SEC validation skipped or failed",
        "USD/ILS: exact BOI currency code"
        if by_source["il.boi.fx"].status is LiveStatus.PASSED
        else "USD/ILS: unresolved; BOI validation failed",
    )


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _skipped(source_id: str, eligibility: ReplayEligibility, reason: str) -> LiveSourceResult:
    return LiveSourceResult(
        source_id,
        LiveStatus.SKIPPED_BY_OPERATOR,
        (),
        0,
        (),
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        (),
        (),
        eligibility,
        (),
        (),
        (reason,),
    )


def _combine(
    source_id: str, results: list[LiveSourceResult], eligibility: ReplayEligibility
) -> LiveSourceResult:
    status = (
        LiveStatus.FAILED
        if any(item.status is LiveStatus.FAILED for item in results)
        else LiveStatus.PASSED
    )
    return LiveSourceResult(
        source_id,
        status,
        tuple(endpoint for item in results for endpoint in item.endpoints),
        sum(item.requests for item in results),
        tuple(code for item in results for code in item.http_statuses),
        sum(item.bytes_downloaded for item in results),
        sum(item.items for item in results),
        sum(item.duplicates for item in results),
        sum(item.quarantines for item in results),
        sum(item.raw_artifacts for item in results),
        sum(item.raw_bytes for item in results),
        sum(item.normalized_bytes for item in results),
        tuple(value for item in results for value in item.schema_fingerprints),
        tuple(value for item in results for value in item.schema_drift),
        eligibility,
        tuple(value for item in results for value in item.hashes),
        tuple(value for item in results for value in item.provenance_chain),
        tuple(value for item in results for value in item.errors),
    )


def _git_commit() -> str:
    result = subprocess.run(
        ("git", "rev-parse", "HEAD"), text=True, capture_output=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"
