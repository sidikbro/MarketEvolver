"""Deterministic clock, cutoff snapshot, immutable commitment, and outcome evaluation."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from market_evolver.company.repositories import SqlCompanyRepository
from market_evolver.errors import IntegrityViolation
from market_evolver.geopolitical.repository import SqlGeopoliticalRepository
from market_evolver.macro.repository import SqlMacroRepository
from market_evolver.market.store import MarketDataStore
from market_evolver.provenance import content_id
from market_evolver.replay.repositories import SqlReplayRepository
from market_evolver.replay.schemas import (
    OutcomeEvaluation,
    ReplayCase,
    ReplayRun,
    ReplaySnapshot,
    ReplayStepMode,
    ResearchCommitment,
)
from market_evolver.storage.models import (
    CanonicalEventModel,
    GovernmentActionModel,
    KnowledgeRelationshipModel,
    NewsItemModel,
)
from market_evolver.time import require_aware_utc


class ReplayClock:
    def __init__(
        self,
        start: datetime,
        mode: ReplayStepMode,
        timestamps: tuple[datetime, ...] = (),
    ) -> None:
        self.current = require_aware_utc(start, "start")
        self.mode = mode
        self.timestamps = tuple(require_aware_utc(item, "timestamp") for item in timestamps)
        if mode is ReplayStepMode.CONFIGURED and self.current not in self.timestamps:
            raise IntegrityViolation("configured replay sequence must contain start")

    def advance(self, commitment: ResearchCommitment) -> datetime:
        if commitment.replay_timestamp != self.current:
            raise IntegrityViolation("commitment does not bind the current replay timestamp")
        if self.mode is ReplayStepMode.DAILY:
            self.current += timedelta(days=1)
            return self.current
        later = tuple(item for item in self.timestamps if item > self.current)
        if not later:
            raise StopIteration("replay clock has no later timestamp")
        self.current = min(later)
        return self.current


class ReplayEngine:
    def __init__(self, session: Session, market: MarketDataStore) -> None:
        self.session = session
        self.market = market
        self.repository = SqlReplayRepository(session)

    def snapshot(self, case: ReplayCase) -> ReplaySnapshot:
        cutoff = case.cutoff
        events = tuple(
            item.event_id
            for item in self.session.scalars(
                select(CanonicalEventModel).where(CanonicalEventModel.first_observed_at <= cutoff)
            )
        )
        policies = tuple(
            item.action_id
            for item in self.session.scalars(
                select(GovernmentActionModel).where(
                    GovernmentActionModel.first_observed_at <= cutoff
                )
            )
        )
        news = tuple(
            item.news_id
            for item in self.session.scalars(
                select(NewsItemModel).where(NewsItemModel.first_observed_at <= cutoff)
            )
        )
        fundamentals: tuple[str, ...] = ()
        company_ids = tuple(
            entity.removeprefix("company.")
            for entity in case.entity_ids
            if entity.startswith("company.")
        )
        if company_ids:
            company_repo = SqlCompanyRepository(self.session)
            fundamentals = tuple(
                item.observation_id
                for company_id in company_ids
                for item in company_repo.get_fundamentals(company_id, cutoff)
            )
        entity_set = set(case.entity_ids)
        graph = tuple(
            item.relationship_id
            for item in self.session.scalars(
                select(KnowledgeRelationshipModel).where(
                    or_(
                        KnowledgeRelationshipModel.source_entity.in_(entity_set),
                        KnowledgeRelationshipModel.target_entity.in_(entity_set),
                    ),
                    KnowledgeRelationshipModel.observed_at <= cutoff,
                    KnowledgeRelationshipModel.valid_from <= cutoff,
                    or_(
                        KnowledgeRelationshipModel.valid_until.is_(None),
                        KnowledgeRelationshipModel.valid_until > cutoff,
                    ),
                )
            )
        )
        market_ids = tuple(
            item.observation_id
            for asset_id in case.asset_ids
            for item in self.market.get_market_data(
                asset_id,
                datetime(1970, 1, 1, tzinfo=UTC),
                cutoff,
                cutoff,
            )
        )
        macro = SqlMacroRepository(self.session)
        macro_observations = tuple(
            observation.observation_id
            for series_id in macro.series_ids()
            for observation in macro.observations_visible_at(series_id, cutoff)
        )
        trends = tuple(
            trend.trend_id
            for series_id in macro.series_ids()
            for trend in macro.trends_visible_at(series_id, cutoff)
        )
        structural = tuple(item.structural_id for item in macro.structural_visible_at(cutoff))
        geopolitical = SqlGeopoliticalRepository(self.session)
        geopolitical_events = geopolitical.events_visible_at(cutoff)
        geopolitical_event_ids = tuple(item.event_id for item in geopolitical_events)
        geopolitical_paths = tuple(
            item.path_id
            for item in geopolitical.paths_visible_at(cutoff, event_ids=geopolitical_event_ids)
        )
        geopolitical_corroborations = tuple(
            item.corroboration_id for item in geopolitical.corroborations_visible_at(cutoff)
        )
        context_id = content_id(
            "replay-snapshot",
            {
                "cutoff": cutoff,
                "events": events,
                "policies": policies,
                "news": news,
                "fundamentals": fundamentals,
                "graph": graph,
                "market": market_ids,
                "macro": macro_observations,
                "trends": trends,
                "structural": structural,
                "geopolitical_events": geopolitical_event_ids,
                "geopolitical_paths": geopolitical_paths,
                "geopolitical_corroborations": geopolitical_corroborations,
            },
        )
        return ReplaySnapshot(
            cutoff,
            context_id,
            market_ids,
            events,
            policies,
            news,
            fundamentals,
            graph,
            macro_observations,
            trends,
            structural,
            geopolitical_event_ids,
            geopolitical_paths,
            geopolitical_corroborations,
        )

    def commit(self, item: ResearchCommitment) -> bool:
        case = self.repository.get_case(item.case_id)
        if case is None or item.replay_timestamp != case.cutoff:
            raise IntegrityViolation("research commitment cutoff does not match replay case")
        inserted = self.repository.add_commitment(item)
        self.session.commit()
        return inserted

    def record_run(self, item: ReplayRun) -> bool:
        inserted = self.repository.add_run(item)
        self.session.commit()
        return inserted

    def evaluate(
        self,
        run: ReplayRun,
        *,
        horizon_end: datetime,
        evaluated_at: datetime,
        direction_requested: bool = False,
    ) -> OutcomeEvaluation:
        horizon = require_aware_utc(horizon_end, "horizon_end")
        evaluated = require_aware_utc(evaluated_at, "evaluated_at")
        if evaluated < horizon:
            raise IntegrityViolation("outcome horizon has not matured")
        case = self.repository.get_case(run.case_id)
        if case is None:
            raise IntegrityViolation("outcome references unknown replay case")
        asset_id = case.asset_ids[0]
        history = self.market.get_market_data(
            asset_id,
            datetime(1970, 1, 1, tzinfo=UTC),
            case.cutoff,
            case.cutoff,
        )
        future = self.market.get_market_data(asset_id, case.cutoff, horizon, evaluated)
        if not history or not future:
            raise IntegrityViolation("insufficient visible market data for outcome")
        start = Decimal(history[-1].effective_close)
        prices = [Decimal(item.effective_close) for item in future]
        forward = prices[-1] / start - 1
        returns = [prices[index] / prices[index - 1] - 1 for index in range(1, len(prices))]
        adverse = min(price / start - 1 for price in prices)
        favorable = max(price / start - 1 for price in prices)
        peak = prices[0]
        drawdown = Decimal(0)
        for price in prices:
            peak = max(peak, price)
            drawdown = min(drawdown, price / peak - 1)
        volatility = None
        if returns:
            mean = sum(returns) / Decimal(len(returns))
            variance = sum((item - mean) ** 2 for item in returns) / Decimal(len(returns))
            volatility = Decimal(str(math.sqrt(float(variance))))
        benchmark_relative = None
        benchmark_ids: tuple[str, ...] = ()
        if case.benchmark_asset_id:
            benchmark_history = self.market.get_market_data(
                case.benchmark_asset_id,
                datetime(1970, 1, 1, tzinfo=UTC),
                case.cutoff,
                case.cutoff,
            )
            benchmark_future = self.market.get_market_data(
                case.benchmark_asset_id, case.cutoff, horizon, evaluated
            )
            if benchmark_history and benchmark_future:
                benchmark_return = (
                    Decimal(benchmark_future[-1].effective_close)
                    / Decimal(benchmark_history[-1].effective_close)
                    - 1
                )
                benchmark_relative = forward - benchmark_return
                benchmark_ids = tuple(item.observation_id for item in benchmark_future)
        result = OutcomeEvaluation(
            run.run_id,
            evaluated,
            horizon,
            _decimal(forward),
            _optional_decimal(benchmark_relative),
            _decimal(adverse),
            _decimal(favorable),
            _optional_decimal(volatility),
            _decimal(drawdown),
            ("up" if forward > 0 else "down" if forward < 0 else "flat")
            if direction_requested
            else None,
            tuple(item.observation_id for item in (*history[-1:], *future)) + benchmark_ids,
        )
        self.repository.add_evaluation(result)
        self.session.commit()
        return result


def _decimal(value: Decimal) -> str:
    return format(value, ".12f").rstrip("0").rstrip(".") or "0"


def _optional_decimal(value: Decimal | None) -> str | None:
    return None if value is None else _decimal(value)
