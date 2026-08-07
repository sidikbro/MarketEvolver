"""event observatory

Revision ID: 0003
Revises: 0002
"""

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "canonical_events",
        sa.Column("event_id", sa.String(96), primary_key=True),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("geography", sa.JSON(), nullable=False),
        sa.Column("entities", sa.JSON(), nullable=False),
        sa.Column("sectors", sa.JSON(), nullable=False),
        sa.Column("affected_asset_classes", sa.JSON(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_at", sa.DateTime(timezone=True)),
        sa.Column("event_status", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("novelty", sa.Float(), nullable=False),
        sa.Column("revision_state", sa.String(16), nullable=False),
        sa.Column(
            "supersedes_event_id",
            sa.String(96),
            sa.ForeignKey("canonical_events.event_id"),
        ),
        sa.Column("causal_mechanisms", sa.JSON(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("attributes", sa.JSON(), nullable=False),
        sa.Column("deduplication_key", sa.String(512), nullable=False),
        sa.Column("material_fingerprint", sa.String(96), nullable=False),
        sa.UniqueConstraint(
            "deduplication_key",
            "material_fingerprint",
            name="uq_canonical_event_material",
        ),
    )
    op.create_index("ix_canonical_events_event_type", "canonical_events", ["event_type"])
    op.create_index(
        "ix_canonical_events_first_observed_at",
        "canonical_events",
        ["first_observed_at"],
    )
    op.create_index("ix_canonical_events_revision_state", "canonical_events", ["revision_state"])
    op.create_table(
        "event_support",
        sa.Column(
            "event_id",
            sa.String(96),
            sa.ForeignKey("canonical_events.event_id"),
            primary_key=True,
        ),
        sa.Column(
            "evidence_id",
            sa.String(96),
            sa.ForeignKey("evidence.provenance_id"),
            primary_key=True,
        ),
        sa.Column(
            "source_id",
            sa.String(96),
            sa.ForeignKey("sources.provenance_id"),
            primary_key=True,
        ),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_event_support_first_observed_at", "event_support", ["first_observed_at"])
    op.create_table(
        "event_transitions",
        sa.Column("transition_id", sa.String(96), primary_key=True),
        sa.Column(
            "event_id",
            sa.String(96),
            sa.ForeignKey("canonical_events.event_id"),
            nullable=False,
        ),
        sa.Column("from_status", sa.String(16)),
        sa.Column("to_status", sa.String(16), nullable=False),
        sa.Column("transitioned_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("reviewer_status", sa.String(24), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "event_id",
            "sequence",
            name="uq_event_transition_sequence",
        ),
    )
    op.create_index("ix_event_transitions_event_id", "event_transitions", ["event_id"])
    op.create_index(
        "ix_event_transitions_transitioned_at",
        "event_transitions",
        ["transitioned_at"],
    )
    op.create_table(
        "event_mechanism_links",
        sa.Column("link_id", sa.String(96), primary_key=True),
        sa.Column(
            "event_id",
            sa.String(96),
            sa.ForeignKey("canonical_events.event_id"),
            nullable=False,
        ),
        sa.Column("mechanism_id", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("expected_horizon", sa.String(16), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("reviewer_status", sa.String(24), nullable=False),
        sa.Column("linked_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_event_mechanism_links_event_id", "event_mechanism_links", ["event_id"])
    op.create_index(
        "ix_event_mechanism_links_mechanism_id",
        "event_mechanism_links",
        ["mechanism_id"],
    )


def downgrade() -> None:
    op.drop_table("event_mechanism_links")
    op.drop_table("event_transitions")
    op.drop_table("event_support")
    op.drop_table("canonical_events")
