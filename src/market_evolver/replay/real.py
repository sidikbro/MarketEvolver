"""Curated real-world replay manifests with strict temporal role separation."""

from __future__ import annotations

import json
import math
import subprocess
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_evolver.errors import GovernanceViolation, IntegrityViolation, ValidationError
from market_evolver.market.history import HistoricalBar
from market_evolver.provenance import content_id
from market_evolver.storage.models import RealReplayCaseModel, RealReplayCommitmentModel
from market_evolver.time import require_aware_utc


class TemporalClass(str, Enum):
    VINTAGE_SAFE = "vintage_safe"
    FORWARD_OBSERVATION_ONLY = "forward_observation_only"
    OUTCOME_MEASUREMENT_ONLY = "outcome_measurement_only"
    TEMPORALLY_AMBIGUOUS = "temporally_ambiguous"


class ReplayDataRole(str, Enum):
    RESEARCH_EVIDENCE = "research_evidence"
    OUTCOME_DATA = "outcome_data"
    RETROSPECTIVE_METADATA = "retrospective_metadata"


class RealCaseStatus(str, Enum):
    USABLE = "USABLE"
    UNUSABLE_FOR_CAUSAL_REPLAY = "UNUSABLE_FOR_CAUSAL_REPLAY"


class EvaluationSet(str, Enum):
    DEVELOPMENT = "development"
    PROTECTED = "protected"


class AnonymizationMode(str, Enum):
    NAMED_AND_HISTORICAL_ALIAS = "named_and_historical_alias"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True, slots=True)
class CaseSelectionAudit:
    rationale: str
    selected_by: str
    selected_at: datetime
    outcome_known_to_selector: bool
    evaluation_set: EvaluationSet

    def __post_init__(self) -> None:
        object.__setattr__(self, "selected_at", require_aware_utc(self.selected_at, "selected_at"))
        if not self.rationale or not self.selected_by:
            raise ValidationError("case selection audit must identify rationale and selector")


@dataclass(frozen=True, slots=True)
class ReplaySourceItem:
    item_id: str
    source_id: str
    source_uri: str
    published_at: datetime | None
    first_observed_at: datetime | None
    temporal_class: TemporalClass
    role: ReplayDataRole
    content_hash: str | None
    revision_of: str | None = None

    def __post_init__(self) -> None:
        for name in ("published_at", "first_observed_at"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, require_aware_utc(value, name))
        if not self.item_id or not self.source_id or not self.source_uri:
            raise ValidationError("replay source item identity is required")
        if self.role is ReplayDataRole.RESEARCH_EVIDENCE:
            if self.temporal_class is not TemporalClass.VINTAGE_SAFE:
                raise GovernanceViolation("only vintage-safe items may be research evidence")
            if self.first_observed_at is None or self.content_hash is None:
                raise ValidationError("research evidence requires observation time and hash")
        if (
            self.role is ReplayDataRole.OUTCOME_DATA
            and self.temporal_class is not TemporalClass.OUTCOME_MEASUREMENT_ONLY
        ):
            raise GovernanceViolation(
                "outcome data requires outcome-measurement-only classification"
            )


