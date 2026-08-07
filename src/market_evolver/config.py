"""Configuration with safe, non-executing defaults."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from market_evolver.errors import ConfigurationError, GovernanceViolation, ValidationError


@dataclass(frozen=True, slots=True)
class ResearchConfig:
    timezone: str = "UTC"
    strict_point_in_time: bool = True
    require_provenance: bool = True


@dataclass(frozen=True, slots=True)
class GovernanceConfig:
    allow_execution: bool = False
    allow_broker_integration: bool = False
    allow_leverage: bool = False
    allow_options: bool = False
    allow_real_money: bool = False
    untrusted_content_may_trigger_execution: bool = False

    def validate(self) -> None:
        if any(
            (
                self.allow_execution,
                self.allow_broker_integration,
                self.allow_leverage,
                self.allow_options,
                self.allow_real_money,
                self.untrusted_content_may_trigger_execution,
            )
        ):
            raise GovernanceViolation("initial skeleton forbids all execution capabilities")


@dataclass(frozen=True, slots=True)
class RuntimePermissions:
    """Host-granted capabilities; never inferred from a model recommendation."""

    network_access: bool = False
    filesystem_write: bool = False
    subprocess: bool = False
    secrets_access: bool = False
    broker_access: bool = False


@dataclass(frozen=True, slots=True)
class DatabaseConfig:
    url_env: str = "MARKET_EVOLVER_DATABASE_URL"
    require_tls: bool = True

    def resolve_url(self, environment: dict[str, str] | None = None) -> str:
        env = os.environ if environment is None else environment
        url = env.get(self.url_env, "").strip()
        if not url:
            raise ConfigurationError(f"database URL is required in {self.url_env}")
        if not url.startswith(("postgresql://", "postgresql+psycopg://")):
            raise ConfigurationError("only PostgreSQL database URLs are allowed")
        if self.require_tls and "sslmode=" not in url:
            separator = "&" if "?" in url else "?"
            url = f"{url}{separator}sslmode=require"
        return url


@dataclass(frozen=True, slots=True)
class ArtifactStorageConfig:
    root: str = "data"
    root_env: str = "MARKET_EVOLVER_ARTIFACT_ROOT"

    def resolve_root(self, environment: dict[str, str] | None = None) -> Path:
        env = os.environ if environment is None else environment
        configured = env.get(self.root_env, self.root).strip()
        if not configured:
            raise ConfigurationError("artifact storage root cannot be empty")
        return Path(configured).expanduser()


@dataclass(frozen=True, slots=True)
class AppConfig:
    research: ResearchConfig
    governance: GovernanceConfig
    runtime_permissions: RuntimePermissions
    database: DatabaseConfig
    artifact_storage: ArtifactStorageConfig


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ValidationError(f"configuration section {name!r} must be a table")
    return value


def load_config(path: str | Path) -> AppConfig:
    with Path(path).open("rb") as handle:
        data = tomllib.load(handle)
    try:
        config = AppConfig(
            research=ResearchConfig(**_section(data, "research")),
            governance=GovernanceConfig(**_section(data, "governance")),
            runtime_permissions=RuntimePermissions(**_section(data, "runtime_permissions")),
            database=DatabaseConfig(**_section(data, "database")),
            artifact_storage=ArtifactStorageConfig(**_section(data, "artifact_storage")),
        )
    except TypeError as exc:
        raise ValidationError(f"invalid configuration: {exc}") from exc
    config.governance.validate()
    if config.runtime_permissions.broker_access:
        raise GovernanceViolation("broker_access is forbidden")
    return config
