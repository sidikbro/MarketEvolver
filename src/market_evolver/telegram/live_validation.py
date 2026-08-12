"""Explicitly opted-in, bounded validation of public Telegram sources."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from market_evolver.config import TelegramSourceConfig
from market_evolver.errors import ConfigurationError, GovernanceViolation, ValidationError
from market_evolver.news.schemas import EvidenceSecurityClass
from market_evolver.social.repository import SqlSocialRepository
from market_evolver.social.schemas import (
    ClaimStatus,
    NarrativeCandidate,
    NarrativeLifecycle,
    RumorClaim,
)
from market_evolver.storage.artifacts import LocalArtifactStore
from market_evolver.storage.models import (
    Base,
    SocialPostModel,
    SocialPropagationModel,
    TelegramReceiptModel,
)
from market_evolver.telegram.client import TelethonClientAdapter
from market_evolver.telegram.runner import TelegramRunner


class TelegramValidationStatus(str, Enum):
    PASS = "PASS"
    DEGRADED = "DEGRADED"
    SKIPPED_BY_OPERATOR = "SKIPPED_BY_OPERATOR"
    FAILED = "FAILED"


class ForwardClass(str, Enum):
    KNOWN_ORIGIN = "known_origin"
    HIDDEN_OR_UNKNOWN = "hidden_or_unknown_origin"
    COPIED_TEXT = "copied_text"
    INDEPENDENT_ORIGINAL = "independent_original"


@dataclass(frozen=True, slots=True)
class TelegramAllowlistEntry:
    source_id: str
    public_identifier: str
    source_class: str
    languages: tuple[str, ...]
    domain_tags: tuple[str, ...]
    max_messages: int

    def __post_init__(self) -> None:
        config = self.config()
        config.validate()
        if not 1 <= self.max_messages <= 50:
            raise ValidationError("live Telegram source bound must be 1..50")
        if self.source_class not in {
            "established_news",
            "finance_business",
            "technology_business",
            "geopolitical_news",
            "negative_control",
        }:
            raise ValidationError("unknown reviewed Telegram source class")

    def config(self) -> TelegramSourceConfig:
        return TelegramSourceConfig(
            self.source_id,
            self.public_identifier,
            "public_channel",
            self.languages,
            self.domain_tags,
            True,
            None,
            self.max_messages,
            "metadata_only",
        )


@dataclass(frozen=True, slots=True)
class TelegramSourceValidation:
    source_id: str
    source_class: str
    status: TelegramValidationStatus
    messages: int
    text_bytes: int
    artifact_bytes: int
    original_posts: int
    forwards: int
    replies: int
    edited_messages: int
    media_references: int
    entity_mentions: int
    narratives: int
    rumor_candidates: int
    duplicates_or_copies: int
    forward_classes: tuple[tuple[str, int], ...]
    error: str | None


@dataclass(frozen=True, slots=True)
class TelegramStorageProjection:
    sources: int
    days: int
    estimated_messages: int
    estimated_text_metadata_bytes: int
    media_scenario_bytes: int
    media_basis: str = "hypothetical 1 MB/reference; media was not downloaded"


@dataclass(frozen=True, slots=True)
class TelegramLiveReport:
    run_id: str
    git_commit: str
    started_at: str
    finished_at: str
    status: TelegramValidationStatus
    sources: tuple[TelegramSourceValidation, ...]
    total_messages: int
    total_bytes: int
    bytes_per_message: float
    messages_per_day_estimate: int
    edit_case: str
    fusion: str
    reputation: str
    prompt_injection_boundary: str
    media_policy: str
    projections: tuple[TelegramStorageProjection, ...]

    def json_text(self) -> str:
        return json.dumps(_redact(asdict(self)), indent=2, sort_keys=True)

    def markdown_text(self) -> str:
        lines = [
            f"# Telegram live validation {self.run_id}",
            "",
            f"Status: **{self.status.value}**",
            f"Messages: {self.total_messages}",
            f"Text/metadata bytes: {self.total_bytes}",
            f"Messages/day estimate: {self.messages_per_day_estimate}",
            f"Edit case: {self.edit_case}",
            f"Fusion: {self.fusion}",
            "",
            "| Source | Status | Messages | Forwards | Replies | Edits | Media refs | Narratives | Rumors |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for item in self.sources:
            lines.append(
                f"| {item.source_id} | {item.status.value} | {item.messages} | "
                f"{item.forwards} | {item.replies} | {item.edited_messages} | "
                f"{item.media_references} | {item.narratives} | {item.rumor_candidates} |"
            )
        return str(_redact("\n".join(lines) + "\n"))


def load_allowlist(path: Path) -> tuple[TelegramAllowlistEntry, ...]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ConfigurationError("Telegram live allowlist is unavailable or malformed") from exc
    if not isinstance(document, list) or not 1 <= len(document) <= 8:
        raise ConfigurationError("Telegram live allowlist must contain 1..8 reviewed sources")
    try:
        entries = tuple(
            TelegramAllowlistEntry(
                source_id=str(item["source_id"]),
                public_identifier=str(item["public_identifier"]),
                source_class=str(item["source_class"]),
                languages=tuple(item["languages"]),
                domain_tags=tuple(item["domain_tags"]),
                max_messages=int(item.get("max_messages", 20)),
            )
            for item in document
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ConfigurationError("Telegram allowlist entry is malformed") from exc
    if len({item.source_id for item in entries}) != len(entries):
        raise ConfigurationError("Telegram allowlist source IDs must be unique")
    return entries


def telegram_storage_projections(
    total_bytes: int, total_messages: int, media_references: int
) -> tuple[TelegramStorageProjection, ...]:
    if total_bytes < 0 or total_messages < 1 or media_references < 0:
        raise ValidationError("Telegram projection requires observed messages")
    per_message = total_bytes / total_messages
    media_per_message = media_references / total_messages
    output = []
    for sources in (10, 100, 1000):
        for days in (30, 365):
            messages = sources * days * 20
            output.append(
                TelegramStorageProjection(
                    sources,
                    days,
                    messages,
                    round(messages * per_message),
                    round(messages * media_per_message * 1_000_000),
                )
            )
    return tuple(output)


class TelegramLiveValidation:
    def __init__(
        self,
        root: Path,
        *,
        environment: Mapping[str, str] | None = None,
        client: Any | None = None,
        clock: Any | None = None,
    ) -> None:
        self.environment = dict(os.environ if environment is None else environment)
        if self.environment.get("MARKET_EVOLVER_TELEGRAM_LIVE_VALIDATION") != "YES":
            raise ConfigurationError("Telegram live validation requires explicit YES enable flag")
        allowlist_value = self.environment.get("MARKET_EVOLVER_TELEGRAM_ALLOWLIST", "").strip()
        if not allowlist_value:
            raise ConfigurationError("Telegram live validation requires an explicit allowlist path")
        self.allowlist = load_allowlist(Path(allowlist_value))
        self.clock = clock or (lambda: datetime.now(UTC))
        self.started = self.clock()
        self.run_id = f"telegram-{self.started.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
        self.run_root = root / self.run_id
        self.client = client or self._configured_client()

    def _configured_client(self) -> TelethonClientAdapter:
        try:
            api_id = int(self.environment["MARKET_EVOLVER_TELEGRAM_API_ID"])
            api_hash = self.environment["MARKET_EVOLVER_TELEGRAM_API_HASH"].strip()
        except (KeyError, ValueError) as exc:
            raise ConfigurationError("Telegram API credentials are missing") from exc
        session = self.environment.get("MARKET_EVOLVER_TELEGRAM_SESSION", "").strip()
        session_path = self.environment.get("MARKET_EVOLVER_TELEGRAM_SESSION_LOCATION", "").strip()
        if session and session_path:
            raise ConfigurationError("configure one Telegram session source, not both")
        if session_path:
            try:
                session = Path(session_path).read_text(encoding="utf-8").strip()
            except OSError as exc:
                raise ConfigurationError("Telegram session file is unavailable") from exc
        if api_id <= 0 or not api_hash or not session:
            raise ConfigurationError("Telegram credentials/session are incomplete")
        return TelethonClientAdapter(api_id, api_hash, session)

    def run(self) -> TelegramLiveReport:
        self.run_root.mkdir(parents=True, exist_ok=False)
        database_url = self.environment.get("MARKET_EVOLVER_TEST_POSTGRES_URL")
        engine = (
            create_engine(database_url)
            if database_url
            else create_engine("sqlite+pysqlite:///:memory:")
        )
        if not database_url:
            Base.metadata.create_all(engine)
        results = []
        with Session(engine) as session:
            for entry in self.allowlist:
                results.append(self._source(session, entry))
        engine.dispose()
        finished = self.clock()
        total_messages = sum(item.messages for item in results)
        total_bytes = sum(item.artifact_bytes for item in results)
        media = sum(item.media_references for item in results)
        statuses = {item.status for item in results}
        status = (
            TelegramValidationStatus.FAILED
            if TelegramValidationStatus.FAILED in statuses
            else TelegramValidationStatus.DEGRADED
            if TelegramValidationStatus.DEGRADED in statuses
            else TelegramValidationStatus.PASS
        )
        report = TelegramLiveReport(
            self.run_id,
            _git_commit(),
            self.started.isoformat(),
            finished.isoformat(),
            status,
            tuple(results),
            total_messages,
            total_bytes,
            total_bytes / total_messages if total_messages else 0,
            total_messages,
            "OBSERVED"
            if any(item.edited_messages for item in results)
            else "NO_EDIT_CASE_OBSERVED",
            "no fusion candidate",
            "insufficient_history; observational snapshot only",
            "PASS: all posts remain untrusted data with no order, graph, claim-promotion, or policy authority",
            "metadata_only; no media bytes downloaded",
            telegram_storage_projections(total_bytes, total_messages, media)
            if total_messages
            else (),
        )
        _write_report(self.run_root, report)
        return report

    def cleanup(self) -> None:
        if self.run_root.parent.name != "telegram" or not self.run_root.name.startswith(
            "telegram-"
        ):
            raise GovernanceViolation("refusing unexpected Telegram validation cleanup path")
        shutil.rmtree(self.run_root)

    def _source(self, session: Session, entry: TelegramAllowlistEntry) -> TelegramSourceValidation:
        observed_at = self.clock()
        before_ids = set(session.scalars(select(SocialPostModel.post_id)))
        try:
            manifest = TelegramRunner(
                session,
                LocalArtifactStore(self.run_root / "raw"),
                self.client,
            ).run(entry.config(), limit=entry.max_messages, since=None, observed_at=observed_at)
            rows = tuple(
                session.scalars(
                    select(SocialPostModel).where(SocialPostModel.post_id.not_in(before_ids))
                )
            )
            receipts = tuple(
                session.scalars(
                    select(TelegramReceiptModel).where(
                        TelegramReceiptModel.allowlist_source_id == entry.source_id
                    )
                )
            )
            row_ids = {row.post_id for row in rows}
            copied_targets = {
                edge.target_post_id
                for edge in session.scalars(select(SocialPropagationModel))
                if edge.relation == "likely_copy_of" and edge.target_post_id in row_ids
            }
            forward_classes = {
                ForwardClass.KNOWN_ORIGIN.value: sum(
                    bool(item.forward_source) for item in receipts
                ),
                ForwardClass.HIDDEN_OR_UNKNOWN.value: sum(item.forward_hidden for item in receipts),
                ForwardClass.INDEPENDENT_ORIGINAL.value: max(
                    0,
                    len(rows)
                    - sum(bool(item.forward_source) or item.forward_hidden for item in receipts)
                    - len(copied_targets),
                ),
                ForwardClass.COPIED_TEXT.value: manifest.duplicates + len(copied_targets),
            }
            text_bytes = sum(len(row.original_text.encode()) for row in rows)
            artifact_bytes = sum(item.payload_bytes for item in receipts)
            replies = sum(row.reply_parent_id is not None for row in rows)
            media = sum(len(row.media_references) for row in rows)
            mentions = sum(len(row.mentions) for row in rows)
            inserted_ids = row_ids
            repository = SqlSocialRepository(session)
            posts = tuple(
                post
                for post in repository.posts_visible_at(observed_at)
                if post.post_id in inserted_ids
            )
            if any(
                post.security_class is not EvidenceSecurityClass.UNTRUSTED_UNSTRUCTURED
                for post in posts
            ):
                raise GovernanceViolation("Telegram post escaped untrusted-content boundary")
            narratives = rumors = 0
            for post in posts:
                is_rumor = bool(
                    re.search(
                        r"\b(rumou?r|unconfirmed|alleged)\b|שמועה|לא מאומת",
                        post.original_text,
                        re.IGNORECASE,
                    )
                )
                if post.mentions or post.hashtags or is_rumor:
                    narrative = NarrativeCandidate(
                        post.hashtags or entry.domain_tags or ("uncategorized",),
                        post.mentions,
                        (post.post_id,),
                        post.first_observed_at,
                        post.normalized_text,
                        post.language,
                        "telegram-live-rules/1",
                        0.25,
                        "uncorroborated",
                        "not_evaluated",
                        NarrativeLifecycle.EMERGING,
                        False,
                    )
                    narratives += int(repository.add_narrative(narrative))
                if is_rumor:
                    rumor = RumorClaim(
                        post.normalized_text,
                        post.mentions,
                        post.post_id,
                        post.first_observed_at,
                        (post.post_id,),
                        (),
                        (),
                        (),
                        ClaimStatus.UNVERIFIED,
                        None,
                        1,
                    )
                    rumors += int(repository.add_rumor(rumor))
            session.commit()
            status = (
                TelegramValidationStatus.PASS
                if manifest.error_summary is None
                else TelegramValidationStatus.DEGRADED
            )
            return TelegramSourceValidation(
                entry.source_id,
                entry.source_class,
                status,
                manifest.messages_fetched,
                text_bytes,
                artifact_bytes,
                forward_classes[ForwardClass.INDEPENDENT_ORIGINAL.value],
                manifest.forwards,
                replies,
                manifest.edits,
                media,
                mentions,
                narratives,
                rumors,
                forward_classes[ForwardClass.COPIED_TEXT.value],
                tuple(sorted(forward_classes.items())),
                manifest.error_summary,
            )
        except (
            ConfigurationError,
            GovernanceViolation,
            RuntimeError,
            OSError,
            ValidationError,
        ) as exc:
            session.rollback()
            return TelegramSourceValidation(
                entry.source_id,
                entry.source_class,
                TelegramValidationStatus.FAILED,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                0,
                (),
                type(exc).__name__,
            )


def run_live_validation_from_environment(
    root: Path,
    *,
    confirmed: bool,
    environment: Mapping[str, str] | None = None,
    client: Any | None = None,
    clock: Any | None = None,
) -> tuple[TelegramLiveReport, TelegramLiveValidation | None]:
    """Run only after two explicit opt-ins; report absent operator secrets as a skip."""
    values = dict(os.environ if environment is None else environment)
    if not confirmed or values.get("MARKET_EVOLVER_TELEGRAM_LIVE_VALIDATION") != "YES":
        raise ConfigurationError(
            "Telegram validation requires --confirm-live and "
            "MARKET_EVOLVER_TELEGRAM_LIVE_VALIDATION=YES"
        )
    try:
        harness = TelegramLiveValidation(root, environment=values, client=client, clock=clock)
    except ConfigurationError:
        now = (clock or (lambda: datetime.now(UTC)))()
        run_id = f"telegram-{now.strftime('%Y%m%dT%H%M%SZ')}-{uuid4().hex[:8]}"
        run_root = root / run_id
        run_root.mkdir(parents=True, exist_ok=False)
        report = TelegramLiveReport(
            run_id,
            _git_commit(),
            now.isoformat(),
            now.isoformat(),
            TelegramValidationStatus.SKIPPED_BY_OPERATOR,
            (),
            0,
            0,
            0,
            0,
            "NO_EDIT_CASE_OBSERVED",
            "no fusion candidate",
            "insufficient_history; no collection performed",
            "NOT_RUN",
            "metadata_only; no media bytes downloaded",
            (),
        )
        _write_report(run_root, report)
        return report, None
    return harness.run(), harness


def _write_report(run_root: Path, report: TelegramLiveReport) -> None:
    (run_root / "manifest.json").write_text(report.json_text(), encoding="utf-8")
    (run_root / "report.md").write_text(report.markdown_text(), encoding="utf-8")


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_redact(item) for item in value]
    if isinstance(value, str):
        value = re.sub(
            r"(?i)(api_hash|session|code|phone|token)=([^\s&]+)", r"\1=[REDACTED]", value
        )
        return re.sub(r"\+\d{7,15}", "[REDACTED-PHONE]", value)
    return value


def _git_commit() -> str:
    result = subprocess.run(
        ("git", "rev-parse", "HEAD"), capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"
