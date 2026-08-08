"""Point-in-time research context assembly."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from market_evolver.company.repositories import SqlCompanyRepository
from market_evolver.errors import IntegrityViolation
from market_evolver.fusion.engine import current_corroboration_state
from market_evolver.fusion.repository import SqlFusionRepository
from market_evolver.geopolitical.repository import SqlGeopoliticalRepository
from market_evolver.macro.repository import SqlMacroRepository
from market_evolver.research.schemas import ContextItem, ResearchContext
from market_evolver.social.repository import SqlSocialRepository
from market_evolver.storage.models import (
    CanonicalEventModel,
    EvidenceModel,
    GovernmentActionModel,
    KnowledgeRelationshipModel,
)
from market_evolver.time import require_aware_utc


class ResearchContextBuilder:
    def __init__(self, session: Session) -> None:
        self.session = session

    def build(self, company_id: str, cutoff: datetime) -> ResearchContext:
        at = require_aware_utc(cutoff, "cutoff")
        companies = SqlCompanyRepository(self.session)
        company = companies.get_company_at(company_id, at)
        if company is None:
            raise IntegrityViolation("company is not visible at research cutoff")
        entity_id = f"company.{company_id}"
        items = [
            ContextItem(
                "company",
                company.company_version_id,
                company.observed_at,
                f"{company.legal_name}; sector={company.sector_id}; domicile={company.domicile}",
            )
        ]
        evidence_ids: set[str] = set()
        for filing in companies.list_filings(company_id, at):
            evidence_ids.update(filing.source_evidence_ids)
            items.append(
                ContextItem(
                    "filing",
                    filing.filing_id,
                    filing.first_observed_at,
                    f"{filing.form_type} for period ending {filing.fiscal_period_end.isoformat()}",
                    filing.source_evidence_ids,
                )
            )
        for fact in companies.get_fundamentals(company_id, at):
            evidence_ids.update(fact.source_evidence_ids)
            items.append(
                ContextItem(
                    "fundamental",
                    fact.observation_id,
                    fact.first_observed_at,
                    f"{fact.metric.value}={fact.value} {fact.unit} ({fact.currency or 'noncurrency'})",
                    fact.source_evidence_ids,
                )
            )
        for exposure in companies.get_exposures(company_id, at):
            evidence_ids.update(exposure.source_evidence_ids)
            items.append(
                ContextItem(
                    "exposure",
                    exposure.exposure_id,
                    exposure.first_observed_at,
                    f"{exposure.exposure_type.value} target={exposure.target}",
                    exposure.source_evidence_ids,
                )
            )
        events = self.session.scalars(
            select(CanonicalEventModel).where(CanonicalEventModel.first_observed_at <= at)
        )
        for event in events:
            if company_id not in event.entities and entity_id not in event.entities:
                continue
            if not self._evidence_visible(tuple(event.evidence_ids), at):
                continue
            evidence_ids.update(event.evidence_ids)
            items.append(
                ContextItem(
                    "event",
                    event.event_id,
                    _utc(event.first_observed_at),
                    f"{event.event_type}: {event.attributes}",
                    tuple(event.evidence_ids),
                )
            )
            for mechanism in event.causal_mechanisms:
                items.append(
                    ContextItem(
                        "mechanism",
                        f"{event.event_id}:mechanism:{mechanism}",
                        _utc(event.first_observed_at),
                        mechanism,
                        tuple(event.evidence_ids),
                    )
                )
        actions = self.session.scalars(
            select(GovernmentActionModel).where(GovernmentActionModel.first_observed_at <= at)
        )
        for action in actions:
            relevant = (
                company_id in action.affected_entities or entity_id in action.affected_entities
            )
            relevant = relevant or company.sector_id in action.affected_sectors
            if not relevant or not self._evidence_visible(tuple(action.source_evidence_ids), at):
                continue
            evidence_ids.update(action.source_evidence_ids)
            items.append(
                ContextItem(
                    "policy",
                    action.action_id,
                    _utc(action.first_observed_at),
                    f"{action.action_type}: {action.title}",
                    tuple(action.source_evidence_ids),
                )
            )
        relationships = self.session.scalars(
            select(KnowledgeRelationshipModel).where(
                or_(
                    KnowledgeRelationshipModel.source_entity == entity_id,
                    KnowledgeRelationshipModel.target_entity == entity_id,
                ),
                KnowledgeRelationshipModel.observed_at <= at,
                KnowledgeRelationshipModel.valid_from <= at,
                or_(
                    KnowledgeRelationshipModel.valid_until.is_(None),
                    KnowledgeRelationshipModel.valid_until > at,
                ),
            )
        )
        for relationship in relationships:
            items.append(
                ContextItem(
                    "graph_relationship",
                    relationship.relationship_id,
                    _utc(relationship.observed_at),
                    (
                        f"{relationship.source_entity} {relationship.relation_type} "
                        f"{relationship.target_entity}; version={relationship.version}; "
                        f"provenance={relationship.provenance}"
                    ),
                )
            )
        macro = SqlMacroRepository(self.session)
        for series_id in macro.series_ids():
            for observation in macro.observations_visible_at(series_id, at):
                items.append(
                    ContextItem(
                        "macro_observation",
                        observation.observation_id,
                        observation.first_observed_at,
                        (
                            f"{observation.name_en} {observation.observation_period}: "
                            f"{observation.value} {observation.unit}"
                        ),
                        observation.provenance,
                    )
                )
            for trend in macro.trends_visible_at(series_id, at):
                items.append(
                    ContextItem(
                        "macro_trend",
                        trend.trend_id,
                        trend.calculated_at,
                        f"{series_id} {trend.horizon.value}: {trend.state.value}",
                        trend.input_observation_ids,
                    )
                )
        for structural_trend in macro.structural_visible_at(at):
            items.append(
                ContextItem(
                    "structural_trend",
                    structural_trend.structural_id,
                    structural_trend.first_observed_at,
                    f"Curated structural candidate: {structural_trend.name}",
                    structural_trend.evidence_ids,
                )
            )
        geopolitical = SqlGeopoliticalRepository(self.session)
        geopolitical_events = geopolitical.events_visible_at(at)
        geopolitical_event_ids = tuple(item.event_id for item in geopolitical_events)
        for geopolitical_event in geopolitical_events:
            evidence_ids.update(geopolitical_event.source_evidence_ids)
            items.append(
                ContextItem(
                    "geopolitical_event",
                    geopolitical_event.event_id,
                    geopolitical_event.first_observed_at,
                    (
                        f"{geopolitical_event.event_type.value}; status={geopolitical_event.status.value}; "
                        f"confirmation={geopolitical_event.confirmation_state.value}; "
                        f"confidence={geopolitical_event.confidence}"
                    ),
                    geopolitical_event.source_evidence_ids,
                )
            )
        for path in geopolitical.paths_visible_at(at, event_ids=geopolitical_event_ids):
            items.append(
                ContextItem(
                    "geopolitical_mechanism_path",
                    path.path_id,
                    path.observed_at,
                    (
                        f"candidate path horizon={path.horizon.value}; "
                        f"mechanisms={','.join(path.mechanisms)}; confidence={path.confidence}"
                    ),
                    path.provenance_ids,
                )
            )
        for corroboration in geopolitical.corroborations_visible_at(at):
            evidence_ids.update(corroboration.evidence_ids)
            items.append(
                ContextItem(
                    "geopolitical_corroboration",
                    corroboration.corroboration_id,
                    corroboration.observed_at,
                    f"{corroboration.kind.value}: {corroboration.rationale}",
                    corroboration.evidence_ids,
                )
            )
        social = SqlSocialRepository(self.session)
        for narrative in social.narratives_visible_at(at):
            items.append(
                ContextItem(
                    "reviewed_social_narrative",
                    narrative.candidate_id,
                    narrative.earliest_observed_at,
                    f"Narrative candidate, not fact: {narrative.proposition}",
                    narrative.supporting_post_ids,
                )
            )
        for rumor in social.rumors_visible_at(at):
            items.append(
                ContextItem(
                    "social_rumor_claim",
                    rumor.claim_id,
                    rumor.first_observed_at,
                    f"Rumor status={rumor.status.value}: {rumor.proposition}",
                    rumor.official_evidence_ids + rumor.news_evidence_ids,
                )
            )
        fusion = SqlFusionRepository(self.session)
        for claim in fusion.claims_visible_at(at):
            if company_id not in claim.entities and entity_id not in claim.entities:
                continue
            if not self._evidence_visible(claim.source_evidence_ids, at):
                continue
            evidence_ids.update(claim.source_evidence_ids)
            contradictions = tuple(
                item
                for item in fusion.contradictions_visible_at(at)
                if item.claim_id == claim.claim_id
            )
            reputation = fusion.reputation_at(claim.originating_source_id, claim.domain, at)
            items.append(
                ContextItem(
                    "fused_claim_bundle",
                    claim.claim_id,
                    claim.first_observed_at,
                    (
                        f"{claim.claim_type.value}: {claim.proposition}; "
                        f"corroboration="
                        f"{current_corroboration_state(self.session, claim.claim_id, at).value}; "
                        f"contradictions={len(contradictions)}; source_domain_precision="
                        f"{None if reputation is None else reputation.precision_resolved}"
                    ),
                    claim.source_evidence_ids,
                )
            )
        for evidence_id in sorted(evidence_ids):
            evidence = self.session.get(EvidenceModel, evidence_id)
            if evidence is None or _utc(evidence.observed_at) > at:
                raise IntegrityViolation("context references unavailable evidence")
            items.append(
                ContextItem(
                    "evidence",
                    evidence.provenance_id,
                    _utc(evidence.observed_at),
                    evidence.claim,
                    (evidence.provenance_id,),
                )
            )
        return ResearchContext(
            at, company_id, tuple(sorted(items, key=lambda item: item.provenance_id))
        )

    def _evidence_visible(self, ids: tuple[str, ...], cutoff: datetime) -> bool:
        return bool(ids) and all(
            (item := self.session.get(EvidenceModel, evidence_id)) is not None
            and _utc(item.observed_at) <= cutoff
            for evidence_id in ids
        )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
