import hashlib
import unittest
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from market_evolver.company.repositories import SqlCompanyRepository, derive_metrics
from market_evolver.company.schemas import (
    CompanyExposure,
    CompanyExposureType,
    CompanyStatus,
    CompanyVersion,
    Filing,
    FilingType,
    FundamentalObservation,
    FundamentalType,
    Listing,
    RestatementStatus,
)
from market_evolver.company.sec import SecEdgarConnector
from market_evolver.company.seed import seed_companies
from market_evolver.errors import ImmutableRecordError, IntegrityViolation, ValidationError
from market_evolver.knowledge.repositories import SqlKnowledgeGraph
from market_evolver.knowledge.schemas import (
    EntityVersion,
    KnowledgeEntityType,
    ResolutionStatus,
)
from market_evolver.knowledge.seed import seed_knowledge_graph
from market_evolver.schemas import Evidence, Source, SourceKind, TrustLevel
from market_evolver.storage.models import ArtifactModel, Base, CompanyModel
from market_evolver.storage.repositories import SqlEvidenceRepository, SqlSourceRepository

T1 = datetime(2025, 1, 1, tzinfo=UTC)
T2 = T1 + timedelta(days=1)
FY_START = date(2024, 1, 1)
FY_END = date(2024, 12, 31)


class CompanyFundamentalsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine("sqlite+pysqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.session = Session(self.engine)
        seed_knowledge_graph(self.session)
        self.repository = SqlCompanyRepository(self.session)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()

    def company(self, **changes) -> CompanyVersion:
        values = {
            "company_id": "test.company",
            "legal_name": "Test Company Ltd.",
            "hebrew_name": "חברת בדיקה",
            "english_name": "Test Company Ltd.",
            "aliases": ("TEST", "חברת בדיקה"),
            "listings": (Listing("TEST", "XTAE", T1),),
            "isin": "IL0000000001",
            "sector_id": "sector.technology",
            "industry_id": None,
            "domicile": "IL",
            "status": CompanyStatus.ACTIVE,
            "dual_listed": False,
            "identifiers": (("TASE-TICKER", "TEST"),),
            "provenance": ("test-seed",),
            "valid_from": T1,
            "valid_until": None,
            "observed_at": T1,
            "version": 1,
        }
        values.update(changes)
        return CompanyVersion(**values)

    def evidence_and_artifact(self, at: datetime) -> tuple[Evidence, str]:
        body = f"filing-{at.isoformat()}".encode()
        digest = hashlib.sha256(body).hexdigest()
        self.session.add(
            ArtifactModel(
                sha256=digest,
                size_bytes=len(body),
                mime_type="application/json",
                relative_path=f"test/{digest}",
                created_at=at,
            )
        )
        source = Source(
            uri=f"https://example.test/{digest}",
            kind=SourceKind.RESEARCH,
            publisher="Official filing source",
            published_at=at,
            observed_at=at,
            ingested_at=at,
            trust=TrustLevel.AUTHORITATIVE,
            content_digest=f"sha256:{digest}",
            mime_type="application/json",
        )
        SqlSourceRepository(self.session).add(source)
        evidence = Evidence(
            claim="Official filing",
            source_ids=(source.provenance_id,),
            observed_at=at,
            excerpt_digest=f"sha256:{digest}",
        )
        SqlEvidenceRepository(self.session).add(evidence)
        return evidence, digest

    def filing(self, company: CompanyVersion, at: datetime = T1, **changes) -> Filing:
        evidence, digest = self.evidence_and_artifact(at)
        values = {
            "company_id": company.company_id,
            "filing_type": FilingType.ANNUAL_REPORT,
            "form_type": "20-F",
            "accession_number": f"0001-{int(at.timestamp())}",
            "source_uri": "https://sec.gov/filing",
            "filed_at": at,
            "first_observed_at": at,
            "fiscal_period_start": FY_START,
            "fiscal_period_end": FY_END,
            "raw_artifact_sha256": digest,
            "source_evidence_ids": (evidence.provenance_id,),
            "parser_version": "test/1",
        }
        values.update(changes)
        return Filing(**values)

    def fact(
        self,
        company: CompanyVersion,
        filing: Filing,
        metric: FundamentalType,
        value: str,
        at: datetime = T1,
        **changes,
    ) -> FundamentalObservation:
        values = {
            "company_id": company.company_id,
            "filing_id": filing.filing_id,
            "metric": metric,
            "value": value,
            "currency": "USD",
            "unit": "USD",
            "fiscal_period_start": FY_START,
            "fiscal_period_end": FY_END,
            "published_at": at,
            "first_observed_at": at,
            "source_evidence_ids": filing.source_evidence_ids,
            "parser_version": "test/1",
        }
        values.update(changes)
        return FundamentalObservation(**values)

    def test_ticker_history_dual_listing_and_delisted_company(self) -> None:
        company = self.company(
            listings=(
                Listing("OLD", "XTAE", T1, T2),
                Listing("NEW", "XTAE", T2),
                Listing("NEW", "XNAS", T2),
            ),
            dual_listed=True,
        )
        self.repository.add_company(company)
        self.assertEqual(self.repository.get_company_at(company.company_id, T1), company)
        delisted = self.company(
            company_id="delisted.company",
            status=CompanyStatus.DELISTED,
            valid_until=T2,
        )
        self.repository.add_company(delisted)
        self.assertIsNone(self.repository.get_company_at(delisted.company_id, T2))

    def test_future_filing_and_restatement_do_not_leak(self) -> None:
        company = self.company()
        self.repository.add_company(company)
        filing = self.filing(company)
        self.repository.add_filing(filing)
        original = self.fact(company, filing, FundamentalType.REVENUE, "100")
        self.repository.add_fundamental(original)
        amended_filing = self.filing(
            company,
            T2,
            accession_number="0001-amended",
            restates_filing_id=filing.filing_id,
        )
        self.repository.add_filing(amended_filing)
        restated = self.fact(
            company,
            amended_filing,
            FundamentalType.REVENUE,
            "110",
            T2,
            restatement_status=RestatementStatus.RESTATED,
            restates_observation_id=original.observation_id,
        )
        self.repository.add_fundamental(restated)
        self.assertEqual(self.repository.get_fundamentals(company.company_id, T1), [original])
        self.assertEqual(self.repository.get_fundamentals(company.company_id, T2), [restated])
        self.assertEqual(self.repository.get_latest_filing(company.company_id, T1), filing)
        self.assertEqual(self.repository.get_latest_filing(company.company_id, T2), amended_filing)

    def test_units_fiscal_period_and_derived_ratio_provenance(self) -> None:
        company = self.company()
        self.repository.add_company(company)
        filing = self.filing(company)
        self.repository.add_filing(filing)
        revenue = self.fact(company, filing, FundamentalType.REVENUE, "200")
        income = self.fact(company, filing, FundamentalType.OPERATING_INCOME, "50")
        debt = self.fact(company, filing, FundamentalType.DEBT, "80")
        cash = self.fact(company, filing, FundamentalType.CASH, "20")
        for fact in (revenue, income, debt, cash):
            self.repository.add_fundamental(fact)
        derived = derive_metrics((revenue, income, debt, cash))
        self.assertEqual({item.metric for item in derived}, {"operating_margin", "net_debt"})
        margin = next(item for item in derived if item.metric == "operating_margin")
        self.assertEqual(margin.value, "0.25")
        self.assertEqual(
            set(margin.input_observation_ids), {revenue.observation_id, income.observation_id}
        )
        with self.assertRaises(ValidationError):
            replace(revenue, fiscal_period_start=date(2025, 1, 1))
        incompatible_cash = replace(cash, currency="ILS", value="10")
        incompatible = derive_metrics((debt, incompatible_cash))
        self.assertEqual(incompatible, ())

    def test_growth_uses_distinct_periods_and_preserves_inputs(self) -> None:
        company = self.company()
        self.repository.add_company(company)
        first_filing = self.filing(company)
        self.repository.add_filing(first_filing)
        first = self.fact(company, first_filing, FundamentalType.REVENUE, "100")
        next_release = datetime(2026, 1, 2, tzinfo=UTC)
        second_filing = self.filing(
            company,
            next_release,
            fiscal_period_start=date(2025, 1, 1),
            fiscal_period_end=date(2025, 12, 31),
        )
        self.repository.add_filing(second_filing)
        second = self.fact(
            company,
            second_filing,
            FundamentalType.REVENUE,
            "125",
            next_release,
            fiscal_period_start=date(2025, 1, 1),
            fiscal_period_end=date(2025, 12, 31),
        )
        growth = derive_metrics((first, second))
        self.assertEqual(len(growth), 1)
        self.assertEqual((growth[0].metric, growth[0].value), ("revenue_growth", "0.25"))
        self.assertEqual(
            growth[0].input_observation_ids,
            (first.observation_id, second.observation_id),
        )

    def test_exposure_versioning_and_no_vague_numeric_inference(self) -> None:
        company = self.company()
        self.repository.add_company(company)
        evidence, _ = self.evidence_and_artifact(T1)
        first = CompanyExposure(
            company_id=company.company_id,
            exposure_type=CompanyExposureType.FOREIGN_CURRENCY_REVENUE,
            target="currency.usd",
            value=None,
            unit=None,
            valid_from=T1,
            valid_until=T2,
            first_observed_at=T1,
            source_evidence_ids=(evidence.provenance_id,),
            version=1,
        )
        second = replace(first, valid_from=T2, valid_until=None, first_observed_at=T2, version=2)
        self.repository.add_exposure(first)
        self.repository.add_exposure(second)
        self.assertEqual(self.repository.get_exposures(company.company_id, T1), [first])
        self.assertEqual(self.repository.get_exposures(company.company_id, T2), [second])
        with self.assertRaises(ValidationError):
            replace(first, value="50")

    def test_duplicate_and_malformed_filing(self) -> None:
        company = self.company()
        self.repository.add_company(company)
        filing = self.filing(company)
        self.assertTrue(self.repository.add_filing(filing)[1])
        self.assertFalse(self.repository.add_filing(filing)[1])
        with self.assertRaises(ValidationError):
            replace(filing, fiscal_period_start=date(2025, 1, 1))

    def test_seed_and_ambiguous_company_alias(self) -> None:
        count, entities, relationships = seed_companies(self.session)
        self.assertEqual((count, entities, relationships), (10, 10, 30))
        graph = SqlKnowledgeGraph(self.session)
        resolution = graph.resolve_alias("NICE", T1)
        self.assertEqual(resolution.status, ResolutionStatus.RESOLVED)
        duplicate = self.company(
            company_id="other.nice",
            aliases=("NICE",),
            listings=(Listing("OTHER", "XTAE", T1),),
        )
        self.repository.add_company(duplicate)
        graph.add_entity(
            EntityVersion(
                entity_id="company.other.nice",
                canonical_name="Other NICE",
                aliases=("NICE",),
                hebrew_name=None,
                english_name="Other NICE",
                entity_type=KnowledgeEntityType.COMPANY,
                geography=("IL",),
                identifiers=(),
                active_from=T1,
                active_until=None,
                observed_at=T1,
                provenance=("test",),
                confidence=1.0,
                version=1,
            )
        )
        self.assertEqual(graph.resolve_alias("NICE", T1).status, ResolutionStatus.AMBIGUOUS)

    def test_append_only_company_mutation(self) -> None:
        company = self.company()
        self.repository.add_company(company)
        model = self.session.get(CompanyModel, company.company_version_id)
        assert model is not None
        model.legal_name = "mutated"
        with self.assertRaises(ImmutableRecordError):
            self.session.flush()


class SecConnectorTests(unittest.TestCase):
    def test_narrow_sec_metadata_and_fact_parsing(self) -> None:
        connector = SecEdgarConnector("MarketEvolver test@example.com")
        filings = connector.parse_filings(
            b'{"filings":{"recent":{"accessionNumber":["1"],"filingDate":["2025-01-02"],'
            b'"reportDate":["2024-12-31"],"form":["20-F"],"primaryDocument":["a.htm"]}}}'
        )
        self.assertEqual(filings[0].form_type, "20-F")
        facts = connector.parse_facts(
            b'{"facts":{"us-gaap":{"Revenues":{"units":{"USD":[{"val":100,"end":'
            b'"2024-12-31","filed":"2025-01-02","accn":"1","form":"20-F"}]}}}}}'
        )
        self.assertEqual(facts[0].value, "100")
        with self.assertRaises(IntegrityViolation):
            connector.parse_filings(
                b'{"filings":{"recent":{"accessionNumber":["1"],"filingDate":["bad"],'
                b'"reportDate":["2024-12-31"],"form":["20-F"],"primaryDocument":["a.htm"]}}}'
            )
        with self.assertRaises(ValidationError):
            connector.fetch_submissions("123")


if __name__ == "__main__":
    unittest.main()
