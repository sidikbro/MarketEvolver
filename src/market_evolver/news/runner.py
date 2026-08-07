"""Raw-first News Lab ingestion with fail-closed quarantine."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from market_evolver.ingestion.connectors import ObservedPayload
from market_evolver.knowledge.repositories import SqlKnowledgeGraph
from market_evolver.news.connectors import BbcBusinessRssConnector, ParsedNews
from market_evolver.news.extraction import (
    DeterministicNewsExtractor,
    content_fingerprint,
    detect_language,
)
from market_evolver.news.repositories import SqlNewsRepository
from market_evolver.news.schemas import (
    DuplicateKind,
    EvidenceSecurityClass,
    ExtractionStatus,
    NewsItem,
)
from market_evolver.provenance import content_id
from market_evolver.schemas import Evidence, Source, SourceKind, TrustLevel
from market_evolver.sources.registry import DEFAULT_REGISTRY, SourceRegistry
from market_evolver.storage.artifacts import ArtifactStore
from market_evolver.storage.models import RawIngestionModel
from market_evolver.storage.repositories import (
    SqlEvidenceRepository,
    SqlSourceRepository,
    add_artifact_metadata,
)

Clock = Callable[[], datetime]


class NewsIngestionRunner:
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

    def run(self, connector: BbcBusinessRssConnector) -> tuple[int, int, int]:
        definition = self.registry.get(connector.source_id)
        fetched = connector.fetch()
        observed = ObservedPayload.observe(fetched, self.clock())
        persisted = connector.persist_raw(observed, self.artifact_store)
        add_artifact_metadata(self.session, persisted.artifact, observed.first_observed_at)
        receipt_id = content_id(
            "raw-receipt",
            {
                "source_id": connector.source_id,
                "dataset": "news-feed",
                "sha256": observed.sha256,
            },
        )
        if self.session.get(RawIngestionModel, receipt_id) is None:
            self.session.add(
                RawIngestionModel(
                    receipt_id=receipt_id,
                    registry_source_id=connector.source_id,
                    dataset="news-feed",
                    source_uri=fetched.source_uri,
                    content_type=fetched.content_type,
                    content_hash=f"sha256:{observed.sha256}",
                    artifact_sha256=observed.sha256,
                    first_observed_at=observed.first_observed_at,
                )
            )
        self.session.commit()  # raw bytes are durable before parser-controlled work
        try:
            if fetched.source_uri != definition.base_uri:
                raise ValueError("retrieval URI violates registered source contract")
            media_type = fetched.content_type.split(";", 1)[0].strip().lower()
            if media_type not in definition.expected_content_types:
                raise ValueError("retrieval content type violates registered source contract")
            parsed = connector.parse(fetched.body)
        except Exception as exc:  # noqa: BLE001 - malformed input must be quarantined
            self._quarantine(
                connector,
                observed,
                receipt_id=receipt_id,
                reason=f"{type(exc).__name__}: {exc}"[:1024],
            )
            self.session.commit()
            return 0, 0, 1

        inserted = duplicates = quarantined = 0
        for entry in parsed:
            try:
                created = self._persist_entry(
                    connector, definition.name, observed, receipt_id, entry
                )
                inserted += int(created)
                duplicates += int(not created)
            except Exception as exc:  # noqa: BLE001 - each invalid item is quarantined
                self._quarantine(
                    connector,
                    observed,
                    receipt_id=receipt_id,
                    reason=f"{type(exc).__name__}: {exc}"[:1024],
                    entry=entry,
                )
                quarantined += 1
        self.session.commit()
        return inserted, duplicates, quarantined

    def _persist_entry(
        self,
        connector: BbcBusinessRssConnector,
        publisher: str,
        observed: ObservedPayload,
        receipt_id: str,
        entry: ParsedNews,
    ) -> bool:
        if entry.published_at > observed.first_observed_at:
            raise ValueError("publication timestamp follows local observation")
        digest = "sha256:" + hashlib.sha256(f"{entry.title}\n{entry.body}".encode()).hexdigest()
        fingerprint = content_fingerprint(entry.title, entry.body)
        repository = SqlNewsRepository(self.session)
        duplicate_kind, related = repository.classify_duplicate(
            source_id=connector.source_id,
            canonical_uri=entry.canonical_uri,
            content_hash=digest,
            fingerprint=fingerprint,
        )
        if duplicate_kind is DuplicateKind.REINGESTED:
            return False
        source = Source(
            uri=entry.canonical_uri,
            kind=SourceKind.NEWS,
            publisher=publisher,
            published_at=entry.published_at,
            observed_at=observed.first_observed_at,
            ingested_at=self.clock(),
            trust=TrustLevel.UNTRUSTED,
            content_digest=digest,
            mime_type=observed.fetched.content_type,
        )
        SqlSourceRepository(self.session).add(source)
        evidence = Evidence(
            claim=f"Publisher states: {entry.title}",
            source_ids=(source.provenance_id,),
            observed_at=observed.first_observed_at,
            excerpt_digest=digest,
        )
        SqlEvidenceRepository(self.session).add(evidence)
        item = NewsItem(
            source_id=connector.source_id,
            title=entry.title,
            body=entry.body,
            language=detect_language(f"{entry.title} {entry.body}"),
            published_at=entry.published_at,
            first_observed_at=observed.first_observed_at,
            updated_at=entry.updated_at,
            last_modified_at=entry.last_modified_at,
            canonical_uri=entry.canonical_uri,
            content_hash=digest,
            raw_artifact_sha256=observed.sha256,
            parser_version=connector.parser_version,
            trust_class=self.registry.get(connector.source_id).trust_class,
            evidence_security_class=EvidenceSecurityClass.UNTRUSTED_UNSTRUCTURED,
            evidence_id=evidence.provenance_id,
            revision_of=related if duplicate_kind is DuplicateKind.REVISION else None,
            extraction_status=ExtractionStatus.EXTRACTED,
            provenance=(receipt_id, source.provenance_id, evidence.provenance_id),
            duplicate_kind=duplicate_kind,
            normalized_fingerprint=fingerprint,
        )
        item, created = repository.add_news(item)
        if created:
            candidate = DeterministicNewsExtractor(SqlKnowledgeGraph(self.session)).extract(
                item, observed.first_observed_at
            )
            repository.add_candidate(candidate)
        return created

    def _quarantine(
        self,
        connector: BbcBusinessRssConnector,
        observed: ObservedPayload,
        *,
        receipt_id: str,
        reason: str,
        entry: ParsedNews | None = None,
    ) -> None:
        title = "Quarantined news payload" if entry is None else entry.title
        body = "Raw content retained in immutable artifact."
        uri = connector.endpoint if entry is None else entry.canonical_uri
        digest = (
            "sha256:"
            + hashlib.sha256(
                observed.fetched.body if entry is None else f"{title}\n{entry.body}".encode()
            ).hexdigest()
        )
        source = Source(
            uri=uri,
            kind=SourceKind.NEWS,
            publisher=self.registry.get(connector.source_id).name,
            published_at=observed.first_observed_at,
            observed_at=observed.first_observed_at,
            ingested_at=self.clock(),
            trust=TrustLevel.UNTRUSTED,
            content_digest=digest,
            mime_type=observed.fetched.content_type,
        )
        SqlSourceRepository(self.session).add(source)
        evidence = Evidence(
            claim="News payload quarantined; no factual claim extracted.",
            source_ids=(source.provenance_id,),
            observed_at=observed.first_observed_at,
            excerpt_digest=digest,
        )
        SqlEvidenceRepository(self.session).add(evidence)
        item = NewsItem(
            source_id=connector.source_id,
            title=title,
            body=body,
            language="und",
            published_at=observed.first_observed_at,
            first_observed_at=observed.first_observed_at,
            canonical_uri=uri,
            content_hash=digest,
            raw_artifact_sha256=observed.sha256,
            parser_version=connector.parser_version,
            trust_class=self.registry.get(connector.source_id).trust_class,
            evidence_security_class=EvidenceSecurityClass.QUARANTINED,
            evidence_id=evidence.provenance_id,
            extraction_status=ExtractionStatus.QUARANTINED,
            quarantine_reason=reason,
            provenance=(receipt_id, source.provenance_id, evidence.provenance_id),
            normalized_fingerprint=content_fingerprint(title, body),
        )
        kind, related = SqlNewsRepository(self.session).classify_duplicate(
            source_id=item.source_id,
            canonical_uri=item.canonical_uri,
            content_hash=item.content_hash,
            fingerprint=item.normalized_fingerprint,
        )
        if kind is DuplicateKind.REINGESTED:
            return
        SqlNewsRepository(self.session).add_news(
            replace(
                item,
                duplicate_kind=kind,
                revision_of=related if kind is DuplicateKind.REVISION else None,
            )
        )
