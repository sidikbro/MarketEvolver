"""Geopolitical Intelligence Lab

Revision ID: 0011
Revises: 0010
"""

import sqlalchemy as sa
from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

_TABLES = (
    "geopolitical_events",
    "geopolitical_candidates",
    "geopolitical_candidate_reviews",
    "geopolitical_transmission_paths",
    "geopolitical_corroborations",
)


def upgrade() -> None:
    op.create_table(
        "geopolitical_events",
        sa.Column("event_id", sa.String(96), primary_key=True),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("geography", sa.JSON(), nullable=False),
        sa.Column("actors", sa.JSON(), nullable=False),
        sa.Column("source_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("announced_at", sa.DateTime(timezone=True)),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("confirmation_state", sa.String(32), nullable=False),
        sa.Column("revision_of", sa.String(96), sa.ForeignKey("geopolitical_events.event_id")),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_index("ix_geopolitical_events_type", "geopolitical_events", ["event_type"])
    op.create_index("ix_geopolitical_events_observed", "geopolitical_events", ["first_observed_at"])
    op.create_table(
        "geopolitical_candidates",
        sa.Column("candidate_id", sa.String(96), primary_key=True),
        sa.Column("source_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("event_type", sa.String(48)),
        sa.Column("actors", sa.JSON(), nullable=False),
        sa.Column("geography", sa.JSON(), nullable=False),
        sa.Column("explicit_timestamps", sa.JSON(), nullable=False),
        sa.Column("mechanism_candidates", sa.JSON(), nullable=False),
        sa.Column("extraction_method", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_state", sa.String(24), nullable=False),
        sa.Column("supporting_spans", sa.JSON(), nullable=False),
    )
    op.create_index("ix_geopolitical_candidates_created", "geopolitical_candidates", ["created_at"])
    op.create_table(
        "geopolitical_candidate_reviews",
        sa.Column("review_id", sa.String(96), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.String(96),
            sa.ForeignKey("geopolitical_candidates.candidate_id"),
            nullable=False,
        ),
        sa.Column("state", sa.String(24), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewer", sa.String(128), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
    )
    op.create_index(
        "ix_geopolitical_reviews_candidate", "geopolitical_candidate_reviews", ["candidate_id"]
    )
    op.create_index(
        "ix_geopolitical_reviews_observed", "geopolitical_candidate_reviews", ["reviewed_at"]
    )
    op.create_table(
        "geopolitical_transmission_paths",
        sa.Column("path_id", sa.String(96), primary_key=True),
        sa.Column(
            "event_id", sa.String(96), sa.ForeignKey("geopolitical_events.event_id"), nullable=False
        ),
        sa.Column("mechanisms", sa.JSON(), nullable=False),
        sa.Column("affected_entities", sa.JSON(), nullable=False),
        sa.Column("horizon", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("provenance_ids", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_geopolitical_paths_event", "geopolitical_transmission_paths", ["event_id"])
    op.create_index(
        "ix_geopolitical_paths_observed", "geopolitical_transmission_paths", ["observed_at"]
    )
    op.create_table(
        "geopolitical_corroborations",
        sa.Column("corroboration_id", sa.String(96), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.String(96),
            sa.ForeignKey("geopolitical_candidates.candidate_id"),
            nullable=False,
        ),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
    )
    op.create_index(
        "ix_geopolitical_corroborations_candidate", "geopolitical_corroborations", ["candidate_id"]
    )
    op.create_index(
        "ix_geopolitical_corroborations_observed", "geopolitical_corroborations", ["observed_at"]
    )
    if op.get_bind().dialect.name == "postgresql":
        for table in _TABLES:
            function = f"forbid_{table}_mutation"
            op.execute(
                f"CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'immutable record'; END; $$"
            )
            op.execute(
                f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION {function}()"
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in reversed(_TABLES):
            op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS forbid_{table}_mutation()")
    for table in reversed(_TABLES):
        op.drop_table(table)
