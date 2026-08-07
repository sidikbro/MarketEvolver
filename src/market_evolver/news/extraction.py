"""Deterministic news normalization, fingerprints, and exact entity extraction."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from market_evolver.knowledge.repositories import SqlKnowledgeGraph
from market_evolver.knowledge.schemas import ResolutionStatus
from market_evolver.news.schemas import NewsEventCandidate, NewsItem


def normalized_text(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def content_fingerprint(title: str, body: str) -> str:
    payload = f"{normalized_text(title)}\n{normalized_text(body)}".encode()
    return hashlib.sha256(payload).hexdigest()


def detect_language(text: str) -> str:
    hebrew = len(re.findall(r"[\u0590-\u05ff]", text))
    latin = len(re.findall(r"[A-Za-z]", text))
    if hebrew and latin:
        return "mixed"
    return "he" if hebrew > latin else "en"


@dataclass(slots=True)
class DeterministicNewsExtractor:
    graph: SqlKnowledgeGraph

    def extract(self, item: NewsItem, at: datetime) -> NewsEventCandidate:
        text = f"{item.title}\n{item.body}"
        entities: set[str] = set()
        spans: set[str] = set()
        for alias in _candidate_spans(text):
            resolution = self.graph.resolve_alias(alias, at)
            if resolution.status is ResolutionStatus.RESOLVED:
                entities.add(resolution.candidates[0].entity_id)
                spans.add(alias)
        return NewsEventCandidate(
            news_id=item.news_id,
            extracted_entities=tuple(sorted(entities)),
            possible_event_type="explicit_entity_mention",
            extraction_method="deterministic-exact-alias/v1",
            confidence=1.0 if entities else 0.0,
            supporting_spans=tuple(sorted(spans)),
            created_at=at,
        )


def _candidate_spans(text: str) -> tuple[str, ...]:
    named = (
        "Bank of Israel",
        "בנק ישראל",
        "TASE",
        "הבורסה לניירות ערך",
        "Israel",
        "ישראל",
        "USD/ILS",
        "USD",
        "EUR",
        "ILS",
    )
    folded = normalized_text(text)
    return tuple(item for item in named if normalized_text(item) in folded)
