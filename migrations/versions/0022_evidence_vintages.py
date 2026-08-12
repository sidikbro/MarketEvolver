"""Historical evidence archive and coverage ledger.

Revision ID: 0022
Revises: 0021
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "evidence_vintages",
        sa.Column("vintage_id", sa.String(96), primary_key=True),
        sa.Column("source_id", sa.String(128), nullable=False, index=True),
        sa.Column(
            "artifact_sha256",
            sa.String(64),
            sa.ForeignKey("artifacts.sha256"),
            nullable=False,
            index=True,
        ),
        sa.Column("canonical_uri", sa.String(2048), nullable=False, index=True),
        sa.Column("source_published_at", sa.DateTime(timezone=True)),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("archived_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("retrieval_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("revision_of", sa.String(96), sa.ForeignKey("evidence_vintages.vintage_id")),
        sa.Column("archive_source", sa.String(128), nullable=False),
        sa.Column("archive_confidence", sa.String(16), nullable=False),
        sa.Column("classification", sa.String(48), nullable=False, index=True),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("server_date_at", sa.DateTime(timezone=True)),
        sa.Column("source_timezone", sa.String(64), nullable=False),
        sa.Column("response_metadata", sa.JSON(), nullable=False),
        sa.Column("retention_class", sa.String(48), nullable=False),
    )
    op.create_table(
        "archive_runs",
        sa.Column("run_id", sa.String(96), primary_key=True),
        sa.Column("source_id", sa.String(128), nullable=False, index=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("snapshots", sa.Integer(), nullable=False),
        sa.Column("inserted", sa.Integer(), nullable=False),
        sa.Column("duplicates", sa.Integer(), nullable=False),
        sa.Column("bytes_downloaded", sa.Integer(), nullable=False),
        sa.Column("revisions", sa.Integer(), nullable=False),
        sa.Column("gaps", sa.Integer(), nullable=False),
        sa.Column("error_summary", sa.String(256)),
    )
    op.create_table(
        "archive_gaps",
        sa.Column("gap_id", sa.String(96), primary_key=True),
        sa.Column("source_id", sa.String(128), nullable=False, index=True),
        sa.Column("expected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reason", sa.String(256), nullable=False),
        sa.Column(
            "resolved_by_vintage_id", sa.String(96), sa.ForeignKey("evidence_vintages.vintage_id")
        ),
    )
    for table in ("evidence_vintages", "archive_runs", "archive_gaps"):
        op.execute(
            f"""CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION marketevolver_reject_immutable_mutation()"""
        )


def downgrade() -> None:
    op.drop_table("archive_gaps")
    op.drop_table("archive_runs")
    op.drop_table("evidence_vintages")
