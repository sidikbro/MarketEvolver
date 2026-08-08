"""Cross-source fusion and reputation

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None

TABLES = (
    "unified_claims",
    "claim_lineage",
    "claim_corroborations",
    "claim_resolutions",
    "claim_contradictions",
    "fusion_scores",
    "fusion_reputation_snapshots",
)


def upgrade():
    op.create_table(
        "unified_claims",
        sa.Column("claim_id", sa.String(96), primary_key=True),
        sa.Column("proposition", sa.Text(), nullable=False),
        sa.Column("claim_type", sa.String(32), nullable=False),
        sa.Column("entities", sa.JSON(), nullable=False),
        sa.Column("geography", sa.JSON(), nullable=False),
        sa.Column("domain", sa.String(32), nullable=False),
        sa.Column("source_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("originating_source_id", sa.String(256), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("revision_of", sa.String(96), sa.ForeignKey("unified_claims.claim_id")),
    )
    op.create_table(
        "claim_lineage",
        sa.Column("lineage_id", sa.String(96), primary_key=True),
        sa.Column(
            "source_claim_id",
            sa.String(96),
            sa.ForeignKey("unified_claims.claim_id"),
            nullable=False,
        ),
        sa.Column(
            "target_claim_id",
            sa.String(96),
            sa.ForeignKey("unified_claims.claim_id"),
            nullable=False,
        ),
        sa.Column("relationship", sa.String(24), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
    )
    op.create_table(
        "claim_corroborations",
        sa.Column("record_id", sa.String(96), primary_key=True),
        sa.Column(
            "claim_id", sa.String(96), sa.ForeignKey("unified_claims.claim_id"), nullable=False
        ),
        sa.Column("evidence_id", sa.String(96), nullable=False),
        sa.Column("source_id", sa.String(256), nullable=False),
        sa.Column("independence", sa.String(24), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
    )
    op.create_table(
        "claim_resolutions",
        sa.Column("resolution_id", sa.String(96), primary_key=True),
        sa.Column(
            "claim_id", sa.String(96), sa.ForeignKey("unified_claims.claim_id"), nullable=False
        ),
        sa.Column("outcome", sa.String(24), nullable=False),
        sa.Column("state", sa.String(32), nullable=False),
        sa.Column("supporting_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("resolving_source_ids", sa.JSON(), nullable=False),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rationale", sa.Text(), nullable=False),
    )
    op.create_table(
        "claim_contradictions",
        sa.Column("contradiction_id", sa.String(96), primary_key=True),
        sa.Column(
            "claim_id", sa.String(96), sa.ForeignKey("unified_claims.claim_id"), nullable=False
        ),
        sa.Column("proposition_a", sa.Text(), nullable=False),
        sa.Column("proposition_b", sa.Text(), nullable=False),
        sa.Column("evidence_a", sa.JSON(), nullable=False),
        sa.Column("evidence_b", sa.JSON(), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("resolution_status", sa.String(24), nullable=False),
        sa.Column("ambiguity", sa.Text(), nullable=False),
    )
    op.create_table(
        "fusion_scores",
        sa.Column("score_id", sa.String(96), primary_key=True),
        sa.Column(
            "claim_id", sa.String(96), sa.ForeignKey("unified_claims.claim_id"), nullable=False
        ),
        sa.Column("source_authority", sa.Float(), nullable=False),
        sa.Column("independence", sa.Float(), nullable=False),
        sa.Column("corroboration_count", sa.Float(), nullable=False),
        sa.Column("provenance_completeness", sa.Float(), nullable=False),
        sa.Column("contradiction_burden", sa.Float(), nullable=False),
        sa.Column("temporal_consistency", sa.Float(), nullable=False),
        sa.Column("historical_reputation", sa.Float(), nullable=False),
        sa.Column("calculated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "fusion_reputation_snapshots",
        sa.Column("snapshot_id", sa.String(96), primary_key=True),
        sa.Column("source_id", sa.String(256), nullable=False),
        sa.Column("domain", sa.String(32), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claims_originated", sa.Integer(), nullable=False),
        sa.Column("confirmed", sa.Integer(), nullable=False),
        sa.Column("contradicted", sa.Integer(), nullable=False),
        sa.Column("unresolved", sa.Integer(), nullable=False),
        sa.Column("precision_resolved", sa.Float(), nullable=False),
        sa.Column("median_confirmation_lead_seconds", sa.Integer()),
        sa.Column("contradiction_rate", sa.Float(), nullable=False),
        sa.Column("copy_forward_rate", sa.Float(), nullable=False),
        sa.Column("original_content_rate", sa.Float(), nullable=False),
        sa.Column("sample_size", sa.Integer(), nullable=False),
        sa.Column("uncertainty", sa.String(128), nullable=False),
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
