"""Disabled source interfaces for future aviation, shipping, and energy data."""

from __future__ import annotations

from typing import Protocol


class DisruptionIndicatorSource(Protocol):
    source_id: str

    def fetch_indicator(self, dataset: str) -> bytes: ...


class DisabledAviationIndicatorSource:
    source_id = "global.icao"


class DisabledShippingIndicatorSource:
    source_id = "global.imo"


class DisabledEnergyIndicatorSource:
    source_id = "global.iea"
