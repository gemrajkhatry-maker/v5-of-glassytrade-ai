"""Underlying Futures Provider — maps option contracts to their underlying futures.

This is the critical bridge between the AMT engine (Layer 1 — underlying futures)
and the execution layer (Layer 2 — option contracts).

For each option symbol (e.g., "CRUDEOIL 16 APR 8900 CALL"):
  → underlying_symbol: broker futures root from instruments.json (e.g. CRUDEOIL25APRFUT)
  → option_symbol: "CRUDEOIL 16 APR 8900 CALL" (for execution)

Loaded from config/instruments.json. Update `underlying_symbol` when contracts roll.
Optional DD+MON derivation is only a fallback when config omits the futures root.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# Pattern: "UNDERLYING DD MON STRIKE CALL/PUT"
# e.g. "CRUDEOIL 16 APR 9000 CALL" → groups: ("CRUDEOIL", "16", "APR", "9000", "CALL")
_OPTION_SYMBOL_RE = re.compile(
    r"^([A-Z]+?)\s+(\d{1,2})\s+(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+(\d+)\s+(CALL|PUT|CE|PE)",
    re.IGNORECASE,
)


def build_futures_symbol(underlying: str, day: str, month: str) -> str:
    """Build a Dhan-resolvable futures symbol from option contract components.

    Args:
        underlying: "CRUDEOIL", "NIFTY", "GOLD", etc.
        day: Day of month, e.g. "16" or "6" (kept for signature compat)
        month: Three-letter month, e.g. "APR"

    Returns:
        Futures symbol in Dhan custom-symbol form, e.g. "NIFTY APR FUT" or
        "CRUDEOIL APR FUT" — resolves against the live broker instrument cache
        (``SEM_CUSTOM_SYMBOL``), so futures roots never go stale across rolls.
    """
    return f"{underlying.upper()} {month.upper()[:3]} FUT"


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
                / "backend"
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

        # Prefer DYNAMIC derivation from the option's own expiry month — it
        # always matches the live broker contract (e.g. "NIFTY AUG FUT"),
        # whereas config `underlying_symbol` goes stale when contracts roll.
        # Config is only a fallback when the option symbol can't be parsed.
        dynamic_symbol = self._derive_futures_symbol(option_symbol, underlying)
        if dynamic_symbol:
            underlying_symbol = dynamic_symbol
        else:
            configured = (config.underlying_symbol or "").strip()
            underlying_symbol = configured
            if not underlying_symbol:
                logger.warning(
                    "No futures symbol derivable from %s and no config symbol",
                    option_symbol,
                )
                return None

        if not underlying_symbol:
            return None

        return DualFeedMapping(
            option_symbol=option_symbol,
            underlying_symbol=underlying_symbol,
            underlying=underlying,
            exchange=exchange,
            config=config,
        )

    def build_futures_routing(
        self, option_symbols: list[str]
    ) -> tuple[dict[str, list[str]], list[str]]:
        """Map each active futures root symbol → option legs that use it for AMT.

        Returns:
            (futures_symbol -> [option symbols], sorted unique futures roots)
        """
        fut_to_opts: dict[str, list[str]] = defaultdict(list)
        for opt in option_symbols:
            m = self.get_mapping(opt)
            if m:
                fut_to_opts[m.underlying_symbol].append(opt)
        ordered = dict(sorted(fut_to_opts.items(), key=lambda x: x[0]))
        return ordered, sorted(fut_to_opts.keys())

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
