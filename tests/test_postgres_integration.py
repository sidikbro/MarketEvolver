"""Optional destructive integration checks for a dedicated PostgreSQL test database."""

import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from market_evolver.knowledge.repositories import SqlKnowledgeGraph
from market_evolver.knowledge.schemas import EntityVersion, KnowledgeEntityType

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


def test_migrations_reach_0005(migrated_engine) -> None:
    with migrated_engine.connect() as connection:
        assert connection.scalar(text("SELECT version_num FROM alembic_version")) == "0005"


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