@dataclass(frozen=True, slots=True)
class HistoricalReplayCase:
    title: str
    geography: tuple[str, ...]
    entities: tuple[str, ...]
    domains: tuple[str, ...]
    cutoff_timestamps: tuple[datetime, ...]
    event_window: tuple[datetime, datetime]
    evaluation_horizons: tuple[str, ...]
    source_manifest: tuple[ReplaySourceItem, ...]
    market_dataset_ids: tuple[str, ...]
    benchmark_ids: tuple[str, ...]
    anonymization_mode: AnonymizationMode
    expected_replay_limitations: tuple[str, ...]
    provenance: tuple[str, ...]
    selection_audit: CaseSelectionAudit
    status: RealCaseStatus
    version: int
    case_id: str = field(init=False)

    def __post_init__(self) -> None:
        cutoffs = tuple(require_aware_utc(item, "cutoff") for item in self.cutoff_timestamps)
        window = tuple(require_aware_utc(item, "event_window") for item in self.event_window)
        object.__setattr__(self, "cutoff_timestamps", cutoffs)
        object.__setattr__(self, "event_window", window)
        if (
            not self.title
            or not self.geography
            or not self.entities
            or not self.domains
            or not cutoffs
            or tuple(sorted(set(cutoffs))) != cutoffs
            or window[1] < window[0]
            or not self.evaluation_horizons
            or not self.provenance
            or self.version < 1
        ):
            raise ValidationError("real replay case manifest is incomplete or unordered")
        research = tuple(
            item for item in self.source_manifest if item.role is ReplayDataRole.RESEARCH_EVIDENCE
        )
        if self.status is RealCaseStatus.USABLE and not research and "quiet" not in self.domains:
            raise ValidationError("usable non-control case requires vintage-safe research evidence")
        if (
            self.status is RealCaseStatus.UNUSABLE_FOR_CAUSAL_REPLAY
            and not self.expected_replay_limitations
        ):
            raise ValidationError("unusable case must explain its temporal/data gap")
        revisions = {item.item_id: item for item in self.source_manifest}
        for item in self.source_manifest:
            if item.revision_of:
                previous = revisions.get(item.revision_of)
                previous_time = (
                    None
                    if previous is None
                    else previous.first_observed_at or previous.published_at
                )
                item_time = item.first_observed_at or item.published_at
                if (
                    previous is None
                    or previous_time is None
                    or item_time is None
                    or item_time <= previous_time
                ):
                    raise ValidationError("invalid real-case revision lineage")
        object.__setattr__(self, "case_id", content_id("real-replay-case", self))

    def evidence_visible_at(self, cutoff: datetime) -> tuple[ReplaySourceItem, ...]:
        at = require_aware_utc(cutoff, "cutoff")
        visible = tuple(
            item
            for item in self.source_manifest
            if item.role is ReplayDataRole.RESEARCH_EVIDENCE
            and item.first_observed_at is not None
            and item.first_observed_at <= at
        )
        revised = {item.revision_of for item in visible if item.revision_of}
        return tuple(item for item in visible if item.item_id not in revised)


@dataclass(frozen=True, slots=True)
class SealedRealCommitment:
    case_id: str
    cutoff: datetime
    mode: str
    context_manifest_hash: str
    assessment: str
    hypothesis: str
    confidence: float
    horizon: str
    falsification_criterion: str
    reviewer_result: str
    expert_version: str
    topology_version: str
    prompt_version: str
    provider_model: str
    seed: int
    committed_at: datetime
    commitment_id: str = field(init=False)

    def __post_init__(self) -> None:
        for name in ("cutoff", "committed_at"):
            object.__setattr__(self, name, require_aware_utc(getattr(self, name), name))
        if self.committed_at < self.cutoff or not 0 <= self.confidence <= 1:
            raise ValidationError("invalid real replay commitment timing/confidence")
        if not all(
            (
                self.case_id,
                self.mode,
                self.context_manifest_hash,
                self.assessment,
                self.hypothesis,
                self.horizon,
                self.falsification_criterion,
                self.reviewer_result,
                self.expert_version,
                self.topology_version,
                self.prompt_version,
                self.provider_model,
            )
        ):
            raise ValidationError("sealed real replay commitment is incomplete")
        object.__setattr__(self, "commitment_id", content_id("real-replay-commitment", self))


class SqlRealReplayRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_case(self, case: HistoricalReplayCase) -> bool:
        if self.session.get(RealReplayCaseModel, case.case_id):
            return False
        self.session.add(
            RealReplayCaseModel(
                case_id=case.case_id,
                status=case.status.value,
                selected_at=case.selection_audit.selected_at,
                payload=_jsonable(asdict(case)),
            )
        )
        self.session.flush()
        return True

    def add_commitment(self, item: SealedRealCommitment) -> bool:
        if self.session.get(RealReplayCommitmentModel, item.commitment_id):
            return False
        if self.session.get(RealReplayCaseModel, item.case_id) is None:
            raise IntegrityViolation("real commitment references unknown case")
        self.session.add(
            RealReplayCommitmentModel(
                commitment_id=item.commitment_id,
                case_id=item.case_id,
                cutoff=item.cutoff,
                mode=item.mode,
                committed_at=item.committed_at,
                payload=_jsonable(asdict(item)),
            )
        )
        self.session.flush()
        return True

    def counts(self) -> tuple[int, int]:
        return (
            len(tuple(self.session.scalars(select(RealReplayCaseModel.case_id)))),
            len(tuple(self.session.scalars(select(RealReplayCommitmentModel.commitment_id)))),
        )


RESEARCH_MODES = (
    "deterministic_baseline",
    "general_market_researcher",
    "fixed_specialist",
    "specialist_skeptical_reviewer",
    "anonymized_specialist",
    "named_specialist",
)
SELECTED_AT = datetime(2026, 8, 12, 16, tzinfo=UTC)


