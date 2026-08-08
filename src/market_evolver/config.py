"""Configuration with safe, non-executing defaults."""

from __future__ import annotations

import os
import re
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
class ResearchProviderConfig:
    provider: str = "mock"
    model: str = "mock-research-v1"
    endpoint_env: str = "MARKET_EVOLVER_LLM_ENDPOINT"
    authorization_env: str = "MARKET_EVOLVER_LLM_AUTHORIZATION"

    def validate(self) -> None:
        if self.provider not in {"mock", "json-http"}:
            raise ConfigurationError("research provider must be mock or json-http")


@dataclass(frozen=True, slots=True)
class MarketStorageConfig:
    root: str = "data/market"
    root_env: str = "MARKET_EVOLVER_MARKET_ROOT"

    def resolve_root(self, environment: dict[str, str] | None = None) -> Path:
        env = os.environ if environment is None else environment
        configured = env.get(self.root_env, self.root).strip()
        if not configured:
            raise ConfigurationError("market Parquet root cannot be empty")
        return Path(configured).expanduser()


@dataclass(frozen=True, slots=True)
class TelegramSourceConfig:
    source_id: str
    public_identifier: str
    source_type: str
    languages: tuple[str, ...]
    domain_tags: tuple[str, ...]
    enabled: bool
    since: str | None = None
    max_messages: int | None = None
    media_policy: str = "metadata_only"

    def validate(self) -> None:
        public_name = self.public_identifier.removeprefix("@")
        if (
            not self.source_id
            or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{4,31}", public_name)
            or self.source_type not in {"public_channel", "public_group"}
        ):
            raise ConfigurationError("invalid Telegram allowlist identity")
        if self.enabled and self.since is None and self.max_messages is None:
            raise ConfigurationError("enabled Telegram source requires bounded collection policy")
        if self.max_messages is not None and not 1 <= self.max_messages <= 1000:
            raise ConfigurationError("Telegram max_messages must be 1..1000")
        if self.media_policy not in {"metadata_only", "none"}:
            raise ConfigurationError("v0.14 Telegram media policy is metadata_only or none")


@dataclass(frozen=True, slots=True)
class TelegramConfig:
    enabled: bool = False
    api_id_env: str = "MARKET_EVOLVER_TELEGRAM_API_ID"
    api_hash_env: str = "MARKET_EVOLVER_TELEGRAM_API_HASH"
    session_env: str = "MARKET_EVOLVER_TELEGRAM_SESSION"
    allowlist: tuple[TelegramSourceConfig, ...] = ()

    def validate(self) -> None:
        ids = {item.source_id for item in self.allowlist}
        if len(ids) != len(self.allowlist):
            raise ConfigurationError("duplicate Telegram allowlist source_id")
        for item in self.allowlist:
            item.validate()
        if self.enabled and not any(item.enabled for item in self.allowlist):
            raise ConfigurationError("Telegram enabled without enabled allowlist source")

    def credentials(self, environment: dict[str, str] | None = None) -> tuple[int, str, str]:
        env = os.environ if environment is None else environment
        try:
            api_id = int(env[self.api_id_env])
            api_hash = env[self.api_hash_env]
            session = env[self.session_env]
        except (KeyError, ValueError) as exc:
            raise ConfigurationError("Telegram credentials are required in environment") from exc
        if not api_hash or not session:
            raise ConfigurationError("Telegram credentials cannot be empty")
        if api_id <= 0:
            raise ConfigurationError("Telegram API ID must be positive")
        return api_id, api_hash, session


@dataclass(frozen=True, slots=True)
class AppConfig:
    research: ResearchConfig
    governance: GovernanceConfig
    runtime_permissions: RuntimePermissions
    database: DatabaseConfig
    artifact_storage: ArtifactStorageConfig
    research_provider: ResearchProviderConfig
    market_storage: MarketStorageConfig
    telegram: TelegramConfig


def _section(data: dict[str, Any], name: str) -> dict[str, Any]:
    value = data.get(name, {})
    if not isinstance(value, dict):
        raise ValidationError(f"configuration section {name!r} must be a table")
    return value


def load_config(path: str | Path) -> AppConfig:
    with Path(path).open("rb") as handle:
        data = tomllib.load(handle)
    try:
        telegram_data = _section(data, "telegram")
        allowlist_raw = telegram_data.pop("allowlist", [])
        if not isinstance(allowlist_raw, list):
            raise ValidationError("telegram allowlist must be an array")
        telegram = TelegramConfig(
            **telegram_data, allowlist=tuple(TelegramSourceConfig(**item) for item in allowlist_raw)
        )
        config = AppConfig(
            research=ResearchConfig(**_section(data, "research")),
            governance=GovernanceConfig(**_section(data, "governance")),
            runtime_permissions=RuntimePermissions(**_section(data, "runtime_permissions")),
            database=DatabaseConfig(**_section(data, "database")),
            artifact_storage=ArtifactStorageConfig(**_section(data, "artifact_storage")),
            research_provider=ResearchProviderConfig(**_section(data, "research_provider")),
            market_storage=MarketStorageConfig(**_section(data, "market_storage")),
            telegram=telegram,
        )
    except TypeError as exc:
        raise ValidationError(f"invalid configuration: {exc}") from exc
    config.governance.validate()
    if config.runtime_permissions.broker_access:
        raise GovernanceViolation("broker_access is forbidden")
    config.research_provider.validate()
    config.telegram.validate()
    return config
