"""News Lab and trusted/untrusted evidence separation

Revision ID: 0005
Revises: 0004
"""

import sqlalchemy as sa
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

_TABLES = (
    "news_items",
    "news_entities",
    "news_event_candidates",
    "news_candidate_reviews",
    "news_corroborations",
    "evidence_contradictions",
)


def upgrade() -> None:
    op.create_table(
        "news_items",
        sa.Column("news_id", sa.String(96), primary_key=True),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column("last_modified_at", sa.DateTime(timezone=True)),
        sa.Column("canonical_uri", sa.String(2048), nullable=False),
        sa.Column("content_hash", sa.String(80), nullable=False),
        sa.Column(
            "raw_artifact_sha256",
            sa.String(64),
            sa.ForeignKey("artifacts.sha256"),
            nullable=False,
        ),
        sa.Column("parser_version", sa.String(64), nullable=False),
        sa.Column("trust_class", sa.String(32), nullable=False),
        sa.Column("evidence_security_class", sa.String(32), nullable=False),
        sa.Column(
            "evidence_id",
            sa.String(96),
            sa.ForeignKey("evidence.provenance_id"),
            nullable=False,
        ),
        sa.Column("revision_of", sa.String(96)),
        sa.Column("extraction_status", sa.String(24), nullable=False),
        sa.Column("quarantine_reason", sa.String(1024)),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("duplicate_kind", sa.String(24), nullable=False),
        sa.Column("normalized_fingerprint", sa.String(64), nullable=False),
    )
    for column in (
        "source_id",
        "first_observed_at",
        "canonical_uri",
        "content_hash",
        "revision_of",
        "normalized_fingerprint",
    ):
        op.create_index(f"ix_news_items_{column}", "news_items", [column])
    op.create_table(
        "news_entities",
        sa.Column("news_id", sa.String(96), sa.ForeignKey("news_items.news_id"), primary_key=True),
        sa.Column("entity_id", sa.String(128), primary_key=True),
        sa.Column("supporting_span", sa.String(512), primary_key=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "news_event_candidates",
        sa.Column("candidate_id", sa.String(96), primary_key=True),
        sa.Column("news_id", sa.String(96), sa.ForeignKey("news_items.news_id"), nullable=False),
        sa.Column("extracted_entities", sa.JSON(), nullable=False),
        sa.Column("possible_event_type", sa.String(128), nullable=False),
        sa.Column("extraction_method", sa.String(128), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("supporting_spans", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_state", sa.String(24), nullable=False),
    )
    op.create_index("ix_news_event_candidates_created_at", "news_event_candidates", ["created_at"])
    op.create_table(
        "news_candidate_reviews",
        sa.Column("review_id", sa.String(96), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.String(96),
            sa.ForeignKey("news_event_candidates.candidate_id"),
            nullable=False,
        ),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewer", sa.String(256), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_news_candidate_reviews_candidate_id",
        "news_candidate_reviews",
        ["candidate_id"],
    )
    op.create_index(
        "ix_news_candidate_reviews_reviewed_at",
        "news_candidate_reviews",
        ["reviewed_at"],
    )
    op.create_table(
        "news_corroborations",
        sa.Column("corroboration_id", sa.String(96), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.String(96),
            sa.ForeignKey("news_event_candidates.candidate_id"),
            nullable=False,
        ),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("independence_assumptions", sa.JSON(), nullable=False),
        sa.Column("timestamp_ordering", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("contradictions", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_news_corroborations_candidate_id", "news_corroborations", ["candidate_id"])
    op.create_index("ix_news_corroborations_created_at", "news_corroborations", ["created_at"])
    op.create_table(
        "evidence_contradictions",
        sa.Column("contradiction_id", sa.String(96), primary_key=True),
        sa.Column(
            "evidence_a",
            sa.String(96),
            sa.ForeignKey("evidence.provenance_id"),
            nullable=False,
        ),
        sa.Column(
            "evidence_b",
            sa.String(96),
            sa.ForeignKey("evidence.provenance_id"),
            nullable=False,
        ),
        sa.Column("contradiction_type", sa.String(128), nullable=False),
        sa.Column("detected_by", sa.String(128), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_evidence_contradictions_created_at",
        "evidence_contradictions",
        ["created_at"],
    )
    for table in _TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION marketevolver_reject_immutable_mutation()
            """
        )


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
        op.drop_table(table)