def curated_real_cases() -> tuple[HistoricalReplayCase, ...]:
    boi_release = (
        "https://www.boi.org.il/en/communication-and-publications/press-releases/a01-01-24/"
    )
    outcome = _source(
        "boi-fx-outcome-2024q1",
        "il.boi.sdmx.exr",
        "https://edge.boi.org.il/FusionEdgeServer/sdmx/v2/data/dataflow/BOI.STATISTICS/EXR/1.0/RER_USD_ILS",
        None,
        None,
        TemporalClass.OUTCOME_MEASUREMENT_ONLY,
        ReplayDataRole.OUTCOME_DATA,
        None,
    )
    decision = _source(
        "boi-rate-2024-01-01",
        "il.boi",
        boi_release,
        datetime(2024, 1, 1, 14, tzinfo=UTC),
        None,
        TemporalClass.TEMPORALLY_AMBIGUOUS,
        ReplayDataRole.RETROSPECTIVE_METADATA,
        None,
    )
    later_report = _source(
        "boi-mpr-2024-01-21",
        "il.boi",
        "https://www.boi.org.il/en/communication-and-publications/press-releases/21-1-24/",
        datetime(2024, 1, 21, 10, tzinfo=UTC),
        None,
        TemporalClass.TEMPORALLY_AMBIGUOUS,
        ReplayDataRole.RETROSPECTIVE_METADATA,
        None,
    )
    return (
        _case(
            "BOI January 2024 rate cut",
            (decision, outcome),
            (datetime(2024, 1, 1, 14, tzinfo=UTC),),
            (datetime(2023, 12, 31, tzinfo=UTC), datetime(2024, 1, 8, tzinfo=UTC)),
            ("institution.boi", "pair.usdils"),
            ("policy", "fx"),
            RealCaseStatus.UNUSABLE_FOR_CAUSAL_REPLAY,
            "official page is dated, but MarketEvolver did not observe and hash it in 2024",
        ),
        _case(
            "BOI decision and later retrospective policy report",
            (decision, later_report, outcome),
            (datetime(2024, 1, 1, 14, tzinfo=UTC), datetime(2024, 1, 21, 10, tzinfo=UTC)),
            (datetime(2024, 1, 1, tzinfo=UTC), datetime(2024, 1, 26, tzinfo=UTC)),
            ("institution.boi",),
            ("policy", "revision"),
            RealCaseStatus.UNUSABLE_FOR_CAUSAL_REPLAY,
            "later report is not a captured correction vintage and cannot revise historical belief",
        ),
        _case(
            "USD/ILS October 2023 movement",
            (outcome,),
            (datetime(2023, 10, 9, 14, tzinfo=UTC),),
            (datetime(2023, 10, 6, tzinfo=UTC), datetime(2023, 10, 16, tzinfo=UTC)),
            ("pair.usdils",),
            ("fx", "geopolitical"),
            RealCaseStatus.UNUSABLE_FOR_CAUSAL_REPLAY,
            "no retained vintage-safe event/news snapshot",
        ),
        _case(
            "Teva 2023 annual filing",
            (
                _ambiguous(
                    "teva-2023-20f",
                    "us.sec.edgar",
                    "https://www.sec.gov/edgar/browse/?CIK=818686&owner=exclude",
                ),
            ),
            (datetime(2024, 2, 12, 12, tzinfo=UTC),),
            (datetime(2024, 2, 12, tzinfo=UTC), datetime(2024, 2, 20, tzinfo=UTC)),
            ("company.teva",),
            ("company_filing",),
            RealCaseStatus.UNUSABLE_FOR_CAUSAL_REPLAY,
            "filing accession and retained fact vintage not yet captured",
        ),
        _case(
            "Israel CPI December 2023 release",
            (
                _ambiguous(
                    "cbs-cpi-2023-12",
                    "il.cbs",
                    "https://www.cbs.gov.il/en/subjects/Pages/Consumer-Price-Index.aspx",
                ),
            ),
            (datetime(2024, 1, 15, 16, tzinfo=UTC),),
            (datetime(2024, 1, 15, tzinfo=UTC), datetime(2024, 1, 22, tzinfo=UTC)),
            ("country.israel",),
            ("macro",),
            RealCaseStatus.UNUSABLE_FOR_CAUSAL_REPLAY,
            "CBS historical publication vintage not retained",
        ),
        _case(
            "October 2023 geopolitical disruption",
            (
                _ambiguous(
                    "news-2023-10-07",
                    "news.unretained",
                    "https://www.bbc.com/news/world-middle-east",
                ),
                outcome,
            ),
            (datetime(2023, 10, 7, 12, tzinfo=UTC), datetime(2023, 10, 9, 14, tzinfo=UTC)),
            (datetime(2023, 10, 7, tzinfo=UTC), datetime(2023, 10, 16, tzinfo=UTC)),
            ("country.israel", "pair.usdils"),
            ("geopolitical", "conflicting_evidence"),
            RealCaseStatus.UNUSABLE_FOR_CAUSAL_REPLAY,
            "article snapshot and edit history unavailable",
        ),
        _case(
            "Quiet USD/ILS control week",
            (outcome,),
            (datetime(2024, 2, 5, 14, tzinfo=UTC),),
            (datetime(2024, 2, 5, tzinfo=UTC), datetime(2024, 2, 12, tzinfo=UTC)),
            ("pair.usdils",),
            ("quiet", "fx"),
            RealCaseStatus.USABLE,
        ),
    )


