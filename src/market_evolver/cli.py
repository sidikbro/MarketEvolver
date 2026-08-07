"""Command-line entry point for source discovery and governed ingestion."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.orm import Session

from market_evolver.config import AppConfig, load_config
from market_evolver.errors import GovernanceViolation
from market_evolver.ingestion.boi import BankOfIsraelConnector
from market_evolver.ingestion.repositories import SqlManifestRepository
from market_evolver.ingestion.runner import IngestionRunner
from market_evolver.knowledge.repositories import SqlKnowledgeGraph
from market_evolver.knowledge.schemas import EntityVersion
from market_evolver.knowledge.seed import seed_knowledge_graph
from market_evolver.news.connectors import BbcBusinessRssConnector
from market_evolver.news.repositories import SqlNewsRepository
from market_evolver.news.runner import NewsIngestionRunner
from market_evolver.news.schemas import NewsItem
from market_evolver.observatory.extraction import BoiEventExtractionPipeline
from market_evolver.observatory.repositories import (
    SqlCanonicalEventRepository,
    observatory_summary,
)
from market_evolver.observatory.schemas import CanonicalEvent, EventStatus
from market_evolver.sources.registry import DEFAULT_REGISTRY
from market_evolver.storage.artifacts import LocalArtifactStore
from market_evolver.storage.database import create_postgres_engine
from market_evolver.storage.telemetry import measure_storage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="market-evolver")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config/default.toml"),
        help="TOML configuration path",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    source = commands.add_parser("source")
    source_commands = source.add_subparsers(dest="source_command", required=True)
    source_commands.add_parser("list")

    ingest = commands.add_parser("ingest")
    ingest.add_argument("connector", choices=("boi",))
    ingest.add_argument(
        "--dataset",
        default=BankOfIsraelConnector.dataset_name,
    )
    commands.add_parser("ingest-status")
    commands.add_parser("storage-telemetry")
    event = commands.add_parser("event")
    event_commands = event.add_subparsers(dest="event_command", required=True)
    event_commands.add_parser("list")
    show = event_commands.add_parser("show")
    show.add_argument("event_id")
    replay = event_commands.add_parser("replay")
    replay.add_argument("--at", required=True)
    event_commands.add_parser("report")
    entity = commands.add_parser("entity")
    entity_commands = entity.add_subparsers(dest="entity_command", required=True)
    entity_list = entity_commands.add_parser("list")
    entity_list.add_argument("--at")
    entity_show = entity_commands.add_parser("show")
    entity_show.add_argument("entity_id")
    entity_show.add_argument("--at")
    entity_resolve = entity_commands.add_parser("resolve")
    entity_resolve.add_argument("alias")
    entity_resolve.add_argument("--at")
    entity_commands.add_parser("seed")
    graph = commands.add_parser("graph")
    graph_commands = graph.add_subparsers(dest="graph_command", required=True)
    trace = graph_commands.add_parser("trace-event")
    trace.add_argument("event_id")
    trace.add_argument("--at", required=True)
    neighbors = graph_commands.add_parser("neighbors")
    neighbors.add_argument("entity_id")
    neighbors.add_argument("--at", required=True)
    news = commands.add_parser("news")
    news_commands = news.add_subparsers(dest="news_command", required=True)
    news_commands.add_parser("source-list")
    news_ingest = news_commands.add_parser("ingest")
    news_ingest.add_argument("source", choices=("bbc-business",))
    news_list = news_commands.add_parser("list")
    news_list.add_argument("--at")
    news_show = news_commands.add_parser("show")
    news_show.add_argument("news_id")
    news_replay = news_commands.add_parser("replay")
    news_replay.add_argument("--at", required=True)
    news_candidates = news_commands.add_parser("candidates")
    news_candidates.add_argument("--at")
    news_quarantine = news_commands.add_parser("quarantine")
    news_quarantine.add_argument("--at")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "source":
        for source in DEFAULT_REGISTRY.list():
            state = "enabled" if source.enabled else "disabled"
            print(f"{source.source_id}\t{state}\t{source.name}\t{source.ingestion_method.value}")
        return 0
    if args.command == "news" and args.news_command == "source-list":
        return _news_source_list()

    config = load_config(args.config)
    engine = create_postgres_engine(config.database)
    with Session(engine) as session:
        if args.command == "ingest":
            return _ingest(args, config, session)
        if args.command == "ingest-status":
            manifests = SqlManifestRepository(session).recent()
            print(
                json.dumps(
                    [
                        {
                            "run_id": item.run_id,
                            "source_id": item.source_id,
                            "dataset": item.dataset,
                            "status": item.status.value,
                            "started_at": item.started_at.isoformat(),
                            "finished_at": (
                                None if item.finished_at is None else item.finished_at.isoformat()
                            ),
                            "items_inserted": item.items_inserted,
                            "duplicates": item.duplicates,
                            "error_summary": item.error_summary,
                        }
                        for item in manifests
                    ],
                    indent=2,
                )
            )
            return 0
        if args.command == "event":
            return _event_command(args, session)
        if args.command == "entity":
            return _entity_command(args, session)
        if args.command == "graph":
            return _graph_command(args, session)
        if args.command == "news":
            return _news_command(args, config, session)
        telemetry = measure_storage(session)
        print(
            json.dumps(
                {
                    "raw_artifact_bytes": telemetry.raw_artifact_bytes,
                    "database_record_counts": telemetry.database_record_counts,
                    "ingestion_bytes_by_day": [
                        {"day": item.day.isoformat(), "bytes": item.value}
                        for item in telemetry.ingestion_bytes_by_day
                    ],
                    "item_growth_by_day": [
                        {"day": item.day.isoformat(), "items": item.value}
                        for item in telemetry.item_growth_by_day
                    ],
                    "news_items_by_day": [
                        {"day": item.day.isoformat(), "items": item.value}
                        for item in telemetry.news_items_by_day
                    ],
                    "raw_news_bytes_by_day": [
                        {"day": item.day.isoformat(), "bytes": item.value}
                        for item in telemetry.raw_news_bytes_by_day
                    ],
                    "news_duplicates_by_day": [
                        {"day": item.day.isoformat(), "items": item.value}
                        for item in telemetry.news_duplicates_by_day
                    ],
                    "news_revisions_by_day": [
                        {"day": item.day.isoformat(), "items": item.value}
                        for item in telemetry.news_revisions_by_day
                    ],
                    "quarantined_news_by_day": [
                        {"day": item.day.isoformat(), "items": item.value}
                        for item in telemetry.quarantined_news_by_day
                    ],
                    "news_items_by_source": telemetry.news_items_by_source,
                    "news_bytes_by_source": telemetry.news_bytes_by_source,
                },
                indent=2,
            )
        )
    return 0


def _ingest(args: argparse.Namespace, config: AppConfig, session: Session) -> int:
    if not config.runtime_permissions.network_access:
        raise GovernanceViolation("ingestion requires host-granted network_access")
    connector = BankOfIsraelConnector()
    manifest = IngestionRunner(
        session,
        LocalArtifactStore(config.artifact_storage.resolve_root()),
    ).run(connector, args.dataset)
    if manifest.status.value == "succeeded":
        BoiEventExtractionPipeline(session).run_pending()
        session.commit()
    print(f"{manifest.run_id}\t{manifest.status.value}")
    return int(manifest.status.value != "succeeded")


def _event_command(args: argparse.Namespace, session: Session) -> int:
    repository = SqlCanonicalEventRepository(session)
    if args.event_command == "show":
        event = repository.get(args.event_id)
        if event is None:
            print(json.dumps({"error": "event not found", "event_id": args.event_id}))
            return 1
        current_status = repository.current_status(event.event_id, datetime.now(UTC))
        print(
            json.dumps(
                {
                    **_event_to_dict(event),
                    "current_status": (None if current_status is None else current_status.value),
                    "transitions": [
                        {
                            "from": (None if item.from_status is None else item.from_status.value),
                            "to": item.to_status.value,
                            "at": item.transitioned_at.isoformat(),
                            "rationale": item.rationale,
                        }
                        for item in repository.transitions(event.event_id)
                    ],
                },
                indent=2,
            )
        )
        return 0
    if args.event_command == "replay":
        cutoff = _parse_timestamp(args.at)
    else:
        cutoff = datetime.now(UTC)
    if args.event_command in ("list", "replay"):
        print(
            json.dumps(
                [
                    {
                        **_event_to_dict(event),
                        "status_at_cutoff": _status_value(
                            repository.current_status(event.event_id, cutoff)
                        ),
                    }
                    for event in repository.get_events_visible_at(cutoff)
                ],
                indent=2,
            )
        )
        return 0
    summary = observatory_summary(session, cutoff)
    print(
        json.dumps(
            {
                "events_by_source": summary.events_by_source,
                "events_by_type": summary.events_by_type,
                "revision_count": summary.revision_count,
                "entities_referenced": summary.entities_referenced,
                "mechanisms_referenced": summary.mechanisms_referenced,
                "coverage_started_at": (
                    None
                    if summary.coverage_started_at is None
                    else summary.coverage_started_at.isoformat()
                ),
                "coverage_ended_at": (
                    None
                    if summary.coverage_ended_at is None
                    else summary.coverage_ended_at.isoformat()
                ),
            },
            indent=2,
        )
    )
    return 0


def _event_to_dict(event: CanonicalEvent) -> dict[str, object]:
    return {
        "event_id": event.event_id,
        "event_type": event.event_type.value,
        "source_ids": event.source_ids,
        "evidence_ids": event.evidence_ids,
        "first_observed_at": event.first_observed_at.isoformat(),
        "published_at": (None if event.published_at is None else event.published_at.isoformat()),
        "effective_at": (None if event.effective_at is None else event.effective_at.isoformat()),
        "event_status": event.event_status.value,
        "revision_state": event.revision_state.value,
        "supersedes_event_id": event.supersedes_event_id,
        "entities": event.entities,
        "mechanisms": event.causal_mechanisms,
        "attributes": dict(event.attributes),
    }


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("--at timestamp must include a timezone")
    return parsed.astimezone(UTC)


def _optional_timestamp(value: str | None) -> datetime:
    return datetime.now(UTC) if value is None else _parse_timestamp(value)


def _status_value(status: EventStatus | None) -> str | None:
    return None if status is None else status.value


def _entity_command(args: argparse.Namespace, session: Session) -> int:
    graph = SqlKnowledgeGraph(session)
    if args.entity_command == "seed":
        entities, relationships, exposures = seed_knowledge_graph(session)
        session.commit()
        print(
            json.dumps(
                {
                    "entities_inserted": entities,
                    "relationships_inserted": relationships,
                    "exposures_inserted": exposures,
                }
            )
        )
        return 0
    cutoff = _optional_timestamp(args.at)
    if args.entity_command == "list":
        print(
            json.dumps(
                [_knowledge_entity_dict(item) for item in graph.list_entities(cutoff)],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.entity_command == "show":
        entity = graph.get_entity_at(args.entity_id, cutoff)
        if entity is None:
            print(json.dumps({"error": "entity not found", "entity_id": args.entity_id}))
            return 1
        print(json.dumps(_knowledge_entity_dict(entity), ensure_ascii=False, indent=2))
        return 0
    resolution = graph.resolve_alias(args.alias, cutoff)
    print(
        json.dumps(
            {
                "status": resolution.status.value,
                "candidates": [_knowledge_entity_dict(item) for item in resolution.candidates],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return int(resolution.status.value != "resolved")


def _graph_command(args: argparse.Namespace, session: Session) -> int:
    graph = SqlKnowledgeGraph(session)
    cutoff = _parse_timestamp(args.at)
    if args.graph_command == "neighbors":
        relationships = graph.get_relationships(args.entity_id, cutoff)
        exposures = graph.get_exposures(args.entity_id, cutoff)
        print(
            json.dumps(
                {
                    "relationships": [
                        {
                            "relationship_id": item.relationship_id,
                            "relation_type": item.relation_type.value,
                            "source": item.source_entity,
                            "target": item.target_entity,
                            "version": item.version,
                            "confidence": item.confidence,
                            "provenance": item.provenance,
                        }
                        for item in relationships
                    ],
                    "exposures": [
                        {
                            "exposure_id": item.exposure_id,
                            "exposure_type": item.exposure_type.value,
                            "subject": item.subject_entity,
                            "target": item.target_entity,
                            "version": item.version,
                            "strength": item.strength.value,
                            "provenance": item.source_evidence,
                        }
                        for item in exposures
                    ],
                },
                indent=2,
            )
        )
        return 0
    trace = graph.trace_event(args.event_id, cutoff)
    print(
        json.dumps(
            {
                "event_id": trace.event_id,
                "cutoff": trace.cutoff.isoformat(),
                "direct_entities": trace.direct_entities,
                "candidate_mechanisms": trace.candidate_mechanisms,
                "paths": [
                    {
                        "entity_ids": item.entity_ids,
                        "relationship_ids": item.relationship_ids,
                        "relationship_versions": item.relationship_versions,
                        "provenance": item.provenance,
                        "confidence": item.confidence,
                        "cutoff_validated": item.cutoff_validated,
                    }
                    for item in trace.paths
                ],
            },
            indent=2,
        )
    )
    return 0


def _news_command(args: argparse.Namespace, config: AppConfig, session: Session) -> int:
    if args.news_command == "source-list":
        return _news_source_list()
    if args.news_command == "ingest":
        if not config.runtime_permissions.network_access:
            raise GovernanceViolation("news ingestion requires host-granted network_access")
        inserted, duplicates, quarantined = NewsIngestionRunner(
            session,
            LocalArtifactStore(config.artifact_storage.resolve_root()),
        ).run(BbcBusinessRssConnector())
        print(
            json.dumps(
                {
                    "inserted": inserted,
                    "duplicates": duplicates,
                    "quarantined": quarantined,
                }
            )
        )
        return int(quarantined > 0)
    repository = SqlNewsRepository(session)
    cutoff = _optional_timestamp(getattr(args, "at", None))
    if args.news_command in {"list", "replay"}:
        print(
            json.dumps(
                [_news_dict(item) for item in repository.get_news_visible_at(cutoff)],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if args.news_command == "show":
        item = repository.get(args.news_id)
        if item is None:
            print(json.dumps({"error": "news not found", "news_id": args.news_id}))
            return 1
        print(json.dumps(_news_dict(item), ensure_ascii=False, indent=2))
        return 0
    if args.news_command == "candidates":
        candidates = repository.get_event_candidates_visible_at(cutoff)
        print(
            json.dumps(
                [
                    {
                        "candidate_id": item.candidate_id,
                        "news_id": item.news_id,
                        "entities": item.extracted_entities,
                        "possible_event_type": item.possible_event_type,
                        "method": item.extraction_method,
                        "confidence": item.confidence,
                        "review_state": item.review_state.value,
                        "created_at": item.created_at.isoformat(),
                    }
                    for item in candidates
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    print(
        json.dumps(
            [_news_dict(item) for item in repository.quarantined(cutoff)],
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _news_source_list() -> int:
    definitions = [item for item in DEFAULT_REGISTRY.list() if item.source_type.value == "news"]
    print(
        json.dumps(
            [
                {
                    "source_id": item.source_id,
                    "name": item.name,
                    "trust_class": item.trust_class.value,
                    "enabled": item.enabled,
                    "languages": item.language,
                }
                for item in definitions
            ],
            indent=2,
        )
    )
    return 0


def _news_dict(item: NewsItem) -> dict[str, object]:
    return {
        "news_id": item.news_id,
        "source_id": item.source_id,
        "title": item.title,
        "language": item.language,
        "published_at": item.published_at.isoformat(),
        "first_observed_at": item.first_observed_at.isoformat(),
        "updated_at": None if item.updated_at is None else item.updated_at.isoformat(),
        "canonical_uri": item.canonical_uri,
        "content_hash": item.content_hash,
        "raw_artifact_sha256": item.raw_artifact_sha256,
        "revision_of": item.revision_of,
        "trust_class": item.trust_class.value,
        "evidence_security_class": item.evidence_security_class.value,
        "extraction_status": item.extraction_status.value,
        "quarantine_reason": item.quarantine_reason,
        "duplicate_kind": item.duplicate_kind.value,
        "provenance": item.provenance,
    }


def _knowledge_entity_dict(entity: EntityVersion) -> dict[str, object]:
    return {
        "entity_id": entity.entity_id,
        "entity_version_id": entity.entity_version_id,
        "canonical_name": entity.canonical_name,
        "hebrew_name": entity.hebrew_name,
        "english_name": entity.english_name,
        "aliases": entity.aliases,
        "entity_type": entity.entity_type.value,
        "geography": entity.geography,
        "identifiers": [
            {"scheme": item.scheme, "value": item.value} for item in entity.identifiers
        ],
        "active_from": entity.active_from.isoformat(),
        "active_until": (None if entity.active_until is None else entity.active_until.isoformat()),
        "observed_at": entity.observed_at.isoformat(),
        "provenance": entity.provenance,
        "confidence": entity.confidence,
        "version": entity.version,
    }


if __name__ == "__main__":
    raise SystemExit(main())
