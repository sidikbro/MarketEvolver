"""Preserve Telegram hashtags on immutable social posts.

Revision ID: 0020
Revises: 0019
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "social_posts",
        sa.Column("hashtags", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.alter_column("social_posts", "hashtags", server_default=None)


def downgrade() -> None:
    op.drop_column("social_posts", "hashtags")
