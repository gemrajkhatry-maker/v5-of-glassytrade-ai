"""Underlying Futures Provider — maps option contracts to their underlying futures.

This is the critical bridge between the AMT engine (Layer 1 — underlying futures)
and the execution layer (Layer 2 — option contracts).

For each option symbol (e.g., "CRUDEOIL 16 APR 8900 CALL"):
  → underlying_symbol: "CRUDEOIL16APRFUT" (dynamically derived from option date)
  → option_symbol: "CRUDEOIL 16 APR 8900 CALL" (for execution)

Loaded from config/instruments.json at startup. Only numeric config (lot_size,
strike_step, etc.) is read from the JSON file — the underlying_symbol is
derived dynamically from the option contract's expiry date, so it never goes
stale when contracts expire.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# Month abbreviation → two-digit number, for building futures symbols
_MONTH_MAP = {
    "JAN": "01", "FEB": "02", "MAR": "03", "APR": "04",
    "MAY": "05", "JUN": "06", "JUL": "07", "AUG": "08",
    "SEP": "09", "OCT": "10", "NOV": "11", "DEC": "12",
}

# Pattern: "UNDERLYING DD MON STRIKE CALL/PUT"
# e.g. "CRUDEOIL 16 APR 9000 CALL" → groups: ("CRUDEOIL", "16", "APR", "9000", "CALL")
_OPTION_SYMBOL_RE = re.compile(
    r"^([A-Z]+?)\s+(\d{1,2})\s+(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+(\d+)\s+(CALL|PUT|CE|PE)",
    re.IGNORECASE,
)


def build_futures_symbol(underlying: str, day: str, month: str) -> str:
    """Build a futures symbol from parsed option contract components.

    Args:
        underlying: "CRUDEOIL", "NIFTY", "GOLD", etc.
        day: Day of month, e.g. "16" or "6"
        month: Three-letter month, e.g. "APR"

    Returns:
        Futures symbol, e.g. "CRUDEOIL16APRFUT" or "NIFTY06APRFUT"
    """
    day_padded = day.zfill(2)
    month_upper = month.upper()
    month_num = _MONTH_MAP.get(month_upper, month_upper[:3].upper())
    return f"{underlying.upper()}{day_padded}{month_num}FUT"


def extract_option_date(symbol: str) -> tuple[str, str, str] | None:
    """Extract (underlying, day, month) from an option symbol.

    Args:
        symbol: e.g. "CRUDEOIL 16 APR 9000 CALL"

    Returns:
        ("CRUDEOIL", "16", "APR") or None if pattern doesn't match.
    """
    clean = symbol.replace("NSE:", "").replace("MCX:", "").strip().upper()
    m = _OPTION_SYMBOL_RE.match(clean)
    if not m:
        return None
    return (m.group(1).upper(), m.group(2), m.group(3).upper())


@dataclass(frozen=True)
class InstrumentConfig:
    """Per-instrument configuration loaded from instruments.json."""

    underlying_symbol: str
    underlying_segment: str
    options_segment: str
    strike_step: int
    lot_size: int
    tick_size: float
    session_start: str
    session_end: str
    ib_window_minutes: int
    big_order_filter_lots: int
    range_bar_size: int
    dead_volume_pct: int


@dataclass(frozen=True)
class DualFeedMapping:
    """Maps an option contract to its underlying futures for AMT analysis."""

    option_symbol: str  # "CRUDEOIL 16 APR 8900 CALL"
    underlying_symbol: str  # "CRUDEOIL16APRFUT" — derived dynamically
    underlying: str  # "CRUDEOIL"
    exchange: str  # "MCX" or "NSE"
    config: InstrumentConfig


class UnderlyingFuturesProvider:
    """Provides underlying futures mapping for option contracts.

    Loads instrument mapping from config/instruments.json.
    For each option symbol, provides the corresponding underlying futures
    symbol for AMT analysis.
    """

    def __init__(self, config_path: str | Path | None = None) -> None:
        if config_path is None:
            config_path = (
                Path(__file__).parent.parent.parent.parent
                / "config"
                / "instruments.json"
            )
        self._config_path = Path(config_path)
        self._instruments: dict[str, dict[str, InstrumentConfig]] = {}
        self._load()

    def _load(self) -> None:
        """Load instrument config from JSON."""
        try:
            with open(self._config_path) as f:
                raw = json.load(f)

            for exchange, underlyings in raw.items():
                self._instruments[exchange] = {}
                for underlying, cfg in underlyings.items():
                    # underlying_symbol is now derived dynamically at lookup time.
                    # We still store it from the JSON for backward compatibility,
                    # but get_mapping() will prefer the dynamic version.
                    self._instruments[exchange][underlying] = InstrumentConfig(
                        underlying_symbol=cfg.get("underlying_symbol", f"{underlying}FUT"),
                        underlying_segment=cfg["underlying_segment"],
                        options_segment=cfg["options_segment"],
                        strike_step=cfg.get("strike_step", 1),
                        lot_size=cfg.get("lot_size", 1),
                        tick_size=cfg.get("tick_size", 0.05),
                        session_start=cfg.get("session_start", "09:15"),
                        session_end=cfg.get("session_end", "15:30"),
                        ib_window_minutes=cfg.get("ib_window_minutes", 30),
                        big_order_filter_lots=cfg.get("big_order_filter_lots", 10),
                        range_bar_size=cfg.get("range_bar_size", 10),
                        dead_volume_pct=cfg.get("dead_volume_pct", 5),
                    )

            logger.info(
                "UnderlyingFuturesProvider loaded: %d exchanges, %d underlyings",
                len(self._instruments),
                sum(len(u) for u in self._instruments.values()),
            )
        except Exception as e:
            logger.error("Failed to load instruments.json: %s", e)
            self._instruments = {}

    def get_mapping(self, option_symbol: str) -> DualFeedMapping | None:
        """Get the dual feed mapping for an option symbol.

        The underlying futures symbol is derived DYNAMICALLY from the option
        contract's expiry date (e.g., "CRUDEOIL 16 APR 9000 CALL" → "CRUDEOIL16APRFUT").
        This avoids stale 2025 contract names from instruments.json.

        Args:
            option_symbol: e.g., "CRUDEOIL 16 APR 8900 CALL"

        Returns:
            DualFeedMapping with underlying futures symbol, or None if not found
        """
        # Extract underlying name from option symbol
        underlying = self._extract_underlying(option_symbol)
        if not underlying:
            return None

        # Find exchange
        exchange = self._find_exchange(underlying)
        if not exchange:
            return None

        # Get instrument config (for numeric settings, NOT the hardcoded futures symbol)
        config = self._instruments.get(exchange, {}).get(underlying)
        if not config:
            return None

        # Derive underlying futures symbol dynamically from the option contract date
        dynamic_symbol = self._derive_futures_symbol(option_symbol, underlying)
        if dynamic_symbol:
            underlying_symbol = dynamic_symbol
            logger.debug(
                "Dual feed mapping: %s → %s (dynamic)", option_symbol, underlying_symbol
            )
        else:
            # Fallback to the hardcoded value from instruments.json
            underlying_symbol = config.underlying_symbol
            logger.warning(
                "Could not derive futures symbol from option date for %s — "
                "falling back to config: %s",
                option_symbol,
                underlying_symbol,
            )

        return DualFeedMapping(
            option_symbol=option_symbol,
            underlying_symbol=underlying_symbol,
            underlying=underlying,
            exchange=exchange,
            config=config,
        )

    def get_underlying_symbol(self, option_symbol: str) -> str | None:
        """Get just the underlying futures symbol for an option contract."""
        mapping = self.get_mapping(option_symbol)
        return mapping.underlying_symbol if mapping else None

    def get_config(self, underlying: str, exchange: str) -> InstrumentConfig | None:
        """Get instrument config for an underlying."""
        return self._instruments.get(exchange, {}).get(underlying)

    def get_all_underlyings(self, exchange: str) -> list[str]:
        """Get all underlyings for an exchange."""
        return list(self._instruments.get(exchange, {}).keys())

    def _derive_futures_symbol(self, option_symbol: str, underlying: str) -> str | None:
        """Derive futures symbol dynamically from option contract date.

        Args:
            option_symbol: e.g. "CRUDEOIL 16 APR 9000 CALL"
            underlying: e.g. "CRUDEOIL"

        Returns:
            e.g. "CRUDEOIL16APRFUT" or None if date can't be parsed
        """
        date_parts = extract_option_date(option_symbol)
        if date_parts:
            _, day, month = date_parts
            return build_futures_symbol(underlying, day, month)

        # Not a standard option symbol — could be a futures symbol itself,
        # or an index option with a different format. Fall back gracefully.
        return None

    def _extract_underlying(self, symbol: str) -> str:
        """Extract underlying name from option symbol.

        "CRUDEOIL 16 APR 8900 CALL" → "CRUDEOIL"
        "NIFTY 30 MAR 23300 PUT" → "NIFTY"
        """
        parts = symbol.split()
        if parts:
            return parts[0].upper()
        return ""

    def _find_exchange(self, underlying: str) -> str | None:
        """Find which exchange an underlying belongs to."""
        for exchange, underlyings in self._instruments.items():
            if underlying in underlyings:
                return exchange
        return None
