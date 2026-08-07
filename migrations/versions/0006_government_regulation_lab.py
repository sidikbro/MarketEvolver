"""Government and Regulation Lab

Revision ID: 0006
Revises: 0005
"""

import sqlalchemy as sa
from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

_TABLES = ("government_actions", "government_transitions", "government_action_candidates")


def upgrade() -> None:
    op.create_table(
        "government_actions",
        sa.Column("action_id", sa.String(96), primary_key=True),
        sa.Column("jurisdiction", sa.String(32), nullable=False),
        sa.Column("issuing_body", sa.String(128), nullable=False),
        sa.Column("action_type", sa.String(32), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description_reference", sa.Text(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("announced_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("effective_at", sa.DateTime(timezone=True)),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("supersedes_action_id", sa.String(96)),
        sa.Column("source_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("affected_entities", sa.JSON(), nullable=False),
        sa.Column("affected_sectors", sa.JSON(), nullable=False),
        sa.Column("candidate_mechanisms", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("expectation_status", sa.String(16), nullable=False),
    )
    for column in (
        "jurisdiction",
        "issuing_body",
        "action_type",
        "first_observed_at",
        "supersedes_action_id",
    ):
        op.create_index(f"ix_government_actions_{column}", "government_actions", [column])
    op.create_table(
        "government_transitions",
        sa.Column("transition_id", sa.String(96), primary_key=True),
        sa.Column(
            "action_id",
            sa.String(96),
            sa.ForeignKey("government_actions.action_id"),
            nullable=False,
        ),
        sa.Column("from_status", sa.String(24)),
        sa.Column("to_status", sa.String(24), nullable=False),
        sa.Column("transitioned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
    )
    op.create_index("ix_government_transitions_action_id", "government_transitions", ["action_id"])
    op.create_index(
        "ix_government_transitions_transitioned_at",
        "government_transitions",
        ["transitioned_at"],
    )
    op.create_table(
        "government_action_candidates",
        sa.Column("candidate_id", sa.String(96), primary_key=True),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("issuing_body", sa.String(128)),
        sa.Column("possible_action_type", sa.String(32)),
        sa.Column("possible_transition", sa.String(24)),
        sa.Column("explicit_dates", sa.JSON(), nullable=False),
        sa.Column("explicit_values", sa.JSON(), nullable=False),
        sa.Column("entities", sa.JSON(), nullable=False),
        sa.Column("candidate_mechanisms", sa.JSON(), nullable=False),
        sa.Column("extraction_method", sa.String(128), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_state", sa.String(24), nullable=False),
        sa.Column("expectation_status", sa.String(16), nullable=False),
    )
    op.create_index(
        "ix_government_action_candidates_created_at",
        "government_action_candidates",
        ["created_at"],
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
