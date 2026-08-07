"""Narrow reviewed RSS connector; no general web scraper."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.request import Request, urlopen
from xml.etree import ElementTree

from market_evolver.errors import ValidationError
from market_evolver.ingestion.connectors import BaseConnector, FetchedPayload


@dataclass(frozen=True, slots=True)
class ParsedNews:
    title: str
    body: str
    canonical_uri: str
    published_at: datetime
    updated_at: datetime | None = None
    last_modified_at: datetime | None = None


class BbcBusinessRssConnector(BaseConnector):
    source_id = "uk.bbc.business"
    parser_version = "bbc-rss/1"
    endpoint = "https://feeds.bbci.co.uk/news/business/rss.xml"
    max_bytes = 2_000_000

    def fetch(self) -> FetchedPayload:
        request = Request(self.endpoint, headers={"User-Agent": "MarketEvolver/0.6"})
        with urlopen(request, timeout=20) as response:
            body = response.read(self.max_bytes + 1)
            content_type = response.headers.get_content_type()
        if len(body) > self.max_bytes:
            raise ValidationError("news feed exceeds configured size limit")
        return FetchedPayload(body, self.endpoint, content_type)

    def parse(self, payload: bytes) -> tuple[ParsedNews, ...]:
        if b"<!DOCTYPE" in payload.upper() or b"<!ENTITY" in payload.upper():
            raise ValidationError("DTD/entity declarations are forbidden in news XML")
        try:
            payload.decode("utf-8", errors="strict")
            root = ElementTree.fromstring(payload)
        except (UnicodeDecodeError, ElementTree.ParseError) as exc:
            raise ValidationError("news feed has corrupt encoding or malformed XML") from exc
        parsed: list[ParsedNews] = []
        for node in root.findall("./channel/item"):
            title = _text(node, "title")
            body = _text(node, "description")
            uri = _text(node, "link")
            published = _parse_timestamp(_text(node, "pubDate"))
            if not title or not body or not uri:
                raise ValidationError("RSS item has inconsistent required metadata")
            if not uri.startswith("https://www.bbc."):
                raise ValidationError("RSS item URI violates reviewed BBC source contract")
            parsed.append(ParsedNews(title, body, uri, published))
        if not parsed:
            raise ValidationError("news feed contained no items")
        return tuple(parsed)


def _text(node: ElementTree.Element, name: str) -> str:
    value = node.findtext(name)
    return "" if value is None else value.strip()


def _parse_timestamp(value: str) -> datetime:
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError("malformed RSS publication timestamp") from exc
    if parsed.tzinfo is None:
        raise ValidationError("RSS publication timestamp is timezone-naive")
    return parsed.astimezone(UTC)