def build_commitments(
    cases: tuple[HistoricalReplayCase, ...], committed_at: datetime
) -> tuple[SealedRealCommitment, ...]:
    output = []
    for case in cases:
        if case.status is not RealCaseStatus.USABLE:
            continue
        for cutoff in case.cutoff_timestamps:
            visible = case.evidence_visible_at(cutoff)
            manifest_hash = content_id("real-context", tuple(item.item_id for item in visible))
            for mode in RESEARCH_MODES:
                provider = (
                    "deterministic-rules/1"
                    if mode == "deterministic_baseline"
                    else "not_run:no_provider_trace"
                )
                output.append(
                    SealedRealCommitment(
                        case.case_id,
                        cutoff,
                        mode,
                        manifest_hash,
                        "Evidence availability recorded; no investment recommendation.",
                        "Measure the committed USD/ILS path without asserting a tradable edge.",
                        0.0 if not visible else 0.35,
                        "5 calendar days",
                        "Inconclusive if the required outcome series is unavailable.",
                        "not_reviewed" if "reviewer" not in mode else "requires_provider_trace",
                        "fixed-experts/v0.18",
                        "topology/v0.20",
                        "real-replay/1",
                        provider,
                        0,
                        committed_at,
                    )
                )
    return tuple(output)


def outcome_metrics(
    bars: tuple[HistoricalBar, ...], cutoff: datetime, horizon_end: datetime
) -> dict[str, str]:
    before = tuple(bar for bar in bars if bar.market_timestamp <= cutoff)
    after = tuple(bar for bar in bars if cutoff < bar.market_timestamp <= horizon_end)
    if not before or not after:
        raise IntegrityViolation("outcome series does not span cutoff and horizon")
    start = Decimal(before[-1].raw_close)
    values = tuple(Decimal(item.raw_close) for item in after)
    returns = tuple(values[index] / values[index - 1] - 1 for index in range(1, len(values)))
    peak = start
    drawdown = Decimal(0)
    for value in values:
        peak = max(peak, value)
        drawdown = min(drawdown, value / peak - 1)
    volatility = Decimal(0)
    if returns:
        mean = sum(returns) / Decimal(len(returns))
        variance = sum((item - mean) ** 2 for item in returns) / Decimal(len(returns))
        volatility = Decimal(str(math.sqrt(float(variance))))
    return {
        "raw_return": str(values[-1] / start - 1),
        "mfe": str(max(value / start - 1 for value in values)),
        "mae": str(min(value / start - 1 for value in values)),
        "drawdown": str(drawdown),
        "volatility": str(volatility),
        "observation_hash": content_id(
            "real-outcome-bars", tuple(item.bar_id for item in (*before[-1:], *after))
        ),
    }


