"""Telegram public-source connector

Revision ID: 0013
Revises: 0012
"""

import sqlalchemy as sa
from alembic import op

revision = "0013"
down_revision = "0012"
branch_labels = None
depends_on = None
TABLES = ("telegram_receipts", "telegram_checkpoints", "telegram_runs")


def upgrade():
    op.create_table(
        "telegram_receipts",
        sa.Column("receipt_id", sa.String(96), primary_key=True),
        sa.Column("allowlist_source_id", sa.String(128), nullable=False),
        sa.Column("post_id", sa.String(96), sa.ForeignKey("social_posts.post_id"), nullable=False),
        sa.Column("native_message_id", sa.Integer(), nullable=False),
        sa.Column("forward_source", sa.String(256)),
        sa.Column("forward_message_id", sa.Integer()),
        sa.Column("forward_hidden", sa.Boolean(), nullable=False),
        sa.Column(
            "artifact_sha256", sa.String(64), sa.ForeignKey("artifacts.sha256"), nullable=False
        ),
        sa.Column("payload_bytes", sa.Integer(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "telegram_checkpoints",
        sa.Column("checkpoint_id", sa.String(96), primary_key=True),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("last_message_id", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "telegram_runs",
        sa.Column("run_id", sa.String(96), primary_key=True),
        sa.Column("source_id", sa.String(128), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("messages_fetched", sa.Integer(), nullable=False),
        sa.Column("inserted", sa.Integer(), nullable=False),
        sa.Column("duplicates", sa.Integer(), nullable=False),
        sa.Column("edits", sa.Integer(), nullable=False),
        sa.Column("forwards", sa.Integer(), nullable=False),
        sa.Column("deletions", sa.Integer(), nullable=False),
        sa.Column("bytes_downloaded", sa.Integer(), nullable=False),
        sa.Column("error_summary", sa.Text()),
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
