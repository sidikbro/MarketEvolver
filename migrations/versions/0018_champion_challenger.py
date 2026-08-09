"""Governed champion/challenger evolution

Revision ID: 0018
Revises: 0017
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None

TABLES = (
    "improvement_proposals",
    "evolvable_expert_versions",
    "evolution_error_attributions",
    "evolution_benchmark_manifests",
    "evolution_holdout_accesses",
    "challenger_evaluations",
    "champion_registry_events",
)


def upgrade():
    op.create_table(
        "improvement_proposals",
        sa.Column("proposal_id", sa.String(96), primary_key=True),
        sa.Column("expert_id", sa.String(96), nullable=False, index=True),
        sa.Column("parent_expert_version", sa.String(96), nullable=False, index=True),
        sa.Column("status", sa.String(24), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "evolvable_expert_versions",
        sa.Column("expert_version_id", sa.String(96), primary_key=True),
        sa.Column("expert_id", sa.String(96), nullable=False, index=True),
        sa.Column("parent_version", sa.String(96), index=True),
        sa.Column("proposal_id", sa.String(96), sa.ForeignKey("improvement_proposals.proposal_id")),
        sa.Column("approval_state", sa.String(32), nullable=False, index=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "evolution_error_attributions",
        sa.Column("attribution_id", sa.String(96), primary_key=True),
        sa.Column(
            "expert_version_id",
            sa.String(96),
            sa.ForeignKey("evolvable_expert_versions.expert_version_id"),
            nullable=False,
        ),
        sa.Column("category", sa.String(48), nullable=False, index=True),
        sa.Column("attributed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("critical", sa.Boolean(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "evolution_benchmark_manifests",
        sa.Column("manifest_id", sa.String(96), primary_key=True),
        sa.Column("dataset_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "evolution_holdout_accesses",
        sa.Column("access_id", sa.String(96), primary_key=True),
        sa.Column(
            "expert_version_id",
            sa.String(96),
            sa.ForeignKey("evolvable_expert_versions.expert_version_id"),
            nullable=False,
        ),
        sa.Column(
            "manifest_id",
            sa.String(96),
            sa.ForeignKey("evolution_benchmark_manifests.manifest_id"),
            nullable=False,
        ),
        sa.Column("partition", sa.String(32), nullable=False, index=True),
        sa.Column("accessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "challenger_evaluations",
        sa.Column("evaluation_id", sa.String(96), primary_key=True),
        sa.Column(
            "challenger_version_id",
            sa.String(96),
            sa.ForeignKey("evolvable_expert_versions.expert_version_id"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "manifest_id",
            sa.String(96),
            sa.ForeignKey("evolution_benchmark_manifests.manifest_id"),
            nullable=False,
        ),
        sa.Column("decision", sa.String(32), nullable=False, index=True),
        sa.Column("safety_veto", sa.Boolean(), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "champion_registry_events",
        sa.Column("event_id", sa.String(96), primary_key=True),
        sa.Column("expert_id", sa.String(96), nullable=False, index=True),
        sa.Column(
            "champion_version_id",
            sa.String(96),
            sa.ForeignKey("evolvable_expert_versions.expert_version_id"),
            nullable=False,
        ),
        sa.Column("action", sa.String(32), nullable=False, index=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, index=True),
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