def write_real_replay_reports(
    root: Path,
    cases: tuple[HistoricalReplayCase, ...],
    commitments: tuple[SealedRealCommitment, ...],
    bars: tuple[HistoricalBar, ...] = (),
) -> Path:
    commit = _git_commit()
    report_root = root / f"real-replay-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    report_root.mkdir(parents=True, exist_ok=False)
    by_case: dict[str, list[SealedRealCommitment]] = {case.case_id: [] for case in cases}
    for item in commitments:
        by_case[item.case_id].append(item)
    for case in cases:
        outcome: dict[str, str] | None = None
        if bars and case.status is RealCaseStatus.USABLE and case.market_dataset_ids:
            try:
                outcome = outcome_metrics(bars, case.cutoff_timestamps[-1], case.event_window[1])
            except IntegrityViolation:
                outcome = None
        payload = {
            "git_commit": commit,
            "case": _jsonable(asdict(case)),
            "commitments": _jsonable([asdict(item) for item in by_case[case.case_id]]),
            "outcomes": outcome or "not_revealed_without_verified_runtime_dataset",
            "financial_advice": False,
        }
        (report_root / f"{case.case_id}.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
        )
        (report_root / f"{case.case_id}.md").write_text(
            _case_markdown(case, by_case[case.case_id], commit, outcome), encoding="utf-8"
        )
    usable = sum(case.status is RealCaseStatus.USABLE for case in cases)
    aggregate = {
        "git_commit": commit,
        "cases": len(cases),
        "usable": usable,
        "unusable": len(cases) - usable,
        "cutoffs": sum(len(case.cutoff_timestamps) for case in cases),
        "sealed_hypotheses": len(commitments),
        "supported": 0,
        "falsified": 0,
        "inconclusive": len(commitments),
        "calibration": None,
        "named_anonymized_gap": None,
        "specialist_generalist_delta": None,
        "reviewer_effect": None,
        "leakage_failures": 0,
        "evidence_gaps": len(cases) - usable,
        "statistical_claim": False,
    }
    (report_root / "aggregate.json").write_text(
        json.dumps(aggregate, indent=2, sort_keys=True), encoding="utf-8"
    )
    return report_root


def _case(
    title: str,
    sources: tuple[ReplaySourceItem, ...],
    cutoffs: tuple[datetime, ...],
    window: tuple[datetime, datetime],
    entities: tuple[str, ...],
    domains: tuple[str, ...],
    status: RealCaseStatus,
    limitation: str = "retrospective selection; small sample; no causal or statistical conclusion",
) -> HistoricalReplayCase:
    return HistoricalReplayCase(
        title,
        ("IL",),
        entities,
        domains,
        cutoffs,
        window,
        ("5 calendar days",),
        sources,
        tuple(item.item_id for item in sources if item.role is ReplayDataRole.OUTCOME_DATA),
        (),
        AnonymizationMode.NAMED_AND_HISTORICAL_ALIAS
        if any(entity.startswith("company.") for entity in entities)
        else AnonymizationMode.NOT_APPLICABLE,
        (limitation,),
        ("catalog:real-replay-cases/1",),
        CaseSelectionAudit(
            "category diversity and defensible source timing; not selected for return magnitude",
            "MarketEvolver v0.25 curated specification",
            SELECTED_AT,
            True,
            EvaluationSet.DEVELOPMENT,
        ),
        status,
        1,
    )


def _source(
    item_id: str,
    source_id: str,
    uri: str,
    published: datetime | None,
    observed: datetime | None,
    temporal: TemporalClass,
    role: ReplayDataRole,
    digest: str | None,
    revision_of: str | None = None,
) -> ReplaySourceItem:
    return ReplaySourceItem(
        item_id, source_id, uri, published, observed, temporal, role, digest, revision_of
    )


def _ambiguous(item_id: str, source_id: str, uri: str) -> ReplaySourceItem:
    return _source(
        item_id,
        source_id,
        uri,
        None,
        None,
        TemporalClass.TEMPORALLY_AMBIGUOUS,
        ReplayDataRole.RETROSPECTIVE_METADATA,
        None,
    )


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    return value


def _case_markdown(
    case: HistoricalReplayCase,
    commitments: list[SealedRealCommitment],
    commit: str,
    outcome: dict[str, str] | None,
) -> str:
    visible = [
        f"- {cutoff.isoformat()}: {', '.join(item.item_id for item in case.evidence_visible_at(cutoff)) or 'no vintage-safe evidence'}"
        for cutoff in case.cutoff_timestamps
    ]
    return "\n".join(
        (
            f"# {case.title}",
            "",
            f"Status: **{case.status.value}**",
            f"Case/version: `{case.case_id}` / {case.version}",
            f"Git commit: `{commit}`",
            "",
            "## Timeline",
            "",
            *visible,
            "",
            f"Sealed commitments: {len(commitments)}",
            "Outcome: "
            + (
                json.dumps(outcome, sort_keys=True)
                if outcome is not None
                else "not revealed without a verified runtime dataset."
            ),
            "",
            "Limitations: " + "; ".join(case.expected_replay_limitations),
            "",
            "This is research validation, not financial advice.",
            "",
        )
    )


def _git_commit() -> str:
    result = subprocess.run(
        ("git", "rev-parse", "HEAD"), capture_output=True, text=True, check=False
    )
    return result.stdout.strip() if result.returncode == 0 else "unknown"
