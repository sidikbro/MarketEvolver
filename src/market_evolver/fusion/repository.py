from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from market_evolver.errors import IntegrityViolation
from market_evolver.fusion.schemas import (
    ClaimContradiction,
    ClaimLineage,
    ClaimResolution,
    ClaimStatus,
    CorroborationRecord,
    CorroborationState,
    FusionScore,
    IndependenceClass,
    LeadTime,
    LineageType,
    ReputationSnapshot,
    ResolutionOutcome,
    UnifiedClaim,
    UnifiedClaimType,
)
from market_evolver.storage.models import (
    ClaimContradictionModel,
    ClaimCorroborationModel,
    ClaimLineageModel,
    ClaimResolutionModel,
    FusionReputationModel,
    FusionScoreModel,
    UnifiedClaimModel,
)
from market_evolver.time import require_aware_utc


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class SqlFusionRepository:
    def __init__(self, session: Session):
        self.session = session

    def add_claim(self, claim: UnifiedClaim) -> bool:
        if self.session.get(UnifiedClaimModel, claim.claim_id):
            return False
        if claim.revision_of:
            prior = self.session.get(UnifiedClaimModel, claim.revision_of)
            if (
                prior is None
                or prior.version + 1 != claim.version
                or utc(prior.first_observed_at) >= claim.first_observed_at
            ):
                raise IntegrityViolation("invalid unified claim revision")
        self.session.add(
            UnifiedClaimModel(
                claim_id=claim.claim_id,
                proposition=claim.proposition,
                claim_type=claim.claim_type.value,
                entities=list(claim.entities),
                geography=list(claim.geography),
                domain=claim.domain,
                source_evidence_ids=list(claim.source_evidence_ids),
                originating_source_id=claim.originating_source_id,
                first_observed_at=claim.first_observed_at,
                valid_from=claim.valid_from,
                valid_until=claim.valid_until,
                status=claim.status.value,
                confidence=claim.confidence,
                provenance=list(claim.provenance),
                version=claim.version,
                revision_of=claim.revision_of,
            )
        )
        return True

    def add_lineage(self, edge: ClaimLineage) -> bool:
        if self.session.get(ClaimLineageModel, edge.lineage_id):
            return False
        source = self.session.get(UnifiedClaimModel, edge.source_claim_id)
        target = self.session.get(UnifiedClaimModel, edge.target_claim_id)
        if source is None or target is None:
            raise IntegrityViolation("claim lineage references unknown claim")
        if edge.observed_at < max(utc(source.first_observed_at), utc(target.first_observed_at)):
            raise IntegrityViolation("claim lineage violates causal ordering")
        self.session.add(
            ClaimLineageModel(
                lineage_id=edge.lineage_id,
                source_claim_id=edge.source_claim_id,
                target_claim_id=edge.target_claim_id,
                relationship=edge.relationship.value,
                observed_at=edge.observed_at,
                evidence_ids=list(edge.evidence_ids),
                rationale=edge.rationale,
            )
        )
        return True

    def add_corroboration(self, record: CorroborationRecord) -> bool:
        if self.session.get(ClaimCorroborationModel, record.record_id):
            return False
        claim = self.session.get(UnifiedClaimModel, record.claim_id)
        if claim is None:
            raise IntegrityViolation("corroboration references unknown claim")
        if record.observed_at < utc(claim.first_observed_at):
            raise IntegrityViolation("corroboration violates causal ordering")
        self.session.add(
            ClaimCorroborationModel(
                record_id=record.record_id,
                claim_id=record.claim_id,
                evidence_id=record.evidence_id,
                source_id=record.source_id,
                independence=record.independence.value,
                state=record.state.value,
                observed_at=record.observed_at,
                rationale=record.rationale,
            )
        )
        return True

    def add_resolution(
        self, resolution: ClaimResolution, *, authoritative_primary: bool = False
    ) -> bool:
        if self.session.get(ClaimResolutionModel, resolution.resolution_id):
            return False
        claim = self.session.get(UnifiedClaimModel, resolution.claim_id)
        if claim is None:
            raise IntegrityViolation("resolution references unknown claim")
        if resolution.resolved_at < utc(claim.first_observed_at):
            raise IntegrityViolation("resolution violates causal ordering")
        if (
            resolution.outcome is not ResolutionOutcome.UNRESOLVED
            and claim.originating_source_id in resolution.resolving_source_ids
            and len(set(resolution.resolving_source_ids)) == 1
            and not (
                authoritative_primary
                and UnifiedClaimType(claim.claim_type)
                in {
                    UnifiedClaimType.FACTUAL_EVENT,
                    UnifiedClaimType.POLICY_ACTION,
                    UnifiedClaimType.COMPANY_DISCLOSURE,
                    UnifiedClaimType.MACRO_RELEASE,
                    UnifiedClaimType.GEOPOLITICAL_EVENT,
                }
            )
        ):
            raise IntegrityViolation("source cannot resolve its own claim")
        self.session.add(
            ClaimResolutionModel(
                resolution_id=resolution.resolution_id,
                claim_id=resolution.claim_id,
                outcome=resolution.outcome.value,
                state=resolution.state.value,
                supporting_evidence_ids=list(resolution.supporting_evidence_ids),
                resolving_source_ids=list(resolution.resolving_source_ids),
                resolved_at=resolution.resolved_at,
                rationale=resolution.rationale,
            )
        )
        return True

    def add_contradiction(self, item: ClaimContradiction) -> bool:
        if self.session.get(ClaimContradictionModel, item.contradiction_id):
            return False
        claim = self.session.get(UnifiedClaimModel, item.claim_id)
        if claim is None:
            raise IntegrityViolation("contradiction references unknown claim")
        if item.observed_at < utc(claim.first_observed_at):
            raise IntegrityViolation("contradiction violates causal ordering")
        self.session.add(
            ClaimContradictionModel(
                contradiction_id=item.contradiction_id,
                claim_id=item.claim_id,
                proposition_a=item.proposition_a,
                proposition_b=item.proposition_b,
                evidence_a=list(item.evidence_a),
                evidence_b=list(item.evidence_b),
                observed_at=item.observed_at,
                resolution_status=item.resolution_status,
                ambiguity=item.ambiguity,
            )
        )
        return True

    def add_score(self, score: FusionScore) -> bool:
        if self.session.get(FusionScoreModel, score.score_id):
            return False
        claim = self.session.get(UnifiedClaimModel, score.claim_id)
        if claim is None:
            raise IntegrityViolation("score references unknown claim")
        if score.calculated_at < utc(claim.first_observed_at):
            raise IntegrityViolation("score violates causal ordering")
        self.session.add(FusionScoreModel(score_id=score.score_id, **_score_values(score)))
        return True

    def add_reputation(self, snapshot: ReputationSnapshot) -> bool:
        if self.session.get(FusionReputationModel, snapshot.snapshot_id):
            return False
        self.session.add(
            FusionReputationModel(snapshot_id=snapshot.snapshot_id, **_reputation_values(snapshot))
        )
        return True

    def claims_visible_at(self, cutoff: datetime) -> tuple[UnifiedClaim, ...]:
        at = require_aware_utc(cutoff, "cutoff")
        rows = tuple(
            self.session.scalars(
                select(UnifiedClaimModel).where(UnifiedClaimModel.first_observed_at <= at)
            )
        )
        revised = {row.revision_of for row in rows if row.revision_of}
        return tuple(_claim(row) for row in rows if row.claim_id not in revised)

    def get_claim(self, claim_id: str, cutoff: datetime) -> UnifiedClaim | None:
        return next(
            (claim for claim in self.claims_visible_at(cutoff) if claim.claim_id == claim_id), None
        )

    def lineage_visible_at(
        self, cutoff: datetime, claim_id: str | None = None
    ) -> tuple[ClaimLineage, ...]:
        at = require_aware_utc(cutoff, "cutoff")
        query = select(ClaimLineageModel).where(ClaimLineageModel.observed_at <= at)
        if claim_id:
            query = query.where(
                or_(
                    ClaimLineageModel.source_claim_id == claim_id,
                    ClaimLineageModel.target_claim_id == claim_id,
                )
            )
        return tuple(_lineage(row) for row in self.session.scalars(query))

    def corroborations_visible_at(
        self, claim_id: str, cutoff: datetime
    ) -> tuple[CorroborationRecord, ...]:
        at = require_aware_utc(cutoff, "cutoff")
        rows = self.session.scalars(
            select(ClaimCorroborationModel).where(
                ClaimCorroborationModel.claim_id == claim_id,
                ClaimCorroborationModel.observed_at <= at,
            )
        )
        return tuple(_corroboration(row) for row in rows)

    def resolutions_visible_at(
        self, claim_id: str, cutoff: datetime
    ) -> tuple[ClaimResolution, ...]:
        at = require_aware_utc(cutoff, "cutoff")
        rows = self.session.scalars(
            select(ClaimResolutionModel)
            .where(
                ClaimResolutionModel.claim_id == claim_id,
                ClaimResolutionModel.resolved_at <= at,
            )
            .order_by(ClaimResolutionModel.resolved_at)
        )
        return tuple(_resolution(row) for row in rows)

    def contradictions_visible_at(self, cutoff: datetime) -> tuple[ClaimContradiction, ...]:
        at = require_aware_utc(cutoff, "cutoff")
        return tuple(
            _contradiction(row)
            for row in self.session.scalars(
                select(ClaimContradictionModel).where(ClaimContradictionModel.observed_at <= at)
            )
        )

    def reputation_at(
        self, source_id: str, domain: str, cutoff: datetime
    ) -> ReputationSnapshot | None:
        at = require_aware_utc(cutoff, "cutoff")
        row = self.session.scalar(
            select(FusionReputationModel)
            .where(
                FusionReputationModel.source_id == source_id,
                FusionReputationModel.domain == domain,
                FusionReputationModel.cutoff <= at,
            )
            .order_by(FusionReputationModel.cutoff.desc())
            .limit(1)
        )
        return None if row is None else _reputation(row)

    def lead_time(self, claim_id: str, cutoff: datetime) -> LeadTime:
        claim = self.get_claim(claim_id, cutoff)
        if claim is None:
            raise IntegrityViolation("claim is not visible at cutoff")
        records = self.corroborations_visible_at(claim_id, cutoff)
        resolutions = self.resolutions_visible_at(claim_id, cutoff)
        times: dict[str, list[datetime]] = {
            key: [] for key in ("social", "news", "official", "filing")
        }
        for record in records:
            prefix = record.source_id.split(".", 1)[0]
            if prefix in times:
                times[prefix].append(record.observed_at)
        confirmed = [
            r.resolved_at
            for r in resolutions
            if r.outcome in {ResolutionOutcome.CONFIRMED, ResolutionOutcome.PARTIALLY_CONFIRMED}
        ]
        contradicted = [
            r.resolved_at for r in resolutions if r.outcome is ResolutionOutcome.CONTRADICTED
        ]
        return LeadTime(
            claim_id,
            _minimum(times["social"]),
            _minimum(times["news"]),
            _minimum(times["official"]),
            _minimum(times["filing"]),
            min(confirmed, default=None),
            min(contradicted, default=None),
        )


