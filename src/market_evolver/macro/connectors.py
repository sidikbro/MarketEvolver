"""Reviewed transformations from existing official ingestion records."""

from __future__ import annotations

from market_evolver.errors import IntegrityViolation
from market_evolver.ingestion.schemas import NormalizedObservation
from market_evolver.macro.schemas import MacroCategory, MacroObservation, SeasonalAdjustment


def boi_fx_macro_observation(item: NormalizedObservation) -> MacroObservation:
    """Map an already-persisted BOI FX observation; never performs a network request."""
    if item.registry_source_id != "il.boi" or item.dataset != "representative-exchange-rates":
        raise IntegrityViolation("macro FX adapter accepts only reviewed BOI representative rates")
    if item.published_at is None:
        raise IntegrityViolation("BOI macro observation requires publisher time")
    currency = item.item_key.upper()
    return MacroObservation(
        series_id=f"il.boi.fx.{currency.casefold()}.ils",
        source_id=item.registry_source_id,
        geography="IL",
        category=MacroCategory.FX,
        observation_period=item.period_start.isoformat(),
        value=item.value,
        unit="rate",
        published_at=item.published_at,
        first_observed_at=item.first_observed_at,
        revision_of=None,
        seasonal_adjustment=SeasonalAdjustment.NOT_APPLICABLE,
        provenance=(item.provenance_id, f"artifact:sha256:{item.raw_artifact_sha256}"),
        parser_version="macro-boi-fx/1",
        name_en=f"BOI representative {currency}/ILS rate",
    )
