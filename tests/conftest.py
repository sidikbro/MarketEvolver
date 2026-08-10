"""Deterministic local integration defaults; never targets a non-test database."""

from __future__ import annotations

import os
import socket

LOCAL_TEST_URL = (
    "postgresql+psycopg://marketevolver_test:marketevolver_test_only"
    "@127.0.0.1:55432/marketevolver_test"
)


def pytest_configure() -> None:
    if "MARKET_EVOLVER_TEST_POSTGRES_URL" not in os.environ and _port_open("127.0.0.1", 55432):
        os.environ["MARKET_EVOLVER_TEST_POSTGRES_URL"] = LOCAL_TEST_URL


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.create_connection((host, port), timeout=0.1):
            return True
    except OSError:
        return False