def _claim(row: UnifiedClaimModel) -> UnifiedClaim:
    return UnifiedClaim(
        row.proposition,
        UnifiedClaimType(row.claim_type),
        tuple(row.entities),
        tuple(row.geography),
        row.domain,
        tuple(row.source_evidence_ids),
        row.originating_source_id,
        utc(row.first_observed_at),
        utc(row.valid_from),
        None if row.valid_until is None else utc(row.valid_until),
        ClaimStatus(row.status),
        row.confidence,
        tuple(row.provenance),
        row.version,
        row.revision_of,
    )


def _minimum(values: list[datetime]) -> datetime | None:
    return min(values) if values else None


def _lineage(row: ClaimLineageModel) -> ClaimLineage:
    return ClaimLineage(
        row.source_claim_id,
        row.target_claim_id,
        LineageType(row.relationship),
        utc(row.observed_at),
        tuple(row.evidence_ids),
        row.rationale,
    )


def _corroboration(row: ClaimCorroborationModel) -> CorroborationRecord:
    return CorroborationRecord(
        row.claim_id,
        row.evidence_id,
        row.source_id,
        IndependenceClass(row.independence),
        CorroborationState(row.state),
        utc(row.observed_at),
        row.rationale,
    )


def _resolution(row: ClaimResolutionModel) -> ClaimResolution:
    return ClaimResolution(
        row.claim_id,
        ResolutionOutcome(row.outcome),
        CorroborationState(row.state),
        tuple(row.supporting_evidence_ids),
        tuple(row.resolving_source_ids),
        utc(row.resolved_at),
        row.rationale,
    )


