"""Command-line entry point for source discovery and governed ingestion."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Sequence
from dataclasses import asdict, replace
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_evolver.company.repositories import SqlCompanyRepository
from market_evolver.company.schemas import CompanyVersion, Filing
from market_evolver.company.seed import seed_companies
from market_evolver.config import AppConfig, load_config
from market_evolver.errors import GovernanceViolation
from market_evolver.evolve.repository import SqlEvolutionRepository
from market_evolver.evolve.schemas import (
    ChampionRegistryEvent,
    ImprovementProposal,
    ProposalStatus,
    ProposalType,
    RegistryAction,
)
from market_evolver.experiment.baselines import walk_forward_windows
from market_evolver.experiment.engine import BacktestEngine
from market_evolver.experiment.repository import SqlExperimentRepository
from market_evolver.experiment.schemas import (
    CostModel,
    EntryRule,
    EvaluationWindow,
    ExitRule,
    ExperimentSpecification,
    ExperimentStatus,
    PartitionKind,
    PositionPolicy,
    RebalanceFrequency,
    RuleOperator,
    SignalClause,
    SignalDefinition,
    SignalKind,
    SignalObservation,
    TestSetAccess,
)
from market_evolver.expert.evaluation import BENCHMARK_CASES
from market_evolver.expert.evaluation import transition as transition_expert
from market_evolver.expert.repository import SqlExpertRepository
from market_evolver.expert.routing import panel_route
from market_evolver.expert.routing import route as route_expert
from market_evolver.expert.schemas import ExpertStatus
from market_evolver.expert.seed import FIXED_EXPERTS
from market_evolver.fusion.benchmark import run_false_rumor_benchmark
from market_evolver.fusion.engine import calculate_reputation, current_corroboration_state
from market_evolver.fusion.repository import SqlFusionRepository
from market_evolver.geopolitical.baselines import calculate_baseline
from market_evolver.geopolitical.extraction import extract_candidate
from market_evolver.geopolitical.repository import SqlGeopoliticalRepository
from market_evolver.government.connectors import BankOfIsraelPolicyConnector
from market_evolver.government.extraction import extract_policy_candidate
from market_evolver.government.repositories import SqlGovernmentRepository
from market_evolver.government.schemas import GovernmentAction
from market_evolver.ingestion.boi import BankOfIsraelConnector
from market_evolver.ingestion.repositories import SqlManifestRepository
from market_evolver.ingestion.runner import IngestionRunner
from market_evolver.knowledge.repositories import SqlKnowledgeGraph
from market_evolver.knowledge.schemas import EntityVersion
from market_evolver.knowledge.seed import seed_knowledge_graph
from market_evolver.macro.repository import SqlMacroRepository
from market_evolver.macro.schemas import (
    MacroCategory,
    MacroObservation,
    SeasonalAdjustment,
    TrendHorizon,
)
from market_evolver.macro.trends import calculate_trend
from market_evolver.market.history import (
    BoiUsdIlsHistoryConnector,
    CompositionHistoryStatus,
    DatasetType,
    HistoricalDataset,
    HistoricalDatasetStore,
    HistoricalReplayEligibility,
    PriceAdjustmentPolicy,
    SourceClass,
    StooqDailyConnector,
    SurvivorshipStatus,
    validate_quality,
)
from market_evolver.market.schemas import AdjustmentStatus, MarketObservation, ObservationType
from market_evolver.market.seed import seed_assets
from market_evolver.market.store import MarketDataStore
from market_evolver.news.connectors import BbcBusinessRssConnector
from market_evolver.news.repositories import SqlNewsRepository
from market_evolver.news.runner import NewsIngestionRunner
from market_evolver.news.schemas import NewsItem
from market_evolver.observatory.extraction import BoiEventExtractionPipeline
from market_evolver.observatory.repositories import (
    SqlCanonicalEventRepository,
    observatory_summary,
)
from market_evolver.observatory.schemas import CanonicalEvent, EventStatus
from market_evolver.paper.policy import NIS_2000_POLICY
from market_evolver.paper.repository import SqlPaperRepository
from market_evolver.paper.runtime import PaperRuntime
from market_evolver.paper.schemas import (
    AllocationPolicy,
    AuditRecord,
    PaperPortfolio,
    PortfolioStatus,
)
from market_evolver.replay.benchmark import BenchmarkRunner, benchmark_metrics
from market_evolver.replay.engine import ReplayEngine
from market_evolver.replay.repositories import SqlReplayRepository
from market_evolver.replay.schemas import ResearchMode
from market_evolver.research.gates import anonymize_context
from market_evolver.research.providers import JsonHttpProvider, MockProvider, ResearchProvider
from market_evolver.research.repositories import SqlResearchRepository
from market_evolver.research.schemas import AnonymizationMapping
from market_evolver.research.service import ResearchService
from market_evolver.social.repository import SqlSocialRepository
from market_evolver.sources.registry import DEFAULT_REGISTRY
from market_evolver.storage.artifacts import LocalArtifactStore
from market_evolver.storage.database import create_postgres_engine
from market_evolver.storage.models import (
    CoordinationCandidateModel,
    EvidenceModel,
    GovernmentCandidateModel,
)
from market_evolver.storage.telemetry import measure_storage
from market_evolver.telegram.client import TelethonClientAdapter
from market_evolver.telegram.runner import TelegramRunner
from market_evolver.topology.repository import SqlTopologyRepository
from market_evolver.topology.schemas import TopologyAction, TopologyRegistryEvent


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="market-evolver")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/default.toml"),
        help="TOML configuration path",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    source = commands.add_parser("source")
    source_commands = source.add_subparsers(dest="source_command", required=True)
    source_commands.add_parser("list")

    ingest = commands.add_parser("ingest")
    ingest.add_argument("connector", choices=("boi",))
    ingest.add_argument(
        "--dataset",
        default=BankOfIsraelConnector.dataset_name,
    )
    commands.add_parser("ingest-status")
    commands.add_parser("storage-telemetry")
    event = commands.add_parser("event")
    event_commands = event.add_subparsers(dest="event_command", required=True)
    event_commands.add_parser("list")
    show = event_commands.add_parser("show")
    show.add_argument("event_id")
    replay = event_commands.add_parser("replay")
    replay.add_argument("--at", required=True)
    event_commands.add_parser("report")
    entity = commands.add_parser("entity")
    entity_commands = entity.add_subparsers(dest="entity_command", required=True)
    entity_list = entity_commands.add_parser("list")
    entity_list.add_argument("--at")
    entity_show = entity_commands.add_parser("show")
    entity_show.add_argument("entity_id")
    entity_show.add_argument("--at")
    entity_resolve = entity_commands.add_parser("resolve")
    entity_resolve.add_argument("alias")
    entity_resolve.add_argument("--at")
    entity_commands.add_parser("seed")
    graph = commands.add_parser("graph")
    graph_commands = graph.add_subparsers(dest="graph_command", required=True)
    trace = graph_commands.add_parser("trace-event")
    trace.add_argument("event_id")
    trace.add_argument("--at", required=True)
    neighbors = graph_commands.add_parser("neighbors")
    neighbors.add_argument("entity_id")
    neighbors.add_argument("--at", required=True)
    news = commands.add_parser("news")
    news_commands = news.add_subparsers(dest="news_command", required=True)
    news_commands.add_parser("source-list")
    news_ingest = news_commands.add_parser("ingest")
    news_ingest.add_argument("source", choices=("bbc-business",))
    news_list = news_commands.add_parser("list")
    news_list.add_argument("--at")
    news_show = news_commands.add_parser("show")
    news_show.add_argument("news_id")
    news_replay = news_commands.add_parser("replay")
    news_replay.add_argument("--at", required=True)
    news_candidates = news_commands.add_parser("candidates")
    news_candidates.add_argument("--at")
    news_quarantine = news_commands.add_parser("quarantine")
    news_quarantine.add_argument("--at")
    policy = commands.add_parser("policy")
    policy_commands = policy.add_subparsers(dest="policy_command", required=True)
    policy_commands.add_parser("source-list")
    policy_ingest = policy_commands.add_parser("ingest")
    policy_ingest.add_argument("source", choices=("boi-interest",))
    policy_list = policy_commands.add_parser("list")
    policy_list.add_argument("--at")
    policy_show = policy_commands.add_parser("show")
    policy_show.add_argument("action_id")
    policy_replay = policy_commands.add_parser("replay")
    policy_replay.add_argument("--at", required=True)
    policy_transitions = policy_commands.add_parser("transitions")
    policy_transitions.add_argument("action_id")
    policy_transitions.add_argument("--at")
    policy_candidates = policy_commands.add_parser("candidates")
    policy_candidates.add_argument("--at")
    company = commands.add_parser("company")
    company_commands = company.add_subparsers(dest="company_command", required=True)
    company_list = company_commands.add_parser("list")
    company_list.add_argument("--at")
    company_show = company_commands.add_parser("show")
    company_show.add_argument("company_id")
    company_show.add_argument("--at")
    company_commands.add_parser("seed")
    fundamentals = commands.add_parser("fundamentals")
    fundamentals_commands = fundamentals.add_subparsers(dest="fundamentals_command", required=True)
    fundamentals_show = fundamentals_commands.add_parser("show")
    fundamentals_show.add_argument("company_id")
    fundamentals_show.add_argument("--at", required=True)
    filings = commands.add_parser("filings")
    filings_commands = filings.add_subparsers(dest="filings_command", required=True)
    filings_list = filings_commands.add_parser("list")
    filings_list.add_argument("company_id")
    filings_list.add_argument("--at")
    exposures = commands.add_parser("exposures")
    exposures_commands = exposures.add_subparsers(dest="exposures_command", required=True)
    exposures_show = exposures_commands.add_parser("show")
    exposures_show.add_argument("company_id")
    exposures_show.add_argument("--at", required=True)
    research = commands.add_parser("research")
    research_commands = research.add_subparsers(dest="research_command", required=True)
    build_context = research_commands.add_parser("build-context")
    build_context.add_argument("company_id")
    build_context.add_argument("--at", required=True)
    build_context.add_argument("--anonymize", action="store_true")
    inspect_context = research_commands.add_parser("inspect-context")
    inspect_context.add_argument("context_id")
    hypothesize = research_commands.add_parser("hypothesize")
    hypothesize.add_argument("company_id")
    hypothesize.add_argument("--at", required=True)
    hypothesize.add_argument("--anonymize", action="store_true")
    review = research_commands.add_parser("review")
    review.add_argument("hypothesis_id")
    trace = research_commands.add_parser("trace")
    trace.add_argument("research_id")
    market = commands.add_parser("market")
    market_commands = market.add_subparsers(dest="market_command", required=True)
    market_commands.add_parser("seed-assets")
    market_commands.add_parser("asset-list")
    market_commands.add_parser("source-list")
    market_ingest = market_commands.add_parser("ingest")
    market_ingest.add_argument("path", type=Path)
    market_ingest.add_argument("--dataset-version", required=True)
    market_history = market_commands.add_parser("ingest-history")
    market_history.add_argument("source", choices=("boi", "stooq"))
    market_history.add_argument("instrument")
    market_history.add_argument("--from", dest="date_from", required=True)
    market_history.add_argument("--to", dest="date_to", required=True)
    market_history.add_argument("--symbol")
    market_history.add_argument("--venue")
    market_history.add_argument("--currency")
    market_history.add_argument("--confirm-live", action="store_true")
    market_validate = market_commands.add_parser("validate-dataset")
    market_validate.add_argument("dataset_id")
    market_quality = market_commands.add_parser("quality-report")
    market_quality.add_argument("dataset_id")
    market_commands.add_parser("coverage")
    replay = commands.add_parser("replay")
    replay_commands = replay.add_subparsers(dest="replay_command", required=True)
    replay_commands.add_parser("seed-cases")
    replay_run = replay_commands.add_parser("run")
    replay_run.add_argument("case")
    replay_run.add_argument(
        "--mode", choices=tuple(item.value for item in ResearchMode), required=True
    )
    replay_run.add_argument("--anonymized", action="store_true")
    replay_inspect = replay_commands.add_parser("inspect")
    replay_inspect.add_argument("run_id")
    benchmark = commands.add_parser("benchmark")
    benchmark_commands = benchmark.add_subparsers(dest="benchmark_command", required=True)
    benchmark_commands.add_parser("run")
    benchmark_commands.add_parser("report")
    macro = commands.add_parser("macro")
    macro_commands = macro.add_subparsers(dest="macro_command", required=True)
    macro_commands.add_parser("source-list")
    macro_ingest = macro_commands.add_parser("ingest")
    macro_ingest.add_argument("path", type=Path)
    macro_series = macro_commands.add_parser("series")
    macro_series.add_argument("series_id")
    macro_series.add_argument("--at")
    trends = commands.add_parser("trends")
    trend_commands = trends.add_subparsers(dest="trends_command", required=True)
    trend_show = trend_commands.add_parser("show")
    trend_show.add_argument("series_id")
    trend_show.add_argument("--at")
    trend_calculate = trend_commands.add_parser("calculate")
    trend_calculate.add_argument("series_id")
    trend_calculate.add_argument("--at", required=True)
    trend_replay = trend_commands.add_parser("replay")
    trend_replay.add_argument("--at", required=True)
    geopolitical = commands.add_parser("geopolitical")
    geopolitical_commands = geopolitical.add_subparsers(dest="geopolitical_command", required=True)
    geopolitical_commands.add_parser("source-list")
    geopolitical_list = geopolitical_commands.add_parser("list")
    geopolitical_list.add_argument("--at")
    geopolitical_show = geopolitical_commands.add_parser("show")
    geopolitical_show.add_argument("event_id")
    geopolitical_replay = geopolitical_commands.add_parser("replay")
    geopolitical_replay.add_argument("--at", required=True)
    geopolitical_extract = geopolitical_commands.add_parser("extract")
    geopolitical_extract.add_argument("evidence_id")
    geopolitical_extract.add_argument("--at", required=True)
    geopolitical_baseline = geopolitical_commands.add_parser("baseline")
    geopolitical_baseline.add_argument("--at", required=True)
    social = commands.add_parser("social")
    social_commands = social.add_subparsers(dest="social_command", required=True)
    social_commands.add_parser("source-list")
    social_posts = social_commands.add_parser("posts")
    social_posts.add_argument("--at")
    social_narratives = social_commands.add_parser("narratives")
    social_narratives.add_argument("--at")
    social_rumor = social_commands.add_parser("rumor")
    social_rumor.add_argument("claim_id")
    social_rumor.add_argument("--at")
    social_prop = social_commands.add_parser("propagation")
    social_prop.add_argument("post_id")
    social_prop.add_argument("--at", required=True)
    social_rep = social_commands.add_parser("reputation")
    social_rep.add_argument("source_id")
    social_rep.add_argument("--domain", default="general_market")
    social_rep.add_argument("--at", required=True)
    social_commands.add_parser("coordination")
    telegram = commands.add_parser("telegram")
    telegram_commands = telegram.add_subparsers(dest="telegram_command", required=True)
    telegram_commands.add_parser("validate")
    telegram_ingest = telegram_commands.add_parser("ingest")
    telegram_ingest.add_argument("source_id")
    telegram_ingest.add_argument("--limit", type=int, default=20)
    telegram_backfill = telegram_commands.add_parser("backfill")
    telegram_backfill.add_argument("source_id")
    telegram_backfill.add_argument("--since", required=True)
    telegram_backfill.add_argument("--limit", type=int, default=100)
    telegram_live = telegram_commands.add_parser("live-validate")
    telegram_live.add_argument("--confirm-live", action="store_true")
    telegram_live.add_argument("--root", type=Path, default=Path("data/live_validation/telegram"))
    telegram_live.add_argument("--cleanup", action="store_true")
    fusion = commands.add_parser("fusion")
    fusion_commands = fusion.add_subparsers(dest="fusion_command", required=True)
    fusion_claim = fusion_commands.add_parser("claim")
    fusion_claim.add_argument("claim_id")
    fusion_claim.add_argument("--at")
    fusion_unresolved = fusion_commands.add_parser("unresolved")
    fusion_unresolved.add_argument("--at")
    fusion_contradictions = fusion_commands.add_parser("contradictions")
    fusion_contradictions.add_argument("--at")
    fusion_lead = fusion_commands.add_parser("lead-time")
    fusion_lead.add_argument("claim_id")
    fusion_lead.add_argument("--at")
    fusion_commands.add_parser("benchmark")
    reputation = commands.add_parser("reputation")
    reputation_commands = reputation.add_subparsers(dest="reputation_command", required=True)
    reputation_source = reputation_commands.add_parser("source")
    reputation_source.add_argument("source_id")
    reputation_source.add_argument("--domain", required=True)
    reputation_source.add_argument("--at", required=True)
    experiment = commands.add_parser("experiment")
    experiment_commands = experiment.add_subparsers(dest="experiment_command", required=True)
    experiment_create = experiment_commands.add_parser("create")
    for name in (
        "hypothesis",
        "context",
        "assets",
        "benchmark",
        "cutoff",
        "research-start",
        "research-end",
        "validation-start",
        "validation-end",
        "test-start",
        "test-end",
        "signal-kind",
        "signal-field",
        "signal-operator",
        "signal-value",
    ):
        experiment_create.add_argument(f"--{name}", required=True)
    experiment_validate = experiment_commands.add_parser("validate")
    experiment_validate.add_argument("experiment_id")
    backtest = commands.add_parser("backtest")
    backtest_commands = backtest.add_subparsers(dest="backtest_command", required=True)
    backtest_run = backtest_commands.add_parser("run")
    backtest_run.add_argument("experiment_id")
    backtest_run.add_argument("--signal-at", action="append", default=[])
    backtest_run.add_argument("--signal-provenance", action="append", default=[])
    backtest_run.add_argument("--at", required=True)
    backtest_show = backtest_commands.add_parser("show")
    backtest_show.add_argument("run_id")
    backtest_compare = backtest_commands.add_parser("compare")
    backtest_compare.add_argument("run_a")
    backtest_compare.add_argument("run_b")
    walkforward = commands.add_parser("walkforward")
    walkforward_commands = walkforward.add_subparsers(dest="walkforward_command", required=True)
    walkforward_run = walkforward_commands.add_parser("run")
    walkforward_run.add_argument("experiment_id")
    paper = commands.add_parser("paper")
    paper_commands = paper.add_subparsers(dest="paper_command", required=True)
    paper_create = paper_commands.add_parser("create")
    paper_create.add_argument("portfolio_id")
    paper_create.add_argument("--name", required=True)
    paper_create.add_argument("--experiment", required=True)
    paper_create.add_argument("--benchmark", required=True)
    paper_create.add_argument("--initial-cash", default="2000")
    for operation in ("start", "step", "status", "positions", "risk", "pause", "resume", "stop"):
        command = paper_commands.add_parser(operation)
        command.add_argument("portfolio_id")
        if operation == "step":
            command.add_argument("--at", required=True)
    expert = commands.add_parser("expert")
    expert_commands = expert.add_subparsers(dest="expert_command", required=True)
    expert_commands.add_parser("seed")
    expert_commands.add_parser("list")
    expert_show = expert_commands.add_parser("show")
    expert_show.add_argument("expert_id")
    expert_route = expert_commands.add_parser("route")
    expert_route.add_argument("subject")
    expert_route.add_argument("--tags", required=True)
    expert_route.add_argument("--geography", default="IL")
    expert_route.add_argument("--at", required=True)
    expert_panel = expert_commands.add_parser("panel")
    expert_panel.add_argument("subject")
    expert_panel.add_argument("--tags", required=True)
    expert_panel.add_argument("--geography", default="IL")
    expert_panel.add_argument("--at", required=True)
    expert_run = expert_commands.add_parser("run")
    expert_run.add_argument("expert_id")
    expert_run.add_argument("--at", required=True)
    expert_score = expert_commands.add_parser("scorecard")
    expert_score.add_argument("expert_id")
    expert_commands.add_parser("benchmark")
    for operation in ("approve", "suspend"):
        item = expert_commands.add_parser(operation)
        item.add_argument("expert_id")
    evolve = commands.add_parser("evolve")
    evolve_commands = evolve.add_subparsers(dest="evolve_command", required=True)
    for operation in ("failures", "propose", "challengers", "history", "rollback"):
        item = evolve_commands.add_parser(operation)
        item.add_argument("expert_id")
    evolve_evaluate = evolve_commands.add_parser("evaluate")
    evolve_evaluate.add_argument("challenger_id")
    evolve_compare = evolve_commands.add_parser("compare")
    evolve_compare.add_argument("champion_id")
    evolve_compare.add_argument("challenger_id")
    for operation in ("promote", "reject"):
        item = evolve_commands.add_parser(operation)
        item.add_argument("challenger_id")
    topology = commands.add_parser("topology")
    topology_commands = topology.add_subparsers(dest="topology_command", required=True)
    topology_commands.add_parser("show")
    topology_commands.add_parser("history")
    topology_commands.add_parser("gaps")
    topology_commands.add_parser("benchmark")
    topology_split = topology_commands.add_parser("propose-split")
    topology_split.add_argument("expert_id")
    topology_merge = topology_commands.add_parser("propose-merge")
    topology_merge.add_argument("expert_a")
    topology_merge.add_argument("expert_b")
    topology_expert = topology_commands.add_parser("propose-expert")
    topology_expert.add_argument("expert_id")
    for operation in ("evaluate", "certify", "activate"):
        item = topology_commands.add_parser(operation)
        item.add_argument("proposal_id")
    topology_commands.add_parser("rollback")
    commands.add_parser("validate-system")
    live = commands.add_parser("validate-live")
    live.add_argument("--confirm-live", action="store_true")
    live.add_argument("--root", type=Path, default=Path("data/live_validation"))
    live.add_argument("--cleanup", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "validate-system":
        from market_evolver.validation import print_validation_report, validate_system

        report = validate_system()
        print_validation_report(report)
        return int(report.status != "PASS")
    if args.command == "validate-live":
        from market_evolver.live_validation import LiveStatus, LiveValidationHarness

        harness = LiveValidationHarness(args.root, opted_in=args.confirm_live)
        live_report = harness.run()
        print(live_report.json_text())
        if args.cleanup:
            harness.cleanup()
        return int(live_report.status is LiveStatus.FAILED)
    if args.command == "telegram" and args.telegram_command == "live-validate":
        from market_evolver.telegram.live_validation import (
            TelegramValidationStatus,
            run_live_validation_from_environment,
        )

        telegram_report, telegram_harness = run_live_validation_from_environment(
            args.root, confirmed=args.confirm_live
        )
        print(telegram_report.json_text())
        if args.cleanup and telegram_harness is not None:
            telegram_harness.cleanup()
        return int(telegram_report.status is TelegramValidationStatus.FAILED)
    if args.command == "market" and args.market_command == "source-list":
        print("il.boi.sdmx.exr\tauthoritative_official\tUSD/ILS only")
        print("global.stooq.experimental\tconvenience_experimental\tresearch only")
        print("il.tase.maya\tdisabled\thistorical OHLCV contract unresolved")
        return 0
    if args.command == "source":
        for source in DEFAULT_REGISTRY.list():
            state = "enabled" if source.enabled else "disabled"
            print(f"{source.source_id}\t{state}\t{source.name}\t{source.ingestion_method.value}")
        return 0
    if args.command == "news" and args.news_command == "source-list":
        return _news_source_list()
    if args.command == "policy" and args.policy_command == "source-list":
        return _policy_source_list()
    if args.command == "macro" and args.macro_command == "source-list":
        for source in DEFAULT_REGISTRY.list():
            if source.source_type.value in {"central_bank", "national_statistics", "government"}:
                print(
                    f"{source.source_id}\t{'enabled' if source.enabled else 'disabled'}\t{source.name}"
                )
        return 0
    if args.command == "geopolitical" and args.geopolitical_command == "source-list":
        source_ids = {
            "il.pmo.statements",
            "il.idf.statements",
            "us.state.statements",
            "global.un.press",
            "global.icao",
            "global.imo",
            "global.iea",
            "uk.bbc.business",
        }
        for source in DEFAULT_REGISTRY.list():
            if source.source_id in source_ids:
                print(
                    f"{source.source_id}\t{'enabled' if source.enabled else 'disabled'}\t{source.name}"
                )
        return 0
    if args.command == "social" and args.social_command == "source-list":
        print("No live social sources enabled; only public synthetic fixtures are available.")
        return 0

    config = load_config(args.config)
    engine = create_postgres_engine(config.database)
    with Session(engine) as session:
        if args.command == "ingest":
            return _ingest(args, config, session)
        if args.command == "ingest-status":
            manifests = SqlManifestRepository(session).recent()
            print(
                json.dumps(
                    [
                        {
                            "run_id": item.run_id,
                            "source_id": item.source_id,
                            "dataset": item.dataset,
                            "status": item.status.value,
                            "started_at": item.started_at.isoformat(),
                            "finished_at": (
                                None if item.finished_at is None else item.finished_at.isoformat()
                            ),
                            "items_inserted": item.items_inserted,
                            "duplicates": item.duplicates,
                            "error_summary": item.error_summary,
                        }
                        for item in manifests
                    ],
                    indent=2,
                )
            )
            return 0
        if args.command == "event":
            return _event_command(args, session)
        if args.command == "entity":
            return _entity_command(args, session)
        if args.command == "graph":
            return _graph_command(args, session)
        if args.command == "news":
            return _news_command(args, config, session)
        if args.command == "policy":
            return _policy_command(args, config, session)
        if args.command in {"company", "fundamentals", "filings", "exposures"}:
            return _company_command(args, session)
        if args.command == "research":
            return _research_command(args, config, session)
        if args.command == "market":
            return _market_command(args, config, session)
        if args.command == "replay":
            return _replay_command(args, config, session)
        if args.command == "benchmark":
            return _benchmark_command(args, config, session)
        if args.command in {"macro", "trends"}:
            return _macro_command(args, session)
        if args.command == "geopolitical":
            return _geopolitical_command(args, session)
        if args.command == "social":
            return _social_command(args, session)
        if args.command == "telegram":
            return _telegram_command(args, config, session)
        if args.command == "fusion":
            return _fusion_command(args, session)
        if args.command == "reputation":
            return _reputation_command(args, session)
        if args.command == "experiment":
            return _experiment_command(args, session)
        if args.command == "backtest":
            return _backtest_command(args, config, session)
        if args.command == "walkforward":
            return _walkforward_command(args, session)
        if args.command == "paper":
            return _paper_command(args, session)
        if args.command == "expert":
            return _expert_command(args, session)
        if args.command == "evolve":
            return _evolve_command(args, session)
        if args.command == "topology":
            return _topology_command(args, session)
        telemetry = measure_storage(session)
        print(
            json.dumps(
                {
                    "raw_artifact_bytes": telemetry.raw_artifact_bytes,
                    "database_record_counts": telemetry.database_record_counts,
                    "telegram_by_source": telemetry.telegram_by_source,
                    "ingestion_bytes_by_day": [
                        {"day": item.day.isoformat(), "bytes": item.value}
                        for item in telemetry.ingestion_bytes_by_day
                    ],
                    "item_growth_by_day": [
                        {"day": item.day.isoformat(), "items": item.value}
                        for item in telemetry.item_growth_by_day
                    ],
                    "news_items_by_day": [
                        {"day": item.day.isoformat(), "items": item.value}
                        for item in telemetry.news_items_by_day
                    ],
                    "raw_news_bytes_by_day": [
                        {"day": item.day.isoformat(), "bytes": item.value}
                        for item in telemetry.raw_news_bytes_by_day
                    ],
                    "news_duplicates_by_day": [
                        {"day": item.day.isoformat(), "items": item.value}
                        for item in telemetry.news_duplicates_by_day
                    ],
                    "news_revisions_by_day": [
                        {"day": item.day.isoformat(), "items": item.value}
                        for item in telemetry.news_revisions_by_day
                    ],
                    "quarantined_news_by_day": [
                        {"day": item.day.isoformat(), "items": item.value}
                        for item in telemetry.quarantined_news_by_day
                    ],
                    "news_items_by_source": telemetry.news_items_by_source,
                    "news_bytes_by_source": telemetry.news_bytes_by_source,
                    "policy_documents_by_day": [
                        {"day": item.day.isoformat(), "items": item.value}
                        for item in telemetry.policy_documents_by_day
                    ],
                    "policy_revisions_by_day": [
                        {"day": item.day.isoformat(), "items": item.value}
                        for item in telemetry.policy_revisions_by_day
                    ],
                    "policy_transitions_by_day": [
                        {"day": item.day.isoformat(), "items": item.value}
                        for item in telemetry.policy_transitions_by_day
                    ],
                    "raw_government_bytes_by_day": [
                        {"day": item.day.isoformat(), "bytes": item.value}
                        for item in telemetry.raw_government_bytes_by_day
                    ],
                    "policy_candidate_count": telemetry.policy_candidate_count,
                    "policy_promotion_count": telemetry.policy_promotion_count,
                    "market_rows_by_day": [
                        {"day": item.day.isoformat(), "rows": item.value}
                        for item in telemetry.market_rows_by_day
                    ],
                    "parquet_bytes_by_day": [
                        {"day": item.day.isoformat(), "bytes": item.value}
                        for item in telemetry.parquet_bytes_by_day
                    ],
                    "market_assets": telemetry.market_assets,
                    "replay_cases": telemetry.replay_cases,
                    "replay_runtime_ms": telemetry.replay_runtime_ms,
                    "benchmark_artifact_bytes": telemetry.benchmark_artifact_bytes,
                    "macro_observations_by_day": [
                        {"day": item.day.isoformat(), "items": item.value}
                        for item in telemetry.macro_observations_by_day
                    ],
                    "macro_series_count": telemetry.macro_series_count,
                    "macro_revision_rate": telemetry.macro_revision_rate,
                    "macro_raw_bytes": telemetry.macro_raw_bytes,
                    "trend_calculations": telemetry.trend_calculations,
                    "macro_replay_impact": telemetry.macro_replay_impact,
                    "geopolitical_candidates_by_day": [
                        {"day": item.day.isoformat(), "items": item.value}
                        for item in telemetry.geopolitical_candidates_by_day
                    ],
                    "geopolitical_confirmed_by_day": [
                        {"day": item.day.isoformat(), "items": item.value}
                        for item in telemetry.geopolitical_confirmed_by_day
                    ],
                    "geopolitical_contradictions_by_day": [
                        {"day": item.day.isoformat(), "items": item.value}
                        for item in telemetry.geopolitical_contradictions_by_day
                    ],
                    "geopolitical_revisions_by_day": [
                        {"day": item.day.isoformat(), "items": item.value}
                        for item in telemetry.geopolitical_revisions_by_day
                    ],
                    "geopolitical_raw_bytes_by_day": [
                        {"day": item.day.isoformat(), "bytes": item.value}
                        for item in telemetry.geopolitical_raw_bytes_by_day
                    ],
                    "geopolitical_affected_mechanisms": telemetry.geopolitical_affected_mechanisms,
                    "geopolitical_replay_inclusions": telemetry.geopolitical_replay_inclusions,
                    "unified_claims_by_day": [
                        {"day": item.day.isoformat(), "items": item.value}
                        for item in telemetry.unified_claims_by_day
                    ],
                    "fused_clusters_by_day": [
                        {"day": item.day.isoformat(), "items": item.value}
                        for item in telemetry.fused_clusters_by_day
                    ],
                    "corroborated_claims_by_day": [
                        {"day": item.day.isoformat(), "items": item.value}
                        for item in telemetry.corroborated_claims_by_day
                    ],
                    "contradicted_claims_by_day": [
                        {"day": item.day.isoformat(), "items": item.value}
                        for item in telemetry.contradicted_claims_by_day
                    ],
                    "average_confirmation_lag_seconds": (
                        telemetry.average_confirmation_lag_seconds
                    ),
                    "source_domain_resolution_counts": (telemetry.source_domain_resolution_counts),
                    "experiments_by_day": [
                        {"day": item.day.isoformat(), "items": item.value}
                        for item in telemetry.experiments_by_day
                    ],
                    "backtests_by_day": [
                        {"day": item.day.isoformat(), "items": item.value}
                        for item in telemetry.backtests_by_day
                    ],
                    "trades_simulated": telemetry.trades_simulated,
                    "backtest_runtime_ms": telemetry.backtest_runtime_ms,
                    "backtest_parquet_bytes_read": telemetry.backtest_parquet_bytes_read,
                    "rejected_experiments": telemetry.rejected_experiments,
                    "leakage_failures": telemetry.leakage_failures,
                    "test_set_accesses": telemetry.test_set_accesses,
                },
                indent=2,
            )
        )
    return 0


def _ingest(args: argparse.Namespace, config: AppConfig, session: Session) -> int:
    if not config.runtime_permissions.network_access:
        raise GovernanceViolation("ingestion requires host-granted network_access")
    connector = BankOfIsraelConnector()
    manifest = IngestionRunner(
        session,
        LocalArtifactStore(config.artifact_storage.resolve_root()),
    ).run(connector, args.dataset)
    if manifest.status.value == "succeeded":
        BoiEventExtractionPipeline(session).run_pending()
        session.commit()
    print(f"{manifest.run_id}\t{manifest.status.value}")
    return int(manifest.status.value != "succeeded")


def _event_command(args: argparse.Namespace, session: Session) -> int:
    repository = SqlCanonicalEventRepository(session)
    if args.event_command == "show":
        event = repository.get(args.event_id)
        if event is None:
            print(json.dumps({"error": "event not found", "event_id": args.event_id}))
            return 1
        current_status = repository.current_status(event.event_id, datetime.now(UTC))
        print(
            json.dumps(
                {
                    **_event_to_dict(event),
                    "current_status": (None if current_status is None else current_status.value),
                    "transitions": [
                        {
                            "from": (None if item.from_status is None else item.from_status.value),
                            "to": item.to_status.value,
                            "at": item.transitioned_at.isoformat(),
                            "rationale": item.rationale,
                        }
                        for item in repository.transitions(event.event_id)
                    ],
                },
                indent=2,
            )
        )
        return 0
    if args.event_command == "replay":
        cutoff = _parse_timestamp(args.at)
    else:
        cutoff = datetime.now(UTC)
    if args.event_command in ("list", "replay"):
        print(
            json.dumps(
                [
                    {
                        **_event_to_dict(event),
                        "status_at_cutoff": _status_value(
                            repository.current_status(event.event_id, cutoff)
                        ),
                    }
                    for event in repository.get_events_visible_at(cutoff)
                ],
                indent=2,
            )
        )
        return 0
    summary = observatory_summary(session, cutoff)
    print(
        json.dumps(
            {
                "events_by_source": summary.events_by_source,
                "events_by_type": summary.events_by_type,
                "revision_count": summary.revision_count,
                "entities_referenced": summary.entities_referenced,
                "mechanisms_referenced": summary.mechanisms_referenced,
                "coverage_started_at": (
                    None
                    if summary.coverage_started_at is None
                    else summary.coverage_started_at.isoformat()
                ),
                "coverage_ended_at": (
                    None
                    if summary.coverage_ended_at is None
                    else summary.coverage_ended_at.isoformat()
                ),
            },
            indent=2,
        )
    )
    return 0


def _event_to_dict(event: CanonicalEvent) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "event_type": event.event_type.value,
        "source_ids": event.source_ids,
        "evidence_ids": event.evidence_ids,
        "first_observed_at": event.first_observed_at.isoformat(),
        "published_at": (None if event.published_at is None else event.published_at.isoformat()),
        "effective_at": (None if event.effective_at is None else event.effective_at.isoformat()),
        "event_status": event.event_status.value,
        "revision_state": event.revision_state.value,
        "supersedes_event_id": event.supersedes_event_id,
        "entities": event.entities,
        "mechanisms": event.causal_mechanisms,
        "attributes": dict(event.attributes),
    }


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("--at timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _optional_timestamp(value: str | None) -> datetime:
    return datetime.now(UTC) if value is None else _parse_timestamp(value)


def _status_value(status: EventStatus | None) -> str | None:
    return None if status is None else status.value


def _entity_command(args: argparse.Namespace, session: Session) -> int:
    graph = SqlKnowledgeGraph(session)
    if args.entity_command == "seed":
        entities, relationships, exposures = seed_knowledge_graph(session)
        session.commit()
        print(
            json.dumps(
                {
                    "entities_inserted": entities,
                    "relationships_inserted": relationships,
                    "exposures_inserted": exposures,
                }
            )
        )
        return 0
    cutoff = _optional_timestamp(args.at)
    if args.entity_command == "list":
        print(
            json.dumps(
                [_knowledge_entity_dict(item) for item in graph.list_entities(cutoff)],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.entity_command == "show":
        entity = graph.get_entity_at(args.entity_id, cutoff)
        if entity is None:
            print(json.dumps({"error": "entity not found", "entity_id": args.entity_id}))
            return 1
        print(json.dumps(_knowledge_entity_dict(entity), ensure_ascii=False, indent=2))
        return 0
    resolution = graph.resolve_alias(args.alias, cutoff)
    print(
        json.dumps(
            {
                "status": resolution.status.value,
                "candidates": [_knowledge_entity_dict(item) for item in resolution.candidates],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return int(resolution.status.value != "resolved")


def _graph_command(args: argparse.Namespace, session: Session) -> int:
    graph = SqlKnowledgeGraph(session)
    cutoff = _parse_timestamp(args.at)
    if args.graph_command == "neighbors":
        relationships = graph.get_relationships(args.entity_id, cutoff)
        exposures = graph.get_exposures(args.entity_id, cutoff)
        print(
            json.dumps(
                {
                    "relationships": [
                        {
                            "relationship_id": item.relationship_id,
                            "relation_type": item.relation_type.value,
                            "source": item.source_entity,
                            "target": item.target_entity,
                            "version": item.version,
                            "confidence": item.confidence,
                            "provenance": item.provenance,
                        }
                        for item in relationships
                    ],
                    "exposures": [
                        {
                            "exposure_id": item.exposure_id,
                            "exposure_type": item.exposure_type.value,
                            "subject": item.subject_entity,
                            "target": item.target_entity,
                            "version": item.version,
                            "strength": item.strength.value,
                            "provenance": item.source_evidence,
                        }
                        for item in exposures
                    ],
                },
                indent=2,
            )
        )
        return 0
    trace = graph.trace_event(args.event_id, cutoff)
    print(
        json.dumps(
            {
                "event_id": trace.event_id,
                "cutoff": trace.cutoff.isoformat(),
                "direct_entities": trace.direct_entities,
                "candidate_mechanisms": trace.candidate_mechanisms,
                "paths": [
                    {
                        "entity_ids": item.entity_ids,
                        "relationship_ids": item.relationship_ids,
                        "relationship_versions": item.relationship_versions,
                        "provenance": item.provenance,
                        "confidence": item.confidence,
                        "cutoff_validated": item.cutoff_validated,
                    }
                    for item in trace.paths
                ],
            },
            indent=2,
        )
    )
    return 0


def _news_command(args: argparse.Namespace, config: AppConfig, session: Session) -> int:
    if args.news_command == "source-list":
        return _news_source_list()
    if args.news_command == "ingest":
        if not config.runtime_permissions.network_access:
            raise GovernanceViolation("news ingestion requires host-granted network_access")
        inserted, duplicates, quarantined = NewsIngestionRunner(
            session,
            LocalArtifactStore(config.artifact_storage.resolve_root()),
        ).run(BbcBusinessRssConnector())
        print(
            json.dumps(
                {
                    "inserted": inserted,
                    "duplicates": duplicates,
                    "quarantined": quarantined,
                }
            )
        )
        return int(quarantined > 0)
    repository = SqlNewsRepository(session)
    cutoff = _optional_timestamp(getattr(args, "at", None))
    if args.news_command in {"list", "replay"}:
        print(
            json.dumps(
                [_news_dict(item) for item in repository.get_news_visible_at(cutoff)],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.news_command == "show":
        item = repository.get(args.news_id)
        if item is None:
            print(json.dumps({"error": "news not found", "news_id": args.news_id}))
            return 1
        print(json.dumps(_news_dict(item), ensure_ascii=False, indent=2))
        return 0
    if args.news_command == "candidates":
        candidates = repository.get_event_candidates_visible_at(cutoff)
        print(
            json.dumps(
                [
                    {
                        "candidate_id": item.candidate_id,
                        "news_id": item.news_id,
                        "entities": item.extracted_entities,
                        "possible_event_type": item.possible_event_type,
                        "method": item.extraction_method,
                        "confidence": item.confidence,
                        "review_state": item.review_state.value,
                        "created_at": item.created_at.isoformat(),
                    }
                    for item in candidates
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    print(
        json.dumps(
            [_news_dict(item) for item in repository.quarantined(cutoff)],
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _news_source_list() -> int:
    definitions = [item for item in DEFAULT_REGISTRY.list() if item.source_type.value == "news"]
    print(
        json.dumps(
            [
                {
                    "source_id": item.source_id,
                    "name": item.name,
                    "trust_class": item.trust_class.value,
                    "enabled": item.enabled,
                    "languages": item.language,
                }
                for item in definitions
            ],
            indent=2,
        )
    )
    return 0


def _policy_source_list() -> int:
    definitions = [
        item
        for item in DEFAULT_REGISTRY.list()
        if item.source_type.value in {"central_bank", "government", "regulator", "legislature"}
    ]
    print(
        json.dumps(
            [
                {
                    "source_id": item.source_id,
                    "name": item.name,
                    "enabled": item.enabled,
                    "method": item.ingestion_method.value,
                }
                for item in definitions
            ],
            indent=2,
        )
    )
    return 0


def _policy_command(args: argparse.Namespace, config: AppConfig, session: Session) -> int:
    if args.policy_command == "source-list":
        return _policy_source_list()
    if args.policy_command == "ingest":
        if not config.runtime_permissions.network_access:
            raise GovernanceViolation("policy ingestion requires host-granted network_access")
        connector = BankOfIsraelPolicyConnector()
        manifest = IngestionRunner(
            session,
            LocalArtifactStore(config.artifact_storage.resolve_root()),
        ).run(connector, connector.dataset_name)
        if manifest.status.value == "succeeded":
            _extract_pending_policy(session)
            session.commit()
        print(f"{manifest.run_id}\t{manifest.status.value}")
        return int(manifest.status.value != "succeeded")
    repository = SqlGovernmentRepository(session)
    cutoff = _optional_timestamp(getattr(args, "at", None))
    if args.policy_command in {"list", "replay"}:
        actions = repository.get_actions_visible_at(cutoff)
        print(
            json.dumps(
                [
                    {
                        **_policy_dict(item),
                        "status_at_cutoff": (
                            None
                            if (status := repository.current_status(item.action_id, cutoff)) is None
                            else status.value
                        ),
                    }
                    for item in actions
                ],
                indent=2,
            )
        )
        return 0
    if args.policy_command == "show":
        action = repository.get(args.action_id)
        if action is None:
            print(json.dumps({"error": "government action not found"}))
            return 1
        print(json.dumps(_policy_dict(action), indent=2))
        return 0
    if args.policy_command == "transitions":
        print(
            json.dumps(
                [
                    {
                        "transition_id": item.transition_id,
                        "from": None if item.from_status is None else item.from_status.value,
                        "to": item.to_status.value,
                        "at": item.transitioned_at.isoformat(),
                        "evidence_ids": item.evidence_ids,
                        "rationale": item.rationale,
                    }
                    for item in repository.transitions(args.action_id, cutoff)
                ],
                indent=2,
            )
        )
        return 0
    print(
        json.dumps(
            [
                {
                    "candidate_id": item.candidate_id,
                    "issuing_body": item.issuing_body,
                    "action_type": (
                        None
                        if item.possible_action_type is None
                        else item.possible_action_type.value
                    ),
                    "transition": (
                        None if item.possible_transition is None else item.possible_transition.value
                    ),
                    "explicit_values": item.explicit_values,
                    "mechanisms": item.candidate_mechanisms,
                    "expectation_status": item.expectation_status.value,
                    "review_state": item.review_state.value,
                }
                for item in repository.get_candidates_visible_at(cutoff)
            ],
            indent=2,
        )
    )
    return 0


def _extract_pending_policy(session: Session) -> None:
    evidence = session.scalars(
        select(EvidenceModel).where(
            EvidenceModel.claim.like("Bank of Israel published current policy interest rate%")
        )
    )
    repository = SqlGovernmentRepository(session)
    for item in evidence:
        candidate = extract_policy_candidate(
            evidence_id=item.provenance_id,
            text=item.claim,
            created_at=item.observed_at,
            issuing_body="institution.boi",
        )
        if session.get(GovernmentCandidateModel, candidate.candidate_id) is None:
            repository.add_candidate(candidate)


def _policy_dict(item: GovernmentAction) -> dict[str, object]:
    return {
        "action_id": item.action_id,
        "jurisdiction": item.jurisdiction,
        "issuing_body": item.issuing_body,
        "action_type": item.action_type.value,
        "title": item.title,
        "status": item.status.value,
        "announced_at": None if item.announced_at is None else item.announced_at.isoformat(),
        "published_at": None if item.published_at is None else item.published_at.isoformat(),
        "effective_at": None if item.effective_at is None else item.effective_at.isoformat(),
        "first_observed_at": item.first_observed_at.isoformat(),
        "supersedes_action_id": item.supersedes_action_id,
        "evidence_ids": item.source_evidence_ids,
        "candidate_mechanisms": item.candidate_mechanisms,
        "expectation_status": item.expectation_status.value,
        "version": item.version,
        "provenance": item.provenance,
    }


def _news_dict(item: NewsItem) -> dict[str, object]:
    return {
        "news_id": item.news_id,
        "source_id": item.source_id,
        "title": item.title,
        "language": item.language,
        "published_at": item.published_at.isoformat(),
        "first_observed_at": item.first_observed_at.isoformat(),
        "updated_at": None if item.updated_at is None else item.updated_at.isoformat(),
        "canonical_uri": item.canonical_uri,
        "content_hash": item.content_hash,
        "raw_artifact_sha256": item.raw_artifact_sha256,
        "revision_of": item.revision_of,
        "trust_class": item.trust_class.value,
        "evidence_security_class": item.evidence_security_class.value,
        "extraction_status": item.extraction_status.value,
        "quarantine_reason": item.quarantine_reason,
        "duplicate_kind": item.duplicate_kind.value,
        "provenance": item.provenance,
    }


def _knowledge_entity_dict(entity: EntityVersion) -> dict[str, object]:
    return {
        "entity_id": entity.entity_id,
        "entity_version_id": entity.entity_version_id,
        "canonical_name": entity.canonical_name,
        "hebrew_name": entity.hebrew_name,
        "english_name": entity.english_name,
        "aliases": entity.aliases,
        "entity_type": entity.entity_type.value,
        "geography": entity.geography,
        "identifiers": [
            {"scheme": item.scheme, "value": item.value} for item in entity.identifiers
        ],
        "active_from": entity.active_from.isoformat(),
        "active_until": (None if entity.active_until is None else entity.active_until.isoformat()),
        "observed_at": entity.observed_at.isoformat(),
        "provenance": entity.provenance,
        "confidence": entity.confidence,
        "version": entity.version,
    }


def _company_command(args: argparse.Namespace, session: Session) -> int:
    repository = SqlCompanyRepository(session)
    if args.command == "company" and args.company_command == "seed":
        companies, entities, relationships = seed_companies(session)
        session.commit()
        print(
            json.dumps(
                {
                    "companies_inserted": companies,
                    "entities_inserted": entities,
                    "relationships_inserted": relationships,
                }
            )
        )
        return 0
    cutoff = _optional_timestamp(getattr(args, "at", None))
    if args.command == "company" and args.company_command == "list":
        print(
            json.dumps(
                [_company_dict(item) for item in repository.list_companies(cutoff)],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.command == "company":
        company = repository.get_company_at(args.company_id, cutoff)
        if company is None:
            print(json.dumps({"error": "company not found", "company_id": args.company_id}))
            return 1
        print(json.dumps(_company_dict(company), ensure_ascii=False, indent=2))
        return 0
    if args.command == "fundamentals":
        print(
            json.dumps(
                [
                    {
                        "observation_id": item.observation_id,
                        "metric": item.metric.value,
                        "value": item.value,
                        "currency": item.currency,
                        "unit": item.unit,
                        "fiscal_period_start": item.fiscal_period_start.isoformat(),
                        "fiscal_period_end": item.fiscal_period_end.isoformat(),
                        "published_at": item.published_at.isoformat(),
                        "first_observed_at": item.first_observed_at.isoformat(),
                        "restatement_status": item.restatement_status.value,
                        "restates_observation_id": item.restates_observation_id,
                        "evidence_ids": item.source_evidence_ids,
                    }
                    for item in repository.get_fundamentals(args.company_id, cutoff)
                ],
                indent=2,
            )
        )
        return 0
    if args.command == "filings":
        print(
            json.dumps(
                [_filing_dict(item) for item in repository.list_filings(args.company_id, cutoff)],
                indent=2,
            )
        )
        return 0
    print(
        json.dumps(
            [
                {
                    "exposure_id": item.exposure_id,
                    "exposure_type": item.exposure_type.value,
                    "target": item.target,
                    "value": item.value,
                    "unit": item.unit,
                    "valid_from": item.valid_from.isoformat(),
                    "valid_until": (
                        None if item.valid_until is None else item.valid_until.isoformat()
                    ),
                    "first_observed_at": item.first_observed_at.isoformat(),
                    "evidence_ids": item.source_evidence_ids,
                    "version": item.version,
                }
                for item in repository.get_exposures(args.company_id, cutoff)
            ],
            indent=2,
        )
    )
    return 0


def _company_dict(item: CompanyVersion) -> dict[str, object]:
    return {
        "company_id": item.company_id,
        "legal_name": item.legal_name,
        "hebrew_name": item.hebrew_name,
        "english_name": item.english_name,
        "aliases": item.aliases,
        "listings": [
            {
                "ticker": listing.ticker,
                "exchange": listing.exchange,
                "valid_from": listing.valid_from.isoformat(),
                "valid_until": (
                    None if listing.valid_until is None else listing.valid_until.isoformat()
                ),
            }
            for listing in item.listings
        ],
        "isin": item.isin,
        "sector_id": item.sector_id,
        "industry_id": item.industry_id,
        "domicile": item.domicile,
        "status": item.status.value,
        "dual_listed": item.dual_listed,
        "identifiers": [{"scheme": key, "value": value} for key, value in item.identifiers],
        "valid_from": item.valid_from.isoformat(),
        "valid_until": None if item.valid_until is None else item.valid_until.isoformat(),
        "observed_at": item.observed_at.isoformat(),
        "version": item.version,
        "provenance": item.provenance,
    }


def _filing_dict(item: Filing) -> dict[str, object]:
    return {
        "filing_id": item.filing_id,
        "company_id": item.company_id,
        "filing_type": item.filing_type.value,
        "form_type": item.form_type,
        "accession_number": item.accession_number,
        "source_uri": item.source_uri,
        "filed_at": item.filed_at.isoformat(),
        "first_observed_at": item.first_observed_at.isoformat(),
        "fiscal_period_start": item.fiscal_period_start.isoformat(),
        "fiscal_period_end": item.fiscal_period_end.isoformat(),
        "raw_artifact_sha256": item.raw_artifact_sha256,
        "evidence_ids": item.source_evidence_ids,
        "parser_version": item.parser_version,
        "restates_filing_id": item.restates_filing_id,
    }


def _research_command(args: argparse.Namespace, config: AppConfig, session: Session) -> int:
    provider = _research_provider(config)
    service = ResearchService(session, provider)
    repository = SqlResearchRepository(session)
    if args.research_command == "inspect-context":
        context = repository.get_context(args.context_id)
        if context is None:
            print(json.dumps({"error": "research context not found"}))
            return 1
        print(json.dumps(_context_dict(context), ensure_ascii=False, indent=2))
        return 0
    if args.research_command == "trace":
        trace = repository.get_trace(args.research_id)
        if trace is None:
            print(json.dumps({"error": "research trace not found"}))
            return 1
        print(
            json.dumps(
                {
                    "trace_id": trace.trace_id,
                    "manifest_id": trace.manifest_id,
                    "provider_call_id": trace.provider_call_id,
                    "claim_ids": trace.claim_ids,
                    "hypothesis_id": trace.hypothesis_id,
                    "reviewer_id": trace.reviewer_id,
                    "validation_state": trace.validation_state,
                    "accepted": trace.accepted,
                    "created_at": trace.created_at.isoformat(),
                },
                indent=2,
            )
        )
        return 0
    if args.research_command == "review":
        hypothesis = repository.get_hypothesis(args.hypothesis_id)
        if hypothesis is None:
            print(json.dumps({"error": "research hypothesis not found"}))
            return 1
        context = repository.context_for_hypothesis(hypothesis.hypothesis_id)
        if context is None:
            print(json.dumps({"error": "hypothesis research context not found"}))
            return 1
        result = service.review(hypothesis, context)
        print(
            json.dumps(
                {
                    "reviewer_id": result.reviewer_id,
                    "accepted": result.accepted,
                    "issues": result.issues,
                    "alternative_explanations": result.alternative_explanations,
                },
                indent=2,
            )
        )
        return int(not result.accepted)
    cutoff = _parse_timestamp(args.at)
    context = service.build_context(args.company_id, cutoff)
    if args.anonymize:
        anonymized = anonymize_context(context)
        context = anonymized.context
        repository.add_context(context)
        repository.add_anonymization_mapping(
            AnonymizationMapping(context.research_context_id, anonymized.mapping, datetime.now(UTC))
        )
        session.commit()
    if args.research_command == "build-context":
        print(json.dumps(_context_dict(context), ensure_ascii=False, indent=2))
        return 0
    hypothesis, trace = service.hypothesize(context)
    print(
        json.dumps(
            {
                "hypothesis_id": hypothesis.hypothesis_id,
                "status": hypothesis.status.value,
                "trace_id": trace.trace_id,
                "accepted": trace.accepted,
            },
            indent=2,
        )
    )
    return 0


def _research_provider(config: AppConfig) -> ResearchProvider:
    definition = config.research_provider
    if definition.provider == "mock":
        return MockProvider()
    if not config.runtime_permissions.network_access:
        raise GovernanceViolation("external research provider requires host-granted network_access")
    endpoint = os.environ.get(definition.endpoint_env, "")
    if not endpoint:
        raise GovernanceViolation("external research provider endpoint is not configured")
    return JsonHttpProvider(
        endpoint,
        definition.model,
        os.environ.get(definition.authorization_env),
    )


def _context_dict(context: object) -> dict[str, object]:
    from market_evolver.research.schemas import ResearchContext

    assert isinstance(context, ResearchContext)
    return {
        "research_context_id": context.research_context_id,
        "cutoff": context.cutoff.isoformat(),
        "subject_id": context.subject_id,
        "anonymized": context.anonymized,
        "items": [
            {
                "kind": item.kind,
                "provenance_id": item.provenance_id,
                "first_observed_at": item.first_observed_at.isoformat(),
                "evidence_ids": item.evidence_ids,
                "text": item.text,
            }
            for item in context.items
        ],
    }


def _market_command(args: argparse.Namespace, config: AppConfig, session: Session) -> int:
    store = MarketDataStore(session, config.market_storage.resolve_root())
    if args.market_command == "seed-assets":
        seed_knowledge_graph(session)
        seed_companies(session)
        inserted = seed_assets(session, store)
        session.commit()
        print(json.dumps({"assets_inserted": inserted}))
        return 0
    if args.market_command == "asset-list":
        print(
            json.dumps(
                [
                    {
                        "asset_id": item.asset_id,
                        "symbol": item.symbol,
                        "venue": item.venue,
                        "asset_type": item.asset_type.value,
                        "currency": item.currency,
                        "company_id": item.company_id,
                        "entity_id": item.entity_id,
                        "benchmark_asset_id": item.benchmark_asset_id,
                    }
                    for item in store.list_assets(datetime.now(UTC))
                ],
                indent=2,
            )
        )
        return 0
    if args.market_command == "ingest-history":
        return _market_history_ingest(args, config, session, store)
    if args.market_command in {"validate-dataset", "quality-report"}:
        history = HistoricalDatasetStore(config.market_storage.resolve_root() / "history")
        manifest = history.root / "manifests" / f"{args.dataset_id}.json"
        if not manifest.is_file():
            raise GovernanceViolation("unknown historical dataset manifest")
        document = json.loads(manifest.read_text(encoding="utf-8"))
        paths = tuple(
            history.root / "parquet" / relative for relative in document.get("parquet_paths", ())
        )
        if not paths:
            paths = tuple((history.root / "parquet").rglob("bars.parquet"))
        bars = history.read_bars(paths)
        report = validate_quality(args.dataset_id, bars)
        print(json.dumps(asdict(report), indent=2))
        return int(report.status == "failed")
    if args.market_command == "coverage":
        history = HistoricalDatasetStore(config.market_storage.resolve_root() / "history")
        paths = tuple((history.root / "parquet").rglob("bars.parquet"))
        print(json.dumps(history.diagnostics(paths) if paths else {"rows": 0}, indent=2))
        return 0
    try:
        document = json.loads(args.path.read_text(encoding="utf-8"))
        if not isinstance(document, list):
            raise TypeError
        observations = tuple(_market_observation_from_dict(item) for item in document)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        raise GovernanceViolation("market ingest file is malformed") from exc
    partition, inserted, duplicates = store.write_observations(
        observations, dataset_version=args.dataset_version
    )
    session.commit()
    print(
        json.dumps(
            {
                "partition_sha256": partition.sha256,
                "rows": partition.row_count,
                "inserted": inserted,
                "duplicates": duplicates,
                "bytes": partition.size_bytes,
            }
        )
    )
    return 0


def _market_history_ingest(
    args: argparse.Namespace, config: AppConfig, session: Session, market_store: MarketDataStore
) -> int:
    if not args.confirm_live:
        raise GovernanceViolation("historical live ingestion requires --confirm-live")
    start = datetime.fromisoformat(args.date_from).date()
    end = datetime.fromisoformat(args.date_to).date()
    retrieved = datetime.now(UTC)
    history = HistoricalDatasetStore(config.market_storage.resolve_root() / "history")
    if args.source == "boi":
        if args.instrument != "asset.fx.usdils":
            raise GovernanceViolation("BOI historical connector is fixed to asset.fx.usdils")
        boi_connector = BoiUsdIlsHistoryConnector()
        body, uri = boi_connector.fetch(start, end)
        raw = history.persist_raw(body, "text/csv")
        bars = boi_connector.parse(body, retrieved_at=retrieved, artifact=raw)
        source_class = SourceClass.AUTHORITATIVE_OFFICIAL
        dataset_type = DatasetType.FX
        venue = "BOI"
        adjustment = PriceAdjustmentPolicy.NOT_APPLICABLE
        survivorship = SurvivorshipStatus.UNKNOWN
        composition = CompositionHistoryStatus.NOT_APPLICABLE
    else:
        if not all((args.symbol, args.venue, args.currency)):
            raise GovernanceViolation("Stooq history requires --symbol, --venue, and --currency")
        stooq_connector = StooqDailyConnector()
        body = stooq_connector.fetch(args.symbol, start, end)
        uri = "https://stooq.com/q/d/l/"
        raw = history.persist_raw(body, "text/csv")
        bars = stooq_connector.parse(
            body,
            instrument_id=args.instrument,
            venue=args.venue,
            currency=args.currency,
            retrieved_at=retrieved,
            artifact=raw,
        )
        source_class = SourceClass.CONVENIENCE_EXPERIMENTAL
        dataset_type = DatasetType.EQUITY_OHLCV
        venue = args.venue
        adjustment = PriceAdjustmentPolicy.RAW_ONLY
        survivorship = SurvivorshipStatus.CURRENT_CONSTITUENTS_ONLY
        composition = CompositionHistoryStatus.UNAVAILABLE
    quality = validate_quality("pending", bars, expected_currency=bars[0].currency)
    if quality.status == "failed":
        raise GovernanceViolation("historical dataset failed quality validation")
    normalized_bytes = json.dumps(
        [asdict(item) for item in bars], default=str, sort_keys=True, separators=(",", ":")
    ).encode()
    normalized = history.persist_raw(normalized_bytes, "application/json")
    paths, hashes, parquet_bytes = history.write_bars(
        bars, source_id=bars[0].source_id, venue=venue
    )
    observations = tuple(
        MarketObservation(
            item.instrument_id,
            item.venue,
            ObservationType.FX_RATE if dataset_type is DatasetType.FX else ObservationType.OHLCV,
            item.market_timestamp,
            item.retrieved_at,
            item.source_id,
            AdjustmentStatus.RAW,
            item.currency,
            item.parser_version,
            (item.raw_artifact_id, f"normalized:sha256:{normalized.sha256}"),
            None if dataset_type is DatasetType.FX else item.raw_open,
            None if dataset_type is DatasetType.FX else item.raw_high,
            None if dataset_type is DatasetType.FX else item.raw_low,
            None if dataset_type is DatasetType.FX else item.raw_close,
            None if dataset_type is DatasetType.FX else item.volume,
            item.raw_close if dataset_type is DatasetType.FX else None,
        )
        for item in bars
    )
    partition, inserted, duplicates = market_store.write_observations(
        observations, dataset_version="historical-bars/1", created_at=retrieved
    )
    contract_fields = tuple(sorted(body.decode("utf-8-sig").splitlines()[0].split(",")))
    contract_hash = (
        "sha256:"
        + hashlib.sha256(json.dumps(contract_fields, separators=(",", ":")).encode()).hexdigest()
    )
    dataset = HistoricalDataset(
        bars[0].source_id,
        source_class,
        dataset_type,
        tuple(sorted({item.instrument_id for item in bars})),
        venue,
        "1d",
        bars[0].market_date,
        bars[-1].market_date,
        retrieved,
        datetime.now(UTC),
        (f"sha256:{raw.sha256}",),
        (f"sha256:{normalized.sha256}",),
        hashes,
        tuple(path.relative_to(history.root / "parquet").as_posix() for path in paths),
        len(bars),
        "Asia/Jerusalem" if venue == "BOI" else "America/New_York",
        adjustment,
        "explicit actions only; unavailable actions degrade backtests",
        survivorship,
        composition,
        bars[0].parser_version,
        "historical-bars/1",
        (f"request:{uri}", f"raw:sha256:{raw.sha256}", f"normalized:sha256:{normalized.sha256}"),
        HistoricalReplayEligibility.OUTCOME_MEASUREMENT_ONLY,
        (("from", start.isoformat()), ("to", end.isoformat())),
        contract_hash,
        "runtime-commit",
    )
    manifest = history.write_manifest(dataset)
    session.commit()
    print(
        json.dumps(
            {
                "dataset_id": dataset.dataset_id,
                "manifest": str(manifest),
                "rows": len(bars),
                "inserted": inserted,
                "duplicates": duplicates,
                "raw_bytes": len(body),
                "normalized_bytes": len(normalized_bytes),
                "parquet_bytes": parquet_bytes,
                "market_partition": partition.sha256,
                "quality": quality.status,
                "replay_eligibility": dataset.replay_eligibility.value,
            },
            indent=2,
        )
    )
    return 0


def _replay_command(args: argparse.Namespace, config: AppConfig, session: Session) -> int:
    market = MarketDataStore(session, config.market_storage.resolve_root())
    replay = ReplayEngine(session, market)
    runner = BenchmarkRunner(session, replay)
    repository = SqlReplayRepository(session)
    if args.replay_command == "seed-cases":
        print(json.dumps({"cases_inserted": runner.seed_cases()}))
        return 0
    if args.replay_command == "inspect":
        run = repository.get_run(args.run_id)
        if run is None:
            print(json.dumps({"error": "replay run not found"}))
            return 1
        print(json.dumps(_run_dict(run), indent=2))
        return 0
    runner.seed_cases()
    case = next(
        (
            item
            for item in repository.list_cases()
            if item.case_id == args.case or item.case_type.value == args.case
        ),
        None,
    )
    if case is None:
        print(json.dumps({"error": "replay case not found"}))
        return 1
    run = runner.run_case(
        case,
        ResearchMode(args.mode),
        named=not args.anonymized,
        now=datetime.now(UTC),
    )
    print(json.dumps(_run_dict(run), indent=2))
    return 0


def _benchmark_command(args: argparse.Namespace, config: AppConfig, session: Session) -> int:
    market = MarketDataStore(session, config.market_storage.resolve_root())
    replay = ReplayEngine(session, market)
    runner = BenchmarkRunner(session, replay)
    repository = SqlReplayRepository(session)
    if args.benchmark_command == "run":
        runs = runner.run_all(datetime.now(UTC))
        print(json.dumps({"runs_created": len(runs), "cases": len(repository.list_cases())}))
        return 0
    runs = tuple(repository.list_runs())
    evaluations = tuple(repository.list_evaluations())
    metrics = benchmark_metrics(runs, evaluations)
    print(
        json.dumps(
            {
                "runs": len(runs),
                "evaluations": len(evaluations),
                **asdict(metrics),
            },
            indent=2,
        )
    )
    return 0


def _macro_command(args: argparse.Namespace, session: Session) -> int:
    repository = SqlMacroRepository(session)
    cutoff = _parse_timestamp(args.at) if getattr(args, "at", None) else datetime.now(UTC)
    if args.command == "macro" and args.macro_command == "ingest":
        try:
            document = json.loads(args.path.read_text(encoding="utf-8"))
            if not isinstance(document, list):
                raise TypeError
            observations = tuple(_macro_observation_from_dict(item) for item in document)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
            raise GovernanceViolation("macro ingest file is malformed") from exc
        inserted = sum(repository.add_observation(item) for item in observations)
        session.commit()
        print(
            json.dumps(
                {
                    "items": len(observations),
                    "inserted": inserted,
                    "duplicates": len(observations) - inserted,
                }
            )
        )
        return 0
    if args.command == "macro":
        items = repository.observations_visible_at(args.series_id, cutoff)
        print(json.dumps([_macro_dict(item) for item in items], indent=2))
        return 0
    if args.trends_command == "calculate":
        observations = repository.observations_visible_at(args.series_id, cutoff)
        created = []
        for horizon in TrendHorizon:
            trend = calculate_trend(observations, horizon, cutoff)
            if repository.add_trend(trend):
                created.append(trend.trend_id)
        session.commit()
        print(json.dumps({"trend_ids": created}))
        return 0
    if args.trends_command == "show":
        trends = repository.trends_visible_at(args.series_id, cutoff)
        print(json.dumps([asdict(item) for item in trends], default=str, indent=2))
        return 0
    output = {
        series_id: [asdict(item) for item in repository.trends_visible_at(series_id, cutoff)]
        for series_id in repository.series_ids()
    }
    print(json.dumps(output, default=str, indent=2))
    return 0


def _geopolitical_command(args: argparse.Namespace, session: Session) -> int:
    repository = SqlGeopoliticalRepository(session)
    cutoff = _parse_timestamp(args.at) if getattr(args, "at", None) else datetime.now(UTC)
    if args.geopolitical_command == "extract":
        evidence = session.get(EvidenceModel, args.evidence_id)
        if evidence is None or _parse_timestamp(evidence.observed_at.isoformat()) > cutoff:
            raise GovernanceViolation("geopolitical extraction requires cutoff-visible evidence")
        candidate = extract_candidate(evidence.claim, evidence.provenance_id, cutoff)
        inserted = repository.add_candidate(candidate)
        session.commit()
        print(json.dumps({"candidate_id": candidate.candidate_id, "inserted": inserted}))
        return 0
    if args.geopolitical_command == "show":
        event = repository.get(args.event_id)
        if event is None:
            print(json.dumps({"error": "geopolitical event not found"}))
            return 1
        print(json.dumps(asdict(event), default=str, indent=2))
        return 0
    events = repository.events_visible_at(cutoff)
    paths = repository.paths_visible_at(cutoff, event_ids=tuple(item.event_id for item in events))
    if args.geopolitical_command == "baseline":
        print(json.dumps(asdict(calculate_baseline(events, paths, cutoff)), default=str, indent=2))
        return 0
    output = {
        "cutoff": cutoff.isoformat(),
        "events": [asdict(item) for item in events],
        "paths": [asdict(item) for item in paths],
        "corroborations": [asdict(item) for item in repository.corroborations_visible_at(cutoff)],
    }
    print(json.dumps(output, default=str, indent=2))
    return 0


def _social_command(args: argparse.Namespace, session: Session) -> int:
    repo = SqlSocialRepository(session)
    cutoff = _parse_timestamp(args.at) if getattr(args, "at", None) else datetime.now(UTC)
    values: tuple[object, ...]
    if args.social_command == "posts":
        values = repo.posts_visible_at(cutoff)
    elif args.social_command == "narratives":
        values = repo.narratives_visible_at(cutoff)
    elif args.social_command == "rumor":
        values = tuple(x for x in repo.rumors_visible_at(cutoff) if x.claim_id == args.claim_id)
    elif args.social_command == "propagation":
        values = repo.propagation(args.post_id, cutoff)
    elif args.social_command == "reputation":
        values = (repo.reputation_at(args.source_id, cutoff, args.domain),)
    else:
        values = tuple(
            session.scalars(
                select(CoordinationCandidateModel).where(
                    CoordinationCandidateModel.observed_at <= cutoff
                )
            )
        )
    print(
        json.dumps(
            [
                asdict(x) if hasattr(x, "__dataclass_fields__") else str(x)  # type: ignore[call-overload]
                for x in values
                if x is not None
            ],
            default=str,
            indent=2,
        )
    )
    return 0


def _experiment_command(args: argparse.Namespace, session: Session) -> int:
    repo = SqlExperimentRepository(session)
    if args.experiment_command == "create":
        spec = ExperimentSpecification(
            args.hypothesis,
            datetime.now(UTC),
            _parse_timestamp(args.cutoff),
            args.context,
            tuple(part.strip() for part in args.assets.split(",") if part.strip()),
            args.benchmark,
            SignalDefinition(
                (
                    SignalClause(
                        SignalKind(args.signal_kind),
                        args.signal_field,
                        RuleOperator(args.signal_operator),
                        args.signal_value,
                    ),
                )
            ),
            EntryRule.NEXT_OPEN,
            ExitRule.FIXED_HOLDING_PERIOD,
            5,
            RebalanceFrequency.EVENT_DRIVEN,
            PositionPolicy.SINGLE_POSITION,
            CostModel(),
            EvaluationWindow(
                *(
                    _parse_timestamp(getattr(args, name))
                    for name in (
                        "research_start",
                        "research_end",
                        "validation_start",
                        "validation_end",
                        "test_start",
                        "test_end",
                    )
                )
            ),
            ("survivorship_reviewed", "corporate_actions_verified"),
            (("holding_period", "5"),),
            "sha256:" + hashlib.sha256(b"marketevolver-v0.16").hexdigest(),
            (args.hypothesis, args.context),
        )
    else:
        prior = repo.specification(args.experiment_id)
        if prior is None:
            raise GovernanceViolation("experiment does not exist")
        spec = replace(
            prior,
            created_at=datetime.now(UTC),
            status=ExperimentStatus.VALIDATED,
            version=prior.version + 1,
            revision_of=prior.experiment_id,
        )
    repo.add_specification(spec)
    session.commit()
    print(spec.experiment_id)
    return 0


def _backtest_command(args: argparse.Namespace, config: AppConfig, session: Session) -> int:
    repo = SqlExperimentRepository(session)
    if args.backtest_command == "show":
        result = repo.result(args.run_id)
        if result is None:
            raise GovernanceViolation("backtest result does not exist")
        print(json.dumps(asdict(result), default=str, indent=2))
        return 0
    if args.backtest_command == "compare":
        left, right = repo.result(args.run_a), repo.result(args.run_b)
        if left is None or right is None:
            raise GovernanceViolation("backtest comparison references missing result")
        print(
            json.dumps(
                {
                    "run_a": left.result_id,
                    "run_b": right.result_id,
                    "net_return_difference": str(
                        Decimal(left.net_return) - Decimal(right.net_return)
                    ),
                    "cost_difference": str(
                        left.transaction_costs.total - right.transaction_costs.total
                    ),
                },
                indent=2,
            )
        )
        return 0
    spec = repo.specification(args.experiment_id)
    if spec is None:
        raise GovernanceViolation("experiment does not exist")
    signals: list[SignalObservation] = []
    for item in args.signal_at:
        asset_id, separator, timestamp = item.partition("=")
        if not separator or asset_id not in spec.asset_universe:
            raise GovernanceViolation("signal-at must be allowlisted asset=timestamp")
        signals.append(
            SignalObservation(
                asset_id,
                _parse_timestamp(timestamp),
                tuple(
                    (clause.field_name, clause.value) for clause in spec.signal_definition.clauses
                ),
                tuple(args.signal_provenance) or ("cli-explicit-signal",),
            )
        )
    cutoff = _parse_timestamp(args.at)
    access = TestSetAccess(
        spec.experiment_id,
        PartitionKind.TEST,
        datetime.now(UTC),
        "historical backtest",
        "market-evolver-cli",
    )
    repo.add_test_access(access)
    session.commit()  # audit boundary precedes every test-set market read
    manifest, result = BacktestEngine(
        session, MarketDataStore(session, config.market_storage.resolve_root())
    ).run(spec, tuple(signals), cutoff=cutoff)
    repo.add_dataset(manifest)
    repo.add_result(result)
    session.commit()
    print(result.result_id)
    return 0


def _walkforward_command(args: argparse.Namespace, session: Session) -> int:
    spec = SqlExperimentRepository(session).specification(args.experiment_id)
    if spec is None:
        raise GovernanceViolation("experiment does not exist")
    points = tuple(
        value.isoformat()
        for value in (
            spec.evaluation_window.research_start,
            spec.evaluation_window.research_end,
            spec.evaluation_window.validation_start,
            spec.evaluation_window.validation_end,
            spec.evaluation_window.test_start,
            spec.evaluation_window.test_end,
        )
    )
    print(json.dumps([asdict(item) for item in walk_forward_windows(points, 2, 2, 2)]))
    return 0


def _paper_command(args: argparse.Namespace, session: Session) -> int:
    repo = SqlPaperRepository(session)
    now = datetime.now(UTC)
    if args.paper_command == "create":
        experiment = SqlExperimentRepository(session).specification(args.experiment)
        if experiment is None or experiment.status not in {
            ExperimentStatus.VALIDATED,
            ExperimentStatus.RUNNING,
        }:
            raise GovernanceViolation("paper portfolio requires a validated experiment")
        repo.add_policy(NIS_2000_POLICY)
        portfolio = PaperPortfolio(
            args.portfolio_id,
            args.name,
            "ILS",
            args.initial_cash,
            now,
            (experiment.experiment_id,),
            (),
            args.benchmark,
            AllocationPolicy.FIXED_NOTIONAL,
            NIS_2000_POLICY.policy_id,
            "v0.16-next-session",
        )
        repo.add_portfolio(portfolio)
        repo.add_snapshot(PaperRuntime.initial_snapshot(portfolio))
        repo.add_audit(AuditRecord(portfolio.portfolio_id, now, "create", "cli-operator", ()))
        session.commit()
        print(portfolio.portfolio_id)
        return 0
    row = repo.latest_portfolio_row(args.portfolio_id)
    if row is None:
        raise GovernanceViolation("paper portfolio does not exist")
    if args.paper_command in {"status", "positions", "risk"}:
        output: dict[str, object] = {
            "portfolio_id": row.portfolio_id,
            "status": row.status,
            "version": row.version,
            "records": repo.counts(row.portfolio_id),
        }
        if args.paper_command == "risk":
            output["policy"] = asdict(NIS_2000_POLICY)
        print(json.dumps(output, default=str, indent=2))
        return 0
    if args.paper_command == "step":
        at = _parse_timestamp(args.at)
        repo.add_audit(
            AuditRecord(
                row.portfolio_id,
                at,
                "step",
                "cli-operator",
                (("mode", "explicit-forward-or-replay"),),
            )
        )
        session.commit()
        print(
            json.dumps(
                {
                    "portfolio_id": row.portfolio_id,
                    "advanced_to": at.isoformat(),
                    "fills": 0,
                    "note": "no admitted signals supplied",
                }
            )
        )
        return 0
    target = {
        "start": PortfolioStatus.ACTIVE,
        "resume": PortfolioStatus.ACTIVE,
        "pause": PortfolioStatus.PAUSED,
        "stop": PortfolioStatus.STOPPED,
    }[args.paper_command]
    repo.transition(
        row.portfolio_id,
        target,
        AuditRecord(row.portfolio_id, now, args.paper_command, "cli-operator", ()),
    )
    session.commit()
    print(target.value)
    return 0


def _expert_command(args: argparse.Namespace, session: Session) -> int:
    repo = SqlExpertRepository(session)
    if args.expert_command == "seed":
        inserted = sum(repo.add_definition(item) for item in FIXED_EXPERTS)
        session.commit()
        print(json.dumps({"inserted": inserted, "fixed": len(FIXED_EXPERTS)}))
        return 0
    if args.expert_command == "benchmark":
        print(
            json.dumps(
                [
                    {"case_id": case, "domain": domain, "expected": expected}
                    for case, domain, expected in BENCHMARK_CASES
                ],
                indent=2,
            )
        )
        return 0
    if args.expert_command == "list":
        print(
            json.dumps(
                [
                    {
                        "expert_id": item.expert_id,
                        "name": item.name,
                        "domain": item.domain,
                        "status": item.status.value,
                        "version": item.version,
                    }
                    for item in repo.list_latest()
                ],
                indent=2,
            )
        )
        return 0
    item = repo.latest(args.expert_id) if hasattr(args, "expert_id") else None
    if args.expert_command in {"show", "scorecard", "run", "approve", "suspend"} and item is None:
        raise GovernanceViolation("expert definition does not exist")
    if args.expert_command in {"show", "scorecard", "run", "approve", "suspend"}:
        assert item is not None
    if args.expert_command == "show":
        assert item is not None
        print(json.dumps(asdict(item), default=str, indent=2))
        return 0
    if args.expert_command == "scorecard":
        assert item is not None
        from market_evolver.storage.models import ExpertScorecardModel

        rows = tuple(
            session.scalars(
                select(ExpertScorecardModel)
                .where(ExpertScorecardModel.expert_definition_id == item.definition_id)
                .order_by(ExpertScorecardModel.cutoff.desc())
            )
        )
        print(json.dumps([row.payload for row in rows], indent=2))
        return 0
    if args.expert_command == "run":
        assert item is not None
        if item.status is not ExpertStatus.APPROVED:
            raise GovernanceViolation("only approved experts may be run")
        print(
            json.dumps(
                {
                    "expert_id": item.expert_id,
                    "cutoff": _parse_timestamp(args.at).isoformat(),
                    "status": "context/provider must be explicitly supplied",
                }
            )
        )
        return 0
    if args.expert_command == "approve":
        raise GovernanceViolation("approval requires a persisted passing benchmark scorecard")
    if args.expert_command == "suspend":
        assert item is not None
        revised = transition_expert(item, ExpertStatus.SUSPENDED, datetime.now(UTC))
        repo.add_definition(revised)
        session.commit()
        print(revised.definition_id)
        return 0
    experts = repo.list_latest()
    cutoff = _parse_timestamp(args.at)
    tags = tuple(part.strip() for part in args.tags.split(",") if part.strip())
    decision = (panel_route if args.expert_command == "panel" else route_expert)(
        args.subject, cutoff, experts, tags=tags, geography=args.geography
    )
    repo.add_routing(decision)
    session.commit()
    print(json.dumps(asdict(decision), default=str))
    return 0


def _evolve_command(args: argparse.Namespace, session: Session) -> int:
    from market_evolver.storage.models import (
        ChallengerEvaluationModel,
        EvolutionErrorAttributionModel,
        EvolvableExpertVersionModel,
    )

    repo = SqlEvolutionRepository(session)
    if args.evolve_command == "history":
        print(json.dumps(repo.history(args.expert_id), default=str, indent=2))
        return 0
    if args.evolve_command == "failures":
        version_ids = select(EvolvableExpertVersionModel.expert_version_id).where(
            EvolvableExpertVersionModel.expert_id == args.expert_id
        )
        rows = tuple(
            session.scalars(
                select(EvolutionErrorAttributionModel).where(
                    EvolutionErrorAttributionModel.expert_version_id.in_(version_ids)
                )
            )
        )
        print(json.dumps([row.payload for row in rows], indent=2))
        return 0
    if args.evolve_command == "challengers":
        rows = tuple(
            session.scalars(
                select(EvolvableExpertVersionModel).where(
                    EvolvableExpertVersionModel.expert_id == args.expert_id,
                    EvolvableExpertVersionModel.parent_version.is_not(None),
                )
            )
        )
        print(json.dumps([row.payload for row in rows], indent=2))
        return 0
    if args.evolve_command == "propose":
        champion_id = repo.current_champion_id(args.expert_id)
        if champion_id is None:
            raise GovernanceViolation("expert has no champion version")
        item = ImprovementProposal(
            args.expert_id,
            champion_id,
            ProposalType.REASONING_CHECKLIST,
            (("reasoning_template", "check evidence|check mechanisms|check contradictions"),),
            "Operator-authored bounded checklist proposal.",
            ("operator-observed-failure",),
            "operator:cli",
            ("audit:cli-explicit",),
            datetime.now(UTC),
            ProposalStatus.PROPOSED,
            ("operator:cli",),
        )
        repo.add_proposal(item)
        session.commit()
        print(item.proposal_id)
        return 0
    challenger_id = args.challenger_id
    challenger = session.get(EvolvableExpertVersionModel, challenger_id)
    if challenger is None:
        raise GovernanceViolation("challenger version does not exist")
    evaluations = tuple(
        session.scalars(
            select(ChallengerEvaluationModel)
            .where(ChallengerEvaluationModel.challenger_version_id == challenger_id)
            .order_by(ChallengerEvaluationModel.evaluated_at.desc())
        )
    )
    if args.evolve_command in {"evaluate", "compare"}:
        print(json.dumps([row.payload for row in evaluations], indent=2))
        return 0
    if args.evolve_command == "reject":
        print(
            json.dumps(
                {
                    "challenger_id": challenger_id,
                    "status": "rejection requires a new append-only evaluated/rejected version",
                }
            )
        )
        return 0
    if args.evolve_command == "promote":
        if (
            not evaluations
            or evaluations[0].decision != "eligible_for_promotion"
            or evaluations[0].safety_veto
        ):
            raise GovernanceViolation("challenger lacks a passing safety-gated evaluation")
        previous = repo.current_champion_id(challenger.expert_id)
        if previous is None:
            raise GovernanceViolation("expert has no current champion")
        event = ChampionRegistryEvent(
            challenger.expert_id,
            challenger_id,
            previous,
            RegistryAction.PROMOTION,
            "governance:cli-operator",
            "explicit CLI promotion",
            datetime.now(UTC),
            (),
            evaluations[0].evaluation_id,
        )
        repo.add_registry_event(event)
        session.commit()
        print(event.event_id)
        return 0
    history = repo.history(args.expert_id)
    if len(history) < 2:
        raise GovernanceViolation("no prior champion is available for rollback")
    current = str(history[-1]["champion_version_id"])
    prior = str(history[-1]["previous_champion_version_id"])
    event = ChampionRegistryEvent(
        args.expert_id,
        prior,
        current,
        RegistryAction.ROLLBACK,
        "governance:cli-operator",
        "explicit CLI rollback",
        datetime.now(UTC),
        (),
        None,
    )
    repo.add_registry_event(event)
    session.commit()
    print(event.event_id)
    return 0


def _topology_command(args: argparse.Namespace, session: Session) -> int:
    from market_evolver.storage.models import (
        TopologyEvaluationModel,
        TopologyGapSignalModel,
        TopologyProposalModel,
        TopologyRegistryEventModel,
    )

    repo = SqlTopologyRepository(session)
    now = datetime.now(UTC)
    if args.topology_command == "show":
        current = repo.active_at(now)
        print(json.dumps(None if current is None else asdict(current), default=str, indent=2))
        return 0
    if args.topology_command == "history":
        print(json.dumps(repo.history(), default=str, indent=2))
        return 0
    if args.topology_command == "gaps":
        rows = tuple(
            session.scalars(
                select(TopologyGapSignalModel).order_by(TopologyGapSignalModel.observed_at.desc())
            )
        )
        print(json.dumps([row.payload for row in rows], indent=2))
        return 0
    if args.topology_command == "benchmark":
        rows = tuple(
            session.scalars(
                select(TopologyEvaluationModel).order_by(
                    TopologyEvaluationModel.evaluated_at.desc()
                )
            )
        )
        print(json.dumps([row.payload for row in rows], indent=2))
        return 0
    if args.topology_command.startswith("propose-"):
        raise GovernanceViolation(
            "topology proposal requires persisted gap evidence and reviewed expert definitions"
        )
    proposal = (
        session.get(TopologyProposalModel, args.proposal_id)
        if hasattr(args, "proposal_id")
        else None
    )
    if args.topology_command in {"evaluate", "certify", "activate"} and proposal is None:
        raise GovernanceViolation("topology proposal does not exist")
    evaluations = (
        tuple(
            session.scalars(
                select(TopologyEvaluationModel)
                .where(TopologyEvaluationModel.proposal_id == args.proposal_id)
                .order_by(TopologyEvaluationModel.evaluated_at.desc())
            )
        )
        if proposal is not None
        else ()
    )
    if args.topology_command in {"evaluate", "certify"}:
        print(json.dumps([row.payload for row in evaluations], indent=2))
        return 0
    if args.topology_command == "activate":
        if (
            not evaluations
            or evaluations[0].decision != "certified_pending_approval"
            or evaluations[0].safety_veto
        ):
            raise GovernanceViolation("topology lacks passing certification and safety gate")
        current = repo.active_at(now)
        if current is None:
            raise GovernanceViolation("no active champion topology")
        event = TopologyRegistryEvent(
            evaluations[0].challenger_topology_id,
            current.topology_version_id,
            TopologyAction.ACTIVATION,
            "governance:cli-operator",
            "explicit certified topology activation",
            now,
        )
        repo.add_registry_event(event)
        session.commit()
        print(event.event_id)
        return 0
    history = tuple(
        session.scalars(
            select(TopologyRegistryEventModel).order_by(TopologyRegistryEventModel.occurred_at)
        )
    )
    if len(history) < 2:
        raise GovernanceViolation("no prior topology is available for rollback")
    current_id = history[-1].topology_version_id
    prior_id = str(history[-1].payload["previous_topology_version_id"])
    event = TopologyRegistryEvent(
        prior_id,
        current_id,
        TopologyAction.ROLLBACK,
        "governance:cli-operator",
        "explicit topology rollback",
        now,
    )
    repo.add_registry_event(event)
    session.commit()
    print(event.event_id)
    return 0


def _fusion_command(args: argparse.Namespace, session: Session) -> int:
    repo = SqlFusionRepository(session)
    cutoff = datetime.now(UTC) if getattr(args, "at", None) is None else _parse_timestamp(args.at)
    output: object
    if args.fusion_command == "benchmark":
        print(json.dumps(asdict(run_false_rumor_benchmark()), indent=2))
        return 0
    if args.fusion_command == "claim":
        claim = repo.get_claim(args.claim_id, cutoff)
        if claim is None:
            raise GovernanceViolation("claim is not visible at cutoff")
        output = {
            "claim": asdict(claim),
            "corroboration_state": current_corroboration_state(
                session, claim.claim_id, cutoff
            ).value,
            "lineage": [asdict(item) for item in repo.lineage_visible_at(cutoff, claim.claim_id)],
            "resolutions": [
                asdict(item) for item in repo.resolutions_visible_at(claim.claim_id, cutoff)
            ],
        }
    elif args.fusion_command == "unresolved":
        output = [
            asdict(claim)
            for claim in repo.claims_visible_at(cutoff)
            if not repo.resolutions_visible_at(claim.claim_id, cutoff)
            or repo.resolutions_visible_at(claim.claim_id, cutoff)[-1].outcome.value == "unresolved"
        ]
    elif args.fusion_command == "contradictions":
        output = [asdict(item) for item in repo.contradictions_visible_at(cutoff)]
    else:
        output = asdict(repo.lead_time(args.claim_id, cutoff))
    print(json.dumps(output, default=str, indent=2))
    return 0


def _reputation_command(args: argparse.Namespace, session: Session) -> int:
    cutoff = _parse_timestamp(args.at)
    stored = SqlFusionRepository(session).reputation_at(args.source_id, args.domain, cutoff)
    snapshot = (
        stored
        if stored is not None and stored.cutoff == cutoff
        else calculate_reputation(session, args.source_id, args.domain, cutoff)
    )
    print(json.dumps(asdict(snapshot), default=str, indent=2))
    return 0


def _telegram_command(args: argparse.Namespace, config: AppConfig, session: Session) -> int:
    if not config.telegram.enabled:
        raise GovernanceViolation("Telegram connector is disabled")
    if (
        not config.runtime_permissions.network_access
        or not config.runtime_permissions.secrets_access
    ):
        raise GovernanceViolation("Telegram requires host-granted network and secrets access")
    api_id, api_hash, session_token = config.telegram.credentials()
    client = TelethonClientAdapter(api_id, api_hash, session_token)
    enabled = tuple(item for item in config.telegram.allowlist if item.enabled)
    if args.telegram_command == "validate":
        results = {
            item.source_id: client.validate_public(item.public_identifier) for item in enabled
        }
        print(json.dumps(results))
        return int(not all(results.values()))
    source = next((item for item in enabled if item.source_id == args.source_id), None)
    if source is None:
        raise GovernanceViolation("Telegram source is not enabled in allowlist")
    since = None
    if args.telegram_command == "backfill":
        since = datetime.fromisoformat(args.since).replace(tzinfo=UTC)
    result = TelegramRunner(
        session, LocalArtifactStore(config.artifact_storage.resolve_root()), client
    ).run(source, limit=args.limit, since=since, observed_at=datetime.now(UTC))
    print(json.dumps(asdict(result), default=str))
    return int(result.status.value == "failed")


def _macro_observation_from_dict(item: object) -> MacroObservation:
    if not isinstance(item, dict):
        raise TypeError
    return MacroObservation(
        series_id=str(item["series_id"]),
        source_id=str(item["source_id"]),
        geography=str(item["geography"]),
        category=MacroCategory(item["category"]),
        observation_period=str(item["observation_period"]),
        value=str(item["value"]),
        unit=str(item["unit"]),
        published_at=_parse_timestamp(str(item["published_at"])),
        first_observed_at=_parse_timestamp(str(item["first_observed_at"])),
        revision_of=None if item.get("revision_of") is None else str(item["revision_of"]),
        seasonal_adjustment=SeasonalAdjustment(item["seasonal_adjustment"]),
        provenance=tuple(str(value) for value in item["provenance"]),
        parser_version=str(item["parser_version"]),
        name_en=str(item["name_en"]),
        name_he=None if item.get("name_he") is None else str(item["name_he"]),
        prior_value=None if item.get("prior_value") is None else str(item["prior_value"]),
        expected_value=None if item.get("expected_value") is None else str(item["expected_value"]),
        expectation_source=None
        if item.get("expectation_source") is None
        else str(item["expectation_source"]),
        expectation_observed_at=(
            None
            if item.get("expectation_observed_at") is None
            else _parse_timestamp(str(item["expectation_observed_at"]))
        ),
    )


def _macro_dict(item: MacroObservation) -> dict[str, object]:
    return {
        "observation_id": item.observation_id,
        "series_id": item.series_id,
        "name_en": item.name_en,
        "name_he": item.name_he,
        "period": item.observation_period,
        "value": item.value,
        "unit": item.unit,
        "published_at": item.published_at.isoformat(),
        "first_observed_at": item.first_observed_at.isoformat(),
        "revision_of": item.revision_of,
        "seasonal_adjustment": item.seasonal_adjustment.value,
        "expectation_status": item.expectation_status.value,
        "surprise": item.surprise,
        "provenance": item.provenance,
    }


def _market_observation_from_dict(item: object) -> MarketObservation:
    if not isinstance(item, dict):
        raise TypeError
    return MarketObservation(
        asset_id=str(item["asset_id"]),
        venue=str(item["venue"]),
        observation_type=ObservationType(item["observation_type"]),
        market_timestamp=_parse_timestamp(str(item["market_timestamp"])),
        observed_at=_parse_timestamp(str(item["observed_at"])),
        source_id=str(item["source_id"]),
        adjustment_status=AdjustmentStatus(item["adjustment_status"]),
        currency=str(item["currency"]),
        parser_version=str(item["parser_version"]),
        provenance=tuple(str(value) for value in item["provenance"]),
        open=None if item.get("open") is None else str(item["open"]),
        high=None if item.get("high") is None else str(item["high"]),
        low=None if item.get("low") is None else str(item["low"]),
        close=None if item.get("close") is None else str(item["close"]),
        volume=None if item.get("volume") is None else str(item["volume"]),
        value=None if item.get("value") is None else str(item["value"]),
    )


def _run_dict(item: object) -> dict[str, object]:
    from market_evolver.replay.schemas import ReplayRun

    assert isinstance(item, ReplayRun)
    return {
        "run_id": item.run_id,
        "case_id": item.case_id,
        "commitment_id": item.commitment_id,
        "named": item.named,
        "started_at": item.started_at.isoformat(),
        "finished_at": item.finished_at.isoformat(),
        "runtime_ms": item.runtime_ms,
        "status": item.status,
    }


if __name__ == "__main__":
    raise SystemExit(main())
