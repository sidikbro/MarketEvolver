from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

from sqlalchemy.orm import Session

from market_evolver.errors import ValidationError
from market_evolver.fusion.repository import SqlFusionRepository
from market_evolver.fusion.schemas import (
    ClaimLineage,
    CorroborationState,
    FusionScore,
    IndependenceClass,
    LineageType,
    ReputationSnapshot,
    ResolutionOutcome,
    UnifiedClaim,
)
from market_evolver.time import require_aware_utc


@dataclass(frozen=True, slots=True)
class FusionMetrics:
    claim_resolution_precision: float
    corroboration_latency_seconds: float
    official_confirmation_lead_seconds: float
    contradiction_rate: float
    unresolved_rate: float
    independence_adjusted_evidence_count: float
    false_amplification_factor: float
    future_reputation_leakage_rate: float


def proposition_fingerprint(value: str) -> str:
    normalized = " ".join(re.sub(r"[^\w\s]", " ", value.casefold()).split())
    return hashlib.sha256(normalized.encode()).hexdigest()


def deterministic_match(
    a: UnifiedClaim, b: UnifiedClaim, *, proximity: timedelta = timedelta(days=3)
) -> bool:
    explicit = set(a.source_evidence_ids) & set(b.source_evidence_ids)
    same_fingerprint = proposition_fingerprint(a.proposition) == proposition_fingerprint(
        b.proposition
    )
    entity_overlap = bool(set(a.entities) & set(b.entities))
    close = abs(a.first_observed_at - b.first_observed_at) <= proximity
    return bool(
        a.claim_type is b.claim_type
        and a.domain == b.domain
        and entity_overlap
        and close
        and (explicit or same_fingerprint)
    )


def classify_independence(
    claim: UnifiedClaim,
    corroborating_source: str,
    lineage: tuple[ClaimLineage, ...],
) -> IndependenceClass:
    if corroborating_source == claim.originating_source_id:
        return IndependenceClass.SAME_PRIMARY_SOURCE
    relationships = {edge.relationship for edge in lineage}
    if LineageType.FORWARDED_FROM in relationships:
        return IndependenceClass.FORWARDED
    if LineageType.COPIED_FROM in relationships:
        return IndependenceClass.COPIED
    if LineageType.DERIVED_FROM in relationships:
        return IndependenceClass.LIKELY_SYNDICATED
    if lineage:
        return IndependenceClass.INDEPENDENT
    return IndependenceClass.UNKNOWN


def fusion_score(
    claim: UnifiedClaim,
    *,
    authority: float,
    independence: IndependenceClass,
    independent_count: int,
    provenance_complete: bool,
    contradiction_count: int,
    temporally_consistent: bool,
    historical_precision: float | None,
    calculated_at: datetime,
) -> FusionScore:
    independence_values = {
        IndependenceClass.INDEPENDENT: 1.0,
        IndependenceClass.UNKNOWN: 0.4,
        IndependenceClass.LIKELY_SYNDICATED: 0.25,
        IndependenceClass.COPIED: 0.0,
        IndependenceClass.FORWARDED: 0.0,
        IndependenceClass.SAME_PRIMARY_SOURCE: 0.0,
    }
    return FusionScore(
        claim.claim_id,
        authority,
        independence_values[independence],
        min(independent_count / 3, 1.0),
        1.0 if provenance_complete else 0.0,
        min(contradiction_count / 3, 1.0),
        1.0 if temporally_consistent else 0.0,
        0.5 if historical_precision is None else historical_precision,
        calculated_at,
    )


