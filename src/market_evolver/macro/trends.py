"""Deterministic macro baselines and direction-neutral mechanism mappings."""

from __future__ import annotations

import math
from datetime import datetime
from decimal import Decimal

from market_evolver.errors import IntegrityViolation
from market_evolver.macro.schemas import (
    MacroCategory,
    MacroObservation,
    TrendHorizon,
    TrendSignal,
    TrendState,
)

CALCULATION_VERSION = "deterministic-macro/1"
HORIZON_WINDOWS = {TrendHorizon.SHORT: 3, TrendHorizon.MEDIUM: 6, TrendHorizon.LONG: 12}
MECHANISMS = {
    MacroCategory.INFLATION: ("financing_cost", "consumer_demand", "construction_input_cost"),
    MacroCategory.INTEREST_RATES: (
        "financing_cost",
        "refinancing_cost",
        "credit_demand",
        "interest_margin",
    ),
    MacroCategory.TOURISM: ("tourism_demand",),
    MacroCategory.FX: ("import_cost", "export_competitiveness", "currency_translation"),
    MacroCategory.HOUSING: ("construction_input_cost", "credit_demand"),
    MacroCategory.CREDIT: ("credit_demand", "financing_cost"),
    MacroCategory.CONSUMER: ("consumer_demand",),
    MacroCategory.GOVERNMENT_SPENDING: ("consumer_demand", "risk_premium"),
    MacroCategory.ENERGY: ("import_cost",),
}


def calculate_trend(
    observations: tuple[MacroObservation, ...], horizon: TrendHorizon, calculated_at: datetime
) -> TrendSignal:
    if not observations:
        raise IntegrityViolation("trend calculation requires observations")
    series = observations[0].series_id
    adjustment = observations[0].seasonal_adjustment
    if any(
        item.series_id != series or item.seasonal_adjustment != adjustment for item in observations
    ):
        raise IntegrityViolation("trend inputs cannot mix series or seasonal adjustments")
    window = observations[-HORIZON_WINDOWS[horizon] :]
    values = [Decimal(item.value) for item in window]
    mean = sum(values) / Decimal(len(values))
    slope = Decimal(0) if len(values) == 1 else (values[-1] - values[0]) / Decimal(len(values) - 1)
    variance = sum((value - mean) ** 2 for value in values) / Decimal(len(values))
    deviation = Decimal(str(math.sqrt(float(variance))))
    z_score = Decimal(0) if deviation == 0 else (values[-1] - mean) / deviation
    if abs(z_score) >= Decimal(2):
        state = TrendState.ANOMALY
    elif slope > 0:
        state = TrendState.RISING
    elif slope < 0:
        state = TrendState.FALLING
    else:
        state = TrendState.STABLE
    return TrendSignal(
        series,
        window[-1].geography,
        window[-1].category,
        horizon,
        state,
        window[-1].observation_period,
        calculated_at,
        CALCULATION_VERSION,
        tuple(item.observation_id for item in window),
        format(slope, "f"),
        format(mean, "f"),
        format(z_score, "f"),
        MECHANISMS.get(window[-1].category, ()),
    )


def latest_value(observations: tuple[MacroObservation, ...]) -> str:
    if not observations:
        raise IntegrityViolation("latest-value baseline requires observations")
    return observations[-1].value
