"""Optional destructive integration checks for a dedicated PostgreSQL test database."""

import hashlib
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from market_evolver.company.repositories import SqlCompanyRepository
from market_evolver.company.schemas import (
    CompanyStatus,
    CompanyVersion,
    Filing,
    FilingType,
    FundamentalObservation,
    FundamentalType,
    Listing,
    RestatementStatus,
)
from market_evolver.company.seed import seed_companies
from market_evolver.config import TelegramSourceConfig
from market_evolver.geopolitical.extraction import extract_candidate
from market_evolver.geopolitical.repository import SqlGeopoliticalRepository
from market_evolver.geopolitical.schemas import (
    ConfirmationState,
    CorroborationKind,
    GeopoliticalCorroboration,
    GeopoliticalEvent,
    GeopoliticalEventType,
    GeopoliticalStatus,
    TransmissionHorizon,
    TransmissionPath,
)
from market_evolver.government.repositories import SqlGovernmentRepository
from market_evolver.government.schemas import (
    GovernmentAction,
    GovernmentActionStatus,
    GovernmentActionType,
)
from market_evolver.knowledge.repositories import SqlKnowledgeGraph
from market_evolver.knowledge.schemas import EntityVersion, KnowledgeEntityType
from market_evolver.knowledge.seed import seed_knowledge_graph
from market_evolver.macro.repository import SqlMacroRepository
from market_evolver.macro.schemas import MacroCategory, MacroObservation, SeasonalAdjustment
from market_evolver.market.schemas import AdjustmentStatus, MarketObservation, ObservationType
from market_evolver.market.seed import seed_assets
from market_evolver.market.store import MarketDataStore
from market_evolver.news.extraction import content_fingerprint
from market_evolver.news.repositories import SqlNewsRepository
from market_evolver.news.schemas import (
    EvidenceSecurityClass,
    ExtractionStatus,
    NewsItem,
)
from market_evolver.replay.engine import ReplayEngine
from market_evolver.replay.repositories import SqlReplayRepository
from market_evolver.replay.schemas import (
    ReplayCase,
    ReplayCaseType,
    ResearchCommitment,
    ResearchMode,
)
from market_evolver.research.providers import MockProvider
from market_evolver.research.repositories import SqlResearchRepository
from market_evolver.research.schemas import ContextItem, ResearchContext
from market_evolver.research.service import ResearchService
from market_evolver.schemas import Evidence, Source, SourceKind, TrustLevel
from market_evolver.social.repository import SqlSocialRepository
from market_evolver.social.schemas import (
    Accessibility,
    SocialSource,
    SocialSourceType,
    VerificationState,
)
from market_evolver.sources.registry import TrustClass
from market_evolver.storage.artifacts import LocalArtifactStore
from market_evolver.storage.models import ArtifactModel, EvidenceModel, TelegramReceiptModel
from market_evolver.storage.repositories import SqlEvidenceRepository, SqlSourceRepository
from market_evolver.telegram.runner import TelegramRunner
from market_evolver.telegram.schemas import TelegramMessage

pytestmark = pytest.mark.postgres


@pytest.fixture(scope="module")
def postgres_url() -> str:
    value = os.environ.get("MARKET_EVOLVER_TEST_POSTGRES_URL")
    if value is None:
        pytest.skip("set MARKET_EVOLVER_TEST_POSTGRES_URL for PostgreSQL integration tests")
    if not value.startswith(("postgresql://", "postgresql+psycopg://")) or "_test" not in value:
        pytest.fail("integration URL must be PostgreSQL and name a dedicated *_test database")
    return value


@pytest.fixture(scope="module")
def migrated_engine(postgres_url: str):
    previous = os.environ.get("MARKET_EVOLVER_DATABASE_URL")
    os.environ["MARKET_EVOLVER_DATABASE_URL"] = postgres_url
    command.upgrade(Config("alembic.ini"), "head")
    engine = create_engine(postgres_url)
    yield engine
    engine.dispose()
    if previous is None:
        os.environ.pop("MARKET_EVOLVER_DATABASE_URL", None)
    else:
        os.environ["MARKET_EVOLVER_DATABASE_URL"] = previous


