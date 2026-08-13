from __future__ import annotations

import hashlib
import json
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

from market_evolver.archive.schemas import ArchiveConfidence, VintageClassification
from market_evolver.archive.service import ArchivePayload
from market_evolver.errors import GovernanceViolation, IntegrityViolation, ValidationError
from market_evolver.news.connectors import BbcBusinessRssConnector


@dataclass(frozen=True, slots=True)
class ReviewedLiveSource:
    source_id: str
    uri: str
    trust_class: str
    expected_content_types: tuple[str, ...]
    maximum_bytes: int
    source_timezone: str


@dataclass(frozen=True, slots=True)
class CapturedLiveDocument:
    payload: ArchivePayload
    normalized: bytes
    normalized_sha256: str
    normalized_size: int


BOI_POLICY_LIVE = ReviewedLiveSource(
    "il.boi",
    "https://www.boi.org.il/PublicApi/GetInterest",
    "authoritative_official",
    ("application/json", "text/json"),
    1_000_000,
    "Asia/Jerusalem",
)

BBC_BUSINESS_LIVE = ReviewedLiveSource(
    "uk.bbc.business",
    "https://feeds.bbci.co.uk/news/business/rss.xml",
    "reviewed_news",
    ("application/rss+xml", "application/xml", "text/xml"),
    2_000_000,
    "UTC",
)


def fetch_reviewed_live(source: ReviewedLiveSource) -> CapturedLiveDocument:
    hostname = urlsplit(source.uri).hostname or ""
    allowed = {
        "il.boi": "www.boi.org.il",
        "uk.bbc.business": "feeds.bbci.co.uk",
    }
    if allowed.get(source.source_id) != hostname:
        raise GovernanceViolation("reviewed live source domain mismatch")
    retrieved = datetime.now(UTC)
    request = urllib.request.Request(
        source.uri,
        headers={"Accept": ", ".join(source.expected_content_types), "User-Agent": "MarketEvolver/0.32 governed-archive"},
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        body = response.read(source.maximum_bytes + 1)
        content_type = response.headers.get_content_type()
        final_uri = response.geturl()
        headers = tuple(
            (name.lower(), value)
            for name in ("Date", "ETag", "Last-Modified", "Content-Type", "Content-Length")
            if (value := response.headers.get(name)) is not None
        )
    if len(body) > source.maximum_bytes:
        raise IntegrityViolation("reviewed live source exceeded byte limit")
    if content_type not in source.expected_content_types:
        raise IntegrityViolation("reviewed live source content type changed")
    if (urlsplit(final_uri).hostname or "") != hostname:
        raise GovernanceViolation("reviewed live source redirected to an unexpected domain")
    server_date = _header_datetime(dict(headers).get("date"))
    published, normalized = _normalize(source, body)
    payload = ArchivePayload(
        source.source_id,
        final_uri,
        body,
        content_type,
        retrieved,
        published,
        server_date,
        source.source_timezone,
        headers,
        VintageClassification.OBSERVED_LIVE_AT_TIME,
        "direct_live_observation",
        ArchiveConfidence.HIGH,
        (("reviewed_contract", "v0.32"),),
    )
    return CapturedLiveDocument(
        payload,
        normalized,
        hashlib.sha256(normalized).hexdigest(),
        len(normalized),
    )


def _normalize(source: ReviewedLiveSource, body: bytes) -> tuple[datetime | None, bytes]:
    if source.source_id == "il.boi":
        try:
            document = json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise IntegrityViolation("BOI live policy JSON is malformed") from exc
        if not isinstance(document, dict) or "currentInterest" not in document:
            raise IntegrityViolation("BOI live policy schema changed")
        selected_policy = {
            key: document.get(key)
            for key in ("currentInterest", "lastUpdate", "nextInterestDate")
        }
        published = _iso_datetime(selected_policy.get("lastUpdate"))
        return published, json.dumps(selected_policy, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    if source.source_id == "uk.bbc.business":
        items = BbcBusinessRssConnector().parse(body)
        selected_news = [
            {
                "title": item.title,
                "body": item.body,
                "canonical_uri": item.canonical_uri,
                "published_at": item.published_at.isoformat(),
            }
            for item in items
        ]
        published = max(item.published_at for item in items)
        return published, json.dumps(selected_news, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    raise ValidationError("unsupported reviewed live source")


def _header_datetime(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = parsedate_to_datetime(value)
    if parsed.tzinfo is None:
        raise IntegrityViolation("server Date header is timezone-naive")
    return parsed.astimezone(UTC)


def _iso_datetime(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise IntegrityViolation("source publication timestamp is timezone-naive")
    return parsed.astimezone(UTC)
