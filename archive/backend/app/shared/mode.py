"""Shared mode detection utilities."""

import os


def is_live_mode() -> bool:
    """Check if the system is running in live trading mode.

    Returns True if GLASSYTRADE_ENV=live or TRADING_MODE=live.
    """
    env_mode = (os.getenv("GLASSYTRADE_ENV", "") or "").strip().lower()
    trading_mode = (os.getenv("TRADING_MODE", "") or "").strip().lower()
    return env_mode == "live" or trading_mode == "live"
