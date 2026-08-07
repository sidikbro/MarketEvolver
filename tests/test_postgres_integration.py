"""Optional destructive integration checks for a dedicated PostgreSQL test database."""

import hashlib
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from market_evolver.government.repositories import SqlGovernmentRepository
from market_evolver.government.schemas import (
    GovernmentAction,
    GovernmentActionStatus,
    GovernmentActionType,
)
from market_evolver.knowledge.repositories import SqlKnowledgeGraph
from market_evolver.knowledge.schemas import EntityVersion, KnowledgeEntityType
from market_evolver.knowledge.seed import seed_knowledge_graph
from market_evolver.news.extraction import content_fingerprint
from market_evolver.news.repositories import SqlNewsRepository
from market_evolver.news.schemas import (
    EvidenceSecurityClass,
    ExtractionStatus,
    NewsItem,
)
from market_evolver.schemas import Evidence, Source, SourceKind, TrustLevel
from market_evolver.sources.registry import TrustClass
from market_evolver.storage.models import ArtifactModel
from market_evolver.storage.repositories import SqlEvidenceRepository, SqlSourceRepository

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


def test_migrations_reach_0006(migrated_engine) -> None:
    with migrated_engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0006"


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
