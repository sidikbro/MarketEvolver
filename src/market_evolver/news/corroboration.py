"""Deterministic corroboration without treating syndication as independence."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from market_evolver.errors import IntegrityViolation
from market_evolver.news.repositories import SqlNewsRepository
from market_evolver.news.schemas import Corroboration, NewsEventCandidate


def corroborate_explicit_candidate(
    session: Session,
    candidate: NewsEventCandidate,
    other_news_id: str,
    created_at: datetime,
) -> Corroboration:
    repository = SqlNewsRepository(session)
    primary = repository.get(candidate.news_id)
    other = repository.get(other_news_id)
    if primary is None or other is None:
        raise IntegrityViolation("corroboration requires known news records")
    if primary.source_id == other.source_id:
        raise IntegrityViolation("same publisher is not independent corroboration")
    if primary.normalized_fingerprint == other.normalized_fingerprint:
        raise IntegrityViolation("syndicated copy is not independent corroboration")
    record = Corroboration(
        candidate_id=candidate.candidate_id,
        evidence_ids=(primary.evidence_id, other.evidence_id),
        source_ids=(primary.source_id, other.source_id),
        independence_assumptions=(
            "different registered publisher identities",
            "normalized content fingerprints differ",
        ),
        timestamp_ordering=(
            f"{primary.news_id}@{primary.first_observed_at.isoformat()}",
            f"{other.news_id}@{other.first_observed_at.isoformat()}",
        ),
        confidence=0.7,
        contradictions=(),
        created_at=created_at,
    )
    return repository.add_corroboration(record)
