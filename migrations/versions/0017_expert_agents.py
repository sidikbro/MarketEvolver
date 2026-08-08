"""Fixed expert agent framework

Revision ID: 0017
Revises: 0016
"""

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

TABLES = (
    "expert_definitions",
    "expert_tool_audits",
    "expert_sessions",
    "expert_assessments",
    "expert_routing_decisions",
    "expert_scorecards",
    "expert_comparisons",
)


def upgrade():
    op.create_table(
        "expert_definitions",
        sa.Column("definition_id", sa.String(96), primary_key=True),
        sa.Column("expert_id", sa.String(96), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, index=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("revision_of", sa.String(96)),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "expert_tool_audits",
        sa.Column("audit_id", sa.String(96), primary_key=True),
        sa.Column(
            "expert_definition_id",
            sa.String(96),
            sa.ForeignKey("expert_definitions.definition_id"),
            nullable=False,
        ),
        sa.Column("session_id", sa.String(96), nullable=False, index=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("decision", sa.String(16), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "expert_sessions",
        sa.Column("session_id", sa.String(96), primary_key=True),
        sa.Column(
            "expert_definition_id",
            sa.String(96),
            sa.ForeignKey("expert_definitions.definition_id"),
            nullable=False,
        ),
        sa.Column("cutoff", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("domain", sa.String(96), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "expert_assessments",
        sa.Column("assessment_id", sa.String(96), primary_key=True),
        sa.Column(
            "session_id", sa.String(96), sa.ForeignKey("expert_sessions.session_id"), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "expert_routing_decisions",
        sa.Column("routing_id", sa.String(96), primary_key=True),
        sa.Column("cutoff", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "expert_scorecards",
        sa.Column("scorecard_id", sa.String(96), primary_key=True),
        sa.Column(
            "expert_definition_id",
            sa.String(96),
            sa.ForeignKey("expert_definitions.definition_id"),
            nullable=False,
        ),
        sa.Column("cutoff", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "expert_comparisons",
        sa.Column("comparison_id", sa.String(96), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    if op.get_bind().dialect.name == "postgresql":
        for table in TABLES:
            op.execute(
                f"CREATE FUNCTION forbid_{table}_mutation() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'immutable record'; END; $$"
            )
            op.execute(
                f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} FOR EACH ROW EXECUTE FUNCTION forbid_{table}_mutation()"
            )


def downgrade():
    if op.get_bind().dialect.name == "postgresql":
        for table in reversed(TABLES):
            op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS forbid_{table}_mutation()")
    for table in reversed(TABLES):
        op.drop_table(table)
