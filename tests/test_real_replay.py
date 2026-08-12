from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from market_evolver.errors import GovernanceViolation, IntegrityViolation, ValidationError
from market_evolver.market.history import HistoricalBar
from market_evolver.replay.real import (
    RESEARCH_MODES,
    AnonymizationMode,
    CaseSelectionAudit,
    EvaluationSet,
    HistoricalReplayCase,
    RealCaseStatus,
    ReplayDataRole,
    ReplaySourceItem,
    TemporalClass,
    build_commitments,
    curated_real_cases,
    outcome_metrics,
    write_real_replay_reports,
)

T0 = datetime(2024, 1, 1, 14, tzinfo=UTC)


@pytest.mark.unit
def test_real_case_catalog_selection_audit_and_statuses() -> None:
    cases = curated_real_cases()
    assert len(cases) == 7
    assert sum(case.status is RealCaseStatus.USABLE for case in cases) == 1
    assert sum(len(case.cutoff_timestamps) for case in cases) == 9
    assert all(case.selection_audit.outcome_known_to_selector for case in cases)
    assert all(case.selection_audit.evaluation_set is EvaluationSet.DEVELOPMENT for case in cases)
    assert all(case.expected_replay_limitations for case in cases)


@pytest.mark.unit
def test_temporal_roles_fail_closed_and_outcomes_are_separate() -> None:
    with pytest.raises(GovernanceViolation):
        ReplaySourceItem(
            "bad",
            "source",
            "https://example.invalid",
            T0,
            T0,
            TemporalClass.TEMPORALLY_AMBIGUOUS,
            ReplayDataRole.RESEARCH_EVIDENCE,
            "sha256:" + "a" * 64,
        )
    for case in curated_real_cases():
        assert all(
            item.role is not ReplayDataRole.OUTCOME_DATA
            for cutoff in case.cutoff_timestamps
            for item in case.evidence_visible_at(cutoff)
        )


@pytest.mark.unit
def test_revision_does_not_leak_to_first_cutoff() -> None:
    case = next(case for case in curated_real_cases() if "later retrospective" in case.title)
    assert all(case.evidence_visible_at(cutoff) == () for cutoff in case.cutoff_timestamps)
    assert case.status is RealCaseStatus.UNUSABLE_FOR_CAUSAL_REPLAY

    original = ReplaySourceItem(
        "original",
        "official.fixture",
        "https://example.invalid/original",
        T0,
        T0,
        TemporalClass.VINTAGE_SAFE,
        ReplayDataRole.RESEARCH_EVIDENCE,
        "sha256:" + "a" * 64,
    )
    revised = ReplaySourceItem(
        "revised",
        "official.fixture",
        "https://example.invalid/revised",
        T0 + timedelta(days=1),
        T0 + timedelta(days=1),
        TemporalClass.VINTAGE_SAFE,
        ReplayDataRole.RESEARCH_EVIDENCE,
        "sha256:" + "b" * 64,
        original.item_id,
    )
    fixture = HistoricalReplayCase(
        "revision fixture",
        ("IL",),
        ("fixture",),
        ("revision",),
        (T0, T0 + timedelta(days=1)),
        (T0, T0 + timedelta(days=2)),
        ("1 day",),
        (original, revised),
        (),
        (),
        AnonymizationMode.NOT_APPLICABLE,
        ("test fixture",),
        ("fixture",),
        CaseSelectionAudit("revision test", "test", T0, False, EvaluationSet.DEVELOPMENT),
        RealCaseStatus.USABLE,
        1,
    )
    assert fixture.evidence_visible_at(T0) == (original,)
    assert fixture.evidence_visible_at(T0 + timedelta(days=1)) == (revised,)


@pytest.mark.unit
def test_commitments_cover_required_comparisons_and_are_content_immutable() -> None:
    commitments = build_commitments(curated_real_cases(), datetime(2026, 8, 12, tzinfo=UTC))
    assert len(commitments) == len(RESEARCH_MODES)
    assert {item.mode for item in commitments} == set(RESEARCH_MODES)
    named = next(item for item in commitments if item.mode == "named_specialist")
    anonymous = next(item for item in commitments if item.mode == "anonymized_specialist")
    general = next(item for item in commitments if item.mode == "general_market_researcher")
    specialist = next(item for item in commitments if item.mode == "fixed_specialist")
    assert named.context_manifest_hash == anonymous.context_manifest_hash
    assert general.context_manifest_hash == specialist.context_manifest_hash
    assert replace(named, confidence=0.9).commitment_id != named.commitment_id


@pytest.mark.unit
def test_outcome_metrics_use_only_post_commit_market_path() -> None:
    def bar(day: int, close: str) -> HistoricalBar:
        timestamp = T0 + timedelta(days=day)
        return HistoricalBar(
            "asset.fx.usdils",
            "BOI",
            timestamp.date(),
            timestamp,
            None,
            datetime(2026, 1, 1, tzinfo=UTC),
            "ILS",
            close,
            close,
            close,
            close,
            "0",
            None,
            None,
            "il.boi.sdmx.exr",
            "sha256:" + "a" * 64,
            "fixture/1",
        )

    result = outcome_metrics(
        (bar(0, "3.6"), bar(1, "3.7"), bar(2, "3.5")), T0, T0 + timedelta(days=2)
    )
    assert Decimal(result["raw_return"]) == Decimal("3.5") / Decimal("3.6") - 1
    with pytest.raises(IntegrityViolation):
        outcome_metrics((bar(0, "3.6"),), T0, T0 + timedelta(days=2))


@pytest.mark.unit
def test_case_reports_are_reproducible_and_do_not_claim_results(tmp_path) -> None:
    cases = curated_real_cases()
    commitments = build_commitments(cases, datetime(2026, 8, 12, tzinfo=UTC))
    root = write_real_replay_reports(tmp_path, cases, commitments)
    assert len(tuple(root.glob("*.md"))) == len(cases)
    aggregate = (root / "aggregate.json").read_text(encoding="utf-8")
    assert '"statistical_claim": false' in aggregate
    assert '"supported": 0' in aggregate


@pytest.mark.unit
def test_selection_audit_and_timestamp_validation() -> None:
    with pytest.raises(ValidationError):
        CaseSelectionAudit("", "", T0, True, EvaluationSet.PROTECTED)
