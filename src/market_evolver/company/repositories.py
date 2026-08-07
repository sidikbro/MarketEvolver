"""Point-in-time company, filing, fundamental, ratio, and exposure persistence."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from market_evolver.company.schemas import (
    CompanyExposure,
    CompanyExposureType,
    CompanyStatus,
    CompanyVersion,
    DerivedMetric,
    Filing,
    FilingType,
    FundamentalObservation,
    FundamentalType,
    Listing,
    RestatementStatus,
)
from market_evolver.errors import IntegrityViolation
from market_evolver.storage.models import (
    ArtifactModel,
    CompanyExposureModel,
    CompanyModel,
    DerivedFundamentalModel,
    EvidenceModel,
    FilingModel,
    FundamentalModel,
)
from market_evolver.time import require_aware_utc


class SqlCompanyRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_company(self, company: CompanyVersion) -> tuple[CompanyVersion, bool]:
        existing = self.session.get(CompanyModel, company.company_version_id)
        if existing is not None:
            restored = self._company(existing)
            if restored != company:
                raise IntegrityViolation("immutable company identity collision")
            return restored, False
        latest = self.session.scalar(
            select(CompanyModel)
            .where(CompanyModel.company_id == company.company_id)
            .order_by(CompanyModel.version.desc())
            .limit(1)
        )
        if latest is not None and company.version != latest.version + 1:
            raise IntegrityViolation("company versions must be sequential")
        self.session.add(
            CompanyModel(
                company_version_id=company.company_version_id,
                company_id=company.company_id,
                legal_name=company.legal_name,
                hebrew_name=company.hebrew_name,
                english_name=company.english_name,
                aliases=list(company.aliases),
                listings=[
                    {
                        "ticker": item.ticker,
                        "exchange": item.exchange,
                        "valid_from": item.valid_from.isoformat(),
                        "valid_until": (
                            None if item.valid_until is None else item.valid_until.isoformat()
                        ),
                    }
                    for item in company.listings
                ],
                isin=company.isin,
                sector_id=company.sector_id,
                industry_id=company.industry_id,
                domicile=company.domicile,
                status=company.status.value,
                dual_listed=company.dual_listed,
                identifiers=[list(item) for item in company.identifiers],
                provenance=list(company.provenance),
                valid_from=company.valid_from,
                valid_until=company.valid_until,
                observed_at=company.observed_at,
                version=company.version,
            )
        )
        self.session.flush()
        return company, True

    def add_filing(self, filing: Filing) -> tuple[Filing, bool]:
        existing = self.session.get(FilingModel, filing.filing_id)
        if existing is not None:
            return self._filing(existing), False
        if self.get_company_at(filing.company_id, filing.first_observed_at) is None:
            raise IntegrityViolation("filing references unknown company")
        if self.session.get(ArtifactModel, filing.raw_artifact_sha256) is None:
            raise IntegrityViolation("filing references unknown raw artifact")
        self._evidence(filing.source_evidence_ids, filing.first_observed_at)
        if (
            filing.restates_filing_id
            and self.session.get(FilingModel, filing.restates_filing_id) is None
        ):
            raise IntegrityViolation("restatement references unknown filing")
        self.session.add(
            FilingModel(
                filing_id=filing.filing_id,
                company_id=filing.company_id,
                filing_type=filing.filing_type.value,
                form_type=filing.form_type,
                accession_number=filing.accession_number,
                source_uri=filing.source_uri,
                filed_at=filing.filed_at,
                first_observed_at=filing.first_observed_at,
                fiscal_period_start=filing.fiscal_period_start,
                fiscal_period_end=filing.fiscal_period_end,
                raw_artifact_sha256=filing.raw_artifact_sha256,
                source_evidence_ids=list(filing.source_evidence_ids),
                parser_version=filing.parser_version,
                restates_filing_id=filing.restates_filing_id,
            )
        )
        self.session.flush()
        return filing, True

    def add_fundamental(
        self, observation: FundamentalObservation
    ) -> tuple[FundamentalObservation, bool]:
        existing = self.session.get(FundamentalModel, observation.observation_id)
        if existing is not None:
            return self._fundamental(existing), False
        filing = self.session.get(FilingModel, observation.filing_id)
        if filing is None or filing.company_id != observation.company_id:
            raise IntegrityViolation("fundamental filing/company mismatch")
        self._evidence(observation.source_evidence_ids, observation.first_observed_at)
        if (
            observation.restates_observation_id
            and self.session.get(FundamentalModel, observation.restates_observation_id) is None
        ):
            raise IntegrityViolation("fundamental restates unknown observation")
        self.session.add(
            FundamentalModel(
                observation_id=observation.observation_id,
                company_id=observation.company_id,
                filing_id=observation.filing_id,
                metric=observation.metric.value,
                value=observation.value,
                currency=observation.currency,
                unit=observation.unit,
                fiscal_period_start=observation.fiscal_period_start,
                fiscal_period_end=observation.fiscal_period_end,
                published_at=observation.published_at,
                first_observed_at=observation.first_observed_at,
                source_evidence_ids=list(observation.source_evidence_ids),
                parser_version=observation.parser_version,
                restatement_status=observation.restatement_status.value,
                restates_observation_id=observation.restates_observation_id,
                dimensions=[list(item) for item in observation.dimensions],
            )
        )
        self.session.flush()
        return observation, True

    def add_exposure(self, exposure: CompanyExposure) -> tuple[CompanyExposure, bool]:
        existing = self.session.get(CompanyExposureModel, exposure.exposure_id)
        if existing is not None:
            return self._exposure(existing), False
        if self.get_company_at(exposure.company_id, exposure.first_observed_at) is None:
            raise IntegrityViolation("exposure references unknown company")
        self._evidence(exposure.source_evidence_ids, exposure.first_observed_at)
        self.session.add(
            CompanyExposureModel(
                exposure_id=exposure.exposure_id,
                company_id=exposure.company_id,
                exposure_type=exposure.exposure_type.value,
                target=exposure.target,
                value=exposure.value,
                unit=exposure.unit,
                valid_from=exposure.valid_from,
                valid_until=exposure.valid_until,
                first_observed_at=exposure.first_observed_at,
                source_evidence_ids=list(exposure.source_evidence_ids),
                version=exposure.version,
            )
        )
        self.session.flush()
        return exposure, True

    def add_derived(self, metric: DerivedMetric) -> tuple[DerivedMetric, bool]:
        existing = self.session.get(DerivedFundamentalModel, metric.derived_id)
        if existing is not None:
            return self._derived(existing), False
        inputs = [self.session.get(FundamentalModel, item) for item in metric.input_observation_ids]
        if any(item is None for item in inputs):
            raise IntegrityViolation("derived metric references unknown fundamentals")
        self.session.add(
            DerivedFundamentalModel(
                derived_id=metric.derived_id,
                company_id=metric.company_id,
                metric=metric.metric,
                value=metric.value,
                unit=metric.unit,
                fiscal_period_end=metric.fiscal_period_end,
                first_observed_at=metric.first_observed_at,
                input_observation_ids=list(metric.input_observation_ids),
                formula_version=metric.formula_version,
            )
        )
        self.session.flush()
        return metric, True

    def get_company_at(self, company_id: str, cutoff: datetime) -> CompanyVersion | None:
        at = require_aware_utc(cutoff, "cutoff")
        model = self.session.scalar(
            select(CompanyModel)
            .where(
                CompanyModel.company_id == company_id,
                CompanyModel.observed_at <= at,
                CompanyModel.valid_from <= at,
                or_(CompanyModel.valid_until.is_(None), CompanyModel.valid_until > at),
            )
            .order_by(CompanyModel.version.desc())
            .limit(1)
        )
        return None if model is None else self._company(model)

    def list_companies(self, cutoff: datetime) -> list[CompanyVersion]:
        ids = self.session.scalars(select(CompanyModel.company_id).distinct())
        return [
            company
            for company_id in sorted(ids)
            if (company := self.get_company_at(company_id, cutoff)) is not None
        ]

    def get_fundamentals(self, company_id: str, cutoff: datetime) -> list[FundamentalObservation]:
        at = require_aware_utc(cutoff, "cutoff")
        models = list(
            self.session.scalars(
                select(FundamentalModel)
                .where(
                    FundamentalModel.company_id == company_id,
                    FundamentalModel.first_observed_at <= at,
                )
                .order_by(FundamentalModel.first_observed_at)
            )
        )
        superseded = {
            item.restates_observation_id
            for item in models
            if item.restates_observation_id is not None
        }
        return [self._fundamental(item) for item in models if item.observation_id not in superseded]

    def get_latest_filing(self, company_id: str, cutoff: datetime) -> Filing | None:
        at = require_aware_utc(cutoff, "cutoff")
        model = self.session.scalar(
            select(FilingModel)
            .where(
                FilingModel.company_id == company_id,
                FilingModel.first_observed_at <= at,
            )
            .order_by(FilingModel.filed_at.desc(), FilingModel.filing_id.desc())
            .limit(1)
        )
        return None if model is None else self._filing(model)

    def list_filings(self, company_id: str, cutoff: datetime) -> list[Filing]:
        at = require_aware_utc(cutoff, "cutoff")
        return [
            self._filing(item)
            for item in self.session.scalars(
                select(FilingModel)
                .where(
                    FilingModel.company_id == company_id,
                    FilingModel.first_observed_at <= at,
                )
                .order_by(FilingModel.filed_at)
            )
        ]

    def get_exposures(self, company_id: str, cutoff: datetime) -> list[CompanyExposure]:
        at = require_aware_utc(cutoff, "cutoff")
        models = self.session.scalars(
            select(CompanyExposureModel).where(
                CompanyExposureModel.company_id == company_id,
                CompanyExposureModel.first_observed_at <= at,
                CompanyExposureModel.valid_from <= at,
                or_(
                    CompanyExposureModel.valid_until.is_(None),
                    CompanyExposureModel.valid_until > at,
                ),
            )
        )
        latest: dict[tuple[str, str], CompanyExposureModel] = {}
        for item in models:
            key = (item.exposure_type, item.target)
            if key not in latest or latest[key].version < item.version:
                latest[key] = item
        return [self._exposure(item) for _, item in sorted(latest.items())]

    def _evidence(self, ids: tuple[str, ...], at: datetime) -> None:
        evidence = [self.session.get(EvidenceModel, item) for item in ids]
        if any(item is None for item in evidence):
            raise IntegrityViolation("unknown company evidence")
        if any(_utc(item.observed_at) > at for item in evidence if item):
            raise IntegrityViolation("company record predates evidence")

    @staticmethod
    def _company(model: CompanyModel) -> CompanyVersion:
        return CompanyVersion(
            company_id=model.company_id,
            legal_name=model.legal_name,
            hebrew_name=model.hebrew_name,
            english_name=model.english_name,
            aliases=tuple(model.aliases),
            listings=tuple(
                Listing(
                    item["ticker"],
                    item["exchange"],
                    datetime.fromisoformat(item["valid_from"]),
                    (
                        None
                        if item["valid_until"] is None
                        else datetime.fromisoformat(item["valid_until"])
                    ),
                )
                for item in model.listings
            ),
            isin=model.isin,
            sector_id=model.sector_id,
            industry_id=model.industry_id,
            domicile=model.domicile,
            status=CompanyStatus(model.status),
            dual_listed=model.dual_listed,
            identifiers=tuple((item[0], item[1]) for item in model.identifiers),
            provenance=tuple(model.provenance),
            valid_from=_utc(model.valid_from),
            valid_until=_utc_optional(model.valid_until),
            observed_at=_utc(model.observed_at),
            version=model.version,
        )

    @staticmethod
    def _filing(model: FilingModel) -> Filing:
        return Filing(
            company_id=model.company_id,
            filing_type=FilingType(model.filing_type),
            form_type=model.form_type,
            accession_number=model.accession_number,
            source_uri=model.source_uri,
            filed_at=_utc(model.filed_at),
            first_observed_at=_utc(model.first_observed_at),
            fiscal_period_start=model.fiscal_period_start,
            fiscal_period_end=model.fiscal_period_end,
            raw_artifact_sha256=model.raw_artifact_sha256,
            source_evidence_ids=tuple(model.source_evidence_ids),
            parser_version=model.parser_version,
            restates_filing_id=model.restates_filing_id,
        )

    @staticmethod
    def _fundamental(model: FundamentalModel) -> FundamentalObservation:
        return FundamentalObservation(
            company_id=model.company_id,
            filing_id=model.filing_id,
            metric=FundamentalType(model.metric),
            value=model.value,
            currency=model.currency,
            unit=model.unit,
            fiscal_period_start=model.fiscal_period_start,
            fiscal_period_end=model.fiscal_period_end,
            published_at=_utc(model.published_at),
            first_observed_at=_utc(model.first_observed_at),
            source_evidence_ids=tuple(model.source_evidence_ids),
            parser_version=model.parser_version,
            restatement_status=RestatementStatus(model.restatement_status),
            restates_observation_id=model.restates_observation_id,
            dimensions=tuple((item[0], item[1]) for item in model.dimensions),
        )

    @staticmethod
    def _exposure(model: CompanyExposureModel) -> CompanyExposure:
        return CompanyExposure(
            company_id=model.company_id,
            exposure_type=CompanyExposureType(model.exposure_type),
            target=model.target,
            value=model.value,
            unit=model.unit,
            valid_from=_utc(model.valid_from),
            valid_until=_utc_optional(model.valid_until),
            first_observed_at=_utc(model.first_observed_at),
            source_evidence_ids=tuple(model.source_evidence_ids),
            version=model.version,
        )

    @staticmethod
    def _derived(model: DerivedFundamentalModel) -> DerivedMetric:
        return DerivedMetric(
            company_id=model.company_id,
            metric=model.metric,
            value=model.value,
            unit=model.unit,
            fiscal_period_end=model.fiscal_period_end,
            first_observed_at=_utc(model.first_observed_at),
            input_observation_ids=tuple(model.input_observation_ids),
            formula_version=model.formula_version,
        )


def derive_metrics(observations: tuple[FundamentalObservation, ...]) -> tuple[DerivedMetric, ...]:
    output: list[DerivedMetric] = []

    def emit(
        name: str,
        value: Decimal,
        unit: str,
        source: tuple[FundamentalObservation, ...],
    ) -> None:
        output.append(
            DerivedMetric(
                company_id=source[0].company_id,
                metric=name,
                value=format(value, "f"),
                unit=unit,
                fiscal_period_end=max(item.fiscal_period_end for item in source),
                first_observed_at=max(item.first_observed_at for item in source),
                input_observation_ids=tuple(item.observation_id for item in source),
                formula_version="deterministic-ratios/1",
            )
        )

    groups: dict[
        tuple[str, object, object, tuple[tuple[str, str], ...]],
        dict[FundamentalType, FundamentalObservation],
    ] = {}
    for item in observations:
        key = (
            item.company_id,
            item.fiscal_period_start,
            item.fiscal_period_end,
            item.dimensions,
        )
        groups.setdefault(key, {})[item.metric] = item

    def pair(
        facts: dict[FundamentalType, FundamentalObservation],
        left: FundamentalType,
        right: FundamentalType,
    ) -> tuple[FundamentalObservation, FundamentalObservation] | None:
        if left not in facts or right not in facts:
            return None
        values = (facts[left], facts[right])
        if (
            values[0].currency != values[1].currency
            or values[0].unit != values[1].unit
            or values[0].company_id != values[1].company_id
        ):
            return None
        return values

    for facts in groups.values():
        for name, left, right, operation, unit in (
            (
                "net_debt",
                FundamentalType.DEBT,
                FundamentalType.CASH,
                "subtract",
                None,
            ),
            (
                "free_cash_flow",
                FundamentalType.OPERATING_CASH_FLOW,
                FundamentalType.CAPEX,
                "subtract",
                None,
            ),
            (
                "operating_margin",
                FundamentalType.OPERATING_INCOME,
                FundamentalType.REVENUE,
                "divide",
                "ratio",
            ),
            (
                "net_margin",
                FundamentalType.NET_INCOME,
                FundamentalType.REVENUE,
                "divide",
                "ratio",
            ),
            (
                "debt_equity",
                FundamentalType.DEBT,
                FundamentalType.EQUITY,
                "divide",
                "ratio",
            ),
        ):
            inputs = pair(facts, left, right)
            if inputs is None:
                continue
            left_value, right_value = (Decimal(item.value) for item in inputs)
            if operation == "divide":
                if right_value == 0:
                    continue
                value = left_value / right_value
            else:
                value = left_value - right_value
            emit(name, value, inputs[0].unit if unit is None else unit, inputs)

    for metric, name in (
        (FundamentalType.REVENUE, "revenue_growth"),
        (FundamentalType.EPS, "eps_growth"),
    ):
        series = sorted(
            (item for item in observations if item.metric is metric),
            key=lambda item: (item.company_id, item.dimensions, item.fiscal_period_end),
        )
        for previous, current in pairwise(series):
            compatible = (
                previous.company_id == current.company_id
                and previous.dimensions == current.dimensions
                and previous.currency == current.currency
                and previous.unit == current.unit
            )
            denominator = Decimal(previous.value)
            if compatible and denominator != 0:
                emit(
                    name,
                    (Decimal(current.value) - denominator) / denominator,
                    "ratio",
                    (previous, current),
                )
    return tuple(output)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _utc_optional(value: datetime | None) -> datetime | None:
    return None if value is None else _utc(value)
