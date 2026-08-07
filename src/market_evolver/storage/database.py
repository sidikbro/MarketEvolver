"""Database engine construction."""

from sqlalchemy import Engine, create_engine

from market_evolver.config import DatabaseConfig


def create_postgres_engine(config: DatabaseConfig) -> Engine:
    """Create a production engine only from a validated PostgreSQL URL."""
    return create_engine(config.resolve_url(), pool_pre_ping=True)
