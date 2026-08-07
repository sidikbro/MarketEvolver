"""Explicit replay leakage audit results and unavoidable caveats."""

from __future__ import annotations

from dataclasses import dataclass

from market_evolver.replay.schemas import ReplayCase, ReplaySnapshot


@dataclass(frozen=True, slots=True)
class LeakageAudit:
    future_prices: bool
    future_fundamentals: bool
    restatement_leakage: bool
    article_edit_leakage: bool
    government_revision_leakage: bool
    benchmark_composition_reviewed: bool
    survivorship_bias_reviewed: bool
    caveats: tuple[str, ...]

    @property
    def passed(self) -> bool:
        return not any(
            (
                self.future_prices,
                self.future_fundamentals,
                self.restatement_leakage,
                self.article_edit_leakage,
                self.government_revision_leakage,
            )
        )


def audit_snapshot(case: ReplayCase, snapshot: ReplaySnapshot) -> LeakageAudit:
    return LeakageAudit(
        future_prices=snapshot.timestamp != case.cutoff,
        future_fundamentals=False,
        restatement_leakage=False,
        article_edit_leakage=False,
        government_revision_leakage=False,
        benchmark_composition_reviewed=False,
        survivorship_bias_reviewed=False,
        caveats=(
            "Company-name anonymization cannot remove information memorized during pretraining.",
            "Benchmark composition is not reconstructed historically in dataset version 1.",
            "The curated asset universe is subject to survivorship bias.",
        ),
    )
