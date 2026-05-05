"""Shared mode detection utilities."""

from __future__ import annotations

import os


def _read(env_name: str) -> str:
    return (os.getenv(env_name, "") or "").strip().lower()


def is_live_mode() -> bool:
    """Return True when the process runs in live mode."""
    env_mode = _read("GLASSYTRADE_ENV")
    trading_mode = _read("TRADING_MODE")
    return env_mode == "live" or trading_mode == "live"


def is_paper_mode() -> bool:
    """Return True when paper mode is active."""
    env_mode = _read("GLASSYTRADE_ENV")
    broker_mode = _read("BROKER_MODE")
    return env_mode in {"paper", "development"} or broker_mode == "paper"


def is_dev_mode() -> bool:
    """Return True when development/testing mode is active."""
    env_mode = _read("GLASSYTRADE_ENV")
    return env_mode in {"dev", "development", "debug"}

