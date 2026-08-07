"""Constrained research intelligence

Revision ID: 0008
Revises: 0007
"""

import sqlalchemy as sa
from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

_TABLES = (
    "research_contexts",
    "research_context_manifests",
    "research_anonymization_mappings",
    "research_provider_calls",
    "research_claims",
    "research_hypotheses_v2",
    "research_reviews",
    "research_traces",
)


def upgrade() -> None:
    op.create_table(
        "research_contexts",
        sa.Column("research_context_id", sa.String(96), primary_key=True),
        sa.Column("cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("subject_id", sa.String(128), nullable=False),
        sa.Column("items", sa.JSON(), nullable=False),
        sa.Column("anonymized", sa.Boolean(), nullable=False),
    )
    op.create_index("ix_research_contexts_cutoff", "research_contexts", ["cutoff"])
    op.create_index("ix_research_contexts_subject_id", "research_contexts", ["subject_id"])
    op.create_table(
        "research_context_manifests",
        sa.Column("manifest_id", sa.String(96), primary_key=True),
        sa.Column(
            "research_context_id",
            sa.String(96),
            sa.ForeignKey("research_contexts.research_context_id"),
            nullable=False,
        ),
        sa.Column("cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("subject_id", sa.String(128), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("event_ids", sa.JSON(), nullable=False),
        sa.Column("policy_ids", sa.JSON(), nullable=False),
        sa.Column("filing_ids", sa.JSON(), nullable=False),
        sa.Column("fundamental_ids", sa.JSON(), nullable=False),
        sa.Column("graph_versions", sa.JSON(), nullable=False),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_research_context_manifests_context",
        "research_context_manifests",
        ["research_context_id"],
    )
    op.create_table(
        "research_anonymization_mappings",
        sa.Column("mapping_id", sa.String(96), primary_key=True),
        sa.Column(
            "research_context_id",
            sa.String(96),
            sa.ForeignKey("research_contexts.research_context_id"),
            nullable=False,
        ),
        sa.Column("values", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_research_anonymization_mappings_context",
        "research_anonymization_mappings",
        ["research_context_id"],
    )
    op.create_table(
        "research_provider_calls",
        sa.Column("call_id", sa.String(96), primary_key=True),
        sa.Column("provider_id", sa.String(128), nullable=False),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("settings", sa.JSON(), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("token_usage", sa.JSON(), nullable=False),
        sa.Column("raw_response_hash", sa.String(72), nullable=False),
        sa.Column("structured_result", sa.JSON(), nullable=False),
    )
    op.create_table(
        "research_claims",
        sa.Column("claim_id", sa.String(96), primary_key=True),
        sa.Column("claim_type", sa.String(16), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("supporting_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("contradicting_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("entities", sa.JSON(), nullable=False),
        sa.Column("mechanisms", sa.JSON(), nullable=False),
        sa.Column("horizon", sa.String(256), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_state", sa.String(16), nullable=False),
    )
    op.create_table(
        "research_hypotheses_v2",
        sa.Column("hypothesis_id", sa.String(96), primary_key=True),
        sa.Column("subject_entities", sa.JSON(), nullable=False),
        sa.Column("mechanism_chain", sa.JSON(), nullable=False),
        sa.Column("evidence_basis", sa.JSON(), nullable=False),
        sa.Column("counterevidence", sa.JSON(), nullable=False),
        sa.Column("expected_horizon", sa.String(256), nullable=False),
        sa.Column("measurable_outcome", sa.Text(), nullable=False),
        sa.Column("falsification_criterion", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("generated_by", sa.String(128), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
    )
    op.create_table(
        "research_reviews",
        sa.Column("reviewer_id", sa.String(96), primary_key=True),
        sa.Column(
            "hypothesis_id",
            sa.String(96),
            sa.ForeignKey("research_hypotheses_v2.hypothesis_id"),
            nullable=False,
        ),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("issues", sa.JSON(), nullable=False),
        sa.Column("alternative_explanations", sa.JSON(), nullable=False),
        sa.Column("stale_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("model_id", sa.String(128), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
    )
    op.create_index("ix_research_reviews_hypothesis", "research_reviews", ["hypothesis_id"])
    op.create_table(
        "research_traces",
        sa.Column("trace_id", sa.String(96), primary_key=True),
        sa.Column(
            "manifest_id",
            sa.String(96),
            sa.ForeignKey("research_context_manifests.manifest_id"),
            nullable=False,
        ),
        sa.Column(
            "provider_call_id",
            sa.String(96),
            sa.ForeignKey("research_provider_calls.call_id"),
            nullable=False,
        ),
        sa.Column("claim_ids", sa.JSON(), nullable=False),
        sa.Column("hypothesis_id", sa.String(96)),
        sa.Column("reviewer_id", sa.String(96)),
        sa.Column("validation_state", sa.String(32), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
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
