from __future__ import annotations

from datetime import datetime
from importlib import import_module
from importlib.util import find_spec
from typing import Any, Protocol

from market_evolver.telegram.schemas import TelegramMessage


class TelegramRateLimit(Exception):
    def __init__(self, seconds: int):
        self.seconds = seconds


class TelegramClient(Protocol):
    def validate_public(self, identifier: str) -> bool: ...
    def fetch(
        self, identifier: str, *, limit: int, since: datetime | None, after_id: int | None
    ) -> tuple[TelegramMessage, ...]: ...


class TelethonClientAdapter:
    """Lazy Telethon adapter; session string and credentials never leave memory."""

    def __init__(self, api_id: int, api_hash: str, session: str):
        self.api_id = api_id
        self.api_hash = api_hash
        self.session = session

    def _client(self) -> Any:
        if find_spec("telethon") is None:
            raise RuntimeError("install market-evolver[telegram] to use Telegram")
        sync = import_module("telethon.sync")
        sessions = import_module("telethon.sessions")
        return sync.TelegramClient(sessions.StringSession(self.session), self.api_id, self.api_hash)

    def validate_public(self, identifier: str) -> bool:
        if "/" in identifier or "+" in identifier or ":" in identifier:
            return False
        with self._client() as client:
            entity = client.get_entity(identifier)
            return bool(getattr(entity, "username", None)) and bool(
                getattr(entity, "broadcast", False) or getattr(entity, "megagroup", False)
            )

    def fetch(
        self, identifier: str, *, limit: int, since: datetime | None, after_id: int | None
    ) -> tuple[TelegramMessage, ...]:
        try:
            with self._client() as client:
                result = []
                # Re-read a bounded recent window so edits to already checkpointed
                # IDs can be observed without turning resume into an unbounded crawl.
                minimum_id = max(0, (after_id or 0) - limit)
                for item in client.iter_messages(identifier, limit=limit, min_id=minimum_id):
                    posted = item.date
                    if since is not None and posted < since:
                        continue
                    forward = getattr(item, "fwd_from", None)
                    source = None
                    hidden = False
                    original_id = None
                    if forward is not None:
                        source = str(getattr(forward, "from_id", "") or "") or None
                        hidden = source is None
                        original_id = getattr(forward, "channel_post", None)
                    media = getattr(item, "media", None)
                    document = getattr(media, "document", None)
                    urls: list[str] = []
                    mentions: list[str] = []
                    hashtags: list[str] = []
                    for entity, entity_text in item.get_entities_text():
                        entity_name = type(entity).__name__.lower()
                        if "url" in entity_name:
                            urls.append(str(getattr(entity, "url", None) or entity_text))
                        elif "mention" in entity_name:
                            mentions.append(entity_text)
                        elif "hashtag" in entity_name:
                            hashtags.append(entity_text)
                    reaction_results = getattr(getattr(item, "reactions", None), "results", ())
                    reaction_count = (
                        sum(int(getattr(reaction, "count", 0)) for reaction in reaction_results)
                        if reaction_results
                        else None
                    )
                    result.append(
                        TelegramMessage(
                            item.id,
                            posted,
                            item.message or "",
                            getattr(item, "edit_date", None),
                            getattr(getattr(item, "reply_to", None), "reply_to_msg_id", None),
                            source,
                            original_id,
                            hidden,
                            getattr(item, "views", None),
                            getattr(item, "forwards", None),
                            reaction_count,
                            tuple(urls),
                            tuple(mentions),
                            tuple(hashtags),
                            None if media is None else type(media).__name__,
                            getattr(document, "size", None),
                            None if document is None else str(document.id),
                            item.message or None,
                            False,
                        )
                    )
                return tuple(result)
        except Exception as exc:
            seconds = getattr(exc, "seconds", None)
            if isinstance(seconds, int):
                raise TelegramRateLimit(seconds) from exc
            raise RuntimeError(type(exc).__name__) from exc
