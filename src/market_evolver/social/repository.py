from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_evolver.errors import IntegrityViolation
from market_evolver.social.schemas import *
from market_evolver.storage.models import *
from market_evolver.time import require_aware_utc


def utc(v: datetime) -> datetime:
    return v.replace(tzinfo=UTC) if v.tzinfo is None else v.astimezone(UTC)


class SqlSocialRepository:
    def __init__(self, session: Session):
        self.session = session

    def add_source(self, x: SocialSource) -> bool:
        if self.session.get(SocialSourceModel, x.source_id):
            return False
        if self.session.scalar(
            select(SocialSourceModel).where(
                SocialSourceModel.platform == x.platform,
                SocialSourceModel.native_source_id == x.native_source_id,
            )
        ):
            raise IntegrityViolation("ambiguous social source identity")
        self.session.add(
            SocialSourceModel(
                source_id=x.source_id,
                platform=x.platform,
                native_source_id=x.native_source_id,
                display_name=x.display_name,
                canonical_uri=x.canonical_uri,
                languages=list(x.languages),
                geography=list(x.geography),
                source_type=x.source_type.value,
                created_at=x.created_at,
                first_observed_at=x.first_observed_at,
                verification_state=x.verification_state.value,
                accessibility=x.accessibility.value,
                provenance=list(x.provenance),
                active=x.active,
            )
        )
        return True

    def add_post(self, x: SocialPost) -> bool:
        if self.session.get(SocialPostModel, x.post_id):
            return False
        if not self.session.get(SocialSourceModel, x.source_id):
            raise IntegrityViolation("post source unknown")
        if x.revision_of:
            p = self.session.get(SocialPostModel, x.revision_of)
            if (
                not p
                or p.native_post_id != x.native_post_id
                or utc(p.first_observed_at) >= x.first_observed_at
            ):
                raise IntegrityViolation("invalid social edit chain")
        self.session.add(
            SocialPostModel(
                post_id=x.post_id,
                platform=x.platform,
                source_id=x.source_id,
                native_post_id=x.native_post_id,
                thread_parent_id=x.thread_parent_id,
                reply_parent_id=x.reply_parent_id,
                posted_at=x.posted_at,
                first_observed_at=x.first_observed_at,
                edited_at=x.edited_at,
                deleted_at=x.deleted_at,
                original_text=x.original_text,
                normalized_text=x.normalized_text,
                language=x.language,
                urls=list(x.urls),
                mentions=list(x.mentions),
                quoted_source_id=x.quoted_source_id,
                metrics=[list(i) for i in x.metrics],
                raw_artifact_sha256=x.raw_artifact_sha256,
                content_hash=x.content_hash,
                media_references=list(x.media_references),
                provenance=list(x.provenance),
                revision_of=x.revision_of,
            )
        )
        return True

    def posts_visible_at(self, cutoff: datetime) -> tuple[SocialPost, ...]:
        at = require_aware_utc(cutoff, "cutoff")
        rows = tuple(
            self.session.scalars(
                select(SocialPostModel).where(SocialPostModel.first_observed_at <= at)
            )
        )
        revised = {r.revision_of for r in rows if r.revision_of}
        return tuple(self._post(r) for r in rows if r.post_id not in revised)

    def add_narrative(self, x: NarrativeCandidate) -> bool:
        if self.session.get(NarrativeCandidateModel, x.candidate_id):
            return False
        self.session.add(
            NarrativeCandidateModel(
                candidate_id=x.candidate_id,
                topics=list(x.topics),
                entities=list(x.entities),
                supporting_post_ids=list(x.supporting_post_ids),
                earliest_observed_at=x.earliest_observed_at,
                proposition=x.proposition,
                language=x.language,
                extraction_method=x.extraction_method,
                confidence=x.confidence,
                corroboration_state=x.corroboration_state,
                contradiction_state=x.contradiction_state,
                lifecycle_state=x.lifecycle_state.value,
                reviewed=x.reviewed,
            )
        )
        return True

    def narratives_visible_at(self, cutoff: datetime) -> tuple[NarrativeCandidate, ...]:
        at = require_aware_utc(cutoff, "cutoff")
        rows = self.session.scalars(
            select(NarrativeCandidateModel).where(
                NarrativeCandidateModel.earliest_observed_at <= at,
                NarrativeCandidateModel.reviewed.is_(True),
            )
        )
        return tuple(
            NarrativeCandidate(
                tuple(r.topics),
                tuple(r.entities),
                tuple(r.supporting_post_ids),
                utc(r.earliest_observed_at),
                r.proposition,
                r.language,
                r.extraction_method,
                r.confidence,
                r.corroboration_state,
                r.contradiction_state,
                NarrativeLifecycle(r.lifecycle_state),
                r.reviewed,
            )
            for r in rows
        )

    def add_rumor(self, x: RumorClaim) -> bool:
        if self.session.get(RumorClaimModel, x.claim_id):
            return False
        if x.revision_of:
            p = self.session.get(RumorClaimModel, x.revision_of)
            if (
                not p
                or x.version != p.version + 1
                or utc(p.first_observed_at) >= x.first_observed_at
            ):
                raise IntegrityViolation("invalid rumor revision")
        self.session.add(
            RumorClaimModel(
                claim_id=x.claim_id,
                proposition=x.proposition,
                entities=list(x.entities),
                origin_post_id=x.origin_post_id,
                first_observed_at=x.first_observed_at,
                supporting_post_ids=list(x.supporting_post_ids),
                contradicting_post_ids=list(x.contradicting_post_ids),
                official_evidence_ids=list(x.official_evidence_ids),
                news_evidence_ids=list(x.news_evidence_ids),
                status=x.status.value,
                revision_of=x.revision_of,
                version=x.version,
            )
        )
        return True

    def rumors_visible_at(self, cutoff: datetime) -> tuple[RumorClaim, ...]:
        at = require_aware_utc(cutoff, "cutoff")
        rows = tuple(
            self.session.scalars(
                select(RumorClaimModel).where(RumorClaimModel.first_observed_at <= at)
            )
        )
        revised = {r.revision_of for r in rows if r.revision_of}
        return tuple(self._rumor(r) for r in rows if r.claim_id not in revised)

    def add_edge(self, x: PropagationEdge) -> bool:
        if self.session.get(SocialPropagationModel, x.edge_id):
            return False
        if not self.session.get(SocialPostModel, x.source_post_id) or not self.session.get(
            SocialPostModel, x.target_post_id
        ):
            raise IntegrityViolation("propagation posts unknown")
        self.session.add(
            SocialPropagationModel(
                edge_id=x.edge_id,
                source_post_id=x.source_post_id,
                target_post_id=x.target_post_id,
                relation=x.relation.value,
                observed_at=x.observed_at,
                provenance=list(x.provenance),
            )
        )
        return True

    def propagation(self, post_id: str, cutoff: datetime) -> tuple[PropagationEdge, ...]:
        at = require_aware_utc(cutoff, "cutoff")
        rows = self.session.scalars(
            select(SocialPropagationModel).where(
                (SocialPropagationModel.source_post_id == post_id)
                | (SocialPropagationModel.target_post_id == post_id),
                SocialPropagationModel.observed_at <= at,
            )
        )
        return tuple(
            PropagationEdge(
                r.source_post_id,
                r.target_post_id,
                PropagationType(r.relation),
                utc(r.observed_at),
                tuple(r.provenance),
            )
            for r in rows
        )

    def add_coordination(self, x: CoordinationCandidate) -> bool:
        if self.session.get(CoordinationCandidateModel, x.coordination_candidate_id):
            return False
        self.session.add(
            CoordinationCandidateModel(
                coordination_candidate_id=x.coordination_candidate_id,
                post_ids=list(x.post_ids),
                source_ids=list(x.source_ids),
                features=[list(i) for i in x.features],
                confidence=x.confidence,
                status=x.status.value,
                observed_at=x.observed_at,
                provenance=list(x.provenance),
            )
        )
        return True

    def add_reputation(self, x: ReputationSnapshot) -> bool:
        if self.session.get(SocialReputationModel, x.snapshot_id):
            return False
        self.session.add(
            SocialReputationModel(
                snapshot_id=x.snapshot_id,
                source_id=x.source_id,
                domain=x.domain,
                window_start=x.window_start,
                window_end=x.window_end,
                computed_at=x.computed_at,
                claims_originated=x.claims_originated,
                confirmed=x.confirmed,
                contradicted=x.contradicted,
                unresolved=x.unresolved,
                median_confirmation_lead_seconds=x.median_confirmation_lead_seconds,
                copy_rate=x.copy_rate,
                original_content_rate=x.original_content_rate,
                sample_size=x.sample_size,
                uncertainty=x.uncertainty,
            )
        )
        return True

    def reputation_at(
        self, source_id: str, cutoff: datetime, domain: str
    ) -> ReputationSnapshot | None:
        at = require_aware_utc(cutoff, "cutoff")
        r = self.session.scalar(
            select(SocialReputationModel)
            .where(
                SocialReputationModel.source_id == source_id,
                SocialReputationModel.domain == domain,
                SocialReputationModel.computed_at <= at,
            )
            .order_by(SocialReputationModel.computed_at.desc())
            .limit(1)
        )
        return (
            None
            if r is None
            else ReputationSnapshot(
                r.source_id,
                r.domain,
                utc(r.window_start),
                utc(r.window_end),
                utc(r.computed_at),
                r.claims_originated,
                r.confirmed,
                r.contradicted,
                r.unresolved,
                r.median_confirmation_lead_seconds,
                r.copy_rate,
                r.original_content_rate,
                r.sample_size,
                r.uncertainty,
            )
        )

    @staticmethod
    def _post(r: SocialPostModel) -> SocialPost:
        return SocialPost(
            r.platform,
            r.source_id,
            r.native_post_id,
            r.thread_parent_id,
            r.reply_parent_id,
            utc(r.posted_at),
            utc(r.first_observed_at),
            None if r.edited_at is None else utc(r.edited_at),
            None if r.deleted_at is None else utc(r.deleted_at),
            r.original_text,
            r.normalized_text,
            r.language,
            tuple(r.urls),
            tuple(r.mentions),
            r.quoted_source_id,
            tuple(tuple(i) for i in r.metrics),
            r.raw_artifact_sha256,
            r.content_hash,
            tuple(r.media_references),
            tuple(r.provenance),
            r.revision_of,
        )

    @staticmethod
    def _rumor(r: RumorClaimModel) -> RumorClaim:
        return RumorClaim(
            r.proposition,
            tuple(r.entities),
            r.origin_post_id,
            utc(r.first_observed_at),
            tuple(r.supporting_post_ids),
            tuple(r.contradicting_post_ids),
            tuple(r.official_evidence_ids),
            tuple(r.news_evidence_ids),
            ClaimStatus(r.status),
            r.revision_of,
            r.version,
        )
