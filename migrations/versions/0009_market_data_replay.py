"""Historical market data and replay benchmark

Revision ID: 0009
Revises: 0008
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None

_TABLES = (
    "assets",
    "market_partitions",
    "market_observations",
    "corporate_actions",
    "trading_sessions",
    "replay_cases",
    "replay_commitments",
    "replay_runs",
    "outcome_evaluations",
    "benchmark_pairs",
)


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("asset_version_id", sa.String(96), primary_key=True),
        sa.Column("asset_id", sa.String(128), nullable=False),
        sa.Column("symbol", sa.String(64), nullable=False),
        sa.Column("venue", sa.String(32), nullable=False),
        sa.Column("asset_type", sa.String(16), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("company_id", sa.String(128)),
        sa.Column("entity_id", sa.String(128), nullable=False),
        sa.Column("benchmark_asset_id", sa.String(128)),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    for name, column in (
        ("ix_assets_asset_id", "asset_id"),
        ("ix_assets_symbol", "symbol"),
        ("ix_assets_venue", "venue"),
        ("ix_assets_company_id", "company_id"),
        ("ix_assets_entity_id", "entity_id"),
    ):
        op.create_index(name, "assets", [column])
    op.create_table(
        "market_partitions",
        sa.Column("sha256", sa.String(64), primary_key=True),
        sa.Column("relative_path", sa.String(1024), nullable=False, unique=True),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("dataset_version", sa.String(64), nullable=False),
    )
    op.create_table(
        "market_observations",
        sa.Column("observation_id", sa.String(96), primary_key=True),
        sa.Column("asset_id", sa.String(128), nullable=False),
        sa.Column("venue", sa.String(32), nullable=False),
        sa.Column("observation_type", sa.String(16), nullable=False),
        sa.Column("market_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("adjustment_status", sa.String(16), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column(
            "partition_sha256",
            sa.String(64),
            sa.ForeignKey("market_partitions.sha256"),
            nullable=False,
        ),
    )
    for name, column in (
        ("ix_market_observations_asset_id", "asset_id"),
        ("ix_market_observations_market_timestamp", "market_timestamp"),
        ("ix_market_observations_observed_at", "observed_at"),
        ("ix_market_observations_partition", "partition_sha256"),
    ):
        op.create_index(name, "market_observations", [column])
    op.create_table(
        "corporate_actions",
        sa.Column("action_id", sa.String(96), primary_key=True),
        sa.Column("asset_id", sa.String(128), nullable=False),
        sa.Column("action_type", sa.String(32), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("announced_at", sa.DateTime(timezone=True)),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("value", sa.String(128)),
        sa.Column("currency", sa.String(8)),
        sa.Column("old_symbol", sa.String(64)),
        sa.Column("new_symbol", sa.String(64)),
    )
    op.create_index("ix_corporate_actions_asset_id", "corporate_actions", ["asset_id"])
    op.create_table(
        "trading_sessions",
        sa.Column("session_id", sa.String(96), primary_key=True),
        sa.Column("venue", sa.String(32), nullable=False),
        sa.Column("session_date", sa.String(10), nullable=False),
        sa.Column("opens_at", sa.DateTime(timezone=True)),
        sa.Column("closes_at", sa.DateTime(timezone=True)),
        sa.Column("is_trading_day", sa.Boolean(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=False),
    )
    op.create_index("ix_trading_sessions_venue", "trading_sessions", ["venue"])
    op.create_table(
        "replay_cases",
        sa.Column("case_id", sa.String(96), primary_key=True),
        sa.Column("case_type", sa.String(32), nullable=False),
        sa.Column("entity_ids", sa.JSON(), nullable=False),
        sa.Column("asset_ids", sa.JSON(), nullable=False),
        sa.Column("cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon", sa.String(64), nullable=False),
        sa.Column("available_evidence_manifest_id", sa.String(96), nullable=False),
        sa.Column("benchmark_asset_id", sa.String(128)),
        sa.Column("expected_output_schema", sa.String(64), nullable=False),
        sa.Column("evaluation_protocol", sa.String(64), nullable=False),
        sa.Column("dataset_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "replay_commitments",
        sa.Column("commitment_id", sa.String(96), primary_key=True),
        sa.Column("case_id", sa.String(96), sa.ForeignKey("replay_cases.case_id"), nullable=False),
        sa.Column("replay_timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("context_manifest_id", sa.String(96), nullable=False),
        sa.Column("hypothesis_id", sa.String(96), nullable=False),
        sa.Column("expected_horizon", sa.String(64), nullable=False),
        sa.Column("measurable_outcome", sa.Text(), nullable=False),
        sa.Column("falsification_criterion", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reviewer_decision", sa.String(32), nullable=False),
        sa.Column("research_mode", sa.String(32), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "replay_runs",
        sa.Column("run_id", sa.String(96), primary_key=True),
        sa.Column("case_id", sa.String(96), sa.ForeignKey("replay_cases.case_id"), nullable=False),
        sa.Column(
            "commitment_id",
            sa.String(96),
            sa.ForeignKey("replay_commitments.commitment_id"),
            nullable=False,
        ),
        sa.Column("named", sa.Boolean(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("runtime_ms", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
    )
    op.create_table(
        "outcome_evaluations",
        sa.Column("evaluation_id", sa.String(96), primary_key=True),
        sa.Column("run_id", sa.String(96), sa.ForeignKey("replay_runs.run_id"), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("horizon_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("forward_return", sa.String(128)),
        sa.Column("benchmark_relative_return", sa.String(128)),
        sa.Column("maximum_adverse_excursion", sa.String(128)),
        sa.Column("maximum_favorable_excursion", sa.String(128)),
        sa.Column("volatility", sa.String(128)),
        sa.Column("drawdown", sa.String(128)),
        sa.Column("direction", sa.String(16)),
        sa.Column("provenance_observation_ids", sa.JSON(), nullable=False),
    )
    op.create_table(
        "benchmark_pairs",
        sa.Column("pair_id", sa.String(96), primary_key=True),
        sa.Column("case_id", sa.String(96), sa.ForeignKey("replay_cases.case_id"), nullable=False),
        sa.Column(
            "named_run_id", sa.String(96), sa.ForeignKey("replay_runs.run_id"), nullable=False
        ),
        sa.Column(
            "anonymized_run_id",
            sa.String(96),
            sa.ForeignKey("replay_runs.run_id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
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
