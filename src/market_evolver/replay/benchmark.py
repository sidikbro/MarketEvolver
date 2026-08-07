"""Small versioned benchmark cases, baseline modes, paired runs, and metrics."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from market_evolver.provenance import content_id
from market_evolver.replay.engine import ReplayEngine
from market_evolver.replay.repositories import SqlReplayRepository
from market_evolver.replay.schemas import (
    BenchmarkMetrics,
    BenchmarkPair,
    OutcomeEvaluation,
    ReplayCase,
    ReplayCaseType,
    ReplayRun,
    ResearchCommitment,
    ResearchMode,
)

DATASET_VERSION = "curated-replay-cases/1"
CASE_CUTOFF = datetime(2025, 1, 2, 16, tzinfo=UTC)

_CASE_DEFINITIONS = (
    (ReplayCaseType.FX_MOVEMENT, "pair.usdils", "asset.fx.usdils", None),
    (ReplayCaseType.BOI_POLICY, "institution.boi", "asset.fx.usdils", None),
    (ReplayCaseType.COMPANY_FILING, "company.nice", "asset.xtae.nice", "asset.index.ta35"),
    (ReplayCaseType.NEWS_EVENT, "company.teva", "asset.xnys.teva", "asset.arcx.spy"),
    (
        ReplayCaseType.CONFLICTING_EVIDENCE,
        "company.elbit.systems",
        "asset.xtae.eslt",
        "asset.index.ta35",
    ),
    (
        ReplayCaseType.REVISED_EVIDENCE,
        "company.icl",
        "asset.xtae.icl",
        "asset.index.ta35",
    ),
    (ReplayCaseType.QUIET, "etf.spy", "asset.arcx.spy", None),
)


def baseline_research(
    mode: ResearchMode,
    *,
    trailing_values: tuple[float, ...] = (),
    has_event: bool = False,
    fundamental_growth: float | None = None,
) -> tuple[str, float]:
    if mode is ResearchMode.NO_INFORMATION:
        return "No-information baseline makes no directional assertion.", 0.0
    if mode is ResearchMode.MOMENTUM:
        change = 0.0 if len(trailing_values) < 2 else trailing_values[-1] / trailing_values[0] - 1
        return f"Trailing market change was {change:.6f}.", min(abs(change), 1.0)
    if mode is ResearchMode.MEAN_REVERSION:
        change = 0.0 if len(trailing_values) < 2 else trailing_values[-1] / trailing_values[0] - 1
        return f"Mean-reversion baseline records trailing deviation {change:.6f}.", min(
            abs(change), 1.0
        )
    if mode is ResearchMode.EVENT_RULES:
        return f"Deterministic event presence was {has_event}.", 1.0
    if mode is ResearchMode.FUNDAMENTALS:
        return f"Deterministic reported fundamental growth was {fundamental_growth}.", 0.5
    if mode is ResearchMode.LLM:
        return "LLM research requires a validated provider trace.", 0.0
    return "LLM plus reviewer requires validated provider and reviewer traces.", 0.0


def curated_cases(created_at: datetime = CASE_CUTOFF) -> tuple[ReplayCase, ...]:
    return tuple(
        ReplayCase(
            case_type,
            (entity_id,),
            (asset_id,),
            CASE_CUTOFF,
            "5 trading days",
            f"benchmark-evidence-manifest:{case_type.value}:v1",
            benchmark,
            "research-hypothesis/v1",
            "forward-market-outcome/1",
            DATASET_VERSION,
            created_at,
        )
        for case_type, entity_id, asset_id, benchmark in _CASE_DEFINITIONS
    )


class BenchmarkRunner:
    def __init__(self, session: Session, replay: ReplayEngine) -> None:
        self.session = session
        self.replay = replay
        self.repository = SqlReplayRepository(session)

    def seed_cases(self) -> int:
        inserted = sum(self.repository.add_case(item) for item in curated_cases())
        self.session.commit()
        return inserted

    def run_case(
        self,
        case: ReplayCase,
        mode: ResearchMode,
        *,
        named: bool,
        now: datetime,
    ) -> ReplayRun:
        snapshot = self.replay.snapshot(case)
        commitment = ResearchCommitment(
            case.case_id,
            case.cutoff,
            snapshot.context_id,
            content_id(
                "baseline-hypothesis",
                {"case": case.case_id, "mode": mode.value, "named": named},
            ),
            case.horizon,
            f"Evaluate the specified {case.case_type.value} outcome under {mode.value}.",
            "The committed measurable outcome is not observed by the horizon.",
            0.5 if mode is not ResearchMode.NO_INFORMATION else 0.0,
            "reviewed" if mode is ResearchMode.LLM_REVIEWED else "not_reviewed",
            mode,
            now,
        )
        self.replay.commit(commitment)
        run = ReplayRun(case.case_id, commitment.commitment_id, named, now, now, 0, "committed")
        self.replay.record_run(run)
        return run

    def run_all(self, now: datetime) -> tuple[ReplayRun, ...]:
        self.seed_cases()
        runs: list[ReplayRun] = []
        for case in self.repository.list_cases():
            for mode in ResearchMode:
                named = self.run_case(case, mode, named=True, now=now)
                anonymous = self.run_case(case, mode, named=False, now=now)
                runs.extend((named, anonymous))
                self.repository.add_pair(
                    BenchmarkPair(case.case_id, named.run_id, anonymous.run_id, now)
                )
        self.session.commit()
        return tuple(runs)


def benchmark_metrics(
    runs: tuple[ReplayRun, ...],
    evaluations: tuple[OutcomeEvaluation, ...],
    *,
    hypotheses_valid: int = 0,
    reviewer_rejections: int = 0,
    unsupported_claims: int = 0,
    provenance_failures: int = 0,
    temporal_leaks: int = 0,
    calibrated_error: float = 0.0,
) -> BenchmarkMetrics:
    total = len(runs)
    relative = [
        float(item.benchmark_relative_return)
        for item in evaluations
        if item.benchmark_relative_return is not None
    ]
    directional = [item.direction for item in evaluations if item.direction is not None]
    by_case: dict[str, dict[bool, list[float]]] = {}
    run_by_id = {item.run_id: item for item in runs}
    for item in evaluations:
        if item.forward_return is None or item.run_id not in run_by_id:
            continue
        run = run_by_id[item.run_id]
        by_case.setdefault(run.case_id, {True: [], False: []})[run.named].append(
            float(item.forward_return)
        )
    gaps = [
        abs(sum(values[True]) / len(values[True]) - sum(values[False]) / len(values[False]))
        for values in by_case.values()
        if values[True] and values[False]
    ]
    denominator = total or 1
    return BenchmarkMetrics(
        hypotheses_valid / denominator,
        reviewer_rejections / denominator,
        unsupported_claims / denominator,
        provenance_failures / denominator,
        temporal_leaks / denominator,
        calibrated_error,
        None
        if not directional
        else sum(item in {"up", "down"} for item in directional) / len(directional),
        None if not relative else sum(relative) / len(relative),
        None if not gaps else sum(gaps) / len(gaps),
    )
