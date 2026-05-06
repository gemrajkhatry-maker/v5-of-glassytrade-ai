"""Underlying futures provider for option-underlying mapping."""
from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_MONTH_MAP = {
    "JAN": "01",
    "FEB": "02",
    "MAR": "03",
    "APR": "04",
    "MAY": "05",
    "JUN": "06",
    "JUL": "07",
    "AUG": "08",
    "SEP": "09",
    "OCT": "10",
    "NOV": "11",
    "DEC": "12",
}
_OPTION_SYMBOL_RE = re.compile(
    r"^([A-Z]+?)\s+(\d{1,2})\s+(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)\s+(\d+)\s+(CALL|PUT|CE|PE)",
    re.IGNORECASE,
)


def build_futures_symbol(underlying: str, day: str, month: str) -> str:
    """Build an exchange-specific futures symbol from option date components."""
    day_padded = day.zfill(2)
    month_num = _MONTH_MAP.get(month.upper(), month.upper()[:3])
    return f"{underlying.upper()}{day_padded}{month_num}FUT"


def extract_option_date(symbol: str) -> tuple[str, str, str] | None:
    """Extract tuple of underlying, day, month from option symbol."""
    clean = symbol.replace("NSE:", "").replace("MCX:", "").strip().upper()
    m = _OPTION_SYMBOL_RE.match(clean)
    if not m:
        return None
    return (m.group(1).upper(), m.group(2), m.group(3).upper())


@dataclass(frozen=True)
class InstrumentConfig:
    """Persistent instrument config loaded from instruments.json."""

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
    """Maps option symbol to the futures symbol used for AMT analysis."""

    option_symbol: str
    underlying_symbol: str
    underlying: str
    exchange: str
    config: InstrumentConfig


class UnderlyingFuturesProvider:
    """Resolve the futures contract for option contracts."""

    def __init__(self, config_path: str | Path | None = None) -> None:
        if config_path is None:
            config_path = Path(__file__).parent.parent.parent.parent / "config" / "instruments.json"
        self._config_path = Path(config_path)
        self._instruments: dict[str, dict[str, InstrumentConfig]] = {}
        self._load()

    def _load(self) -> None:
        try:
            with open(self._config_path) as handle:
                raw = json.load(handle)
            for exchange, underlyings in raw.items():
                self._instruments[exchange] = {}
                for underlying, cfg in underlyings.items():
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
        except Exception as exc:
            logger.error("Failed to load instruments config: %s", exc)
            self._instruments = {}

    def _extract_underlying(self, symbol: str) -> str:
        parts = symbol.replace("NSE:", "").replace("MCX:", "").strip().split()
        return parts[0].upper() if parts else ""

    def _find_exchange(self, underlying: str) -> str | None:
        for exchange, underlyings in self._instruments.items():
            if underlying in underlyings:
                return exchange
        return None

    def _derive_futures_symbol(self, option_symbol: str, underlying: str) -> str | None:
        date_parts = extract_option_date(option_symbol)
        if not date_parts:
            return None
        _, day, month = date_parts
        return build_futures_symbol(underlying, day, month)

    def get_mapping(self, option_symbol: str) -> DualFeedMapping | None:
        underlying = self._extract_underlying(option_symbol)
        if not underlying:
            return None
        exchange = self._find_exchange(underlying)
        if not exchange:
            return None
        config = self._instruments.get(exchange, {}).get(underlying)
        if not config:
            return None

        configured = config.underlying_symbol.strip()
        dynamic_symbol = self._derive_futures_symbol(option_symbol, underlying)

        if configured:
            underlying_symbol = configured
            if dynamic_symbol and configured != dynamic_symbol:
                logger.debug(
                    "Dual feed configured mapping: %s -> %s (dynamic %s)",
                    option_symbol,
                    underlying_symbol,
                    dynamic_symbol,
                )
        elif dynamic_symbol:
            underlying_symbol = dynamic_symbol
            logger.debug("Dual feed dynamic mapping: %s -> %s", option_symbol, underlying_symbol)
        else:
            return None

        return DualFeedMapping(
            option_symbol=option_symbol,
            underlying_symbol=underlying_symbol,
            underlying=underlying,
            exchange=exchange,
            config=config,
        )

    def build_futures_routing(self, option_symbols: list[str]) -> tuple[dict[str, list[str]], list[str]]:
        future_to_options: dict[str, list[str]] = defaultdict(list)
        for option_symbol in option_symbols:
            mapping = self.get_mapping(option_symbol)
            if mapping is not None:
                future_to_options[mapping.underlying_symbol].append(option_symbol)
        ordered = dict(sorted(future_to_options.items(), key=lambda item: item[0]))
        return ordered, sorted(future_to_options.keys())

    def get_underlying_symbol(self, option_symbol: str) -> str | None:
        mapping = self.get_mapping(option_symbol)
        return mapping.underlying_symbol if mapping else None

    def get_config(self, underlying: str, exchange: str) -> InstrumentConfig | None:
        return self._instruments.get(exchange, {}).get(underlying)

    def get_all_underlyings(self, exchange: str) -> list[str]:
        return list(self._instruments.get(exchange, {}).keys())

