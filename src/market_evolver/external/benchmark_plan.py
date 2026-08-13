from __future__ import annotations

from dataclasses import replace

from market_evolver.external.schemas import ComparisonMode, FairComparisonManifest


def common_v028_manifests() -> tuple[FairComparisonManifest, ...]:
    """One bounded proposed case; execution remains blocked until inputs are verified."""
    common = FairComparisonManifest(
        ("AAPL",),
        "2025-04-01/2025-04-03",
        "100000 USD",
        "0 bps provisional",
        "decision after prior close; fill at next open",
        "daily bars visible through prior close; news/fundamentals excluded",
        "deepseek/deepseek-v4-flash",
        "temperature=0,max_tokens=512,retries=3",
        1,
        "AAPL buy-and-hold over identical fills",
        "USD",
        "disabled",
        ComparisonMode.NATIVE_REFERENCE,
        ("v028-proposed-common-case:not-executed",),
    )
    return tuple(
        replace(common, mode=mode)
        for mode in (
            ComparisonMode.NATIVE_REFERENCE,
            ComparisonMode.GENERALIST,
            ComparisonMode.SPECIALIST,
            ComparisonMode.SPECIALIST_REVIEWED,
            ComparisonMode.ANONYMIZED,
        )
    )
