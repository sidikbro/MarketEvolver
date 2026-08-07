"""Company universe and fundamentals

Revision ID: 0007
Revises: 0006
"""

import sqlalchemy as sa
from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

_TABLES = (
    "companies",
    "filings",
    "fundamentals",
    "derived_fundamentals",
    "company_exposures",
)


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("company_version_id", sa.String(96), primary_key=True),
        sa.Column("company_id", sa.String(128), nullable=False),
        sa.Column("legal_name", sa.String(512), nullable=False),
        sa.Column("hebrew_name", sa.String(512)),
        sa.Column("english_name", sa.String(512), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=False),
        sa.Column("listings", sa.JSON(), nullable=False),
        sa.Column("isin", sa.String(32)),
        sa.Column("sector_id", sa.String(128), nullable=False),
        sa.Column("industry_id", sa.String(128)),
        sa.Column("domicile", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("dual_listed", sa.Boolean(), nullable=False),
        sa.Column("identifiers", sa.JSON(), nullable=False),
        sa.Column("provenance", sa.JSON(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_index("ix_companies_company_id", "companies", ["company_id"])
    op.create_index("ix_companies_isin", "companies", ["isin"])
    op.create_table(
        "filings",
        sa.Column("filing_id", sa.String(96), primary_key=True),
        sa.Column("company_id", sa.String(128), nullable=False),
        sa.Column("filing_type", sa.String(32), nullable=False),
        sa.Column("form_type", sa.String(32), nullable=False),
        sa.Column("accession_number", sa.String(64), nullable=False, unique=True),
        sa.Column("source_uri", sa.String(2048), nullable=False),
        sa.Column("filed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("fiscal_period_start", sa.Date(), nullable=False),
        sa.Column("fiscal_period_end", sa.Date(), nullable=False),
        sa.Column(
            "raw_artifact_sha256",
            sa.String(64),
            sa.ForeignKey("artifacts.sha256"),
            nullable=False,
        ),
        sa.Column("source_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=False),
        sa.Column("restates_filing_id", sa.String(96), sa.ForeignKey("filings.filing_id")),
    )
    op.create_index("ix_filings_company_id", "filings", ["company_id"])
    op.create_table(
        "fundamentals",
        sa.Column("observation_id", sa.String(96), primary_key=True),
        sa.Column("company_id", sa.String(128), nullable=False),
        sa.Column("filing_id", sa.String(96), sa.ForeignKey("filings.filing_id"), nullable=False),
        sa.Column("metric", sa.String(32), nullable=False),
        sa.Column("value", sa.String(128), nullable=False),
        sa.Column("currency", sa.String(8)),
        sa.Column("unit", sa.String(64), nullable=False),
        sa.Column("fiscal_period_start", sa.Date(), nullable=False),
        sa.Column("fiscal_period_end", sa.Date(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("parser_version", sa.String(64), nullable=False),
        sa.Column("restatement_status", sa.String(16), nullable=False),
        sa.Column(
            "restates_observation_id",
            sa.String(96),
            sa.ForeignKey("fundamentals.observation_id"),
        ),
        sa.Column("dimensions", sa.JSON(), nullable=False),
    )
    op.create_index("ix_fundamentals_company_id", "fundamentals", ["company_id"])
    op.create_table(
        "derived_fundamentals",
        sa.Column("derived_id", sa.String(96), primary_key=True),
        sa.Column("company_id", sa.String(128), nullable=False),
        sa.Column("metric", sa.String(32), nullable=False),
        sa.Column("value", sa.String(128), nullable=False),
        sa.Column("unit", sa.String(64), nullable=False),
        sa.Column("fiscal_period_end", sa.Date(), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("input_observation_ids", sa.JSON(), nullable=False),
        sa.Column("formula_version", sa.String(64), nullable=False),
    )
    op.create_index("ix_derived_fundamentals_company_id", "derived_fundamentals", ["company_id"])
    op.create_table(
        "company_exposures",
        sa.Column("exposure_id", sa.String(96), primary_key=True),
        sa.Column("company_id", sa.String(128), nullable=False),
        sa.Column("exposure_type", sa.String(32), nullable=False),
        sa.Column("target", sa.String(128), nullable=False),
        sa.Column("value", sa.String(128)),
        sa.Column("unit", sa.String(64)),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True)),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source_evidence_ids", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_index("ix_company_exposures_company_id", "company_exposures", ["company_id"])
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