def test_migrations_reach_0013(migrated_engine) -> None:
    with migrated_engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0013"


def test_telegram_revision_cutoff_and_append_only(migrated_engine, tmp_path: Path) -> None:
    token = uuid4().hex
    source_config = TelegramSourceConfig(
        f"telegram.integration.{token}",
        f"public_{token}",
        "public_channel",
        ("en",),
        ("integration",),
        True,
        None,
        10,
        "metadata_only",
    )
    observed = datetime.now(UTC) - timedelta(minutes=3)

    class StaticTelegramClient:
        messages: tuple[TelegramMessage, ...] = ()

        def validate_public(self, identifier: str) -> bool:
            return True

        def fetch(self, identifier, *, limit, since, after_id):
            return self.messages

    client = StaticTelegramClient()
    with Session(migrated_engine) as session:
        runner = TelegramRunner(
            session, LocalArtifactStore(tmp_path), client, sleeper=lambda _: None
        )
        client.messages = (TelegramMessage(1, observed, "original"),)
        runner.run(source_config, limit=10, since=None, observed_at=observed)
        client.messages = (
            TelegramMessage(1, observed, "edited", edited_at=observed + timedelta(minutes=1)),
        )
        runner.run(
            source_config,
            limit=10,
            since=None,
            observed_at=observed + timedelta(minutes=1),
        )
        client.messages = (
            TelegramMessage(1, observed, "", deleted=True),
            TelegramMessage(
                2,
                observed + timedelta(minutes=1),
                "forwarded",
                forward_source="@public_origin",
                forward_message_id=9,
            ),
        )
        runner.run(
            source_config,
            limit=10,
            since=None,
            observed_at=observed + timedelta(minutes=2),
        )
        repo = SqlSocialRepository(session)
        assert repo.posts_visible_at(observed)[0].original_text == "original"
        assert repo.posts_visible_at(observed + timedelta(minutes=1))[0].original_text == "edited"
        after_deletion = repo.posts_visible_at(observed + timedelta(minutes=2))
        assert next(post for post in after_deletion if post.native_post_id == "1").deleted_at
        assert (
            session.scalar(
                text(
                    "SELECT count(*) FROM telegram_receipts "
                    "WHERE allowlist_source_id = :source_id AND forward_source IS NOT NULL"
                ),
                {"source_id": source_config.source_id},
            )
            == 1
        )
        receipt_id = session.scalar(
            text(
                "SELECT receipt_id FROM telegram_receipts "
                "WHERE allowlist_source_id = :source_id LIMIT 1"
            ),
            {"source_id": source_config.source_id},
        )
        with pytest.raises(DBAPIError):
            session.execute(
                text("UPDATE telegram_receipts SET payload_bytes = 0 WHERE receipt_id = :id"),
                {"id": receipt_id},
            )
            session.flush()
        session.rollback()
        assert session.get(TelegramReceiptModel, receipt_id) is not None


