"""Deterministic BOI event extraction and pending-observation pipeline."""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_evolver.errors import IntegrityViolation
from market_evolver.ingestion.repositories import SqlObservationRepository
from market_evolver.ingestion.schemas import NormalizedObservation
from market_evolver.observatory.entities import (
    DEFAULT_ENTITY_REGISTRY,
    EntityRegistry,
)
from market_evolver.observatory.repositories import (
    SqlCanonicalEventRepository,
    SqlEventMechanismRepository,
)
from market_evolver.observatory.schemas import (
    CanonicalEvent,
    EventMechanismLink,
    EventStatus,
    EventType,
    ExpectedHorizon,
    ReviewerStatus,
    RevisionState,
)
from market_evolver.schemas import Evidence, Source
from market_evolver.storage.models import EvidenceModel
from market_evolver.storage.repositories import SqlEvidenceRepository, SqlSourceRepository


class BoiEventExtractor:
    """Pure rules for supported BOI USD/EUR representative-rate observations."""

    unusual_move_threshold_percent = Decimal("1.0")

    def __init__(self, entities: EntityRegistry = DEFAULT_ENTITY_REGISTRY) -> None:
        self.entities = entities

    def extract(
        self,
        observation: NormalizedObservation,
        source: Source,
        evidence: Evidence,
        previous: NormalizedObservation | None,
    ) -> tuple[CanonicalEvent, ...]:
        currency = observation.item_key.upper()
        currency_entity = f"currency.{currency.lower()}"
        if observation.registry_source_id != "il.boi" or not self.entities.contains(
            currency_entity
        ):
            return ()
        period = observation.period_start.isoformat()
        update = self._event(
            observation,
            source,
            evidence,
            currency_entity,
            event_type=EventType.REPRESENTATIVE_EXCHANGE_RATE_UPDATE,
            mechanisms=("currency_translation",),
            novelty=1.0,
            tags=("boi", "official", "representative_rate", currency.lower()),
            attributes=(
                ("currency", currency),
                ("period", period),
                ("unit", observation.unit),
                ("value", observation.value),
            ),
            deduplication_key=f"boi.fx.rate:{currency}:{period}",
        )
        if previous is None:
            return (update,)

        previous_value = Decimal(previous.value)
        current_value = Decimal(observation.value)
        if previous_value == 0:
            raise IntegrityViolation("cannot calculate rate movement from a zero prior value")
        change = ((current_value / previous_value) - 1) * 100
        change_text = format(change.quantize(Decimal("0.000001")), "f")
        movement = self._event(
            observation,
            source,
            evidence,
            currency_entity,
            event_type=EventType.RATE_MOVEMENT,
            mechanisms=(
                "currency_translation",
                "import_cost",
                "export_competitiveness",
            ),
            novelty=0.8,
            tags=("boi", "official", "fx_movement", currency.lower()),
            attributes=(
                ("change_percent", change_text),
                ("currency", currency),
                ("current_value", observation.value),
                ("period", period),
                ("previous_value", previous.value),
            ),
            deduplication_key=f"boi.fx.movement:{currency}:{period}",
        )
        events = [update, movement]
        if abs(change) >= self.unusual_move_threshold_percent:
            events.append(
                self._event(
                    observation,
                    source,
                    evidence,
                    currency_entity,
                    event_type=EventType.UNUSUAL_FX_MOVE,
                    mechanisms=(
                        "currency_translation",
                        "import_cost",
                        "export_competitiveness",
                        "risk_premium",
                    ),
                    novelty=1.0,
                    tags=("boi", "official", "unusual_fx_move", currency.lower()),
                    attributes=movement.attributes,
                    deduplication_key=f"boi.fx.unusual:{currency}:{period}",
                )
            )
        return tuple(events)

    @staticmethod
    def _event(
        observation: NormalizedObservation,
        source: Source,
        evidence: Evidence,
        currency_entity: str,
        *,
        event_type: EventType,
        mechanisms: tuple[str, ...],
        novelty: float,
        tags: tuple[str, ...],
        attributes: tuple[tuple[str, str], ...],
        deduplication_key: str,
    ) -> CanonicalEvent:
        return CanonicalEvent(
            event_type=event_type,
            source_ids=(source.provenance_id,),
            evidence_ids=(evidence.provenance_id,),
            geography=("IL",),
            entities=(
                "institution.boi",
                "currency.ils",
                currency_entity,
                "country.il",
                "sector.financial",
                "cohort.exporters",
                "cohort.importers",
            ),
            sectors=("sector.financial",),
            affected_asset_classes=("foreign_exchange",),
            published_at=observation.published_at,
            first_observed_at=observation.first_observed_at,
            effective_at=observation.effective_at,
            event_status=EventStatus.CONFIRMED,
            confidence=1.0,
            novelty=novelty,
            revision_state=RevisionState.ORIGINAL,
            supersedes_event_id=None,
            causal_mechanisms=mechanisms,
            tags=tags,
            attributes=attributes,
            deduplication_key=deduplication_key,
        )

    @staticmethod
    def mechanism_links(event: CanonicalEvent) -> tuple[EventMechanismLink, ...]:
        horizons = {
            "currency_translation": ExpectedHorizon.IMMEDIATE,
            "import_cost": ExpectedHorizon.WEEKS,
            "export_competitiveness": ExpectedHorizon.MONTHS,
            "risk_premium": ExpectedHorizon.DAYS,
        }
        confidences = {
            "currency_translation": 0.95,
            "import_cost": 0.75,
            "export_competitiveness": 0.70,
            "risk_premium": 0.65,
        }
        return tuple(
            EventMechanismLink(
                event_id=event.event_id,
                mechanism_id=mechanism_id,
                confidence=confidences[mechanism_id],
                expected_horizon=horizons[mechanism_id],
                rationale=(
                    f"Deterministic {event.event_type.value} rule links this "
                    f"direction-neutral mechanism"
                ),
                evidence_ids=event.evidence_ids,
                reviewer_status=ReviewerStatus.RULE_VALIDATED,
                linked_at=event.first_observed_at,
            )
            for mechanism_id in event.causal_mechanisms
        )