def calculate_reputation(
    session: Session,
    source_id: str,
    domain: str,
    cutoff: datetime,
    *,
    window: timedelta = timedelta(days=365),
) -> ReputationSnapshot:
    cutoff = require_aware_utc(cutoff, "cutoff")
    if window <= timedelta(0):
        raise ValidationError("reputation window must be positive")
    repo = SqlFusionRepository(session)
    start = cutoff - window
    claims = tuple(
        claim
        for claim in repo.claims_visible_at(cutoff)
        if claim.originating_source_id == source_id
        and claim.domain == domain
        and start <= claim.first_observed_at <= cutoff
    )
    confirmed = contradicted = unresolved = copies = 0
    leads: list[int] = []
    for claim in claims:
        resolutions = repo.resolutions_visible_at(claim.claim_id, cutoff)
        latest = resolutions[-1] if resolutions else None
        if latest is None or latest.outcome is ResolutionOutcome.UNRESOLVED:
            unresolved += 1
        elif latest.outcome in {ResolutionOutcome.CONFIRMED, ResolutionOutcome.PARTIALLY_CONFIRMED}:
            confirmed += 1
            leads.append(int((latest.resolved_at - claim.first_observed_at).total_seconds()))
        elif latest.outcome is ResolutionOutcome.CONTRADICTED:
            contradicted += 1
        lineages = repo.lineage_visible_at(cutoff, claim.claim_id)
        copies += int(
            any(
                edge.relationship in {LineageType.COPIED_FROM, LineageType.FORWARDED_FROM}
                and edge.target_claim_id == claim.claim_id
                for edge in lineages
            )
        )
    resolved = confirmed + contradicted
    sample = len(claims)
    precision = confirmed / resolved if resolved else 0.0
    contradiction_rate = contradicted / resolved if resolved else 0.0
    copy_rate = copies / sample if sample else 0.0
    uncertainty = "insufficient_sample" if sample < 5 else f"deterministic_n={sample}"
    return ReputationSnapshot(
        source_id,
        domain,
        start,
        cutoff,
        sample,
        confirmed,
        contradicted,
        unresolved,
        precision,
        None if not leads else int(median(leads)),
        contradiction_rate,
        copy_rate,
        1 - copy_rate,
        sample,
        uncertainty,
    )


def current_corroboration_state(
    session: Session, claim_id: str, cutoff: datetime
) -> CorroborationState:
    repo = SqlFusionRepository(session)
    resolutions = repo.resolutions_visible_at(claim_id, cutoff)
    if resolutions:
        return resolutions[-1].state
    records = repo.corroborations_visible_at(claim_id, cutoff)
    if any(record.state is CorroborationState.OFFICIALLY_CONFIRMED for record in records):
        return CorroborationState.OFFICIALLY_CONFIRMED
    independent = sum(record.independence is IndependenceClass.INDEPENDENT for record in records)
    return (
        CorroborationState.INDEPENDENTLY_CORROBORATED
        if independent >= 2
        else CorroborationState.WEAKLY_CORROBORATED
        if records
        else CorroborationState.UNCORROBORATED
    )


def calculate_metrics(session: Session, cutoff: datetime) -> FusionMetrics:
    cutoff = require_aware_utc(cutoff, "cutoff")
    repo = SqlFusionRepository(session)
    claims = repo.claims_visible_at(cutoff)
    confirmed = contradicted = unresolved = 0
    lags: list[float] = []
    official_leads: list[float] = []
    adjusted = 0.0
    dependent = 0
    for claim in claims:
        resolutions = repo.resolutions_visible_at(claim.claim_id, cutoff)
        latest = resolutions[-1] if resolutions else None
        if latest is None or latest.outcome is ResolutionOutcome.UNRESOLVED:
            unresolved += 1
        elif latest.outcome in {
            ResolutionOutcome.CONFIRMED,
            ResolutionOutcome.PARTIALLY_CONFIRMED,
        }:
            confirmed += 1
            lags.append((latest.resolved_at - claim.first_observed_at).total_seconds())
        elif latest.outcome is ResolutionOutcome.CONTRADICTED:
            contradicted += 1
        records = repo.corroborations_visible_at(claim.claim_id, cutoff)
        adjusted += sum(record.independence is IndependenceClass.INDEPENDENT for record in records)
        dependent += sum(
            record.independence
            in {
                IndependenceClass.COPIED,
                IndependenceClass.FORWARDED,
                IndependenceClass.LIKELY_SYNDICATED,
            }
            for record in records
        )
        lead = repo.lead_time(claim.claim_id, cutoff)
        if lead.first_social is not None and lead.confirmation_time is not None:
            official_leads.append((lead.confirmation_time - lead.first_social).total_seconds())
    resolved = confirmed + contradicted
    count = len(claims)
    return FusionMetrics(
        confirmed / resolved if resolved else 0.0,
        sum(lags) / len(lags) if lags else 0.0,
        sum(official_leads) / len(official_leads) if official_leads else 0.0,
        contradicted / resolved if resolved else 0.0,
        unresolved / count if count else 0.0,
        adjusted,
        dependent / max(adjusted, 1.0),
        0.0,
    )
