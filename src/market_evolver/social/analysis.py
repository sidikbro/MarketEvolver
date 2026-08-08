import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from market_evolver.social.schemas import DuplicateClass, SocialPost


def normalize_social_text(text: str) -> str:
    value = unicodedata.normalize("NFKC", text).casefold()
    value = re.sub(r"https?://\S+", " <url> ", value)
    return " ".join(value.split())


def duplicate_class(a: SocialPost, b: SocialPost) -> DuplicateClass:
    if a.content_hash == b.content_hash:
        return DuplicateClass.EXACT
    if a.quoted_source_id == b.source_id or b.quoted_source_id == a.source_id:
        return DuplicateClass.REPOST
    if a.normalized_text == b.normalized_text:
        return DuplicateClass.EDITED
    ta = set(a.normalized_text.split())
    tb = set(b.normalized_text.split())
    similarity = len(ta & tb) / max(1, len(ta | tb))
    if similarity >= 0.8:
        return DuplicateClass.NEAR
    return DuplicateClass.INDEPENDENT


@dataclass(frozen=True, slots=True)
class NarrativeMetrics:
    mention_count: int
    unique_sources: int
    original_post_ratio: float
    repost_copy_ratio: float
    source_concentration: float
    narrative_velocity_per_hour: float
    cross_source_diversity: float
    cross_language_spread: int
    edit_delete_rate: float
    corroboration_lag_seconds: int | None
    contradiction_rate: float


def narrative_metrics(
    posts: tuple[SocialPost, ...],
    duplicates: tuple[DuplicateClass, ...],
    start: datetime,
    end: datetime,
) -> NarrativeMetrics:
    n = len(posts)
    sources = {p.source_id for p in posts}
    originals = sum(d is DuplicateClass.INDEPENDENT for d in duplicates)
    counts = {s: sum(p.source_id == s for p in posts) for s in sources}
    hours = max((end - start).total_seconds() / 3600, 1 / 3600)
    return NarrativeMetrics(
        n,
        len(sources),
        originals / max(n, 1),
        (n - originals) / max(n, 1),
        max(counts.values(), default=0) / max(n, 1),
        n / hours,
        len(sources) / max(n, 1),
        len({p.language for p in posts}),
        sum(p.edited_at is not None or p.deleted_at is not None for p in posts) / max(n, 1),
        None,
        0.0,
    )
