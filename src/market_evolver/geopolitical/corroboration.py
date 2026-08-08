"""Deterministic source independence and official-response classification."""

from market_evolver.geopolitical.schemas import CorroborationKind


def classify_corroboration(
    *,
    source_a: str,
    fingerprint_a: str,
    source_b: str,
    fingerprint_b: str,
    official_response: bool = False,
    contradiction: bool = False,
) -> CorroborationKind:
    if source_a == source_b or fingerprint_a == fingerprint_b:
        return CorroborationKind.SYNDICATED
    if official_response:
        return (
            CorroborationKind.OFFICIAL_CONTRADICTION
            if contradiction
            else CorroborationKind.OFFICIAL_CONFIRMATION
        )
    if contradiction:
        return CorroborationKind.UNRESOLVED_CONFLICT
    return CorroborationKind.INDEPENDENT