def _contradiction(row: ClaimContradictionModel) -> ClaimContradiction:
    return ClaimContradiction(
        row.claim_id,
        row.proposition_a,
        row.proposition_b,
        tuple(row.evidence_a),
        tuple(row.evidence_b),
        utc(row.observed_at),
        row.resolution_status,
        row.ambiguity,
    )


def _score_values(score: FusionScore) -> dict[str, object]:
    return {
        name: getattr(score, name)
        for name in (
            "claim_id",
            "source_authority",
            "independence",
            "corroboration_count",
            "provenance_completeness",
            "contradiction_burden",
            "temporal_consistency",
            "historical_reputation",
            "calculated_at",
        )
    }


def _reputation_values(item: ReputationSnapshot) -> dict[str, object]:
    return {
        name: getattr(item, name)
        for name in (
            "source_id",
            "domain",
            "window_start",
            "cutoff",
            "claims_originated",
            "confirmed",
            "contradicted",
            "unresolved",
            "precision_resolved",
            "median_confirmation_lead_seconds",
            "contradiction_rate",
            "copy_forward_rate",
            "original_content_rate",
            "sample_size",
            "uncertainty",
        )
    }


def _reputation(row: FusionReputationModel) -> ReputationSnapshot:
    return ReputationSnapshot(
        row.source_id,
        row.domain,
        utc(row.window_start),
        utc(row.cutoff),
        row.claims_originated,
        row.confirmed,
        row.contradicted,
        row.unresolved,
        row.precision_resolved,
        row.median_confirmation_lead_seconds,
        row.contradiction_rate,
        row.copy_forward_rate,
        row.original_content_rate,
        row.sample_size,
        row.uncertainty,
    )
