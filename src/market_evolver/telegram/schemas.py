from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from market_evolver.errors import ValidationError
from market_evolver.provenance import content_id
from market_evolver.time import require_aware_utc


class TelegramRunStatus(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL = "partial"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class TelegramMessage:
    native_id: int
    posted_at: datetime
    text: str
    edited_at: datetime | None = None
    reply_to_id: int | None = None
    forward_source: str | None = None
    forward_message_id: int | None = None
    forward_hidden: bool = False
    views: int | None = None
    forwards: int | None = None
    reactions: int | None = None
    urls: tuple[str, ...] = ()
    mentions: tuple[str, ...] = ()
    hashtags: tuple[str, ...] = ()
    media_type: str | None = None
    media_size: int | None = None
    media_id: str | None = None
    caption: str | None = None
    deleted: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "posted_at", require_aware_utc(self.posted_at, "posted_at"))
        if self.edited_at is not None:
            object.__setattr__(self, "edited_at", require_aware_utc(self.edited_at, "edited_at"))
        if self.native_id <= 0 or (self.forward_hidden and self.forward_source is not None):
            raise ValidationError("invalid Telegram message/forward metadata")


@dataclass(frozen=True, slots=True)
class TelegramCheckpoint:
    source_id: str
    last_message_id: int
    updated_at: datetime
    checkpoint_id: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "updated_at", require_aware_utc(self.updated_at, "updated_at"))
        object.__setattr__(self, "checkpoint_id", content_id("telegram-checkpoint", self))


@dataclass(frozen=True, slots=True)
class TelegramRunManifest:
    run_id: str
    source_id: str
    started_at: datetime
    finished_at: datetime
    status: TelegramRunStatus
    messages_fetched: int
    inserted: int
    duplicates: int
    edits: int
    forwards: int
    deletions: int
    bytes_downloaded: int
    error_summary: str | None
