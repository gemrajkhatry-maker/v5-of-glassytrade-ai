"""Shared mode detection utilities."""

import os
from typing import Final


_VALID_MODES: Final = frozenset({"development", "paper", "live"})


def resolve_runtime_mode() -> str:
    """Resolve one validated mode from the process environment.

    ``GLASSYTRADE_ENV`` is the canonical source. ``TRADING_MODE`` remains a
    compatibility mirror, but a disagreement is unsafe because it can build a
    live OMS while another subsystem permits paper-only operations.
    """
    env_mode = (os.getenv("GLASSYTRADE_ENV", "paper") or "").strip().lower()
    trading_mode = (os.getenv("TRADING_MODE", "") or "").strip().lower()

    if env_mode not in _VALID_MODES:
        raise ValueError(
            f"unsupported runtime mode {env_mode!r}; expected one of "
            f"{sorted(_VALID_MODES)}"
        )
    if trading_mode and trading_mode not in _VALID_MODES:
        raise ValueError(
            f"unsupported runtime mode {trading_mode!r}; expected one of "
            f"{sorted(_VALID_MODES)}"
        )
    if trading_mode and trading_mode != env_mode:
        raise ValueError(
            f"conflicting runtime modes: GLASSYTRADE_ENV={env_mode!r}, "
            f"TRADING_MODE={trading_mode!r}"
        )
    return env_mode


def is_live_mode() -> bool:
    """Return whether the validated process mode is live."""
    return resolve_runtime_mode() == "live"
