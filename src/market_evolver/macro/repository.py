"""SQLAlchemy repository for immutable, revision-aware macro intelligence."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_evolver.errors import IntegrityViolation
from market_evolver.macro.schemas import (
    MacroCategory,
    MacroObservation,
    SeasonalAdjustment,
    StructuralTrend,
    TrendDivergence,
    TrendHorizon,
    TrendSignal,
    TrendState,
)
from market_evolver.storage.models import (
    MacroObservationModel,
    StructuralTrendModel,
    TrendDivergenceModel,
    TrendSignalModel,
)
from market_evolver.time import require_aware_utc


class SqlMacroRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_observation(self, item: MacroObservation) -> bool:
        if self.session.get(MacroObservationModel, item.observation_id) is not None:
            return False
        if item.revision_of is not None:
            previous = self.session.get(MacroObservationModel, item.revision_of)
            if previous is None:
                raise IntegrityViolation("macro revision references an unknown observation")
            if (
                previous.series_id != item.series_id
                or previous.observation_period != item.observation_period
                or previous.seasonal_adjustment != item.seasonal_adjustment.value
                or _utc(previous.first_observed_at) >= item.first_observed_at
            ):
                raise IntegrityViolation("macro revision chain changes identity or causal order")
        self.session.add(
            MacroObservationModel(
                observation_id=item.observation_id,
                series_id=item.series_id,
                source_id=item.source_id,
                geography=item.geography,
                category=item.category.value,
                observation_period=item.observation_period,
                value=item.value,
                unit=item.unit,
                published_at=item.published_at,
                first_observed_at=item.first_observed_at,
                revision_of=item.revision_of,
                seasonal_adjustment=item.seasonal_adjustment.value,
                provenance=list(item.provenance),
                parser_version=item.parser_version,
                name_en=item.name_en,
                name_he=item.name_he,
                prior_value=item.prior_value,
                expected_value=item.expected_value,
                expectation_source=item.expectation_source,
                expectation_observed_at=item.expectation_observed_at,
            )
        )
        return True

    def observations_visible_at(
        self,
        series_id: str,
        cutoff: datetime,
        *,
        seasonal_adjustment: SeasonalAdjustment | None = None,
    ) -> tuple[MacroObservation, ...]:
        at = require_aware_utc(cutoff, "cutoff")
        statement = select(MacroObservationModel).where(
            MacroObservationModel.series_id == series_id,
            MacroObservationModel.first_observed_at <= at,
        )
        if seasonal_adjustment is not None:
            statement = statement.where(
                MacroObservationModel.seasonal_adjustment == seasonal_adjustment.value
            )
        rows = tuple(self.session.scalars(statement))
        latest: dict[tuple[str, str], MacroObservationModel] = {}
        for row in rows:
            key = (row.observation_period, row.seasonal_adjustment)
            incumbent = latest.get(key)
            if incumbent is None or _utc(row.first_observed_at) > _utc(incumbent.first_observed_at):
                latest[key] = row
        return tuple(
            self._observation(row)
            for row in sorted(
                latest.values(),
                key=lambda value: (value.observation_period, value.seasonal_adjustment),
            )
        )

    def series_ids(self) -> tuple[str, ...]:
        return tuple(
            self.session.scalars(
                select(MacroObservationModel.series_id)
                .distinct()
                .order_by(MacroObservationModel.series_id)
            )
        )

    def add_trend(self, item: TrendSignal) -> bool:
        if self.session.get(TrendSignalModel, item.trend_id) is not None:
            return False
        for observation_id in item.input_observation_ids:
            observation = self.session.get(MacroObservationModel, observation_id)
            if observation is None or _utc(observation.first_observed_at) > item.calculated_at:
                raise IntegrityViolation("trend references unavailable macro input")
        self.session.add(
            TrendSignalModel(
                trend_id=item.trend_id,
                series_id=item.series_id,
                geography=item.geography,
                category=item.category.value,
                horizon=item.horizon.value,
                state=item.state.value,
                as_of_period=item.as_of_period,
                calculated_at=item.calculated_at,
                calculation_version=item.calculation_version,
                input_observation_ids=list(item.input_observation_ids),
                slope=item.slope,
                rolling_mean=item.rolling_mean,
                z_score=item.z_score,
                mechanism_ids=list(item.mechanism_ids),
            )
        )
        return True

    def trends_visible_at(self, series_id: str, cutoff: datetime) -> tuple[TrendSignal, ...]:
        at = require_aware_utc(cutoff, "cutoff")
        rows = tuple(
            self.session.scalars(
                select(TrendSignalModel).where(
                    TrendSignalModel.series_id == series_id,
                    TrendSignalModel.calculated_at <= at,
                )
            )
        )
        latest: dict[str, TrendSignalModel] = {}
        for row in rows:
            incumbent = latest.get(row.horizon)
            if incumbent is None or _utc(row.calculated_at) > _utc(incumbent.calculated_at):
                latest[row.horizon] = row
        return tuple(self._trend(latest[key]) for key in sorted(latest))

    def add_divergence(self, item: TrendDivergence) -> bool:
        if self.session.get(TrendDivergenceModel, item.divergence_id) is not None:
            return False
        if any(
            self.session.get(TrendSignalModel, key) is None
            for key in (item.left_trend_id, item.right_trend_id)
        ):
            raise IntegrityViolation("divergence references unknown trend")
        self.session.add(
            TrendDivergenceModel(
                divergence_id=item.divergence_id,
                left_trend_id=item.left_trend_id,
                right_trend_id=item.right_trend_id,
                description=item.description,
                observed_at=item.observed_at,
                provenance_ids=list(item.provenance_ids),
            )
        )
        return True

    def divergences_visible_at(self, cutoff: datetime) -> tuple[TrendDivergence, ...]:
        at = require_aware_utc(cutoff, "cutoff")
        rows = self.session.scalars(
            select(TrendDivergenceModel).where(TrendDivergenceModel.observed_at <= at)
        )
        return tuple(
            TrendDivergence(
                row.left_trend_id,
                row.right_trend_id,
                row.description,
                _utc(row.observed_at),
                tuple(row.provenance_ids),
            )
            for row in rows
        )

    def add_structural_trend(self, item: StructuralTrend) -> bool:
        if self.session.get(StructuralTrendModel, item.structural_id) is not None:
            return False
        self.session.add(
            StructuralTrendModel(
                structural_id=item.structural_id,
                name=item.name,
                description=item.description,
                geography=item.geography,
                valid_from=item.valid_from,
                valid_until=item.valid_until,
                first_observed_at=item.first_observed_at,
                evidence_ids=list(item.evidence_ids),
                mechanism_ids=list(item.mechanism_ids),
                curated=item.curated,
            )
        )
        return True

    def structural_visible_at(self, cutoff: datetime) -> tuple[StructuralTrend, ...]:
        at = require_aware_utc(cutoff, "cutoff")
        rows = self.session.scalars(
            select(StructuralTrendModel).where(
                StructuralTrendModel.first_observed_at <= at,
                StructuralTrendModel.valid_from <= at,
            )
        )
        return tuple(
            StructuralTrend(
                row.structural_id,
                row.name,
                row.description,
                row.geography,
                _utc(row.valid_from),
                None if row.valid_until is None else _utc(row.valid_until),
                _utc(row.first_observed_at),
                tuple(row.evidence_ids),
                tuple(row.mechanism_ids),
                row.curated,
            )
            for row in rows
            if row.valid_until is None or _utc(row.valid_until) > at
        )

    @staticmethod
    def _observation(row: MacroObservationModel) -> MacroObservation:
        return MacroObservation(
            row.series_id,
            row.source_id,
            row.geography,
            MacroCategory(row.category),
            row.observation_period,
            row.value,
            row.unit,
            _utc(row.published_at),
            _utc(row.first_observed_at),
            row.revision_of,
            SeasonalAdjustment(row.seasonal_adjustment),
            tuple(row.provenance),
            row.parser_version,
            row.name_en,
            row.name_he,
            row.prior_value,
            row.expected_value,
            row.expectation_source,
            None if row.expectation_observed_at is None else _utc(row.expectation_observed_at),
        )

    @staticmethod
    def _trend(row: TrendSignalModel) -> TrendSignal:
        return TrendSignal(
            row.series_id,
            row.geography,
            MacroCategory(row.category),
            TrendHorizon(row.horizon),
            TrendState(row.state),
            row.as_of_period,
            _utc(row.calculated_at),
            row.calculation_version,
            tuple(row.input_observation_ids),
            row.slope,
            row.rolling_mean,
            row.z_score,
            tuple(row.mechanism_ids),
        )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
