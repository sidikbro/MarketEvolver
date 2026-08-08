"""Social and Narrative Intelligence Foundation

Revision ID: 0012
Revises: 0011
"""

import sqlalchemy as sa
from alembic import op

revision = "0012"
down_revision = "0011"
branch_labels = None
depends_on = None
TABLES = (
    "social_sources",
    "social_posts",
    "narrative_candidates",
    "rumor_claims",
    "social_propagation_edges",
    "coordination_candidates",
    "social_reputation_snapshots",
)


def upgrade():
    op.create_table(
        "social_sources",
        sa.Column("source_id", sa.String(96), primary_key=True),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("native_source_id", sa.String(256), nullable=False),
        sa.Column("display_name", sa.String(256), nullable=False),
        sa.Column("canonical_uri", sa.String(2048)),
        sa.Column("languages", sa.JSON(), nullable=False),
        sa.Column("geography", sa.JSON(), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True)),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verification_state", sa.String(32), nullable=False),
        sa.Column("accessibility", sa.String(16), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.UniqueConstraint("platform", "native_source_id", name="uq_social_source_identity"),
    )
    op.create_table(
        "social_posts",
        sa.Column("post_id", sa.String(96), primary_key=True),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column(
            "source_id", sa.String(96), sa.ForeignKey("social_sources.source_id"), nullable=False
        ),
        sa.Column("native_post_id", sa.String(256), nullable=False),
        sa.Column("thread_parent_id", sa.String(96)),
        sa.Column("reply_parent_id", sa.String(96)),
        sa.Column("posted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("edited_at", sa.DateTime(timezone=True)),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
        sa.Column("original_text", sa.Text(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("urls", sa.JSON(), nullable=False),
        sa.Column("mentions", sa.JSON(), nullable=False),
        sa.Column("quoted_source_id", sa.String(96)),
        sa.Column("metrics", sa.JSON(), nullable=False),
        sa.Column("raw_artifact_sha256", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(71), nullable=False),
        sa.Column("media_references", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("revision_of", sa.String(96), sa.ForeignKey("social_posts.post_id")),
    )
    op.create_table(
        "narrative_candidates",
        sa.Column("candidate_id", sa.String(96), primary_key=True),
        sa.Column("topics", sa.JSON(), nullable=False),
        sa.Column("entities", sa.JSON(), nullable=False),
        sa.Column("supporting_post_ids", sa.JSON(), nullable=False),
        sa.Column("earliest_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("proposition", sa.Text(), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("extraction_method", sa.String(64), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("corroboration_state", sa.String(32), nullable=False),
        sa.Column("contradiction_state", sa.String(32), nullable=False),
        sa.Column("lifecycle_state", sa.String(16), nullable=False),
        sa.Column("reviewed", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "rumor_claims",
        sa.Column("claim_id", sa.String(96), primary_key=True),
        sa.Column("proposition", sa.Text(), nullable=False),
        sa.Column("entities", sa.JSON(), nullable=False),
        sa.Column("origin_post_id", sa.String(96), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("supporting_post_ids", sa.JSON(), nullable=False),
        sa.Column("contradicting_post_ids", sa.JSON(), nullable=False),
        sa.Column("official_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("news_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("revision_of", sa.String(96), sa.ForeignKey("rumor_claims.claim_id")),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_table(
        "social_propagation_edges",
        sa.Column("edge_id", sa.String(96), primary_key=True),
        sa.Column(
            "source_post_id", sa.String(96), sa.ForeignKey("social_posts.post_id"), nullable=False
        ),
        sa.Column(
            "target_post_id", sa.String(96), sa.ForeignKey("social_posts.post_id"), nullable=False
        ),
        sa.Column("relation", sa.String(32), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
    )
    op.create_table(
        "coordination_candidates",
        sa.Column("coordination_candidate_id", sa.String(96), primary_key=True),
        sa.Column("post_ids", sa.JSON(), nullable=False),
        sa.Column("source_ids", sa.JSON(), nullable=False),
        sa.Column("features", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
    )
    op.create_table(
        "social_reputation_snapshots",
        sa.Column("snapshot_id", sa.String(96), primary_key=True),
        sa.Column(
            "source_id", sa.String(96), sa.ForeignKey("social_sources.source_id"), nullable=False
        ),
        sa.Column("domain", sa.String(32), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("computed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claims_originated", sa.Integer(), nullable=False),
        sa.Column("confirmed", sa.Integer(), nullable=False),
        sa.Column("contradicted", sa.Integer(), nullable=False),
        sa.Column("unresolved", sa.Integer(), nullable=False),
        sa.Column("median_confirmation_lead_seconds", sa.Integer()),
        sa.Column("copy_rate", sa.Float(), nullable=False),
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
