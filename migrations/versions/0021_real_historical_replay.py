"""Real historical replay cases and sealed commitments.

Revision ID: 0021
Revises: 0020
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "real_replay_cases",
        sa.Column("case_id", sa.String(96), primary_key=True),
        sa.Column("status", sa.String(40), nullable=False, index=True),
        sa.Column("selected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "real_replay_commitments",
        sa.Column("commitment_id", sa.String(96), primary_key=True),
        sa.Column(
            "case_id",
            sa.String(96),
            sa.ForeignKey("real_replay_cases.case_id"),
            nullable=False,
            index=True,
        ),
        sa.Column("cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mode", sa.String(64), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    for table in ("real_replay_cases", "real_replay_commitments"):
        op.execute(
            f"""CREATE TRIGGER trg_{table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW EXECUTE FUNCTION marketevolver_reject_immutable_mutation()"""
        )


def downgrade() -> None:
    op.drop_table("real_replay_commitments")
    op.drop_table("real_replay_cases")
