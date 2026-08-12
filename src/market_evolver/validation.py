"""One-command deterministic system validation; critical skips are failures."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

DEFAULT_TEST_POSTGRES_URL = (
    "postgresql+psycopg://marketevolver_test:marketevolver_test_only"
    "@127.0.0.1:55432/marketevolver_test"
)


@dataclass(frozen=True, slots=True)
class ValidationCheck:
    name: str
    status: str
    command: str
    detail: str
    critical: bool = True


@dataclass(frozen=True, slots=True)
class ValidationReport:
    status: str
    checks: tuple[ValidationCheck, ...]
    failures: tuple[str, ...]
    skips: tuple[str, ...]


def validate_system(root: Path | None = None) -> ValidationReport:
    project = root or Path.cwd()
    python = sys.executable
    checks: list[ValidationCheck] = []
    checks.append(_run("ruff", (python, "-m", "ruff", "check", "src", "tests"), project))
    checks.append(_run("mypy", (python, "-m", "mypy", "src/market_evolver"), project))
    offline = _run(
        "offline_tests",
        (
            python,
            "-m",
            "pytest",
            "-m",
            "not postgres and not live and not external_provider",
            "--cov=market_evolver",
            "--cov-report=term-missing:skip-covered",
            "--cov-report=xml:coverage.xml",
        ),
        project,
    )
    checks.append(offline)
    for name, evidence in (
        ("duckdb_parquet", "tests/test_market_replay.py, tests/test_paper.py"),
        ("provenance", "tests/test_provenance.py and integration scenario"),
        ("historical_replay", "replay, cross-lab, topology cutoff tests"),
        ("safety", "adversarial evolution/topology/paper tests"),
        ("topology", "tests/test_topology.py and integration scenario"),
        ("paper_accounting", "tests/test_paper.py and integration scenario"),
    ):
        checks.append(ValidationCheck(name, offline.status, "included in offline_tests", evidence))

    url = os.environ.get("MARKET_EVOLVER_TEST_POSTGRES_URL", DEFAULT_TEST_POSTGRES_URL)
    database_ready, database_detail = _postgres_ready(url)
    if not database_ready:
        failure = ValidationCheck(
            "postgres",
            "FAIL",
            "pytest -m postgres",
            f"required dedicated PostgreSQL unavailable: {database_detail}",
        )
        checks.extend(
            (
                failure,
                ValidationCheck(
                    "migrations",
                    "FAIL",
                    "alembic upgrade head",
                    "not run because PostgreSQL is unavailable",
                ),
            )
        )
    else:
        environment = {
            **os.environ,
            "MARKET_EVOLVER_TEST_POSTGRES_URL": url,
            "MARKET_EVOLVER_DATABASE_URL": url,
        }
        postgres = _run(
            "postgres", (python, "-m", "pytest", "-m", "postgres", "-rA"), project, environment
        )
        if "SKIPPED" in postgres.detail.upper():
            postgres = ValidationCheck(
                "postgres", "FAIL", postgres.command, "critical PostgreSQL suite reported skips"
            )
        checks.append(postgres)
        checks.append(_migration_check(url, project, environment))
    failures = tuple(item.name for item in checks if item.critical and item.status != "PASS")
    skips = tuple(item.name for item in checks if item.status == "SKIP")
    return ValidationReport("PASS" if not failures else "FAIL", tuple(checks), failures, skips)


def print_validation_report(report: ValidationReport) -> None:
    print(json.dumps(asdict(report), indent=2))


def _run(
    name: str, command: tuple[str, ...], root: Path, environment: dict[str, str] | None = None
) -> ValidationCheck:
    result = subprocess.run(
        command,
        cwd=root,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    output = result.stdout.strip()
    detail = output[-4000:] if output else "completed without output"
    return ValidationCheck(
        name, "PASS" if result.returncode == 0 else "FAIL", " ".join(command), detail
    )


def _postgres_ready(url: str) -> tuple[bool, str]:
    if "_test" not in url:
        return False, "URL does not identify a dedicated *_test database"
    engine = create_engine(url, pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            database = str(connection.scalar(text("SELECT current_database()")))
            if not database.endswith("_test"):
                return False, f"connected database {database!r} is not dedicated test database"
        return True, database
    except (SQLAlchemyError, OSError) as exc:
        return False, f"{type(exc).__name__}: {exc}"
    finally:
        engine.dispose()


def _migration_check(url: str, root: Path, environment: dict[str, str]) -> ValidationCheck:
    migrated = _run(
        "migration_command", (sys.executable, "-m", "alembic", "upgrade", "head"), root, environment
    )
    if migrated.status != "PASS":
        return ValidationCheck("migrations", "FAIL", migrated.command, migrated.detail)
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            version = connection.scalar(text("SELECT version_num FROM alembic_version"))
        status = "PASS" if version == "0021" else "FAIL"
        return ValidationCheck(
            "migrations",
            status,
            migrated.command,
            f"clean/idempotent migration head={version}; expected=0021",
        )
    finally:
        engine.dispose()
