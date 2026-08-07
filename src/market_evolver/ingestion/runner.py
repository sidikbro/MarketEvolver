"""Ordered ingestion orchestration with durable failure manifests."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from market_evolver.errors import GovernanceViolation
from market_evolver.ingestion.connectors import (
    IngestionConnector,
    ObservedPayload,
    PersistedPayload,
)
from market_evolver.ingestion.repositories import (
    SqlManifestRepository,
    SqlObservationRepository,
)
from market_evolver.ingestion.schemas import (
    IngestionManifest,
    IngestionStatus,
    NormalizedObservation,
)
from market_evolver.provenance import content_id
from market_evolver.schemas import Source, SourceKind, TrustLevel
from market_evolver.sources.registry import DEFAULT_REGISTRY, SourceRegistry
from market_evolver.storage.artifacts import ArtifactStore
from market_evolver.storage.models import RawIngestionModel
from market_evolver.storage.repositories import (
    SqlEvidenceRepository,
    SqlSourceRepository,
    add_artifact_metadata,
)

Clock = Callable[[], datetime]


class IngestionRunner:
    def __init__(
        self,
        session: Session,
        artifact_store: ArtifactStore,
        *,
        registry: SourceRegistry = DEFAULT_REGISTRY,
        clock: Clock | None = None,
    ) -> None:
        self.session = session
        self.artifact_store = artifact_store
        self.registry = registry
        self.clock = clock or (lambda: datetime.now(UTC))

    def run(self, connector: IngestionConnector, dataset: str) -> IngestionManifest:
        definition = self.registry.get(connector.source_id)
        if not definition.enabled:
            raise GovernanceViolation(f"source is disabled: {connector.source_id}")
        started = self.clock()
        run_id = str(uuid4())
        manifest_repository = SqlManifestRepository(self.session)
        running = self._manifest(
            run_id,
            connector,
            dataset,
            started,
            status=IngestionStatus.RUNNING,
        )
        manifest_repository.start(running)
        self.session.commit()

        bytes_downloaded = 0
        artifact_created = 0
        items_fetched = 0
        try:
            fetched = connector.fetch(dataset)
            bytes_downloaded = len(fetched.body)
            observed = ObservedPayload.observe(fetched, self.clock())
            artifact_created = int(not self.artifact_store.exists(observed.sha256))
            persisted = connector.persist_raw(observed, self.artifact_store)
            add_artifact_metadata(self.session, persisted.artifact, observed.first_observed_at)

            receipt = self._find_receipt(connector.source_id, dataset, observed.sha256)
            if receipt is None:
                receipt = RawIngestionModel(
                    receipt_id=content_id(
                        "raw-receipt",
                        {
                            "source_id": connector.source_id,
                            "dataset": dataset,
                            "sha256": observed.sha256,
                        },
                    ),
                    registry_source_id=connector.source_id,
                    dataset=dataset,
                    source_uri=fetched.source_uri,
                    content_type=fetched.content_type,
                    content_hash=f"sha256:{observed.sha256}",
                    artifact_sha256=observed.sha256,
                    first_observed_at=observed.first_observed_at,
                )
                self.session.add(receipt)
                self.session.commit()
            else:
                observed = ObservedPayload.observe(fetched, _utc(receipt.first_observed_at))
                persisted = PersistedPayload(observed, persisted.artifact)
                duplicate_count = SqlObservationRepository(self.session).count_for_artifact(
                    connector.source_id, dataset, observed.sha256
                )
                if duplicate_count:
                    finished = self._manifest(
                        run_id,
                        connector,
                        dataset,
                        started,
                        status=IngestionStatus.SUCCEEDED,
                        finished_at=self.clock(),
                        items_fetched=duplicate_count,
                        duplicates=duplicate_count,
                        bytes_downloaded=bytes_downloaded,
                    )
                    manifest_repository.finish(finished)
                    self.session.commit()
                    return finished

            # Raw artifact and receipt are durable before connector-controlled parsing.
            normalized_payload = connector.normalize(persisted)
            parsed_items = connector.parse(normalized_payload, dataset)
            items_fetched = len(parsed_items)
            published_values = [
                item.published_at for item in parsed_items if item.published_at is not None
            ]
            source = Source(
                uri=fetched.source_uri,
                kind=SourceKind.MARKET_DATA,
                publisher=definition.name,
                published_at=max(published_values) if published_values else None,
                observed_at=observed.first_observed_at,
                ingested_at=self.clock(),
                effective_at=None,
                trust=TrustLevel.AUTHORITATIVE,
                content_digest=f"sha256:{observed.sha256}",
                mime_type=fetched.content_type,
            )
            SqlSourceRepository(self.session).add(source)

            observation_repository = SqlObservationRepository(self.session)
            evidence_repository = SqlEvidenceRepository(self.session)
            inserted = 0
            duplicates = 0
            for item in parsed_items:
                observation = NormalizedObservation(
                    registry_source_id=connector.source_id,
                    source_record_id=source.provenance_id,
                    dataset=dataset,
                    item_key=item.item_key,
                    period_start=item.period_start,
                    period_end=item.period_end,
                    published_at=item.published_at,
                    first_observed_at=observed.first_observed_at,
                    effective_at=item.effective_at,
                    superseded_at=item.superseded_at,
                    value=item.value,
                    unit=item.unit,
                    raw_artifact_sha256=observed.sha256,
                    content_hash=f"sha256:{observed.sha256}",
                    parser_version=connector.parser_version,
                )
                persisted_observation, created = observation_repository.add(observation)
                evidence_repository.add(
                    connector.emit_evidence(item, source, persisted_observation)
                )
                inserted += int(created)
                duplicates += int(not created)

            finished = self._manifest(
                run_id,
                connector,
                dataset,
                started,
                status=IngestionStatus.SUCCEEDED,
                finished_at=self.clock(),
                items_fetched=items_fetched,
                items_inserted=inserted,
                duplicates=duplicates,
                bytes_downloaded=bytes_downloaded,
                raw_artifacts_created=artifact_created,
            )
            manifest_repository.finish(finished)
            self.session.commit()
            return finished
        except Exception as exc:  # noqa: BLE001 - every ingestion failure needs a manifest
            self.session.rollback()
            failed = self._manifest(
                run_id,
                connector,
                dataset,
                started,
                status=IngestionStatus.FAILED,
                finished_at=self.clock(),
                items_fetched=items_fetched,
                bytes_downloaded=bytes_downloaded,
                raw_artifacts_created=artifact_created,
                error_summary=f"{type(exc).__name__}: {exc}"[:2048],
            )
            SqlManifestRepository(self.session).finish(failed)
            self.session.commit()
            return failed

    def _find_receipt(self, source_id: str, dataset: str, sha256: str) -> RawIngestionModel | None:
        statement = select(RawIngestionModel).where(
            RawIngestionModel.registry_source_id == source_id,
            RawIngestionModel.dataset == dataset,
            RawIngestionModel.artifact_sha256 == sha256,
        )
        return self.session.scalar(statement)

    @staticmethod
    def _manifest(
        run_id: str,
        connector: IngestionConnector,
        dataset: str,
        started_at: datetime,
        *,
        status: IngestionStatus,
        finished_at: datetime | None = None,
        items_fetched: int = 0,
        items_inserted: int = 0,
        duplicates: int = 0,
        bytes_downloaded: int = 0,
        raw_artifacts_created: int = 0,
        error_summary: str | None = None,
    ) -> IngestionManifest:
        return IngestionManifest(
            run_id=run_id,
            source_id=connector.source_id,
            dataset=dataset,
            started_at=started_at,
            finished_at=finished_at,
            status=status,
            items_fetched=items_fetched,
            items_inserted=items_inserted,
            duplicates=duplicates,
            bytes_downloaded=bytes_downloaded,
            raw_artifacts_created=raw_artifacts_created,
            parser_version=connector.parser_version,
            error_summary=error_summary,
        )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
