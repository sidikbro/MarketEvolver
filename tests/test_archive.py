from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from market_evolver.archive.repository import SqlArchiveRepository
from market_evolver.archive.schemas import (
    ArchiveConfidence,
    ArchiveGap,
    VintageClassification,
)
from market_evolver.archive.service import (
    ARCHIVE_JOBS,
    ArchivePayload,
    ArchiveService,
    archive_storage_projection,
    evaluate_replay_upgrade,
    replay_backfill_report,
)
from market_evolver.errors import GovernanceViolation, ValidationError
from market_evolver.replay.real import curated_real_cases
from market_evolver.storage.models import Base

T0 = datetime(2025, 1, 1, 10, tzinfo=UTC)


@pytest.fixture
def archive(tmp_path):
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield ArchiveService(session, tmp_path), session
    session.close()
    engine.dispose()


def payload(
    content: bytes = b"v1",
    *,
    classification: VintageClassification = VintageClassification.OBSERVED_LIVE_AT_TIME,
    published_at: datetime | None = None,
    proof=(),
    revision_of: str | None = None,
) -> ArchivePayload:
    return ArchivePayload(
        "il.boi",
        "https://www.boi.org.il/archive/item",
        content,
        "application/json",
        T0,
        published_at,
        T0,
        "Asia/Jerusalem",
        (("date", "Wed, 01 Jan 2025 10:00:00 GMT"),),
        classification,
        "direct_live_observation"
        if classification is VintageClassification.OBSERVED_LIVE_AT_TIME
        else "boi_official_archive",
        ArchiveConfidence.HIGH,
        proof,
        revision_of,
    )


@pytest.mark.unit
def test_live_observed_vintage_and_duplicate_are_immutable(archive) -> None:
    service, session = archive
    first, inserted = service.archive(payload())
    duplicate, inserted_again = service.archive(payload())
    assert inserted and not inserted_again
    assert first.vintage_id == duplicate.vintage_id
    assert first.replay_eligible
    assert SqlArchiveRepository(session).coverage()[0].bytes_archived == 2


@pytest.mark.unit
def test_official_archive_requires_real_release_proof(archive) -> None:
    service, _ = archive
    official, inserted = service.archive(
        payload(
            classification=VintageClassification.OFFICIAL_ARCHIVED_VINTAGE,
            published_at=T0 - timedelta(days=10),
            proof=(("official_archive_proof", "accession-or-release-version"),),
        )
    )
    assert inserted and official.valid_from == T0 - timedelta(days=10)
    with pytest.raises(GovernanceViolation):
        service.archive(
            payload(
                b"unproven",
                classification=VintageClassification.OFFICIAL_ARCHIVED_VINTAGE,
                published_at=T0 - timedelta(days=10),
            )
        )


@pytest.mark.unit
def test_present_day_copy_never_claims_historical_availability(archive) -> None:
    service, _ = archive
    current, _ = service.archive(
        payload(
            classification=VintageClassification.RETROSPECTIVELY_AVAILABLE_CURRENT_COPY,
            published_at=T0 - timedelta(days=365),
        )
    )
    assert not current.replay_eligible
    assert current.valid_from == current.first_observed_at


@pytest.mark.unit
def test_revision_chain_and_gap_coverage(archive) -> None:
    service, session = archive
    first, _ = service.archive(payload())
    second_payload = payload(b"v2", revision_of=first.vintage_id)
    second_payload = replace(second_payload, retrieved_at=T0 + timedelta(days=1))
    second, _ = service.archive(second_payload)
    assert second.revision_of == first.vintage_id
    gap = ArchiveGap("il.boi", T0, T0 + timedelta(hours=1), "expected snapshot missing")
    SqlArchiveRepository(session).add_gap(gap)
    session.commit()
    coverage = SqlArchiveRepository(session).coverage()[0]
    assert coverage.revisions == 1 and coverage.gaps == 1


@pytest.mark.unit
def test_replay_upgrade_requires_archive_proof(archive) -> None:
    service, _ = archive
    case = next(case for case in curated_real_cases() if case.title == "Teva 2023 annual filing")
    missing = evaluate_replay_upgrade(case, ())
    assert not missing.eligible and missing.required_new_case_version == 2
    item = case.source_manifest[0]
    vintage, _ = service.archive(
        ArchivePayload(
            "us.sec.edgar",
            item.source_uri,
            b"accession metadata",
            "application/json",
            T0,
            T0 - timedelta(days=300),
            T0,
            "America/New_York",
            (),
            VintageClassification.OFFICIAL_ARCHIVED_VINTAGE,
            "sec_accession_archive",
            ArchiveConfidence.HIGH,
            (("official_archive_proof", "accession:fixture"),),
        )
    )
    decision = evaluate_replay_upgrade(case, (vintage,))
    assert decision.eligible and decision.supporting_vintage_ids == (vintage.vintage_id,)


@pytest.mark.unit
def test_timezone_gap_jobs_projection_and_backfill_report() -> None:
    with pytest.raises(ValidationError):
        ArchiveGap("il.boi", datetime(2025, 1, 1), T0, "naive")  # noqa: DTZ001
    assert {job.family for job in ARCHIVE_JOBS} >= {"boi", "news", "sec", "cbs"}
    projections = archive_storage_projection(100)
    assert len(projections) == 4 and projections[-1]["scenario"] == "media_enabled_hypothetical"
    report = replay_backfill_report(curated_real_cases())
    assert len(report) == 6
