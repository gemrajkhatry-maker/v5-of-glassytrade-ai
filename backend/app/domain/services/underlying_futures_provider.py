"""Underlying Futures Provider — maps option contracts to their underlying futures.

This is the critical bridge between the AMT engine (Layer 1 — underlying futures)
and the execution layer (Layer 2 — option contracts).

For each option symbol (e.g., "CRUDEOIL 16 APR 8900 CALL"):
  → underlying_symbol: "CRUDEOIL25APRFUT" (for AMT analysis)
  → option_symbol: "CRUDEOIL 16 APR 8900 CALL" (for execution)

Loaded from config/instruments.json at startup.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


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
    underlying_symbol: str  # "CRUDEOIL25APRFUT"
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
                    self._instruments[exchange][underlying] = InstrumentConfig(
                        underlying_symbol=cfg["underlying_symbol"],
                        underlying_segment=cfg["underlying_segment"],
                        options_segment=cfg["options_segment"],
                        strike_step=cfg["strike_step"],
                        lot_size=cfg["lot_size"],
                        tick_size=cfg["tick_size"],
                        session_start=cfg["session_start"],
                        session_end=cfg["session_end"],
                        ib_window_minutes=cfg["ib_window_minutes"],
                        big_order_filter_lots=cfg["big_order_filter_lots"],
                        range_bar_size=cfg["range_bar_size"],
                        dead_volume_pct=cfg["dead_volume_pct"],
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

        # Get instrument config
        config = self._instruments.get(exchange, {}).get(underlying)
        if not config:
            return None

        return DualFeedMapping(
            option_symbol=option_symbol,
            underlying_symbol=config.underlying_symbol,
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