class BoiEventExtractionPipeline:
    def __init__(self, session: Session, extractor: BoiEventExtractor | None = None) -> None:
        self.session = session
        self.extractor = extractor or BoiEventExtractor()

    def run_pending(self) -> tuple[int, int]:
        observations = SqlObservationRepository(self.session).list_for_source("il.boi")
        event_repository = SqlCanonicalEventRepository(self.session)
        mechanism_repository = SqlEventMechanismRepository(self.session)
        source_repository = SqlSourceRepository(self.session)
        evidence_repository = SqlEvidenceRepository(self.session)
        previous_by_currency: dict[str, NormalizedObservation] = {}
        inserted = 0
        duplicates = 0

        for observation in observations:
            source = source_repository.get(observation.source_record_id)
            evidence_model = self.session.scalar(
                select(EvidenceModel).where(
                    EvidenceModel.excerpt_digest == observation.provenance_id
                )
            )
            if source is None or evidence_model is None:
                raise IntegrityViolation("observation lacks source/evidence provenance")
            evidence = evidence_repository.get(evidence_model.provenance_id)
            assert evidence is not None
            candidates = self.extractor.extract(
                observation,
                source,
                evidence,
                previous_by_currency.get(observation.item_key),
            )
            for candidate in candidates:
                prior_event = event_repository.latest_for_key_before(
                    candidate.deduplication_key, candidate.first_observed_at
                )
                if (
                    prior_event is not None
                    and prior_event.material_fingerprint != candidate.material_fingerprint
                ):
                    candidate = replace(
                        candidate,
                        event_status=EventStatus.REVISED,
                        revision_state=RevisionState.CORRECTED,
                        supersedes_event_id=prior_event.event_id,
                    )
                persisted, created = event_repository.add(candidate)
                inserted += int(created)
                duplicates += int(not created)
                for link in self.extractor.mechanism_links(persisted):
                    mechanism_repository.add(link)
            previous_by_currency[observation.item_key] = observation
        self.session.flush()
        return inserted, duplicates
