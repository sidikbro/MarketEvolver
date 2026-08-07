"""source registry ingestion persistence

Revision ID: 0002
Revises: 0001
"""

import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "sources", "published_at", existing_type=sa.DateTime(timezone=True), nullable=True
    )
    op.create_table(
        "raw_ingestions",
        sa.Column("receipt_id", sa.String(96), primary_key=True),
        sa.Column("registry_source_id", sa.String(128), nullable=False),
        sa.Column("dataset", sa.String(128), nullable=False),
        sa.Column("source_uri", sa.String(2048), nullable=False),
        sa.Column("content_type", sa.String(255), nullable=False),
        sa.Column("content_hash", sa.String(80), nullable=False),
        sa.Column(
            "artifact_sha256",
            sa.String(64),
            sa.ForeignKey("artifacts.sha256"),
            nullable=False,
        ),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "registry_source_id",
            "dataset",
            "artifact_sha256",
            name="uq_raw_ingestion_source_dataset_artifact",
        ),
    )
    op.create_index(
        "ix_raw_ingestions_registry_source_id", "raw_ingestions", ["registry_source_id"]
    )
    op.create_index("ix_raw_ingestions_first_observed_at", "raw_ingestions", ["first_observed_at"])
    op.create_table(
        "normalized_observations",
        sa.Column("provenance_id", sa.String(96), primary_key=True),
        sa.Column("registry_source_id", sa.String(128), nullable=False),
        sa.Column(
            "source_record_id",
            sa.String(96),
            sa.ForeignKey("sources.provenance_id"),
            nullable=False,
        ),
        sa.Column("dataset", sa.String(128), nullable=False),
        sa.Column("item_key", sa.String(256), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True)),
        sa.Column("superseded_at", sa.DateTime(timezone=True)),
        sa.Column("value", sa.String(256), nullable=False),
        sa.Column("unit", sa.String(64), nullable=False),
        sa.Column(
            "raw_artifact_sha256",
            sa.String(64),
            sa.ForeignKey("artifacts.sha256"),
            nullable=False,
        ),
        sa.Column("content_hash", sa.String(80), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=False),
    )
    op.create_index(
        "ix_normalized_observations_registry_source_id",
        "normalized_observations",
        ["registry_source_id"],
    )
    op.create_index(
        "ix_normalized_observations_first_observed_at",
        "normalized_observations",
        ["first_observed_at"],
    )
    op.create_table(
        "ingestion_manifests",
        sa.Column("run_id", sa.String(36), primary_key=True),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("dataset", sa.String(128), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("items_fetched", sa.Integer(), nullable=False),
        sa.Column("items_inserted", sa.Integer(), nullable=False),
        sa.Column("duplicates", sa.Integer(), nullable=False),
        sa.Column("bytes_downloaded", sa.BigInteger(), nullable=False),
        sa.Column("raw_artifacts_created", sa.Integer(), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=False),
        sa.Column("error_summary", sa.String(2048)),
    )
    op.create_index("ix_ingestion_manifests_source_id", "ingestion_manifests", ["source_id"])
    op.create_index("ix_ingestion_manifests_status", "ingestion_manifests", ["status"])


def downgrade() -> None:
    op.drop_table("ingestion_manifests")
    op.drop_table("normalized_observations")
    op.drop_table("raw_ingestions")
    op.alter_column(
        "sources", "published_at", existing_type=sa.DateTime(timezone=True), nullable=False
    )
