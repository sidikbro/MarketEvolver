"""Paper portfolio and deterministic risk governor

Revision ID: 0016
Revises: 0015
"""

import sqlalchemy as sa
from alembic import op

revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None

TABLES = (
    "paper_risk_policies",
    "paper_portfolios",
    "paper_account_snapshots",
    "paper_signals",
    "paper_orders",
    "paper_risk_evaluations",
    "paper_execution_decisions",
    "paper_fills",
    "paper_audit_journal",
)


def upgrade():
    op.create_table(
        "paper_risk_policies",
        sa.Column("policy_id", sa.String(96), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("limits", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
    )
    op.create_table(
        "paper_portfolios",
        sa.Column("portfolio_version_id", sa.String(160), primary_key=True),
        sa.Column("portfolio_id", sa.String(96), nullable=False, index=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("revision_of", sa.String(160)),
    )
    op.create_table(
        "paper_account_snapshots",
        sa.Column("snapshot_id", sa.String(96), primary_key=True),
        sa.Column("portfolio_id", sa.String(96), nullable=False, index=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("account", sa.JSON(), nullable=False),
    )
    op.create_table(
        "paper_signals",
        sa.Column("signal_id", sa.String(96), primary_key=True),
        sa.Column("portfolio_id", sa.String(96), nullable=False, index=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "paper_orders",
        sa.Column("candidate_id", sa.String(96), primary_key=True),
        sa.Column(
            "signal_id", sa.String(96), sa.ForeignKey("paper_signals.signal_id"), nullable=False
        ),
        sa.Column("portfolio_id", sa.String(96), nullable=False, index=True),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "paper_risk_evaluations",
        sa.Column("evaluation_id", sa.String(96), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.String(96),
            sa.ForeignKey("paper_orders.candidate_id"),
            nullable=False,
        ),
        sa.Column("portfolio_id", sa.String(96), nullable=False, index=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("action", sa.String(24), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "paper_execution_decisions",
        sa.Column("decision_id", sa.String(96), primary_key=True),
        sa.Column(
            "candidate_id",
            sa.String(96),
            sa.ForeignKey("paper_orders.candidate_id"),
            nullable=False,
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "paper_fills",
        sa.Column("fill_id", sa.String(96), primary_key=True),
        sa.Column(
            "decision_id",
            sa.String(96),
            sa.ForeignKey("paper_execution_decisions.decision_id"),
            nullable=False,
        ),
        sa.Column("portfolio_id", sa.String(96), nullable=False, index=True),
        sa.Column("filled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "paper_audit_journal",
        sa.Column("audit_id", sa.String(96), primary_key=True),
        sa.Column("portfolio_id", sa.String(96), nullable=False, index=True),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("kind", sa.String(64), nullable=False),
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
