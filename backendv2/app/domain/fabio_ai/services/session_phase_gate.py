"""Session phase determination for LLM entry gating.

Extracted from LLMEntryHandler. Provides time-based session classification
for NSE and MCX markets.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from app.shared.timezones import IST

_MCX_COMMODITIES = (
    "GOLD",
    "GOLDM",
    "SILVER",
    "SILVERM",
    "CRUDEOIL",
    "CRUDEOILM",
    "NATURALGAS",
    "COPPER",
    "ZINC",
    "ALUMINIUM",
    "LEAD",
    "NICKEL",
)


def _is_mcx_symbol(symbol: str) -> bool:
    if not symbol:
        return False
    first_token = symbol.split(" ")[0].upper()
    return first_token in _MCX_COMMODITIES


def _to_ist_datetime(timestamp: float | int | str | datetime | None) -> datetime:
    if isinstance(timestamp, datetime):
        dt = timestamp
    elif timestamp is None:
        dt = datetime.now(tz=IST)
    else:
        if isinstance(timestamp, str):
            ts = float(timestamp)
        else:
            ts = float(timestamp)
        if ts > 1_000_000_000_000:
            dt = datetime.fromtimestamp(ts / 1_000_000_000, tz=IST)
        else:
            dt = datetime.fromtimestamp(ts, tz=IST)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    return dt.astimezone(IST)


@dataclass(frozen=True)
class SessionPhaseInfo:
    """Session phase metadata."""

    session_name: str
    phase_int: int
    allow_entry: bool
    allow_trend: bool
    session_market: str

    @property
    def session(self) -> str:
        return self.session_name


def get_session_phase(
    timestamp: float | int | str | datetime | None,
    market: str = "MCX",
    symbol: str = "",
) -> SessionPhaseInfo:
    """Determine session phase based on timestamp and market/symbol."""
    dt = _to_ist_datetime(timestamp)
    m = market.upper()
    if _is_mcx_symbol(symbol):
        m = "MCX"
    elif m not in {"NSE", "MCX"}:
        m = "NSE"

    minutes = dt.hour * 60 + dt.minute
    if m == "NSE":
        if minutes < 9 * 60 + 15:
            return SessionPhaseInfo("PRE_MARKET", 0, False, False, "NSE")
        if minutes < 9 * 60 + 30:
            return SessionPhaseInfo("NSE_OPENING", 1, False, False, "NSE")
        if minutes < 11 * 60 + 30:
            return SessionPhaseInfo("NSE_PRIMARY", 2, True, True, "NSE")
        if minutes < 14 * 60:
            return SessionPhaseInfo("NSE_MIDDAY", 3, True, False, "NSE")
        if minutes < 15 * 60 + 15:
            return SessionPhaseInfo("NSE_POWER_HOUR", 4, True, True, "NSE")
        if minutes < 15 * 60 + 30:
            return SessionPhaseInfo("NSE_CLOSE", 5, False, False, "NSE")
        return SessionPhaseInfo("POST_MARKET", 0, False, False, "NSE")

    # MCX
    if minutes < 9 * 60:
        return SessionPhaseInfo("MCX_PRE_MARKET", 0, False, False, "MCX")
    if minutes < 9 * 60 + 15:
        return SessionPhaseInfo("MCX_PRE_OPEN", 0, False, False, "MCX")
    if minutes < 14 * 60:
        return SessionPhaseInfo("MCX_MORNING", 1, True, True, "MCX")
    if minutes < 18 * 60:
        return SessionPhaseInfo("MCX_AFTERNOON", 2, True, True, "MCX")
    if minutes < 23 * 60:
        return SessionPhaseInfo("MCX_EVENING", 3, True, True, "MCX")
    if minutes < 23 * 60 + 30:
        return SessionPhaseInfo("MCX_CLOSE", 4, False, False, "MCX")
    return SessionPhaseInfo("MCX_POST_MARKET", 0, False, False, "MCX")
