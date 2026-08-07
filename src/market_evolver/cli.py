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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "source":
        for source in DEFAULT_REGISTRY.list():
            state = "enabled" if source.enabled else "disabled"
            print(f"{source.source_id}\t{state}\t{source.name}\t{source.ingestion_method.value}")
        return 0

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


def _status_value(status: EventStatus | None) -> str | None:
    return None if status is None else status.value


if __name__ == "__main__":
    raise SystemExit(main())
