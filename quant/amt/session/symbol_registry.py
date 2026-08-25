"""Symbol Registry — single source of truth for exchange↔symbol mapping.

Eliminates the duplicated _MCX_UNDERLYINGS frozenset that appeared in:
  - app/infrastructure/adapters/dhan_adapter.py
  - app/domain/fabio_ai/services/option_scanner.py

All exchange-detection logic now lives here.

Note: ``parse_symbol_metadata`` and ``is_market_open`` were migrated from the
backend application layer into this module (2026-08-08) so the canonical
symbol/exchange/option home also owns option-metadata and market-hours logic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime, time as dtime
from typing import FrozenSet
from zoneinfo import ZoneInfo

from quant.contracts.instrument_registry import (
    DEFAULT_REGISTRY,
    UnknownInstrumentError,
    root_token,
)

IST_ZONE = ZoneInfo("Asia/Kolkata")


@dataclass(frozen=True)
class SymbolRegistry:
    """Registry mapping symbols to exchanges.

    Thread-safe, immutable, injectable via constructor.
    """

    # Defaults sourced from the unified InstrumentRegistry (Phase 3) rather
    # than a duplicated exchange table — exchange_for() below tries the
    # registry first anyway; these frozensets only back the legacy
    # _extract_underlying prefix-match fallback used by from_exchange_configs
    # callers that inject their own sets.
    mcx_underlyings: FrozenSet[str] = field(
        default_factory=lambda: DEFAULT_REGISTRY.mcx_roots()
    )
    nse_underlyings: FrozenSet[str] = field(
        default_factory=lambda: DEFAULT_REGISTRY.nse_session_roots()
    )

    def exchange_for(self, symbol: str) -> str:
        """Determine exchange from a trading symbol.

        Args:
            symbol: e.g. "CRUDEOIL 17 MAR 6100 CALL" or "NIFTY 27 FEB 25500 CE"

        Returns:
            "MCX" or "NSE"
        """
        spec = DEFAULT_REGISTRY.try_resolve(symbol)
        if spec is not None:
            if spec.exchange == "MCX":
                return "MCX"
            return "NSE"
        underlying = self._extract_underlying(symbol)
        if underlying in self.mcx_underlyings:
            return "MCX"
        if underlying in self.nse_underlyings:
            return "NSE"
        raise UnknownInstrumentError(
            f"Unknown instrument root from {symbol!r} — refusing silent MCX default"
        )

    def is_mcx(self, symbol: str) -> bool:
        return self.exchange_for(symbol) == "MCX"

    def is_nse(self, symbol: str) -> bool:
        return self.exchange_for(symbol) == "NSE"

    def is_option(self, symbol: str) -> bool:
        from quant.contracts.instrument_registry import is_option_contract
        return is_option_contract(symbol)

    def all_underlyings(self) -> FrozenSet[str]:
        return self.mcx_underlyings | self.nse_underlyings

    def _extract_underlying(self, symbol: str) -> str:
        if not symbol:
            return ""
        clean = (
            str(symbol)
            .upper()
            .replace("NSE:", "")
            .replace("NFO:", "")
            .replace("MCX:", "")
            .replace("BSE:", "")
            .strip()
        )
        for u in sorted(self.all_underlyings(), key=len, reverse=True):
            if clean.startswith(u):
                return u
        return re.split(r"[-_\s]+", clean)[0]

    @classmethod
    def from_exchange_configs(
        cls, configs: dict[str, ExchangeConfig]
    ) -> SymbolRegistry:
        """Build from ExchangeConfig instances.

        Args:
            configs: {"NSE": ExchangeConfig, "MCX": ExchangeConfig}
        """
        nse = configs.get("NSE")
        mcx = configs.get("MCX")
        return cls(
            mcx_underlyings=mcx.underlyings if mcx else frozenset(),
            nse_underlyings=nse.underlyings if nse else frozenset(),
        )


# ---------------------------------------------------------------------------
# Symbol metadata parsing
# ---------------------------------------------------------------------------

_MONTH_MAP = {
    "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
    "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
}

_SYMBOL_RE = re.compile(
    r'([A-Z]+)\s+(\d{1,2})\s+([A-Z]{3})\s+(\d+)\s+(CALL|PUT)',
    re.IGNORECASE,
)


def parse_symbol_metadata(symbol: str, spot: float = 0.0) -> dict:
    """Parse NSE option symbol into metadata dict.

    Example: 'NIFTY 27 MAR 23500 CALL'
    Returns: {option_type_flag, strike, expiry_date, dte, dte_normalized, moneyness_pct}

    option_type_flag: 1.0=CALL, -1.0=PUT, 0.0=unknown
    dte_normalized: dte / 30.0 (0=expired, 1=30 days)
    moneyness_pct: (spot-strike)/spot for CALL, (strike-spot)/spot for PUT
    """
    m = _SYMBOL_RE.search(symbol.upper())
    if not m:
        return {
            "option_type_flag": 0.0, "strike": 0.0, "dte": 0.0,
            "dte_normalized": 0.0, "moneyness_pct": 0.0,
        }

    day_str, month_str, strike_str, opt_type = (
        m.group(2), m.group(3), m.group(4), m.group(5)
    )
    strike = float(strike_str)
    opt_flag = 1.0 if opt_type.upper() == "CALL" else -1.0

    # Build expiry date from the date embedded in the symbol (DAY MON). NSE
    # weeklies expire Tuesday; monthlies on the last Tuesday — no weekday
    # table needed since the symbol carries the authoritative date.
    try:
        now_ist = datetime.now(IST_ZONE)
        month_num = _MONTH_MAP.get(month_str, now_ist.month)
        year = now_ist.year if month_num >= now_ist.month else now_ist.year + 1
        expiry = date(year, month_num, int(day_str))
        dte = max(0, (expiry - now_ist.date()).days)
    except (ValueError, KeyError):
        dte = 0

    dte_norm = min(dte / 30.0, 1.0)
    moneyness = 0.0
    if spot > 0 and strike > 0:
        if opt_flag == 1.0:   # CALL: positive when ITM (spot > strike)
            moneyness = (spot - strike) / spot
        else:                  # PUT: positive when ITM (strike > spot)
            moneyness = (strike - spot) / spot

    return {
        "option_type_flag": opt_flag,
        "strike": strike,
        "dte": float(dte),
        "dte_normalized": dte_norm,
        "moneyness_pct": moneyness,
    }


# ---------------------------------------------------------------------------
# Market hours gate
# ---------------------------------------------------------------------------

# NSE equity + options: Mon-Fri 09:15-15:30 IST
from quant.contracts.timezones import NSE_SESSION_OPEN, NSE_SESSION_CLOSE, MCX_SESSION_OPEN, MCX_SESSION_CLOSE

_NSE_OPENIST  = NSE_SESSION_OPEN
_NSE_CLOSEIST = NSE_SESSION_CLOSE

# MCX commodity derivatives: Mon-Fri 09:00-23:30 IST (23:55 in US DST)
_MCX_OPENIST  = MCX_SESSION_OPEN
_MCX_CLOSEIST = MCX_SESSION_CLOSE

# Exchanges whose hours span midnight (none currently, but structure supports it)
_EXCHANGE_HOURS: dict[str, tuple[dtime, dtime]] = {
    "NSE":    (_NSE_OPENIST, _NSE_CLOSEIST),
    "NSE_EQ": (_NSE_OPENIST, _NSE_CLOSEIST),
    "BSE":    (_NSE_OPENIST, _NSE_CLOSEIST),
    "MCX":    (_MCX_OPENIST, _MCX_CLOSEIST),
    "NFO":    (_NSE_OPENIST, _NSE_CLOSEIST),  # NSE F&O
}


def is_market_open(ts: str | None = None, exchange: str | None = None) -> bool:
    """True during live trading hours for the given exchange (IST, Mon-Fri).

    Exchange-specific hours:
      NSE / NSE_EQ / BSE / NFO : 09:15 – 15:30 IST
      MCX                       : 09:00 – 23:30 IST

    Falls back to NSE hours when exchange is unknown.
    On timestamp parse error returns False (fail-closed — safer than allowing
    trades at arbitrary times).
    """
    try:
        if ts:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(IST_ZONE)
        else:
            dt = datetime.now(IST_ZONE)

        if dt.weekday() >= 5:   # Saturday=5, Sunday=6
            return False

        t = dt.time()
        exch_upper = (exchange or "NSE").upper()
        open_t, close_t = _EXCHANGE_HOURS.get(exch_upper, (_NSE_OPENIST, _NSE_CLOSEIST))
        return open_t <= t <= close_t
    except Exception:
        return False   # fail-closed: don't allow trades on parse error
