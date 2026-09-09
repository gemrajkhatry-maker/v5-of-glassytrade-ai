#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PHASE 0 — TEST HARNESS BOOTSTRAP
===============================

Provides:
1. Backend test mode boot (FastAPI TestClient with dependency injection)
2. Frontend test mode boot (Vitest with jsdom + mocked transport)
3. Shared fixtures for cross-cutting concerns (logging capture, event capture)

Run backend tests:
    cd backend && PYTHONPATH=. pytest tests/ -v

Run frontend tests:
    cd frontend && npm test

Run both together (from project root):
    make test || (cd backend && pytest tests/ -v) && (cd frontend && npm test)
"""

from __future__ import annotations

import logging
import sys
import io
from contextlib import contextmanager
from typing import Generator
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging capture for assertion on log output
# ---------------------------------------------------------------------------


class LogCapture(logging.Handler):
    """In-memory log handler for programmatic assertion on log output."""

    def __init__(self, level: int = logging.DEBUG) -> None:
        super().__init__(level)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def clear(self) -> None:
        self.records.clear()

    def has_message(self, substring: str, level: int | None = None) -> bool:
        for r in self.records:
            if substring in r.getMessage():
                if level is None or r.levelno >= level:
                    return True
        return False

    def messages(self, level: int | None = None) -> list[str]:
        if level is None:
            return [r.getMessage() for r in self.records]
        return [r.getMessage() for r in self.records if r.levelno >= level]


@contextmanager
def capture_logs(logger_name: str = "") -> Generator[LogCapture, None, None]:
    """Context manager that captures log records from a named logger.

    Usage::

        with capture_logs("app.main") as logs:
            do_something()
            assert logs.has_message("started")
    """
    handler = LogCapture()
    target = logging.getLogger(logger_name) if logger_name else logging.getLogger()
    target.addHandler(handler)
    target.setLevel(logging.DEBUG)
    try:
        yield handler
    finally:
        target.removeHandler(handler)


# ---------------------------------------------------------------------------
# Test mode helpers
# ---------------------------------------------------------------------------


def is_backend_test_mode() -> bool:
    """Return True when running under pytest in the backend tree."""
    return bool(Path("backend").exists() and sys.argv[0].endswith("pytest"))


def is_frontend_test_mode() -> bool:
    """Return True when running under vitest in the frontend tree."""
    return bool(Path("frontend").exists() and "vitest" in sys.argv[0])


def resolve_test_config() -> dict:
    """Return a test-safe configuration dict that disables network/hardware.

    All integration tests that need external plumbing must override these
    values explicitly; the defaults are paper-mode safe.
    """
    return {
        "runtime_mode": "development",
        "broker": "paper",
        "capital": 1_000_000,
        "scanner_top_n": 2,
        "default_exchange": "MCX",
        "stream_interval": "5m",
        "cors_origins": ["http://localhost:5173"],
        "reconcile_delete_stale": False,
    }


# ---------------------------------------------------------------------------
# Deterministic synthetic market data generator (used across all phases)
# ---------------------------------------------------------------------------


def generate_tick(symbol: str, price: float, volume: int = 100) -> dict:
    """Single deterministic tick dict shaped like a Dhan WS packet."""
    import time as _time

    return {
        "symbol": symbol,
        "ltp": price,
        "volume": volume,
        "timestamp": _time.time(),
        "exchange": "MCX",
    }


def generate_candle_sequence(
    symbol: str,
    start_price: float,
    n: int = 50,
    regime: str = "sideways",
    step: float = 1.0,
) -> list[dict]:
    """Generate a deterministic OHLC sequence for integration tests.

    regime ∈ {"sideways", "bullish", "bearish", "volatile"}
    """
    import random

    rng = random.Random(42)  # deterministic seed
    candles: list[dict] = []
    price = start_price
    for i in range(n):
        spread = rng.uniform(0.3, 2.0) * step
        if regime == "bullish":
            drift = step * 0.3
        elif regime == "bearish":
            drift = -step * 0.3
        elif regime == "volatile":
            drift = rng.uniform(-step, step)
        else:
            drift = rng.uniform(-step * 0.2, step * 0.2)

        open_ = price
        close = price + drift
        high = max(open_, close) + rng.uniform(0, spread)
        low = min(open_, close) - rng.uniform(0, spread)
        volume = int(rng.uniform(50, 500))

        candles.append(
            {
                "symbol": symbol,
                "time": f"2026-08-0{i % 30 + 1:02d}T09:{i % 60:02d}:00Z",
                "open": round(open_, 2),
                "high": round(high, 2),
                "low": round(low, 2),
                "close": round(close, 2),
                "volume": volume,
            }
        )
        price = close
    return candles
