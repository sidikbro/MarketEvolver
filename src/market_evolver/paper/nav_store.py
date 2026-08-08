"""Derived NAV export. PostgreSQL snapshots remain the authoritative ledger."""

from __future__ import annotations

import hashlib
from pathlib import Path

import duckdb

from market_evolver.paper.schemas import PaperAccountSnapshot


class NavHistoryStore:
    def __init__(self, root: Path):
        self.root = root

    def export(self, portfolio_id: str, snapshots: tuple[PaperAccountSnapshot, ...]) -> Path:
        target = self.root / "paper" / portfolio_id / "nav.parquet"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError("derived NAV export is immutable")
        rows = [
            (item.timestamp, item.nav, item.benchmark_nav, item.kill_state.value)
            for item in snapshots
        ]
        connection = duckdb.connect()
        try:
            connection.execute(
                "CREATE TABLE nav(timestamp TIMESTAMPTZ, nav DECIMAL(28,8), benchmark_nav DECIMAL(28,8), kill_state VARCHAR)"
            )
            connection.executemany("INSERT INTO nav VALUES (?, ?, ?, ?)", rows)
            connection.execute("COPY nav TO ? (FORMAT PARQUET)", [str(target)])
        finally:
            connection.close()
        return target

    @staticmethod
    def sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @staticmethod
    def rows(path: Path) -> int:
        connection = duckdb.connect()
        try:
            row = connection.execute("SELECT count(*) FROM read_parquet(?)", [str(path)]).fetchone()
            assert row is not None
            return int(row[0])
        finally:
            connection.close()
