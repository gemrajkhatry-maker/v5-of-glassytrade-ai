"""Resolve GLASSYTRADE_STRATEGY to a real strategies/*.yaml name.

Legacy / typo names (e.g. nse_index_options) and missing files fall back so
base+env never silently run without a strategy overlay (which reverts to NSE in development.yaml).
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_STRATEGY_ALIASES: dict[str, str] = {
    "nse_index_options": "nse_options",
    "nse_index": "nse_options",
    "index_options": "nse_options",
    "nifty_options": "nse_options",
    "mcx": "mcx_options",
    "commodity": "mcx_options",
    "commodities": "mcx_options",
    "mcxcommodity": "mcx_options",
}


def normalize_strategy_token(name: str | None) -> str:
    s = (name or "").strip()
    if not s:
        return "mcx_options"
    key = s.lower().replace(" ", "_").replace("-", "_")
    return _STRATEGY_ALIASES.get(key, s)


def resolved_strategy_for_filesystem(config_dir: Path, strategy: str | None) -> str:
    """Return a strategy that has ``strategies/{name}.yaml``; else ``mcx_options``."""
    s = normalize_strategy_token(strategy)
    p = config_dir / "strategies" / f"{s}.yaml"
    if p.is_file():
        return s
    logger.warning(
        "No strategy file at %s (GLASSYTRADE_STRATEGY=%r); using mcx_options",
        p,
        strategy,
    )
    return "mcx_options"
