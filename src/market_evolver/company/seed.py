"""Small reviewed company universe seed and knowledge-graph links."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy.orm import Session

from market_evolver.company.repositories import SqlCompanyRepository
from market_evolver.company.schemas import CompanyStatus, CompanyVersion, Listing
from market_evolver.knowledge.repositories import SqlKnowledgeGraph
from market_evolver.knowledge.schemas import (
    EntityVersion,
    ExternalIdentifier,
    KnowledgeEntityType,
    RecordStatus,
    Relationship,
    RelationType,
)

SEED_AT = datetime(2025, 1, 1, tzinfo=UTC)
LISTED_FROM = datetime(2000, 1, 1, tzinfo=UTC)
PROVENANCE = ("seed:marketevolver:company-universe:v0.8",)

_COMPANIES = (
    ("bank.leumi", "Bank Leumi le-Israel B.M.", "בנק לאומי", "LUMI", "sector.banks", None, None),
    ("bank.hapoalim", "Bank Hapoalim B.M.", "בנק הפועלים", "POLI", "sector.banks", None, None),
    (
        "azrieli.group",
        "Azrieli Group Ltd.",
        "קבוצת עזריאלי",
        "AZRG",
        "sector.real_estate",
        None,
        None,
    ),
    ("melisron", "Melisron Ltd.", "מליסרון", "MLSR", "sector.real_estate", None, None),
    ("nice", "NICE Ltd.", "נייס", "NICE", "sector.technology", "NICE", "0001003935"),
    (
        "elbit.systems",
        "Elbit Systems Ltd.",
        "אלביט מערכות",
        "ESLT",
        "sector.defense",
        "ESLT",
        "0001027664",
    ),
    (
        "newmed.energy",
        "NewMed Energy – Limited Partnership",
        "ניו-מד אנרג'י",
        "NWMD",
        "sector.energy",
        None,
        None,
    ),
    ("shufersal", "Shufersal Ltd.", "שופרסל", "SAE", "sector.retail", None, None),
    (
        "teva",
        "Teva Pharmaceutical Industries Ltd.",
        "טבע",
        "TEVA",
        "sector.pharmaceuticals",
        "TEVA",
        "0000818686",
    ),
    ("icl", "ICL Group Ltd.", "איי.סי.אל", "ICL", "sector.industrials", "ICL", "0000941221"),
)


def seed_companies(session: Session, *, observed_at: datetime = SEED_AT) -> tuple[int, int, int]:
    companies = SqlCompanyRepository(session)
    graph = SqlKnowledgeGraph(session)
    company_count = entity_count = relationship_count = 0
    for company_id, name, hebrew, tase, sector, nyse, cik in _COMPANIES:
        listings = [Listing(tase, "XTAE", LISTED_FROM)]
        if nyse:
            listings.append(Listing(nyse, "XNYS", LISTED_FROM))
        identifiers = tuple(
            item
            for item in (("SEC-CIK", cik) if cik else None, ("TASE-TICKER", tase))
            if item is not None
        )
        company = CompanyVersion(
            company_id=company_id,
            legal_name=name,
            hebrew_name=hebrew,
            english_name=name,
            aliases=(tase, hebrew),
            listings=tuple(listings),
            isin=None,
            sector_id=sector,
            industry_id=None,
            domicile="IL",
            status=CompanyStatus.ACTIVE,
            dual_listed=nyse is not None,
            identifiers=identifiers,
            provenance=PROVENANCE,
            valid_from=LISTED_FROM,
            valid_until=None,
            observed_at=observed_at,
            version=1,
        )
        _, created = companies.add_company(company)
        company_count += int(created)
        entity = EntityVersion(
            entity_id=f"company.{company_id}",
            canonical_name=name,
            aliases=(tase, hebrew),
            hebrew_name=hebrew,
            english_name=name,
            entity_type=KnowledgeEntityType.COMPANY,
            geography=("IL",),
            identifiers=tuple(ExternalIdentifier(scheme, value) for scheme, value in identifiers),
            active_from=LISTED_FROM,
            active_until=None,
            observed_at=observed_at,
            provenance=PROVENANCE,
            confidence=1.0,
            version=1,
        )
        _, created = graph.add_entity(entity)
        entity_count += int(created)
        targets = (sector, "exchange.tase", "country.il")
        types = (RelationType.BELONGS_TO, RelationType.LISTED_ON, RelationType.OPERATES_IN)
        for relation_type, target in zip(types, targets, strict=True):
            _, created = graph.add_relationship(
                Relationship(
                    relation_type=relation_type,
                    source_entity=entity.entity_id,
                    target_entity=target,
                    valid_from=LISTED_FROM,
                    valid_until=None,
                    observed_at=observed_at,
                    confidence=1.0,
                    provenance=PROVENANCE,
                    status=RecordStatus.ACTIVE,
                    version=1,
                )
            )
            relationship_count += int(created)
    session.flush()
    return company_count, entity_count, relationship_count
