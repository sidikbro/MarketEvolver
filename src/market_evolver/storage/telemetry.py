"""Measured storage and ingestion growth, without forecasting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from market_evolver.storage.models import (
    AnonymizationMappingModel,
    ArtifactModel,
    AssetModel,
    BenchmarkPairModel,
    CanonicalEventModel,
    CompanyExposureModel,
    CompanyModel,
    ContextManifestModel,
    DerivedFundamentalModel,
    EventMechanismLinkModel,
    EventModel,
    EventSupportModel,
    EventTransitionModel,
    EvidenceContradictionModel,
    EvidenceModel,
    FilingModel,
    FundamentalModel,
    GovernmentActionModel,
    GovernmentCandidateModel,
    GovernmentTransitionModel,
    HypothesisModel,
    IngestionManifestModel,
    KnowledgeAliasModel,
    KnowledgeEntityModel,
    KnowledgeExposureModel,
    KnowledgeRelationshipModel,
    MacroObservationModel,
    MarketObservationModel,
    MarketPartitionModel,
    NewsCandidateModel,
    NewsCandidateReviewModel,
    NewsCorroborationModel,
    NewsEntityModel,
    NewsItemModel,
    NormalizedObservationModel,
    OutcomeEvaluationModel,
    ProviderCallModel,
    RawIngestionModel,
    ReplayCaseModel,
    ReplayCommitmentModel,
    ReplayRunModel,
    ResearchClaimModel,
    ResearchContextModel,
    ResearchDecisionModel,
    ResearchHypothesisModel,
    ResearchReviewModel,
    ResearchTraceModel,
    SourceModel,
    StructuralTrendModel,
    TrendDivergenceModel,
    TrendSignalModel,
)


@dataclass(frozen=True, slots=True)
class DailyMeasurement:
    day: date
    value: int


@dataclass(frozen=True, slots=True)
class StorageTelemetry:
    raw_artifact_bytes: int
    database_record_counts: dict[str, int]
    ingestion_bytes_by_day: tuple[DailyMeasurement, ...]
    item_growth_by_day: tuple[DailyMeasurement, ...]
    news_items_by_day: tuple[DailyMeasurement, ...] = ()
    raw_news_bytes_by_day: tuple[DailyMeasurement, ...] = ()
    news_duplicates_by_day: tuple[DailyMeasurement, ...] = ()
    news_revisions_by_day: tuple[DailyMeasurement, ...] = ()
    quarantined_news_by_day: tuple[DailyMeasurement, ...] = ()
    news_items_by_source: dict[str, int] | None = None
    news_bytes_by_source: dict[str, int] | None = None
    policy_documents_by_day: tuple[DailyMeasurement, ...] = ()
    policy_revisions_by_day: tuple[DailyMeasurement, ...] = ()
    policy_transitions_by_day: tuple[DailyMeasurement, ...] = ()
    raw_government_bytes_by_day: tuple[DailyMeasurement, ...] = ()
    policy_candidate_count: int = 0
    policy_promotion_count: int = 0
    market_rows_by_day: tuple[DailyMeasurement, ...] = ()
    parquet_bytes_by_day: tuple[DailyMeasurement, ...] = ()
    market_assets: int = 0
    replay_cases: int = 0
    replay_runtime_ms: int = 0
    benchmark_artifact_bytes: int = 0
    macro_observations_by_day: tuple[DailyMeasurement, ...] = ()
    macro_series_count: int = 0
    macro_revision_rate: float = 0.0
    macro_raw_bytes: int = 0
    trend_calculations: int = 0
    macro_replay_impact: int = 0


def measure_storage(session: Session) -> StorageTelemetry:
    counts = {
        model.__tablename__: _count(session, model)
        for model in (
            ArtifactModel,
            SourceModel,
            EvidenceModel,
            EventModel,
            HypothesisModel,
            ResearchDecisionModel,
            NormalizedObservationModel,
            RawIngestionModel,
            IngestionManifestModel,
            CanonicalEventModel,
            EventSupportModel,
            EventTransitionModel,
            EventMechanismLinkModel,
            KnowledgeEntityModel,
            KnowledgeAliasModel,
            KnowledgeRelationshipModel,
            KnowledgeExposureModel,
            NewsItemModel,
            NewsEntityModel,
            NewsCandidateModel,
            NewsCandidateReviewModel,
            NewsCorroborationModel,
            EvidenceContradictionModel,
            GovernmentActionModel,
            GovernmentTransitionModel,
            GovernmentCandidateModel,
            CompanyModel,
            FilingModel,
            FundamentalModel,
            DerivedFundamentalModel,
            CompanyExposureModel,
            ResearchContextModel,
            ContextManifestModel,
            ProviderCallModel,
            ResearchClaimModel,
            ResearchHypothesisModel,
            ResearchReviewModel,
            ResearchTraceModel,
            AnonymizationMappingModel,
            AssetModel,
            MarketPartitionModel,
            MarketObservationModel,
            ReplayCaseModel,
            ReplayCommitmentModel,
            ReplayRunModel,
            OutcomeEvaluationModel,
            BenchmarkPairModel,
            MacroObservationModel,
            TrendSignalModel,
            TrendDivergenceModel,
            StructuralTrendModel,
        )
    }
    raw_bytes = int(
        session.scalar(select(func.coalesce(func.sum(ArtifactModel.size_bytes), 0))) or 0
    )
    ingestion_rows = session.execute(
        select(
            func.date(IngestionManifestModel.started_at),
            func.sum(IngestionManifestModel.bytes_downloaded),
        )
        .group_by(func.date(IngestionManifestModel.started_at))
        .order_by(func.date(IngestionManifestModel.started_at))
    )
    growth_rows = session.execute(
        select(
            func.date(NormalizedObservationModel.first_observed_at),
            func.count(NormalizedObservationModel.provenance_id),
        )
        .group_by(func.date(NormalizedObservationModel.first_observed_at))
        .order_by(func.date(NormalizedObservationModel.first_observed_at))
    )
    news_models = tuple(session.scalars(select(NewsItemModel)))
    artifact_sizes = {
        item.sha256: item.size_bytes for item in session.scalars(select(ArtifactModel))
    }
    news_by_day: dict[date, int] = {}
    duplicate_by_day: dict[date, int] = {}
    revision_by_day: dict[date, int] = {}
    quarantine_by_day: dict[date, int] = {}
    source_volume: dict[str, int] = {}
    source_artifacts: dict[str, set[str]] = {}
    artifact_days: dict[date, set[str]] = {}
    for item in news_models:
        day = item.first_observed_at.date()
        news_by_day[day] = news_by_day.get(day, 0) + 1
        source_volume[item.source_id] = source_volume.get(item.source_id, 0) + 1
        source_artifacts.setdefault(item.source_id, set()).add(item.raw_artifact_sha256)
        artifact_days.setdefault(day, set()).add(item.raw_artifact_sha256)
        if item.duplicate_kind in {"reingested", "syndicated"}:
            duplicate_by_day[day] = duplicate_by_day.get(day, 0) + 1
        if item.duplicate_kind == "revision":
            revision_by_day[day] = revision_by_day.get(day, 0) + 1
        if item.evidence_security_class == "quarantined":
            quarantine_by_day[day] = quarantine_by_day.get(day, 0) + 1
    policy_actions = tuple(session.scalars(select(GovernmentActionModel)))
    policy_transitions = tuple(session.scalars(select(GovernmentTransitionModel)))
    policy_candidates = tuple(session.scalars(select(GovernmentCandidateModel)))
    policy_by_day: dict[date, int] = {}
    policy_revisions: dict[date, int] = {}
    transition_by_day: dict[date, int] = {}
    for policy_action in policy_actions:
        day = policy_action.first_observed_at.date()
        policy_by_day[day] = policy_by_day.get(day, 0) + 1
        if policy_action.version > 1:
            policy_revisions[day] = policy_revisions.get(day, 0) + 1
    for policy_transition in policy_transitions:
        day = policy_transition.transitioned_at.date()
        transition_by_day[day] = transition_by_day.get(day, 0) + 1
    government_artifacts: dict[date, set[str]] = {}
    for receipt in session.scalars(
        select(RawIngestionModel).where(RawIngestionModel.dataset == "policy-interest-rate")
    ):
        government_artifacts.setdefault(receipt.first_observed_at.date(), set()).add(
            receipt.artifact_sha256
        )
    market_rows: dict[date, int] = {}
    for observation in session.scalars(select(MarketObservationModel)):
        day = observation.observed_at.date()
        market_rows[day] = market_rows.get(day, 0) + 1
    parquet_bytes: dict[date, int] = {}
    partitions = tuple(session.scalars(select(MarketPartitionModel)))
    for partition in partitions:
        day = partition.created_at.date()
        parquet_bytes[day] = parquet_bytes.get(day, 0) + partition.size_bytes
    macro_rows = tuple(session.scalars(select(MacroObservationModel)))
    macro_by_day: dict[date, int] = {}
    for macro_observation in macro_rows:
        day = macro_observation.first_observed_at.date()
        macro_by_day[day] = macro_by_day.get(day, 0) + 1
    macro_artifacts = {
        receipt.artifact_sha256
        for receipt in session.scalars(select(RawIngestionModel))
        if receipt.dataset.startswith("macro-")
    }
    return StorageTelemetry(
        raw_artifact_bytes=raw_bytes,
        database_record_counts=counts,
        ingestion_bytes_by_day=tuple(
            DailyMeasurement(date.fromisoformat(str(day)), int(value))
            for day, value in ingestion_rows
        ),
        item_growth_by_day=tuple(
            DailyMeasurement(date.fromisoformat(str(day)), int(value)) for day, value in growth_rows
        ),
        news_items_by_day=_measurements(news_by_day),
        raw_news_bytes_by_day=_measurements(
            {
                day: sum(artifact_sizes.get(digest, 0) for digest in digests)
                for day, digests in artifact_days.items()
            }
        ),
        news_duplicates_by_day=_measurements(duplicate_by_day),
        news_revisions_by_day=_measurements(revision_by_day),
        quarantined_news_by_day=_measurements(quarantine_by_day),
        news_items_by_source=dict(sorted(source_volume.items())),
        news_bytes_by_source={
            source_id: sum(artifact_sizes.get(digest, 0) for digest in digests)
            for source_id, digests in sorted(source_artifacts.items())
        },
        policy_documents_by_day=_measurements(policy_by_day),
        policy_revisions_by_day=_measurements(policy_revisions),
        policy_transitions_by_day=_measurements(transition_by_day),
        raw_government_bytes_by_day=_measurements(
            {
                day: sum(artifact_sizes.get(digest, 0) for digest in digests)
                for day, digests in government_artifacts.items()
            }
        ),
        policy_candidate_count=len(policy_candidates),
        policy_promotion_count=sum(item.review_state == "promoted" for item in policy_candidates),
        market_rows_by_day=_measurements(market_rows),
        parquet_bytes_by_day=_measurements(parquet_bytes),
        market_assets=len(set(session.scalars(select(AssetModel.asset_id)))),
        replay_cases=_count(session, ReplayCaseModel),
        replay_runtime_ms=int(
            session.scalar(select(func.coalesce(func.sum(ReplayRunModel.runtime_ms), 0))) or 0
        ),
        benchmark_artifact_bytes=sum(item.size_bytes for item in partitions),
        macro_observations_by_day=_measurements(macro_by_day),
        macro_series_count=len({item.series_id for item in macro_rows}),
        macro_revision_rate=(
            sum(item.revision_of is not None for item in macro_rows) / len(macro_rows)
            if macro_rows
            else 0.0
        ),
        macro_raw_bytes=sum(artifact_sizes.get(key, 0) for key in macro_artifacts),
        trend_calculations=_count(session, TrendSignalModel),
        macro_replay_impact=_count(session, TrendSignalModel),
    )


def _count(session: Session, model: type) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _measurements(values: dict[date, int]) -> tuple[DailyMeasurement, ...]:
    return tuple(DailyMeasurement(day, values[day]) for day in sorted(values))
