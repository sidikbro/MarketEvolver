"""persistent evidence store

Revision ID: 0001
Revises:
"""

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "artifacts",
        sa.Column("sha256", sa.String(64), primary_key=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("relative_path", sa.String(512), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "sources",
        sa.Column("provenance_id", sa.String(96), primary_key=True),
        sa.Column("uri", sa.String(2048), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("publisher", sa.String(512), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True)),
        sa.Column("trust", sa.String(32), nullable=False),
        sa.Column("content_digest", sa.String(80), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("artifact_sha256", sa.String(64), sa.ForeignKey("artifacts.sha256")),
    )
    op.create_table(
        "evidence",
        sa.Column("provenance_id", sa.String(96), primary_key=True),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("excerpt_digest", sa.String(80), nullable=False),
        sa.Column("embedding", Vector(1536)),
    )
    op.create_table(
        "events",
        sa.Column("provenance_id", sa.String(96), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("known_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
    )
    op.create_table(
        "hypotheses",
        sa.Column("provenance_id", sa.String(96), primary_key=True),
        sa.Column("statement", sa.Text(), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("event_ids", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
    )
    op.create_table(
        "research_decisions",
        sa.Column("provenance_id", sa.String(96), primary_key=True),
        sa.Column("recommendation", sa.String(32), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("knowledge_cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hypothesis_ids", sa.JSON(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
    )
    op.create_index("ix_sources_observed_at", "sources", ["observed_at"])
    op.create_index("ix_evidence_observed_at", "evidence", ["observed_at"])
    op.create_index("ix_events_known_at", "events", ["known_at"])
    op.create_index("ix_hypotheses_as_of", "hypotheses", ["as_of"])
    op.create_index(
        "ix_research_decisions_knowledge_cutoff",
        "research_decisions",
        ["knowledge_cutoff"],
    )


def downgrade() -> None:
    op.drop_table("research_decisions")
    op.drop_table("hypotheses")
    op.drop_table("events")
    op.drop_table("evidence")
    op.drop_table("sources")
    op.drop_table("artifacts")
