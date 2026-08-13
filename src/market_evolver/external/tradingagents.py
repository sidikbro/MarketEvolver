from __future__ import annotations

from datetime import datetime

from market_evolver.errors import ValidationError
from market_evolver.external.schemas import ExternalRunImport

ALLOWED_IMPORT_FIELDS = frozenset(
    {
        "benchmark_id",
        "repository_manifest_id",
        "market_evolver_sha",
        "dataset_hashes",
        "config_hashes",
        "model_provider",
        "prompt_hashes",
        "seeds",
        "environment",
        "started_at",
        "finished_at",
        "decisions",
        "portfolio_path_hash",
        "reported_metrics",
        "runtime_ms",
        "reproducibility_log_hash",
    }
)


def import_tradingagents_result(payload: dict[str, object]) -> ExternalRunImport:
    """Import a narrow reproducibility record, never an external code tree or dataset."""
    unexpected = sorted(set(payload) - ALLOWED_IMPORT_FIELDS)
    if unexpected:
        raise ValidationError(f"unsupported external run fields: {unexpected}")
    try:
        return ExternalRunImport(
            benchmark_id=str(payload["benchmark_id"]),
            repository_manifest_id=str(payload["repository_manifest_id"]),
            market_evolver_sha=str(payload["market_evolver_sha"]),
            dataset_hashes=tuple(str(item) for item in _sequence(payload["dataset_hashes"])),
            config_hashes=tuple(str(item) for item in _sequence(payload["config_hashes"])),
            model_provider=str(payload["model_provider"]),
            prompt_hashes=tuple(str(item) for item in _sequence(payload["prompt_hashes"])),
            seeds=tuple(int(str(item)) for item in _sequence(payload["seeds"])),
            environment=tuple(
                (str(item[0]), str(item[1])) for item in _pairs(payload["environment"])
            ),
            started_at=_datetime(payload["started_at"]),
            finished_at=_datetime(payload["finished_at"]),
            decisions=tuple(str(item) for item in _sequence(payload["decisions"])),
            portfolio_path_hash=str(payload["portfolio_path_hash"]),
            reported_metrics=tuple(
                (str(item[0]), float(str(item[1]))) for item in _pairs(payload["reported_metrics"])
            ),
            runtime_ms=int(str(payload["runtime_ms"])),
            reproducibility_log_hash=str(payload["reproducibility_log_hash"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise ValidationError("malformed external run import") from exc


def _sequence(value: object) -> tuple[object, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValidationError("external run collection must be a list")
    return tuple(value)


def _pairs(value: object) -> tuple[tuple[object, object], ...]:
    output = []
    for item in _sequence(value):
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValidationError("external run mapping entries must be pairs")
        output.append((item[0], item[1]))
    return tuple(output)


def _datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValidationError("external run timestamp must be ISO-8601 text")
    return datetime.fromisoformat(value)
