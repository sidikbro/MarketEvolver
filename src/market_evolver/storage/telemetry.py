"""Measured storage and ingestion growth, without forecasting."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import TypedDict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from market_evolver.storage.models import (
    AnonymizationMappingModel,
    ArtifactModel,
    AssetModel,
    BacktestDatasetModel,
    BacktestResultModel,
    BenchmarkPairModel,
    CanonicalEventModel,
    ClaimContradictionModel,
    ClaimCorroborationModel,
    ClaimLineageModel,
    ClaimResolutionModel,
    CompanyExposureModel,
    CompanyModel,
    ContextManifestModel,
    CoordinationCandidateModel,
    DerivedFundamentalModel,
    EventMechanismLinkModel,
    EventModel,
    EventSupportModel,
    EventTransitionModel,
    EvidenceContradictionModel,
    EvidenceModel,
    ExperimentRegistryModel,
    ExperimentSpecificationModel,
    ExpertAssessmentModel,
    ExpertComparisonModel,
    ExpertDefinitionModel,
    ExpertRoutingModel,
    ExpertScorecardModel,
    ExpertSessionModel,
    ExpertToolAuditModel,
    FilingModel,
    FundamentalModel,
    FusionReputationModel,
    FusionScoreModel,
    GeopoliticalCandidateModel,
    GeopoliticalCandidateReviewModel,
    GeopoliticalCorroborationModel,
    GeopoliticalEventModel,
    GeopoliticalTransmissionModel,
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
    NarrativeCandidateModel,
    NewsCandidateModel,
    NewsCandidateReviewModel,
    NewsCorroborationModel,
    NewsEntityModel,
    NewsItemModel,
    NormalizedObservationModel,
    OutcomeEvaluationModel,
    PaperAccountSnapshotModel,
    PaperAuditModel,
    PaperExecutionDecisionModel,
    PaperFillModel,
    PaperOrderModel,
    PaperPortfolioModel,
    PaperRiskEvaluationModel,
    PaperRiskPolicyModel,
    PaperSignalModel,
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
    RumorClaimModel,
    SocialPostModel,
    SocialPropagationModel,
    SocialReputationModel,
    SocialSourceModel,
    SourceModel,
    StructuralTrendModel,
    TelegramCheckpointModel,
    TelegramReceiptModel,
    TelegramRunModel,
    TestSetAccessModel,
    TrendDivergenceModel,
    TrendSignalModel,
    UnifiedClaimModel,
)


@dataclass(frozen=True, slots=True)
class DailyMeasurement:
    day: date
    value: int


class TelegramSourceTelemetry(TypedDict):
    messages: int
    bytes: int
    originals: int
    forwards: int
    copies: int
    edits: int
    deletions: int
    media_references: int
    rumor_candidates: int
    narrative_candidates: int
    messages_by_day: dict[str, int]
    bytes_by_day: dict[str, int]


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
    geopolitical_candidates_by_day: tuple[DailyMeasurement, ...] = ()
    geopolitical_confirmed_by_day: tuple[DailyMeasurement, ...] = ()
    geopolitical_contradictions_by_day: tuple[DailyMeasurement, ...] = ()
    geopolitical_revisions_by_day: tuple[DailyMeasurement, ...] = ()
    geopolitical_raw_bytes_by_day: tuple[DailyMeasurement, ...] = ()
    geopolitical_affected_mechanisms: dict[str, int] | None = None
    geopolitical_replay_inclusions: int = 0
    social_posts_by_day: tuple[DailyMeasurement, ...] = ()
    social_source_count: int = 0
    social_narrative_count: int = 0
    social_rumor_count: int = 0
    social_duplicate_count: int = 0
    social_coordination_count: int = 0
    telegram_by_source: dict[str, TelegramSourceTelemetry] | None = None
    unified_claims_by_day: tuple[DailyMeasurement, ...] = ()
    fused_clusters_by_day: tuple[DailyMeasurement, ...] = ()
    corroborated_claims_by_day: tuple[DailyMeasurement, ...] = ()
    contradicted_claims_by_day: tuple[DailyMeasurement, ...] = ()
    average_confirmation_lag_seconds: float = 0.0
    source_domain_resolution_counts: dict[str, int] | None = None
    experiments_by_day: tuple[DailyMeasurement, ...] = ()
    backtests_by_day: tuple[DailyMeasurement, ...] = ()
    trades_simulated: int = 0
    backtest_runtime_ms: int = 0
    backtest_parquet_bytes_read: int = 0
    rejected_experiments: int = 0
    leakage_failures: int = 0
    test_set_accesses: int = 0
    paper_signals_received: int = 0
    paper_orders_proposed: int = 0
    paper_fills: int = 0
    paper_snapshots: int = 0
    paper_risk_triggers: int = 0
    paper_halt_events: int = 0
    expert_sessions: int = 0
    expert_routing_decisions: int = 0
    expert_tools_requested: int = 0
    expert_tool_denials: int = 0
    expert_scorecards: int = 0
    expert_comparisons: int = 0
    expert_sessions_by_day: tuple[DailyMeasurement, ...] = ()
    expert_sessions_by_domain: dict[str, int] | None = None


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
            SocialSourceModel,
            SocialPostModel,
            NarrativeCandidateModel,
            RumorClaimModel,
            SocialPropagationModel,
            CoordinationCandidateModel,
            SocialReputationModel,
            TelegramReceiptModel,
            TelegramCheckpointModel,
            TelegramRunModel,
            UnifiedClaimModel,
            ClaimLineageModel,
            ClaimCorroborationModel,
            ClaimResolutionModel,
            ClaimContradictionModel,
            FusionScoreModel,
            FusionReputationModel,
            ExperimentSpecificationModel,
            BacktestDatasetModel,
            BacktestResultModel,
            TestSetAccessModel,
            ExperimentRegistryModel,
            TrendDivergenceModel,
            StructuralTrendModel,
            GeopoliticalEventModel,
            GeopoliticalCandidateModel,
            GeopoliticalCandidateReviewModel,
            GeopoliticalTransmissionModel,
            GeopoliticalCorroborationModel,
            PaperRiskPolicyModel,
            PaperPortfolioModel,
            PaperAccountSnapshotModel,
            PaperSignalModel,
            PaperOrderModel,
            PaperRiskEvaluationModel,
            PaperExecutionDecisionModel,
            PaperFillModel,
            PaperAuditModel,
            ExpertDefinitionModel,
            ExpertToolAuditModel,
            ExpertSessionModel,
            ExpertAssessmentModel,
            ExpertRoutingModel,
            ExpertScorecardModel,
            ExpertComparisonModel,
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
    geopolitical_candidates: dict[date, int] = {}
    for candidate in session.scalars(select(GeopoliticalCandidateModel)):
        day = candidate.created_at.date()
        geopolitical_candidates[day] = geopolitical_candidates.get(day, 0) + 1
    geopolitical_confirmed: dict[date, int] = {}
    geopolitical_revisions: dict[date, int] = {}
    geopolitical_events = tuple(session.scalars(select(GeopoliticalEventModel)))
    for geopolitical_event in geopolitical_events:
        day = geopolitical_event.first_observed_at.date()
        if geopolitical_event.confirmation_state == "confirmed":
            geopolitical_confirmed[day] = geopolitical_confirmed.get(day, 0) + 1
        if geopolitical_event.version > 1:
            geopolitical_revisions[day] = geopolitical_revisions.get(day, 0) + 1
    geopolitical_contradictions: dict[date, int] = {}
    for corroboration in session.scalars(select(GeopoliticalCorroborationModel)):
        if corroboration.kind in {"official_contradiction", "unresolved_conflict"}:
            day = corroboration.observed_at.date()
            geopolitical_contradictions[day] = geopolitical_contradictions.get(day, 0) + 1
    geopolitical_mechanisms: dict[str, int] = {}
    for path in session.scalars(select(GeopoliticalTransmissionModel)):
        for mechanism in path.mechanisms:
            geopolitical_mechanisms[mechanism] = geopolitical_mechanisms.get(mechanism, 0) + 1
    geopolitical_artifacts: dict[date, set[str]] = {}
    for receipt in session.scalars(select(RawIngestionModel)):
        if receipt.dataset.startswith("geopolitical-"):
            geopolitical_artifacts.setdefault(receipt.first_observed_at.date(), set()).add(
                receipt.artifact_sha256
            )
    social_days: dict[date, int] = {}
    for social_post in session.scalars(select(SocialPostModel)):
        day = social_post.first_observed_at.date()
        social_days[day] = social_days.get(day, 0) + 1
    telegram_stats: dict[str, TelegramSourceTelemetry] = {}
    for telegram_receipt in session.scalars(select(TelegramReceiptModel)):
        stats = telegram_stats.setdefault(
            telegram_receipt.allowlist_source_id,
            {
                "messages": 0,
                "bytes": 0,
                "originals": 0,
                "forwards": 0,
                "copies": 0,
                "edits": 0,
                "deletions": 0,
                "media_references": 0,
                "rumor_candidates": 0,
                "narrative_candidates": 0,
                "messages_by_day": {},
                "bytes_by_day": {},
            },
        )
        stats["messages"] += 1
        stats["bytes"] += telegram_receipt.payload_bytes
        stats["forwards"] += int(
            telegram_receipt.forward_source is not None or telegram_receipt.forward_hidden
        )
        stats["originals"] += int(
            telegram_receipt.forward_source is None and not telegram_receipt.forward_hidden
        )
        telegram_day = telegram_receipt.observed_at.date().isoformat()
        messages_by_day = stats["messages_by_day"]
        bytes_by_day = stats["bytes_by_day"]
        messages_by_day[telegram_day] = messages_by_day.get(telegram_day, 0) + 1
        bytes_by_day[telegram_day] = (
            bytes_by_day.get(telegram_day, 0) + telegram_receipt.payload_bytes
        )
        post = session.get(SocialPostModel, telegram_receipt.post_id)
        if post is not None:
            stats["edits"] += int(post.edited_at is not None)
            stats["deletions"] += int(post.deleted_at is not None)
            stats["media_references"] += len(post.media_references)
            copy_count = int(
                session.scalar(
                    select(func.count())
                    .select_from(SocialPropagationModel)
                    .where(
                        SocialPropagationModel.target_post_id == post.post_id,
                        SocialPropagationModel.relation == "likely_copy_of",
                    )
                )
                or 0
            )
            stats["copies"] += copy_count
            if copy_count and telegram_receipt.forward_source is None:
                stats["originals"] = max(0, stats["originals"] - 1)
            stats["rumor_candidates"] += sum(
                post.post_id in row.supporting_post_ids
                for row in session.scalars(select(RumorClaimModel))
            )
            stats["narrative_candidates"] += sum(
                post.post_id in row.supporting_post_ids
                for row in session.scalars(select(NarrativeCandidateModel))
            )
    fusion_claim_days: dict[date, int] = {}
    claim_rows = tuple(session.scalars(select(UnifiedClaimModel)))
    for claim in claim_rows:
        claim_day = claim.first_observed_at.date()
        fusion_claim_days[claim_day] = fusion_claim_days.get(claim_day, 0) + 1
    cluster_days: dict[date, int] = {}
    for lineage in session.scalars(select(ClaimLineageModel)):
        lineage_day = lineage.observed_at.date()
        cluster_days[lineage_day] = cluster_days.get(lineage_day, 0) + 1
    corroborated_days: dict[date, int] = {}
    contradicted_days: dict[date, int] = {}
    confirmation_lags: list[float] = []
    source_domain_counts: dict[str, int] = {}
    for resolution in session.scalars(select(ClaimResolutionModel)):
        resolution_day = resolution.resolved_at.date()
        resolution_claim = session.get(UnifiedClaimModel, resolution.claim_id)
        if resolution_claim is not None:
            resolution_key = (
                f"{resolution_claim.originating_source_id}:"
                f"{resolution_claim.domain}:{resolution.outcome}"
            )
            source_domain_counts[resolution_key] = source_domain_counts.get(resolution_key, 0) + 1
        if resolution.outcome in {"confirmed", "partially_confirmed"}:
            corroborated_days[resolution_day] = corroborated_days.get(resolution_day, 0) + 1
            if resolution_claim is not None:
                confirmation_lags.append(
                    (resolution.resolved_at - resolution_claim.first_observed_at).total_seconds()
                )
        elif resolution.outcome == "contradicted":
            contradicted_days[resolution_day] = contradicted_days.get(resolution_day, 0) + 1
    experiment_days: dict[date, int] = {}
    experiment_rows = tuple(session.scalars(select(ExperimentSpecificationModel)))
    for experiment in experiment_rows:
        experiment_day = experiment.created_at.date()
        experiment_days[experiment_day] = experiment_days.get(experiment_day, 0) + 1
    backtest_days: dict[date, int] = {}
    backtest_rows = tuple(session.scalars(select(BacktestResultModel)))
    for backtest in backtest_rows:
        backtest_day = backtest.started_at.date()
        backtest_days[backtest_day] = backtest_days.get(backtest_day, 0) + 1
    expert_session_rows = tuple(session.scalars(select(ExpertSessionModel)))
    expert_days: dict[date, int] = {}
    expert_domains: dict[str, int] = {}
    for row in expert_session_rows:
        session_day = row.started_at.date()
        expert_days[session_day] = expert_days.get(session_day, 0) + 1
        expert_domains[row.domain] = expert_domains.get(row.domain, 0) + 1
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
        geopolitical_candidates_by_day=_measurements(geopolitical_candidates),
        geopolitical_confirmed_by_day=_measurements(geopolitical_confirmed),
        geopolitical_contradictions_by_day=_measurements(geopolitical_contradictions),
        geopolitical_revisions_by_day=_measurements(geopolitical_revisions),
        geopolitical_raw_bytes_by_day=_measurements(
            {
                day: sum(artifact_sizes.get(digest, 0) for digest in digests)
                for day, digests in geopolitical_artifacts.items()
            }
        ),
        geopolitical_affected_mechanisms=dict(sorted(geopolitical_mechanisms.items())),
        geopolitical_replay_inclusions=len(geopolitical_events),
        social_posts_by_day=_measurements(social_days),
        social_source_count=_count(session, SocialSourceModel),
        social_narrative_count=_count(session, NarrativeCandidateModel),
        social_rumor_count=_count(session, RumorClaimModel),
        social_duplicate_count=_count(session, SocialPropagationModel),
        social_coordination_count=_count(session, CoordinationCandidateModel),
        telegram_by_source=telegram_stats,
        unified_claims_by_day=_measurements(fusion_claim_days),
        fused_clusters_by_day=_measurements(cluster_days),
        corroborated_claims_by_day=_measurements(corroborated_days),
        contradicted_claims_by_day=_measurements(contradicted_days),
        average_confirmation_lag_seconds=(
            sum(confirmation_lags) / len(confirmation_lags) if confirmation_lags else 0.0
        ),
        source_domain_resolution_counts=source_domain_counts,
        experiments_by_day=_measurements(experiment_days),
        backtests_by_day=_measurements(backtest_days),
        trades_simulated=sum(item.executed_trades for item in backtest_rows),
        backtest_runtime_ms=sum(item.runtime_ms for item in backtest_rows),
        backtest_parquet_bytes_read=sum(item.parquet_bytes_read for item in backtest_rows),
        rejected_experiments=sum(
            item.status in {"rejected", "invalid"} for item in experiment_rows
        ),
        leakage_failures=sum(
            any("future" in reason or "leakage" in reason for reason in item.rejection_reasons)
            for item in backtest_rows
        ),
        test_set_accesses=_count(session, TestSetAccessModel),
        paper_signals_received=_count(session, PaperSignalModel),
        paper_orders_proposed=_count(session, PaperOrderModel),
        paper_fills=_count(session, PaperFillModel),
        paper_snapshots=_count(session, PaperAccountSnapshotModel),
        paper_risk_triggers=int(
            session.scalar(
                select(func.count())
                .select_from(PaperRiskEvaluationModel)
                .where(PaperRiskEvaluationModel.action != "approved")
            )
            or 0
        ),
        paper_halt_events=int(
            session.scalar(
                select(func.count())
                .select_from(PaperRiskEvaluationModel)
                .where(PaperRiskEvaluationModel.action == "portfolio_halted")
            )
            or 0
        ),
        expert_sessions=_count(session, ExpertSessionModel),
        expert_routing_decisions=_count(session, ExpertRoutingModel),
        expert_tools_requested=_count(session, ExpertToolAuditModel),
        expert_tool_denials=int(
            session.scalar(
                select(func.count())
                .select_from(ExpertToolAuditModel)
                .where(ExpertToolAuditModel.decision == "denied")
            )
            or 0
        ),
        expert_scorecards=_count(session, ExpertScorecardModel),
        expert_comparisons=_count(session, ExpertComparisonModel),
        expert_sessions_by_day=_measurements(expert_days),
        expert_sessions_by_domain=dict(sorted(expert_domains.items())),
    )


def _count(session: Session, model: type) -> int:
    return int(session.scalar(select(func.count()).select_from(model)) or 0)


def _measurements(values: dict[date, int]) -> tuple[DailyMeasurement, ...]:
    return tuple(DailyMeasurement(day, values[day]) for day in sorted(values))
