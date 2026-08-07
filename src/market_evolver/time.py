"""UTC and point-in-time validation."""

from __future__ import annotations

from datetime import UTC, datetime

from market_evolver.errors import PointInTimeViolation, ValidationError


def require_aware_utc(value: datetime, field: str = "timestamp") -> datetime:
    """Return a normalized UTC datetime, rejecting naive timestamps."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValidationError(f"{field} must be timezone-aware")
    return value.astimezone(UTC)


def validate_source_timeline(
    *, published_at: datetime | None, observed_at: datetime, ingested_at: datetime
) -> None:
    """Ensure the recorded source lifecycle is causal."""
    observed = require_aware_utc(observed_at, "observed_at")
    ingested = require_aware_utc(ingested_at, "ingested_at")
    published = None if published_at is None else require_aware_utc(published_at, "published_at")
    if published is not None and published > observed:
        raise PointInTimeViolation("published_at cannot be after observed_at")
    if observed > ingested:
        raise PointInTimeViolation("observed_at cannot be after ingested_at")


def ensure_available_at(available_at: datetime, cutoff: datetime) -> None:
    """Reject look-ahead: information must have been available by the cutoff."""
    available = require_aware_utc(available_at, "available_at")
    normalized_cutoff = require_aware_utc(cutoff, "cutoff")
    if available > normalized_cutoff:
        raise PointInTimeViolation(
            f"information available at {available.isoformat()} is after "
            f"cutoff {normalized_cutoff.isoformat()}"
        )