def test_append_only_update_and_delete_are_rejected(migrated_engine) -> None:
    digest = uuid4().hex + uuid4().hex
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO artifacts
                    (sha256, size_bytes, mime_type, relative_path, created_at)
                VALUES (:digest, 1, 'text/plain', :path, :created)
                """
            ),
            {"digest": digest, "path": f"integration/{digest}", "created": datetime.now(UTC)},
        )
    with pytest.raises(DBAPIError), migrated_engine.begin() as connection:
        connection.execute(
            text("UPDATE artifacts SET size_bytes = 2 WHERE sha256 = :digest"),
            {"digest": digest},
        )
    with pytest.raises(DBAPIError), migrated_engine.begin() as connection:
        connection.execute(text("DELETE FROM artifacts WHERE sha256 = :digest"), {"digest": digest})


def test_transaction_rollback_and_point_in_time_query(migrated_engine) -> None:
    rolled_back = uuid4().hex + uuid4().hex
    with migrated_engine.connect() as connection:
        transaction = connection.begin()
        connection.execute(
            text(
                """
                INSERT INTO artifacts
                    (sha256, size_bytes, mime_type, relative_path, created_at)
                VALUES (:digest, 1, 'text/plain', :path, :created)
                """
            ),
            {
                "digest": rolled_back,
                "path": f"integration/{rolled_back}",
                "created": datetime.now(UTC),
            },
        )
        transaction.rollback()
        assert (
            connection.scalar(
                text("SELECT count(*) FROM artifacts WHERE sha256 = :digest"),
                {"digest": rolled_back},
            )
            == 0
        )

    now = datetime.now(UTC)
    entity_id = f"integration.entity.{uuid4().hex}"
    with Session(migrated_engine) as session:
        graph = SqlKnowledgeGraph(session)
        graph.add_entity(
            EntityVersion(
                entity_id=entity_id,
                canonical_name="Integration entity",
                aliases=("Integration entity",),
                hebrew_name=None,
                english_name="Integration entity",
                entity_type=KnowledgeEntityType.COMPANY,
                geography=("IL",),
                identifiers=(),
                active_from=now - timedelta(days=1),
                active_until=None,
                observed_at=now,
                provenance=("postgres-integration-test",),
                confidence=1.0,
                version=1,
            )
        )
        session.commit()
        assert graph.get_entity_at(entity_id, now - timedelta(seconds=1)) is None
        assert graph.get_entity_at(entity_id, now + timedelta(seconds=1)) is not None


def test_news_and_government_cutoff_replay(migrated_engine) -> None:
    observed = datetime.now(UTC)
    token = uuid4().hex
    body = f"Bank of Israel policy integration {token}"
    title = f"Policy integration {token}"
    digest = hashlib.sha256(f"{title}\n{body}".encode()).hexdigest()
    with Session(migrated_engine) as session:
        seed_knowledge_graph(session)
        session.add(
            ArtifactModel(
                sha256=digest,
                size_bytes=len(body.encode()),
                mime_type="text/plain",
                relative_path=f"integration/{digest}",
                created_at=observed,
            )
        )
        source = Source(
            uri=f"https://example.test/policy/{token}",
            kind=SourceKind.GOVERNMENT,
            publisher="Integration authority",
            published_at=observed,
            observed_at=observed,
            ingested_at=observed,
            trust=TrustLevel.AUTHORITATIVE,
            content_digest=f"sha256:{digest}",
            mime_type="text/plain",
        )
        SqlSourceRepository(session).add(source)
        evidence = Evidence(
            claim=title,
            source_ids=(source.provenance_id,),
            observed_at=observed,
            excerpt_digest=f"sha256:{digest}",
        )
        SqlEvidenceRepository(session).add(evidence)
        news = NewsItem(
            source_id="integration.authority",
            title=title,
            body=body,
            language="en",
            published_at=observed,
            first_observed_at=observed,
            canonical_uri=f"https://example.test/policy/{token}",
            content_hash=f"sha256:{digest}",
            raw_artifact_sha256=digest,
            parser_version="integration/1",
            trust_class=TrustClass.OFFICIAL,
            evidence_security_class=EvidenceSecurityClass.TRUSTED_UNSTRUCTURED,
            evidence_id=evidence.provenance_id,
            extraction_status=ExtractionStatus.EXTRACTED,
            provenance=(source.provenance_id, evidence.provenance_id),
            normalized_fingerprint=content_fingerprint(title, body),
        )
        SqlNewsRepository(session).add_news(news)
        action = GovernmentAction(
            jurisdiction="IL",
            issuing_body="institution.boi",
            action_type=GovernmentActionType.MONETARY_POLICY,
            title=title,
            description_reference=news.news_id,
            status=GovernmentActionStatus.PUBLISHED,
            announced_at=observed,
            published_at=observed,
            effective_at=None,
            first_observed_at=observed,
            expires_at=None,
            supersedes_action_id=None,
            source_evidence_ids=(evidence.provenance_id,),
            affected_entities=("institution.boi",),
            affected_sectors=("sector.banks",),
            candidate_mechanisms=("financing_cost",),
            confidence=1.0,
            provenance=(evidence.provenance_id,),
            version=1,
        )
        SqlGovernmentRepository(session).add_action(action)
        session.commit()
        before = observed - timedelta(microseconds=1)
        after = observed + timedelta(microseconds=1)
        assert SqlNewsRepository(session).get_news_visible_at(before) == []
        assert SqlNewsRepository(session).get_news_visible_at(after) == [news]
        assert SqlGovernmentRepository(session).get_actions_visible_at(before) == []
        assert SqlGovernmentRepository(session).get_actions_visible_at(after) == [action]


def test_company_history_restatement_and_append_only(migrated_engine) -> None:
    observed = datetime.now(UTC)
    revised_at = observed + timedelta(seconds=1)
    token = uuid4().hex
    company = CompanyVersion(
        company_id=f"integration.company.{token}",
        legal_name="PostgreSQL Integration Company Ltd.",
        hebrew_name=None,
        english_name="PostgreSQL Integration Company Ltd.",
        aliases=(f"PG-{token}",),
        listings=(Listing(f"PG{token[:4]}", "XTAE", observed),),
        isin=None,
        sector_id="sector.technology",
        industry_id=None,
        domicile="IL",
        status=CompanyStatus.ACTIVE,
        dual_listed=False,
        identifiers=(("TEST", token),),
        provenance=("postgres-integration-test",),
        valid_from=observed,
        valid_until=None,
        observed_at=observed,
        version=1,
    )
    digest1 = hashlib.sha256(f"filing-{token}".encode()).hexdigest()
    digest2 = hashlib.sha256(f"restatement-{token}".encode()).hexdigest()
    with Session(migrated_engine) as session:
        repository = SqlCompanyRepository(session)
        repository.add_company(company)
        evidence_ids: list[str] = []
        for at, digest in ((observed, digest1), (revised_at, digest2)):
            session.add(
                ArtifactModel(
                    sha256=digest,
                    size_bytes=1,
                    mime_type="application/json",
                    relative_path=f"integration/{digest}",
                    created_at=at,
                )
            )
            source = Source(
                uri=f"https://example.test/filing/{digest}",
                kind=SourceKind.RESEARCH,
                publisher="Integration filing authority",
                published_at=at,
                observed_at=at,
                ingested_at=at,
                trust=TrustLevel.AUTHORITATIVE,
                content_digest=f"sha256:{digest}",
                mime_type="application/json",
            )
            SqlSourceRepository(session).add(source)
            evidence = Evidence(
                claim=f"Integration filing {digest}",
                source_ids=(source.provenance_id,),
                observed_at=at,
                excerpt_digest=f"sha256:{digest}",
            )
            SqlEvidenceRepository(session).add(evidence)
            evidence_ids.append(evidence.provenance_id)
        filing = Filing(
            company_id=company.company_id,
            filing_type=FilingType.ANNUAL_REPORT,
            form_type="20-F",
            accession_number=f"{token}-original",
            source_uri=f"https://example.test/filing/{digest1}",
            filed_at=observed,
            first_observed_at=observed,
            fiscal_period_start=observed.date() - timedelta(days=365),
            fiscal_period_end=observed.date() - timedelta(days=1),
            raw_artifact_sha256=digest1,
            source_evidence_ids=(evidence_ids[0],),
            parser_version="integration/1",
        )
        repository.add_filing(filing)
        original = FundamentalObservation(
            company_id=company.company_id,
            filing_id=filing.filing_id,
            metric=FundamentalType.REVENUE,
            value="100",
            currency="ILS",
            unit="ILS million",
            fiscal_period_start=filing.fiscal_period_start,
            fiscal_period_end=filing.fiscal_period_end,
            published_at=observed,
            first_observed_at=observed,
            source_evidence_ids=(evidence_ids[0],),
            parser_version="integration/1",
        )
        repository.add_fundamental(original)
        revised_filing = Filing(
            company_id=company.company_id,
            filing_type=FilingType.ANNUAL_REPORT,
            form_type="20-F/A",
            accession_number=f"{token}-amended",
            source_uri=f"https://example.test/filing/{digest2}",
            filed_at=revised_at,
            first_observed_at=revised_at,
            fiscal_period_start=filing.fiscal_period_start,
            fiscal_period_end=filing.fiscal_period_end,
            raw_artifact_sha256=digest2,
            source_evidence_ids=(evidence_ids[1],),
            parser_version="integration/1",
            restates_filing_id=filing.filing_id,
        )
        repository.add_filing(revised_filing)
        restated = FundamentalObservation(
            company_id=company.company_id,
            filing_id=revised_filing.filing_id,
            metric=FundamentalType.REVENUE,
            value="110",
            currency="ILS",
            unit="ILS million",
            fiscal_period_start=filing.fiscal_period_start,
            fiscal_period_end=filing.fiscal_period_end,
            published_at=revised_at,
            first_observed_at=revised_at,
            source_evidence_ids=(evidence_ids[1],),
            parser_version="integration/1",
            restatement_status=RestatementStatus.RESTATED,
            restates_observation_id=original.observation_id,
        )
        repository.add_fundamental(restated)
        session.commit()
        assert (
            repository.get_company_at(company.company_id, observed - timedelta(microseconds=1))
            is None
        )
        assert repository.get_company_at(company.company_id, observed) == company
        assert repository.get_fundamentals(company.company_id, observed) == [original]
        assert repository.get_fundamentals(company.company_id, revised_at) == [restated]

    with pytest.raises(DBAPIError), migrated_engine.begin() as connection:
        connection.execute(
            text("UPDATE companies SET legal_name = 'mutated' WHERE company_version_id = :id"),
            {"id": company.company_version_id},
        )


def test_research_context_trace_reviewer_replay_and_append_only(migrated_engine) -> None:
    now = datetime.now(UTC)
    cutoff = now - timedelta(seconds=1)
    token = uuid4().hex
    evidence_id = f"integration-evidence:{token}"
    context = ResearchContext(
        cutoff,
        f"integration.company.{token}",
        (
            ContextItem(
                "evidence",
                evidence_id,
                cutoff,
                "Integration evidence reports a measurable observation.",
                (evidence_id,),
            ),
        ),
    )
    provider = MockProvider(clock=lambda: now)
    with Session(migrated_engine) as session:
        service = ResearchService(session, provider)
        hypothesis, trace = service.hypothesize(context)
        review = service.review(hypothesis, context)
        repository = SqlResearchRepository(session)
        assert repository.get_context(context.research_context_id) == context
        assert repository.get_hypothesis(hypothesis.hypothesis_id, cutoff) is None
        assert repository.get_hypothesis(hypothesis.hypothesis_id, now) == hypothesis
        assert repository.get_trace(trace.trace_id) == trace
        assert review.hypothesis_id == hypothesis.hypothesis_id

    with pytest.raises(DBAPIError), migrated_engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE research_contexts SET subject_id = 'mutated' "
                "WHERE research_context_id = :id"
            ),
            {"id": context.research_context_id},
        )


def test_market_parquet_replay_cutoff_and_commitment_append_only(migrated_engine) -> None:
    now = datetime.now(UTC)
    token = uuid4().hex
    with tempfile.TemporaryDirectory() as directory, Session(migrated_engine) as session:
        seed_knowledge_graph(session)
        seed_companies(session)
        store = MarketDataStore(session, Path(directory))
        seed_assets(session, store)
        observation = MarketObservation(
            "asset.xtae.nice",
            "XTAE",
            ObservationType.OHLCV,
            now - timedelta(hours=2),
            now - timedelta(hours=1),
            "integration.market",
            AdjustmentStatus.RAW,
            "ILS",
            "integration/1",
            (f"integration:{token}",),
            "99",
            "101",
            "98",
            "100",
            "1000",
        )
        store.write_observations((observation,), dataset_version=f"integration/{token}")
        assert (
            store.get_market_data(
                observation.asset_id,
                observation.market_timestamp,
                observation.market_timestamp,
                observation.observed_at - timedelta(microseconds=1),
            )
            == []
        )
        assert store.get_market_data(
            observation.asset_id,
            observation.market_timestamp,
            observation.market_timestamp,
            observation.observed_at,
        ) == [observation]
        case = ReplayCase(
            ReplayCaseType.QUIET,
            ("company.nice",),
            (observation.asset_id,),
            observation.observed_at,
            "1 day",
            f"manifest:{token}",
            None,
            "research-hypothesis/v1",
            "forward-market-outcome/1",
            f"integration/{token}",
            now,
        )
        repository = SqlReplayRepository(session)
        repository.add_case(case)
        commitment = ResearchCommitment(
            case.case_id,
            case.cutoff,
            f"context:{token}",
            f"hypothesis:{token}",
            case.horizon,
            "Observe a measurable outcome.",
            "The outcome is absent.",
            0.5,
            "reviewed",
            ResearchMode.NO_INFORMATION,
            now,
        )
        ReplayEngine(session, store).commit(commitment)
        commitment_id = commitment.commitment_id

    with pytest.raises(DBAPIError), migrated_engine.begin() as connection:
        connection.execute(
            text("UPDATE replay_commitments SET confidence = 0.9 WHERE commitment_id = :id"),
            {"id": commitment_id},
        )


def test_macro_revision_cutoff_and_database_append_only(migrated_engine) -> None:
    now = datetime.now(UTC)
    token = uuid4().hex
    with Session(migrated_engine) as session:
        repository = SqlMacroRepository(session)
        original = MacroObservation(
            f"integration.cpi.{token}",
            "il.cbs",
            "IL",
            MacroCategory.INFLATION,
            "2025-01",
            "100",
            "index",
            now - timedelta(hours=3),
            now - timedelta(hours=2),
            None,
            SeasonalAdjustment.UNADJUSTED,
            (f"source:{token}:1",),
            "integration/1",
            "Consumer Price Index",
            "מדד המחירים לצרכן",
        )
        revised = MacroObservation(
            original.series_id,
            "il.cbs",
            "IL",
            MacroCategory.INFLATION,
            "2025-01",
            "101",
            "index",
            now - timedelta(hours=1),
            now,
            original.observation_id,
            SeasonalAdjustment.UNADJUSTED,
            (f"source:{token}:2",),
            "integration/1",
            "Consumer Price Index",
            "מדד המחירים לצרכן",
        )
        repository.add_observation(original)
        repository.add_observation(revised)
        session.commit()
        assert (
            repository.observations_visible_at(original.series_id, now - timedelta(hours=1))[0]
            == original
        )
        assert repository.observations_visible_at(original.series_id, now)[0] == revised
        observation_id = original.observation_id

    with pytest.raises(DBAPIError), migrated_engine.begin() as connection:
        connection.execute(
            text("UPDATE macro_observations SET value = '999' WHERE observation_id = :id"),
            {"id": observation_id},
        )


def test_geopolitical_confirmation_contradiction_paths_and_append_only(migrated_engine) -> None:
    now = datetime.now(UTC)
    t1 = now - timedelta(hours=2)
    t2 = now - timedelta(hours=1)
    token = uuid4().hex
    rumor_id = f"integration-geo-rumor:{token}"
    official_id = f"integration-geo-official:{token}"
    with Session(migrated_engine) as session:
        for evidence_id, observed, claim in (
            (rumor_id, t1, "Israel airport closed"),
            (official_id, t2, "Official confirmation of closure"),
        ):
            session.add(
                EvidenceModel(
                    provenance_id=evidence_id,
                    claim=claim,
                    source_ids=[f"source:{evidence_id}"],
                    observed_at=observed,
                    excerpt_digest=f"sha256:{'b' * 64}",
                    embedding=None,
                )
            )
        session.flush()
        repository = SqlGeopoliticalRepository(session)
        rumor = GeopoliticalEvent(
            GeopoliticalEventType.AIRSPACE_DISRUPTION,
            ("Israel",),
            ("Israel",),
            (rumor_id,),
            GeopoliticalStatus.REPORTED,
            t1,
            t1,
            t1,
            None,
            0.5,
            ConfirmationState.UNVERIFIED,
            None,
            (rumor_id,),
            1,
        )
        confirmed = GeopoliticalEvent(
            rumor.event_type,
            rumor.geography,
            rumor.actors,
            (official_id,),
            GeopoliticalStatus.ONGOING,
            t1,
            t1,
            t2,
            None,
            0.9,
            ConfirmationState.CONFIRMED,
            rumor.event_id,
            (official_id,),
            2,
        )
        repository.add_event(rumor)
        repository.add_event(confirmed)
        path = TransmissionPath(
            confirmed.event_id,
            ("airline_capacity", "tourism_demand"),
            ("country.israel",),
            TransmissionHorizon.IMMEDIATE,
            0.8,
            "Closure can constrain airline capacity.",
            (official_id,),
            t2,
        )
        repository.add_path(path)
        candidate = extract_candidate("Israel airport closed", rumor_id, t1)
        repository.add_candidate(candidate)
        contradiction = GeopoliticalCorroboration(
            candidate.candidate_id,
            (rumor_id, official_id),
            ("news.integration", "official.integration"),
            CorroborationKind.UNRESOLVED_CONFLICT,
            t2,
            "Official and news accounts conflict.",
            0.5,
        )
        repository.add_corroboration(contradiction)
        session.commit()
        assert repository.events_visible_at(t1) == (rumor,)
        assert repository.events_visible_at(t2) == (confirmed,)
        assert repository.corroborations_visible_at(t1) == ()
        assert repository.corroborations_visible_at(t2) == (contradiction,)
        assert repository.paths_visible_at(t2, event_ids=(confirmed.event_id,)) == (path,)
        event_id = rumor.event_id

    with pytest.raises(DBAPIError), migrated_engine.begin() as connection:
        connection.execute(
            text("UPDATE geopolitical_events SET confidence = 0 WHERE event_id = :id"),
            {"id": event_id},
        )


def test_social_source_append_only(migrated_engine) -> None:
    now = datetime.now(UTC)
    token = uuid4().hex
    with Session(migrated_engine) as session:
        source = SocialSource(
            "fixture",
            token,
            "Public fixture",
            None,
            ("en",),
            ("IL",),
            SocialSourceType.PUBLIC_CHANNEL,
            now,
            now,
            VerificationState.UNVERIFIED,
            Accessibility.PUBLIC,
            (f"fixture:{token}",),
        )
        SqlSocialRepository(session).add_source(source)
        session.commit()
        source_id = source.source_id
    with pytest.raises(DBAPIError), migrated_engine.begin() as connection:
        connection.execute(
            text("UPDATE social_sources SET display_name='mutated' WHERE source_id=:id"),
            {"id": source_id},
        )
