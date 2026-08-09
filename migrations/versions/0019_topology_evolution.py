"""Governed expert topology evolution

Revision ID: 0019
Revises: 0018
"""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None

TABLES = (
    "topology_proposals",
    "topology_gap_signals",
    "expert_topology_versions",
    "topology_evaluations",
    "topology_registry_events",
    "topology_routing_traces",
    "topology_holdout_accesses",
)


def upgrade():
    op.create_table(
        "topology_proposals",
        sa.Column("proposal_id", sa.String(96), primary_key=True),
        sa.Column("proposal_type", sa.String(32), nullable=False, index=True),
        sa.Column("status", sa.String(24), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "topology_gap_signals",
        sa.Column("signal_id", sa.String(96), primary_key=True),
        sa.Column("expert_id", sa.String(96), nullable=False, index=True),
        sa.Column("category", sa.String(48), nullable=False, index=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "expert_topology_versions",
        sa.Column("topology_version_id", sa.String(96), primary_key=True),
        sa.Column("parent_topology_version_id", sa.String(96), index=True),
        sa.Column("proposal_id", sa.String(96), sa.ForeignKey("topology_proposals.proposal_id")),
        sa.Column("state", sa.String(32), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "topology_evaluations",
        sa.Column("evaluation_id", sa.String(96), primary_key=True),
        sa.Column(
            "proposal_id",
            sa.String(96),
            sa.ForeignKey("topology_proposals.proposal_id"),
            nullable=False,
        ),
        sa.Column(
            "challenger_topology_id",
            sa.String(96),
            sa.ForeignKey("expert_topology_versions.topology_version_id"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(40), nullable=False, index=True),
        sa.Column("safety_veto", sa.Boolean(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "topology_registry_events",
        sa.Column("event_id", sa.String(96), primary_key=True),
        sa.Column(
            "topology_version_id",
            sa.String(96),
            sa.ForeignKey("expert_topology_versions.topology_version_id"),
            nullable=False,
        ),
        sa.Column("action", sa.String(32), nullable=False, index=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "topology_routing_traces",
        sa.Column("trace_id", sa.String(96), primary_key=True),
        sa.Column(
            "topology_version_id",
            sa.String(96),
            sa.ForeignKey("expert_topology_versions.topology_version_id"),
            nullable=False,
        ),
        sa.Column("cutoff", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("correct", sa.Boolean(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "topology_holdout_accesses",
        sa.Column("access_id", sa.String(96), primary_key=True),
        sa.Column(
            "topology_version_id",
            sa.String(96),
            sa.ForeignKey("expert_topology_versions.topology_version_id"),
            nullable=False,
        ),
        sa.Column("benchmark_manifest_id", sa.String(96), nullable=False),
        sa.Column("accessed_at", sa.DateTime(timezone=True), nullable=False),
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
