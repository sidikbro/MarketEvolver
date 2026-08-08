"""Hypothesis testing and backtest engine

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None

TABLES = (
    "experiment_specifications",
    "backtest_datasets",
    "backtest_results",
    "test_set_accesses",
    "experiment_registry_snapshots",
)


def upgrade():
    op.create_table(
        "experiment_specifications",
        sa.Column("experiment_id", sa.String(96), primary_key=True),
        sa.Column("hypothesis_id", sa.String(96), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("research_context_id", sa.String(96), nullable=False),
        sa.Column("asset_universe", sa.JSON(), nullable=False),
        sa.Column("benchmark", sa.String(96), nullable=False),
        sa.Column("signal_definition", sa.JSON(), nullable=False),
        sa.Column("entry_rule", sa.String(24), nullable=False),
        sa.Column("exit_rule", sa.String(32), nullable=False),
        sa.Column("holding_period", sa.Integer(), nullable=False),
        sa.Column("rebalance_frequency", sa.String(24), nullable=False),
        sa.Column("position_policy", sa.String(24), nullable=False),
        sa.Column("cost_model", sa.JSON(), nullable=False),
        sa.Column("evaluation_window", sa.JSON(), nullable=False),
        sa.Column("exclusion_rules", sa.JSON(), nullable=False),
        sa.Column("parameter_manifest", sa.JSON(), nullable=False),
        sa.Column("code_version_hash", sa.String(80), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column(
            "revision_of", sa.String(96), sa.ForeignKey("experiment_specifications.experiment_id")
        ),
    )
    op.create_table(
        "backtest_datasets",
        sa.Column("manifest_id", sa.String(96), primary_key=True),
        sa.Column("dataset_version", sa.String(64), nullable=False),
        sa.Column("parquet_hashes", sa.JSON(), nullable=False),
        sa.Column("source_versions", sa.JSON(), nullable=False),
        sa.Column("parameter_hash", sa.String(80), nullable=False),
        sa.Column("seed", sa.Integer(), nullable=False),
        sa.Column("rows_read", sa.Integer(), nullable=False),
        sa.Column("bytes_read", sa.BigInteger(), nullable=False),
    )
    op.create_table(
        "backtest_results",
        sa.Column("result_id", sa.String(96), primary_key=True),
        sa.Column(
            "experiment_id",
            sa.String(96),
            sa.ForeignKey("experiment_specifications.experiment_id"),
            nullable=False,
        ),
        sa.Column(
            "dataset_manifest_id",
            sa.String(96),
            sa.ForeignKey("backtest_datasets.manifest_id"),
            nullable=False,
        ),
        sa.Column("reproducibility", sa.JSON(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("transaction_costs", sa.JSON(), nullable=False),
        sa.Column("number_of_signals", sa.Integer(), nullable=False),
        sa.Column("executed_trades", sa.Integer(), nullable=False),
        sa.Column("skipped_signals", sa.Integer(), nullable=False),
        sa.Column("rejection_reasons", sa.JSON(), nullable=False),
        sa.Column("nav", sa.JSON(), nullable=False),
        sa.Column("position_paths", sa.JSON(), nullable=False),
        sa.Column("runtime_ms", sa.Integer(), nullable=False),
        sa.Column("parquet_bytes_read", sa.BigInteger(), nullable=False),
    )
    op.create_table(
        "test_set_accesses",
        sa.Column("audit_id", sa.String(96), primary_key=True),
        sa.Column(
            "experiment_id",
            sa.String(96),
            sa.ForeignKey("experiment_specifications.experiment_id"),
            nullable=False,
        ),
        sa.Column("partition", sa.String(16), nullable=False),
        sa.Column("accessed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purpose", sa.String(256), nullable=False),
        sa.Column("actor", sa.String(128), nullable=False),
    )
    op.create_table(
        "experiment_registry_snapshots",
        sa.Column("snapshot_id", sa.String(96), primary_key=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hypotheses_generated", sa.Integer(), nullable=False),
        sa.Column("experiments_executed", sa.Integer(), nullable=False),
        sa.Column("rejected_experiments", sa.Integer(), nullable=False),
        sa.Column("reported_experiments", sa.Integer(), nullable=False),
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
