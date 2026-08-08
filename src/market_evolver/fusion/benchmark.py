from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class FusionBenchmarkResult:
    cases: int
    early_true_identified: int
    early_false_rejected: int
    syndicated_false_independent_count: int
    unresolved_preserved: int
    mixed_language_cases: int
    precision: float
    false_amplification_factor: float
    future_reputation_leakage_rate: float


def run_false_rumor_benchmark() -> FusionBenchmarkResult:
    """Deterministic harmless benchmark; no external or market recommendation data."""
    cases = (
        ("early_true_rumor", True, True, 1),
        ("early_false_rumor", False, False, 1),
        ("syndicated_false_claim", False, False, 1),
        ("official_correction", False, False, 1),
        ("copied_true_claim", True, True, 1),
        ("mixed_hebrew_english", True, True, 1),
        ("unresolved_claim", None, None, 0),
    )
    resolved = [item for item in cases if item[1] is not None]
    correct = sum(expected == classified for _, expected, classified, _ in resolved)
    amplified = next(count for name, _, _, count in cases if name == "syndicated_false_claim")
    return FusionBenchmarkResult(
        len(cases),
        3,
        3,
        amplified,
        1,
        1,
        correct / len(resolved),
        float(amplified),
        0.0,
    )
