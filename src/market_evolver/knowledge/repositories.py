"""PostgreSQL/SQLAlchemy knowledge graph with cutoff-aware indexed queries."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from market_evolver.errors import IntegrityViolation
from market_evolver.knowledge.schemas import (
    AliasRecord,
    AliasResolution,
    EntityVersion,
    EventTrace,
    Exposure,
    ExternalIdentifier,
    GraphPath,
    KnowledgeEntityType,
    RecordStatus,
    Relationship,
    RelationType,
    ResolutionStatus,
    normalize_alias,
)
from market_evolver.observatory.repositories import SqlCanonicalEventRepository
from market_evolver.storage.models import (
    KnowledgeAliasModel,
    KnowledgeEntityModel,
    KnowledgeExposureModel,
    KnowledgeRelationshipModel,
)
from market_evolver.time import require_aware_utc


class KnowledgeGraph(Protocol):
    def get_entity_at(self, entity_id: str, cutoff: datetime) -> EntityVersion | None: ...
    def resolve_alias(self, alias: str, cutoff: datetime) -> AliasResolution: ...
    def get_relationships(self, entity_id: str, cutoff: datetime) -> list[Relationship]: ...
    def get_exposures(self, entity_id: str, cutoff: datetime) -> list[Exposure]: ...
    def trace_event(self, event_id: str, cutoff: datetime) -> EventTrace: ...


class SqlKnowledgeGraph:
    def __init__(self, session: Session) -> None:
        self.session = session

    def add_entity(self, entity: EntityVersion) -> tuple[EntityVersion, bool]:
        existing = self.session.get(KnowledgeEntityModel, entity.entity_version_id)
        if existing is not None:
            return self._entity(existing), False
        self._require_next_version(
            KnowledgeEntityModel,
            (KnowledgeEntityModel.entity_id == entity.entity_id,),
            entity.version,
            "entity",
        )
        self.session.add(
            KnowledgeEntityModel(
                entity_version_id=entity.entity_version_id,
                entity_id=entity.entity_id,
                canonical_name=entity.canonical_name,
                aliases=list(entity.aliases),
                hebrew_name=entity.hebrew_name,
                english_name=entity.english_name,
                entity_type=entity.entity_type.value,
                geography=list(entity.geography),
                identifiers=[[item.scheme, item.value] for item in entity.identifiers],
                active_from=entity.active_from,
                active_until=entity.active_until,
                observed_at=entity.observed_at,
                provenance=list(entity.provenance),
                confidence=entity.confidence,
                version=entity.version,
            )
        )
        self.session.flush()
        aliases = {
            entity.canonical_name,
            entity.english_name,
            *entity.aliases,
            *(item.value for item in entity.identifiers),
        }
        if entity.hebrew_name:
            aliases.add(entity.hebrew_name)
        for alias in sorted(aliases):
            self.add_alias(
                AliasRecord(
                    alias=alias,
                    entity_version_id=entity.entity_version_id,
                    valid_from=entity.active_from,
                    valid_until=entity.active_until,
                    observed_at=entity.observed_at,
                    provenance=entity.provenance,
                )
            )
        return entity, True

    def add_alias(self, alias: AliasRecord) -> tuple[AliasRecord, bool]:
        if self.session.get(KnowledgeEntityModel, alias.entity_version_id) is None:
            raise IntegrityViolation("alias references an unknown entity version")
        if self.session.get(KnowledgeAliasModel, alias.alias_id) is not None:
            return alias, False
        self.session.add(
            KnowledgeAliasModel(
                alias_id=alias.alias_id,
                alias=alias.alias,
                normalized_alias=alias.normalized_alias,
                entity_version_id=alias.entity_version_id,
                valid_from=alias.valid_from,
                valid_until=alias.valid_until,
                observed_at=alias.observed_at,
                provenance=list(alias.provenance),
            )
        )
        self.session.flush()
        return alias, True

    def add_relationship(self, relationship: Relationship) -> tuple[Relationship, bool]:
        existing = self.session.get(KnowledgeRelationshipModel, relationship.relationship_id)
        if existing is not None:
            return self._relationship(existing), False
        self._require_entity_ids(
            (relationship.source_entity, relationship.target_entity),
            relationship.observed_at,
        )
        self._require_next_version(
            KnowledgeRelationshipModel,
            (
                KnowledgeRelationshipModel.source_entity == relationship.source_entity,
                KnowledgeRelationshipModel.target_entity == relationship.target_entity,
                KnowledgeRelationshipModel.relation_type == relationship.relation_type.value,
            ),
            relationship.version,
            "relationship",
        )
        self.session.add(
            KnowledgeRelationshipModel(
                relationship_id=relationship.relationship_id,
                relation_type=relationship.relation_type.value,
                source_entity=relationship.source_entity,
                target_entity=relationship.target_entity,
                valid_from=relationship.valid_from,
                valid_until=relationship.valid_until,
                observed_at=relationship.observed_at,
                confidence=relationship.confidence,
                provenance=list(relationship.provenance),
                status=relationship.status.value,
                version=relationship.version,
            )
        )
        self.session.flush()
        return relationship, True

    def add_exposure(self, exposure: Exposure) -> tuple[Exposure, bool]:
        existing = self.session.get(KnowledgeExposureModel, exposure.exposure_id)
        if existing is not None:
            return self._exposure(existing), False
        self._require_entity_ids(
            (exposure.subject_entity, exposure.target_entity),
            exposure.observed_at,
        )
        self._require_next_version(
            KnowledgeExposureModel,
            (
                KnowledgeExposureModel.subject_entity == exposure.subject_entity,
                KnowledgeExposureModel.target_entity == exposure.target_entity,
                KnowledgeExposureModel.exposure_type == exposure.exposure_type.value,
            ),
            exposure.version,
            "exposure",
        )
        self.session.add(
            KnowledgeExposureModel(
                exposure_id=exposure.exposure_id,
                exposure_type=exposure.exposure_type.value,
                subject_entity=exposure.subject_entity,
                target_entity=exposure.target_entity,
                direction=exposure.direction.value,
                strength=exposure.strength.value,
                unit=exposure.unit,
                value=exposure.value,
                effective_from=exposure.effective_from,
                effective_until=exposure.effective_until,
                observed_at=exposure.observed_at,
                confidence=exposure.confidence,
                source_evidence=list(exposure.source_evidence),
                status=exposure.status.value,
                version=exposure.version,
            )
        )
        self.session.flush()
        return exposure, True

    def get_entity_at(self, entity_id: str, cutoff: datetime) -> EntityVersion | None:
        normalized = require_aware_utc(cutoff, "cutoff")
        model = self.session.scalar(
            select(KnowledgeEntityModel)
            .where(
                KnowledgeEntityModel.entity_id == entity_id,
                KnowledgeEntityModel.observed_at <= normalized,
                KnowledgeEntityModel.active_from <= normalized,
                or_(
                    KnowledgeEntityModel.active_until.is_(None),
                    KnowledgeEntityModel.active_until > normalized,
                ),
            )
            .order_by(
                KnowledgeEntityModel.version.desc(),
                KnowledgeEntityModel.entity_version_id.desc(),
            )
            .limit(1)
        )
        return None if model is None else self._entity(model)

    def list_entities(
        self, cutoff: datetime, entity_type: KnowledgeEntityType | None = None
    ) -> list[EntityVersion]:
        normalized = require_aware_utc(cutoff, "cutoff")
        ids = set(
            self.session.scalars(
                select(KnowledgeEntityModel.entity_id).where(
                    KnowledgeEntityModel.observed_at <= normalized
                )
            )
        )
        entities = [
            entity
            for entity_id in sorted(ids)
            if (entity := self.get_entity_at(entity_id, normalized)) is not None
        ]
        return [item for item in entities if entity_type is None or item.entity_type is entity_type]

    def resolve_alias(self, alias: str, cutoff: datetime) -> AliasResolution:
        normalized_cutoff = require_aware_utc(cutoff, "cutoff")
        normalized_value = normalize_alias(alias)
        models = self.session.scalars(
            select(KnowledgeAliasModel).where(
                KnowledgeAliasModel.normalized_alias == normalized_value,
                KnowledgeAliasModel.observed_at <= normalized_cutoff,
                KnowledgeAliasModel.valid_from <= normalized_cutoff,
                or_(
                    KnowledgeAliasModel.valid_until.is_(None),
                    KnowledgeAliasModel.valid_until > normalized_cutoff,
                ),
            )
        )
        by_entity: dict[str, EntityVersion] = {}
        for model in models:
            entity_model = self.session.get(KnowledgeEntityModel, model.entity_version_id)
            if entity_model is None:
                continue
            entity = self.get_entity_at(entity_model.entity_id, normalized_cutoff)
            if entity is not None and entity.entity_version_id == model.entity_version_id:
                by_entity[entity.entity_id] = entity
        candidates = tuple(sorted(by_entity.values(), key=lambda item: item.entity_id))
        if len(candidates) == 1:
            status = ResolutionStatus.RESOLVED
        elif candidates:
            status = ResolutionStatus.AMBIGUOUS
        else:
            status = ResolutionStatus.NOT_FOUND
        return AliasResolution(status, candidates)

    def get_relationships(self, entity_id: str, cutoff: datetime) -> list[Relationship]:
        normalized = require_aware_utc(cutoff, "cutoff")
        models = self.session.scalars(
            select(KnowledgeRelationshipModel)
            .where(
                or_(
                    KnowledgeRelationshipModel.source_entity == entity_id,
                    KnowledgeRelationshipModel.target_entity == entity_id,
                ),
                KnowledgeRelationshipModel.observed_at <= normalized,
                KnowledgeRelationshipModel.valid_from <= normalized,
                or_(
                    KnowledgeRelationshipModel.valid_until.is_(None),
                    KnowledgeRelationshipModel.valid_until > normalized,
                ),
            )
            .order_by(
                KnowledgeRelationshipModel.source_entity,
                KnowledgeRelationshipModel.target_entity,
                KnowledgeRelationshipModel.relation_type,
                KnowledgeRelationshipModel.version.desc(),
            )
        )
        latest = self._latest_records(
            models,
            key=lambda item: (
                item.source_entity,
                item.target_entity,
                item.relation_type,
            ),
        )
        return [
            self._relationship(item) for item in latest if item.status == RecordStatus.ACTIVE.value
        ]

    def get_exposures(self, entity_id: str, cutoff: datetime) -> list[Exposure]:
        normalized = require_aware_utc(cutoff, "cutoff")
        models = self.session.scalars(
            select(KnowledgeExposureModel)
            .where(
                or_(
                    KnowledgeExposureModel.subject_entity == entity_id,
                    KnowledgeExposureModel.target_entity == entity_id,
                ),
                KnowledgeExposureModel.observed_at <= normalized,
                KnowledgeExposureModel.effective_from <= normalized,
                or_(
                    KnowledgeExposureModel.effective_until.is_(None),
                    KnowledgeExposureModel.effective_until > normalized,
                ),
            )
            .order_by(
                KnowledgeExposureModel.subject_entity,
                KnowledgeExposureModel.target_entity,
                KnowledgeExposureModel.exposure_type,
                KnowledgeExposureModel.version.desc(),
            )
        )
        latest = self._latest_records(
            models,
            key=lambda item: (
                item.subject_entity,
                item.target_entity,
                item.exposure_type,
            ),
        )
        return [self._exposure(item) for item in latest if item.status == RecordStatus.ACTIVE.value]

    def trace_event(self, event_id: str, cutoff: datetime, *, max_depth: int = 3) -> EventTrace:
        normalized = require_aware_utc(cutoff, "cutoff")
        events = {
            item.event_id: item
            for item in SqlCanonicalEventRepository(self.session).get_events_visible_at(normalized)
        }
        event = events.get(event_id)
        if event is None:
            raise IntegrityViolation("event is not visible at cutoff")
        direct_entities = tuple(
            sorted(
                entity_id
                for entity_id in event.entities
                if self.get_entity_at(entity_id, normalized) is not None
            )
        )
        candidate_mechanisms = tuple(
            sorted(
                mechanism_entity
                for mechanism_id in event.causal_mechanisms
                if self.get_entity_at(
                    mechanism_entity := f"mechanism.{mechanism_id}",
                    normalized,
                )
                is not None
            )
        )
        starts = tuple(dict.fromkeys((*direct_entities, *candidate_mechanisms)))
        paths: list[GraphPath] = []
        frontier: list[
            tuple[str, tuple[str, ...], tuple[str, ...], tuple[int, ...], float, set[str]]
        ] = [
            (
                start,
                (start,),
                (),
                (),
                event.confidence,
                set(event.evidence_ids),
            )
            for start in starts
        ]
        for _depth in range(max_depth):
            next_frontier = []
            for node, nodes, relation_ids, versions, confidence, provenance in frontier:
                for relationship in self.get_relationships(node, normalized):
                    target = (
                        relationship.target_entity
                        if relationship.source_entity == node
                        else relationship.source_entity
                    )
                    if target in nodes:
                        continue
                    next_nodes = (*nodes, target)
                    next_ids = (*relation_ids, relationship.relationship_id)
                    next_versions = (*versions, relationship.version)
                    next_provenance = provenance.union(relationship.provenance)
                    next_confidence = confidence * relationship.confidence
                    path = GraphPath(
                        entity_ids=next_nodes,
                        relationship_ids=next_ids,
                        relationship_versions=next_versions,
                        provenance=tuple(sorted(next_provenance)),
                        confidence=next_confidence,
                        cutoff_validated=True,
                    )
                    paths.append(path)
                    next_frontier.append(
                        (
                            target,
                            next_nodes,
                            next_ids,
                            next_versions,
                            next_confidence,
                            next_provenance,
                        )
                    )
            frontier = next_frontier
            if not frontier:
                break
        unique_paths = {path.relationship_ids: path for path in paths}
        return EventTrace(
            event_id=event.event_id,
            cutoff=normalized,
            direct_entities=direct_entities,
            candidate_mechanisms=candidate_mechanisms,
            paths=tuple(
                sorted(
                    unique_paths.values(),
                    key=lambda item: (len(item.relationship_ids), item.relationship_ids),
                )
            ),
        )

    def _require_entity_ids(self, entity_ids: tuple[str, ...], cutoff: datetime) -> None:
        if any(self.get_entity_at(item, cutoff) is None for item in entity_ids):
            raise IntegrityViolation("knowledge edge references an unavailable entity")

    def _require_next_version(
        self,
        model: Any,
        filters: tuple[Any, ...],
        version: int,
        label: str,
    ) -> None:
        previous = self.session.scalar(
            select(model.version).where(*filters).order_by(model.version.desc()).limit(1)
        )
        expected = 1 if previous is None else int(previous) + 1
        if version != expected:
            raise IntegrityViolation(f"{label} version must be {expected}")

    @staticmethod
    def _latest_records(models: Iterable[object], key):  # type: ignore[no-untyped-def]
        seen: set[tuple[str, ...]] = set()
        latest = []
        for model in models:
            identity = key(model)
            if identity not in seen:
                seen.add(identity)
                latest.append(model)
        return latest

    @staticmethod
    def _entity(model: KnowledgeEntityModel) -> EntityVersion:
        entity = EntityVersion(
            entity_id=model.entity_id,
            canonical_name=model.canonical_name,
            aliases=tuple(model.aliases),
            hebrew_name=model.hebrew_name,
            english_name=model.english_name,
            entity_type=KnowledgeEntityType(model.entity_type),
            geography=tuple(model.geography),
            identifiers=tuple(
                ExternalIdentifier(str(item[0]), str(item[1])) for item in model.identifiers
            ),
            active_from=_utc(model.active_from),
            active_until=_utc_optional(model.active_until),
            observed_at=_utc(model.observed_at),
            provenance=tuple(model.provenance),
            confidence=model.confidence,
            version=model.version,
        )
        if entity.entity_version_id != model.entity_version_id:
            raise IntegrityViolation("stored entity identity mismatch")
        return entity

    @staticmethod
    def _relationship(model: KnowledgeRelationshipModel) -> Relationship:
        relationship = Relationship(
            relation_type=RelationType(model.relation_type),
            source_entity=model.source_entity,
            target_entity=model.target_entity,
            valid_from=_utc(model.valid_from),
            valid_until=_utc_optional(model.valid_until),
            observed_at=_utc(model.observed_at),
            confidence=model.confidence,
            provenance=tuple(model.provenance),
            status=RecordStatus(model.status),
            version=model.version,
        )
        if relationship.relationship_id != model.relationship_id:
            raise IntegrityViolation("stored relationship identity mismatch")
        return relationship

    @staticmethod
    def _exposure(model: KnowledgeExposureModel) -> Exposure:
        from market_evolver.knowledge.schemas import (
            ExposureDirection,
            ExposureStrength,
            ExposureType,
        )

        exposure = Exposure(
            exposure_type=ExposureType(model.exposure_type),
            subject_entity=model.subject_entity,
            target_entity=model.target_entity,
            direction=ExposureDirection(model.direction),
            strength=ExposureStrength(model.strength),
            unit=model.unit,
            value=model.value,
            effective_from=_utc(model.effective_from),
            effective_until=_utc_optional(model.effective_until),
            observed_at=_utc(model.observed_at),
            confidence=model.confidence,
            source_evidence=tuple(model.source_evidence),
            status=RecordStatus(model.status),
            version=model.version,
        )
        if exposure.exposure_id != model.exposure_id:
            raise IntegrityViolation("stored exposure identity mismatch")
        return exposure


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _utc_optional(value: datetime | None) -> datetime | None:
    return None if value is None else _utc(value)
