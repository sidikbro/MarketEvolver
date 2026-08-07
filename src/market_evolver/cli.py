"""Command-line entry point for source discovery and governed ingestion."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy.orm import Session

from market_evolver.config import AppConfig, load_config
from market_evolver.errors import GovernanceViolation
from market_evolver.ingestion.boi import BankOfIsraelConnector
from market_evolver.ingestion.repositories import SqlManifestRepository
from market_evolver.ingestion.runner import IngestionRunner
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
    print(f"{manifest.run_id}\t{manifest.status.value}")
    return int(manifest.status.value != "succeeded")


if __name__ == "__main__":
    raise SystemExit(main())
