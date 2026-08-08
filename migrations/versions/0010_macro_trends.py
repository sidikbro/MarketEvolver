"""Trends and Macro Intelligence Lab

Revision ID: 0010
Revises: 0009
"""

import sqlalchemy as sa
from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_TABLES = ("macro_observations", "trend_signals", "trend_divergences", "structural_trends")


def upgrade() -> None:
    op.create_table(
        "macro_observations",
        sa.Column("observation_id", sa.String(96), primary_key=True),
        sa.Column("series_id", sa.String(128), nullable=False),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("geography", sa.String(32), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("observation_period", sa.String(32), nullable=False),
        sa.Column("value", sa.String(128), nullable=False),
        sa.Column("unit", sa.String(64), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revision_of", sa.String(96), sa.ForeignKey("macro_observations.observation_id")),
        sa.Column("seasonal_adjustment", sa.String(32), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=False),
        sa.Column("name_en", sa.String(256), nullable=False),
        sa.Column("name_he", sa.String(256)),
        sa.Column("prior_value", sa.String(128)),
        sa.Column("expected_value", sa.String(128)),
        sa.Column("expectation_source", sa.String(128)),
        sa.Column("expectation_observed_at", sa.DateTime(timezone=True)),
    )
    for name, column in (
        ("ix_macro_observations_series_id", "series_id"),
        ("ix_macro_observations_source_id", "source_id"),
        ("ix_macro_observations_period", "observation_period"),
        ("ix_macro_observations_observed", "first_observed_at"),
    ):
        op.create_index(name, "macro_observations", [column])
    op.create_table(
        "trend_signals",
        sa.Column("trend_id", sa.String(96), primary_key=True),
        sa.Column("series_id", sa.String(128), nullable=False),
        sa.Column("geography", sa.String(32), nullable=False),
        sa.Column("category", sa.String(32), nullable=False),
        sa.Column("horizon", sa.String(16), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("as_of_period", sa.String(32), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("calculation_version", sa.String(64), nullable=False),
        sa.Column("input_observation_ids", sa.JSON(), nullable=False),
        sa.Column("slope", sa.String(128)),
        sa.Column("rolling_mean", sa.String(128)),
        sa.Column("z_score", sa.String(128)),
        sa.Column("mechanism_ids", sa.JSON(), nullable=False),
    )
    op.create_index("ix_trend_signals_series_id", "trend_signals", ["series_id"])
    op.create_index("ix_trend_signals_calculated", "trend_signals", ["calculated_at"])
    op.create_table(
        "trend_divergences",
        sa.Column("divergence_id", sa.String(96), primary_key=True),
        sa.Column(
            "left_trend_id", sa.String(96), sa.ForeignKey("trend_signals.trend_id"), nullable=False
        ),
        sa.Column(
            "right_trend_id", sa.String(96), sa.ForeignKey("trend_signals.trend_id"), nullable=False
        ),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provenance_ids", sa.JSON(), nullable=False),
    )
    op.create_index("ix_trend_divergences_observed", "trend_divergences", ["observed_at"])
    op.create_table(
        "structural_trends",
        sa.Column("structural_id", sa.String(128), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("geography", sa.String(32), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("mechanism_ids", sa.JSON(), nullable=False),
        sa.Column("curated", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_structural_trends_observed", "structural_trends", ["first_observed_at"])
    if op.get_bind().dialect.name == "postgresql":
        for table in _TABLES:
            function = f"forbid_{table}_mutation"
            op.execute(
                f"CREATE FUNCTION {function}() RETURNS trigger LANGUAGE plpgsql AS $$ "
                "BEGIN RAISE EXCEPTION 'immutable record'; END; $$"
            )
            op.execute(
                f"CREATE TRIGGER {table}_immutable BEFORE UPDATE OR DELETE ON {table} "
                f"FOR EACH ROW EXECUTE FUNCTION {function}()"
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        for table in reversed(_TABLES):
            op.execute(f"DROP TRIGGER IF EXISTS {table}_immutable ON {table}")
            op.execute(f"DROP FUNCTION IF EXISTS forbid_{table}_mutation()")
    for table in reversed(_TABLES):
        op.drop_table(table)
