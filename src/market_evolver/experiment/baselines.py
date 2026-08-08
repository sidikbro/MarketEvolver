from __future__ import annotations

from dataclasses import dataclass

BASELINES = (
    "cash",
    "buy_and_hold_benchmark",
    "equal_weight_universe",
    "momentum",
    "mean_reversion",
    "deterministic_event_rule",
    "deterministic_macro_rule",
)


@dataclass(frozen=True, slots=True)
class FalseRumorSafetyResult:
    mode: str
    return_value: float
    delay_cost: float
    false_positive_exposure: float
    drawdown: float


def false_rumor_safety_experiment() -> tuple[FalseRumorSafetyResult, ...]:
    """Synthetic deterministic comparison; values are fixtures, not performance claims."""
    return (
        FalseRumorSafetyResult("first_social_rumor", -0.08, 0.0, 1.0, -0.12),
        FalseRumorSafetyResult("independent_corroboration", 0.02, 0.01, 0.25, -0.04),
        FalseRumorSafetyResult("official_confirmation", 0.01, 0.02, 0.0, -0.02),
        FalseRumorSafetyResult("no_trade", 0.0, 0.0, 0.0, 0.0),
    )


@dataclass(frozen=True, slots=True)
class WalkForwardWindow:
    research: tuple[str, str]
    validation: tuple[str, str]
    forward_test: tuple[str, str]


def walk_forward_windows(
    points: tuple[str, ...], research_size: int, validation_size: int, test_size: int
) -> tuple[WalkForwardWindow, ...]:
    step = test_size
    width = research_size + validation_size + test_size
    if min(research_size, validation_size, test_size) < 1:
        raise ValueError("walk-forward windows must be positive")
    return tuple(
        WalkForwardWindow(
            (points[index], points[index + research_size - 1]),
            (points[index + research_size], points[index + research_size + validation_size - 1]),
            (points[index + research_size + validation_size], points[index + width - 1]),
        )
        for index in range(0, len(points) - width + 1, step)
    )
