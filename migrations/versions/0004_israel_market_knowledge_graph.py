"""Israel market knowledge graph and database immutability

Revision ID: 0004
Revises: 0003
"""

import sqlalchemy as sa
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

_APPEND_ONLY_TABLES = (
    "artifacts",
    "sources",
    "evidence",
    "events",
    "hypotheses",
    "research_decisions",
    "raw_ingestions",
    "normalized_observations",
    "canonical_events",
    "event_support",
    "event_transitions",
    "event_mechanism_links",
    "knowledge_entities",
    "knowledge_aliases",
    "knowledge_relationships",
    "knowledge_exposures",
)


def upgrade() -> None:
    op.create_table(
        "knowledge_entities",
        sa.Column("entity_version_id", sa.String(96), primary_key=True),
        sa.Column("entity_id", sa.String(128), nullable=False),
        sa.Column("canonical_name", sa.String(512), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("hebrew_name", sa.String(512)),
        sa.Column("english_name", sa.String(512), nullable=False),
        sa.Column("entity_type", sa.String(32), nullable=False),
        sa.Column("geography", sa.JSON(), nullable=False),
        sa.Column("identifiers", sa.JSON(), nullable=False),
        sa.Column("active_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("active_until", sa.DateTime(timezone=True)),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("entity_id", "version", name="uq_knowledge_entity_version"),
    )
    op.create_index("ix_knowledge_entities_entity_id", "knowledge_entities", ["entity_id"])
    op.create_index("ix_knowledge_entities_entity_type", "knowledge_entities", ["entity_type"])
    op.create_index("ix_knowledge_entities_observed_at", "knowledge_entities", ["observed_at"])
    op.create_table(
        "knowledge_aliases",
        sa.Column("alias_id", sa.String(96), primary_key=True),
        sa.Column("alias", sa.String(512), nullable=False),
        sa.Column("normalized_alias", sa.String(512), nullable=False),
        sa.Column(
            "entity_version_id",
            sa.String(96),
            sa.ForeignKey("knowledge_entities.entity_version_id"),
            nullable=False,
        ),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
    )
    op.create_index(
        "ix_knowledge_aliases_normalized_alias",
        "knowledge_aliases",
        ["normalized_alias"],
    )
    op.create_index(
        "ix_knowledge_aliases_entity_version_id",
        "knowledge_aliases",
        ["entity_version_id"],
    )
    op.create_index("ix_knowledge_aliases_observed_at", "knowledge_aliases", ["observed_at"])
    op.create_table(
        "knowledge_relationships",
        sa.Column("relationship_id", sa.String(96), primary_key=True),
        sa.Column("relation_type", sa.String(32), nullable=False),
        sa.Column("source_entity", sa.String(128), nullable=False),
        sa.Column("target_entity", sa.String(128), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "source_entity",
            "target_entity",
            "relation_type",
            "version",
            name="uq_knowledge_relationship_version",
        ),
    )
    op.create_index(
        "ix_knowledge_relationships_relation_type",
        "knowledge_relationships",
        ["relation_type"],
    )
    op.create_index(
        "ix_knowledge_relationships_source_entity",
        "knowledge_relationships",
        ["source_entity"],
    )
    op.create_index(
        "ix_knowledge_relationships_target_entity",
        "knowledge_relationships",
        ["target_entity"],
    )
    op.create_index(
        "ix_knowledge_relationships_observed_at",
        "knowledge_relationships",
        ["observed_at"],
    )
    op.create_table(
        "knowledge_exposures",
        sa.Column("exposure_id", sa.String(96), primary_key=True),
        sa.Column("exposure_type", sa.String(32), nullable=False),
        sa.Column("subject_entity", sa.String(128), nullable=False),
        sa.Column("target_entity", sa.String(128), nullable=False),
        sa.Column("direction", sa.String(24), nullable=False),
        sa.Column("strength", sa.String(16), nullable=False),
        sa.Column("unit", sa.String(64)),
        sa.Column("value", sa.String(128)),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_until", sa.DateTime(timezone=True)),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source_evidence", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint(
            "subject_entity",
            "target_entity",
            "exposure_type",
            "version",
            name="uq_knowledge_exposure_version",
        ),
    )
    op.create_index(
        "ix_knowledge_exposures_exposure_type",
        "knowledge_exposures",
        ["exposure_type"],
    )
    op.create_index(
        "ix_knowledge_exposures_subject_entity",
        "knowledge_exposures",
        ["subject_entity"],
    )
    op.create_index(
        "ix_knowledge_exposures_target_entity",
        "knowledge_exposures",
        ["target_entity"],
    )
    op.create_index(
        "ix_knowledge_exposures_observed_at",
        "knowledge_exposures",
        ["observed_at"],
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION marketevolver_reject_immutable_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION
                'UPDATE/DELETE forbidden on append-only table %', TG_TABLE_NAME
                USING ERRCODE = '55000';
        END;
        $$
        """
    )
    for table in _APPEND_ONLY_TABLES:
        op.execute(
            f"""
            CREATE TRIGGER trg_{table}_append_only
            BEFORE UPDATE OR DELETE ON {table}
            FOR EACH ROW
            EXECUTE FUNCTION marketevolver_reject_immutable_mutation()
            """
        )


def downgrade() -> None:
    for table in reversed(_APPEND_ONLY_TABLES):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON {table}")
    op.execute("DROP FUNCTION IF EXISTS marketevolver_reject_immutable_mutation()")
    op.drop_table("knowledge_exposures")
    op.drop_table("knowledge_relationships")
    op.drop_table("knowledge_aliases")
    op.drop_table("knowledge_entities")
