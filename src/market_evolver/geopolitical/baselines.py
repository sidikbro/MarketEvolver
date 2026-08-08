"""Descriptive geopolitical baselines; never trading signals."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from market_evolver.geopolitical.schemas import (
    ConfirmationState,
    GeopoliticalEvent,
    TransmissionPath,
)

_WEIGHTS = {
    ConfirmationState.UNVERIFIED: 0.1,
    ConfirmationState.PARTIALLY_CONFIRMED: 0.5,
    ConfirmationState.CONFIRMED: 1.0,
    ConfirmationState.DISPUTED: 0.25,
    ConfirmationState.CONTRADICTED: 0.0,
    ConfirmationState.RESOLVED: 0.25,
}


@dataclass(frozen=True, slots=True)
class GeopoliticalBaseline:
    event_present: bool
    confirmed_event_count: int
    mechanism_exposure_count: int
    disruption_duration_buckets: tuple[tuple[str, str], ...]
    confirmation_weighted_event_score: float


def calculate_baseline(
    events: tuple[GeopoliticalEvent, ...], paths: tuple[TransmissionPath, ...], cutoff: datetime
) -> GeopoliticalBaseline:
    buckets = []
    for event in events:
        if event.started_at is None:
            bucket = "unknown"
        else:
            days = ((event.ended_at or cutoff) - event.started_at).total_seconds() / 86400
            bucket = (
                "hours_to_10_days"
                if days <= 10
                else "weeks_to_3_months"
                if days <= 92
                else "over_3_months"
            )
        buckets.append((event.event_id, bucket))
    return GeopoliticalBaseline(
        bool(events),
        sum(item.confirmation_state is ConfirmationState.CONFIRMED for item in events),
        len({mechanism for path in paths for mechanism in path.mechanisms}),
        tuple(buckets),
        sum(_WEIGHTS[item.confirmation_state] * item.confidence for item in events),
    )
