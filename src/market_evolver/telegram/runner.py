from __future__ import annotations

import hashlib
import json
import time
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_evolver.config import TelegramSourceConfig
from market_evolver.errors import GovernanceViolation
from market_evolver.social.analysis import normalize_social_text
from market_evolver.social.repository import SqlSocialRepository, utc
from market_evolver.social.schemas import (
    Accessibility,
    PropagationEdge,
    PropagationType,
    SocialPost,
    SocialSource,
    SocialSourceType,
    VerificationState,
)
from market_evolver.storage.artifacts import LocalArtifactStore
from market_evolver.storage.models import (
    ArtifactModel,
    SocialPostModel,
    SocialSourceModel,
    TelegramCheckpointModel,
    TelegramReceiptModel,
    TelegramRunModel,
)
from market_evolver.telegram.client import TelegramClient, TelegramRateLimit
from market_evolver.telegram.schemas import (
    TelegramCheckpoint,
    TelegramRunManifest,
    TelegramRunStatus,
)


class TelegramRunner:
    def __init__(
        self,
        session: Session,
        artifacts: LocalArtifactStore,
        client: TelegramClient,
        sleeper: Callable[[float], None] = time.sleep,
    ):
        self.session = session
        self.artifacts = artifacts
        self.client = client
        self.sleeper = sleeper

    def run(
        self,
        config: TelegramSourceConfig,
        *,
        limit: int,
        since: datetime | None,
        observed_at: datetime,
    ) -> TelegramRunManifest:
        if not config.enabled or limit < 1 or limit > min(config.max_messages or 1000, 1000):
            raise GovernanceViolation("Telegram source disabled or collection bound exceeded")
        if not self.client.validate_public(config.public_identifier):
            raise GovernanceViolation("Telegram source is not publicly accessible")
        checkpoint = self.session.scalar(
            select(TelegramCheckpointModel)
            .where(TelegramCheckpointModel.source_id == config.source_id)
            .order_by(TelegramCheckpointModel.updated_at.desc())
            .limit(1)
        )
        after = None if checkpoint is None else checkpoint.last_message_id
        started = observed_at
        error = None
        for attempt in range(3):
            try:
                messages = self.client.fetch(
                    config.public_identifier, limit=limit, since=since, after_id=after
                )
                break
            except TelegramRateLimit as exc:
                if attempt == 2:
                    messages = ()
                    error = "rate limit retries exhausted"
                else:
                    self.sleeper(min(exc.seconds, 60))
            except (OSError, RuntimeError) as exc:
                messages = ()
                error = type(exc).__name__
                break
        inserted = duplicates = edits = forwards = deletions = bytes_count = 0
        repo = SqlSocialRepository(self.session)
        source = self._source(config, observed_at, repo)
        for message in messages:
            if message.posted_at > observed_at or (
                message.edited_at is not None and message.edited_at > observed_at
            ):
                raise GovernanceViolation("Telegram timestamps violate causal ordering")
            raw = json.dumps(
                asdict(message), default=str, sort_keys=True, separators=(",", ":")
            ).encode()
            artifact = self.artifacts.put(raw, mime_type="application/json")
            bytes_count += len(raw)
            if not self.session.get(ArtifactModel, artifact.sha256):
                self.session.add(
                    ArtifactModel(
                        sha256=artifact.sha256,
                        size_bytes=artifact.size_bytes,
                        mime_type=artifact.mime_type,
                        relative_path=artifact.relative_path,
                        created_at=observed_at,
                    )
                )
                self.session.flush()
            previous = self.session.scalar(
                select(SocialPostModel)
                .where(
                    SocialPostModel.source_id == source.source_id,
                    SocialPostModel.native_post_id == str(message.native_id),
                )
                .order_by(SocialPostModel.first_observed_at.desc())
                .limit(1)
            )
            text_value = (
                (previous.original_text if message.deleted and previous else message.text)
                or message.caption
                or "[media-only]"
            )
            digest = "sha256:" + hashlib.sha256(text_value.encode()).hexdigest()
            if (
                previous
                and previous.content_hash == digest
                and bool(previous.deleted_at) == message.deleted
            ):
                duplicates += 1
                continue
            post = SocialPost(
                "telegram",
                source.source_id,
                str(message.native_id),
                None,
                None if message.reply_to_id is None else str(message.reply_to_id),
                message.posted_at,
                observed_at,
                message.edited_at,
                observed_at if message.deleted else None,
                text_value,
                normalize_social_text(text_value),
                self._language(text_value),
                message.urls,
                message.mentions,
                message.forward_source,
                tuple(
                    (k, v)
                    for k, v in (
                        ("views", message.views),
                        ("forwards", message.forwards),
                        ("reactions", message.reactions),
                    )
                    if v is not None
                ),
                artifact.sha256,
                "sha256:" + hashlib.sha256(text_value.encode()).hexdigest(),
                (
                    tuple(filter(None, (message.media_type, message.media_id, message.caption)))
                    if config.media_policy == "metadata_only"
                    else ()
                ),
                (
                    f"telegram:{config.source_id}:{message.native_id}",
                    f"artifact:sha256:{artifact.sha256}",
                ),
                None if previous is None else previous.post_id,
            )
            repo.add_post(post)
            self.session.flush()
            inserted += 1
            edits += int(previous is not None and not message.deleted)
            deletions += int(message.deleted)
            forwards += int(message.forward_source is not None or message.forward_hidden)
            receipt_id = hashlib.sha256(f"{post.post_id}:{artifact.sha256}".encode()).hexdigest()
            self.session.add(
                TelegramReceiptModel(
                    receipt_id=receipt_id,
                    allowlist_source_id=config.source_id,
                    post_id=post.post_id,
                    native_message_id=message.native_id,
                    forward_source=message.forward_source,
                    forward_message_id=message.forward_message_id,
                    forward_hidden=message.forward_hidden,
                    artifact_sha256=artifact.sha256,
                    payload_bytes=len(raw),
                    observed_at=observed_at,
                )
            )
            if previous is None and not message.forward_source and not message.forward_hidden:
                copied_from = self.session.scalar(
                    select(SocialPostModel)
                    .where(
                        SocialPostModel.post_id != post.post_id,
                        SocialPostModel.normalized_text == post.normalized_text,
                        SocialPostModel.first_observed_at <= observed_at,
                    )
                    .order_by(SocialPostModel.first_observed_at.asc())
                    .limit(1)
                )
                if copied_from is not None:
                    repo.add_edge(
                        PropagationEdge(
                            copied_from.post_id,
                            post.post_id,
                            PropagationType.LIKELY_COPY_OF,
                            observed_at,
                            (copied_from.post_id, post.post_id),
                        )
                    )
            if previous and not message.deleted:
                relation = (
                    PropagationType.FORWARDED_FROM
                    if message.forward_source or message.forward_hidden
                    else PropagationType.LIKELY_COPY_OF
                )
                repo.add_edge(
                    PropagationEdge(
                        previous.post_id,
                        post.post_id,
                        relation,
                        observed_at,
                        (previous.post_id, post.post_id),
                    )
                )
            if message.forward_source and message.forward_message_id:
                origin_source = self.session.scalar(
                    select(SocialSourceModel).where(
                        SocialSourceModel.platform == "telegram",
                        SocialSourceModel.native_source_id == message.forward_source,
                    )
                )
                if origin_source:
                    origin_post = self.session.scalar(
                        select(SocialPostModel)
                        .where(
                            SocialPostModel.source_id == origin_source.source_id,
                            SocialPostModel.native_post_id == str(message.forward_message_id),
                        )
                        .order_by(SocialPostModel.first_observed_at.desc())
                        .limit(1)
                    )
                    if origin_post:
                        repo.add_edge(
                            PropagationEdge(
                                origin_post.post_id,
                                post.post_id,
                                PropagationType.FORWARDED_FROM,
                                observed_at,
                                (origin_post.post_id, post.post_id),
                            )
                        )
        if messages:
            cp = TelegramCheckpoint(
                config.source_id, max(m.native_id for m in messages), observed_at
            )
            self.session.add(
                TelegramCheckpointModel(
                    checkpoint_id=cp.checkpoint_id,
                    source_id=cp.source_id,
                    last_message_id=cp.last_message_id,
                    updated_at=cp.updated_at,
                )
            )
        status = (
            TelegramRunStatus.SUCCEEDED
            if error is None
            else TelegramRunStatus.PARTIAL
            if inserted
            else TelegramRunStatus.FAILED
        )
        manifest = TelegramRunManifest(
            uuid4().hex,
            config.source_id,
            started,
            observed_at,
            status,
            len(messages),
            inserted,
            duplicates,
            edits,
            forwards,
            deletions,
            bytes_count,
            error,
        )
        self.session.add(TelegramRunModel(**asdict(manifest)))
        self.session.commit()
        return manifest

    def _source(
        self, c: TelegramSourceConfig, at: datetime, repo: SqlSocialRepository
    ) -> SocialSource:
        row = self.session.scalar(
            select(SocialSourceModel).where(
                SocialSourceModel.platform == "telegram",
                SocialSourceModel.native_source_id == c.public_identifier,
            )
        )
        if row:
            return SocialSource(
                "telegram",
                row.native_source_id,
                row.display_name,
                row.canonical_uri,
                tuple(row.languages),
                tuple(row.geography),
                SocialSourceType(row.source_type),
                None if row.created_at is None else utc(row.created_at),
                utc(row.first_observed_at),
                VerificationState(row.verification_state),
                Accessibility.PUBLIC,
                tuple(row.provenance),
                row.active,
            )
        source = SocialSource(
            "telegram",
            c.public_identifier,
            c.source_id,
            f"https://t.me/{c.public_identifier.lstrip('@')}",
            c.languages,
            (),
            SocialSourceType(c.source_type),
            None,
            at,
            VerificationState.UNVERIFIED,
            Accessibility.PUBLIC,
            (f"allowlist:{c.source_id}",),
        )
        repo.add_source(source)
        self.session.flush()
        return source

    @staticmethod
    def _language(text: str) -> str:
        he = any("\u0590" <= x <= "\u05ff" for x in text)
        en = any(x.isascii() and x.isalpha() for x in text)
        return "mixed" if he and en else "he" if he else "en"
