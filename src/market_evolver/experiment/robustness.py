from __future__ import annotations

import random
from dataclasses import dataclass
from statistics import mean


@dataclass(frozen=True, slots=True)
class RobustnessReport:
    bootstrap_interval: tuple[float, float]
    permutation_mean: float
    period_returns: tuple[float, ...]
    sensitivity: tuple[tuple[str, float], ...]
    leave_one_period_out: tuple[float, ...]
    seed: int


def robustness_report(
    returns: tuple[float, ...],
    sensitivity_results: tuple[tuple[str, float], ...],
    *,
    seed: int = 0,
    samples: int = 500,
) -> RobustnessReport:
    if not returns:
        return RobustnessReport((0.0, 0.0), 0.0, (), sensitivity_results, (), seed)
    rng = random.Random(seed)
    boot = sorted(mean(rng.choices(returns, k=len(returns))) for _ in range(samples))
    shuffled_means = []
    for _ in range(samples):
        values = list(returns)
        rng.shuffle(values)
        signs = [1 if rng.random() >= 0.5 else -1 for _ in values]
        shuffled_means.append(mean(value * sign for value, sign in zip(values, signs, strict=True)))
    leave_one_out = tuple(
        mean(returns[:index] + returns[index + 1 :]) if len(returns) > 1 else 0.0
        for index in range(len(returns))
    )
    return RobustnessReport(
        (boot[int(samples * 0.025)], boot[min(samples - 1, int(samples * 0.975))]),
        mean(shuffled_means),
        returns,
        sensitivity_results,
        leave_one_out,
        seed,
    )
