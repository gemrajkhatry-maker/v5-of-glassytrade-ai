"""Session Context — time-of-day session awareness & opening relation.

Supports two market regimes:
  - NSE/MCX (Indian markets): 5-phase IST structure per Fabio methodology
  - Crypto/Global: London / New York / Asia / Overlap

The NSE phases directly map to Fabio's transcript:
  Phase 1 (09:15–09:30 IST): Opening Noise — DO NOT TRADE
  Phase 2 (09:30–11:30 IST): Primary Setup Window — ALL MODELS ACTIVE
  Phase 3 (11:30–14:00 IST): Midday Consolidation — REVERSION ONLY
  Phase 4 (14:00–15:15 IST): Power Hour — ALL MODELS ACTIVE
  Phase 5 (15:15–15:30 IST): Close Protection — EXIT ONLY, NO NEW ENTRIES

MCX sessions:
  Pre-open (09:00–09:15 IST): DO NOT TRADE
  Morning  (09:15–14:00 IST): ALL MODELS ACTIVE
  Afternoon (14:00–18:00 IST): ALL MODELS ACTIVE
  Evening  (18:00–23:00 IST): Reduced liquidity — be selective
  Close    (23:00–23:30 IST): EXIT ONLY
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone, timedelta
from functools import lru_cache
from typing import Literal


# ---------------------------------------------------------------------------
# Value Objects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionInfo:
    """Current trading session context."""

    session: str  # Phase name (see below)
    phase: int  # 0=no-trade, 1-5 for NSE, 1-4 for MCX
    is_london: bool
    is_new_york: bool
    opening_relation: str  # "IN_BALANCE" | "OUT_ABOVE" | "OUT_BELOW"
    favor_strategy: str  # "MEAN_REVERSION" | "TREND_CONTINUATION" | "NEUTRAL"
    allow_entry: bool  # Whether new entries are permitted in this phase
    allow_trend: bool  # Whether trend continuation model is active
    allow_reversion: bool  # Whether mean reversion model is active
    force_exit: bool  # Whether all positions should be closed (Phase 5)
    market: str  # "NSE" | "MCX" | "GLOBAL"


# ---------------------------------------------------------------------------
# IST timezone offset
# ---------------------------------------------------------------------------

_IST = timezone(timedelta(hours=5, minutes=30))


def _to_ist(timestamp: str | datetime | None) -> datetime:
    """Convert timestamp to IST datetime."""
    if timestamp is None:
        dt = datetime.now(_IST)
    elif isinstance(timestamp, str):
        try:
            # Handle epoch timestamps (e.g. "1771832400.0" from Dhan adapter)
            stripped = timestamp.strip()
            if (
                stripped.replace(".", "", 1).lstrip("-").isdigit()
                and "T" not in stripped
                and len(stripped) >= 9
            ):
                dt = datetime.fromtimestamp(float(stripped), tz=timezone.utc)
            else:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except (ValueError, TypeError, OSError):
            dt = datetime.now(_IST)
    else:
        dt = timestamp

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_IST)


# ---------------------------------------------------------------------------
# NSE Session Phases (IST)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=128)
def _get_nse_phase(
    ist_hour: int, ist_minute: int
) -> tuple[str, int, bool, bool, bool, bool, str]:
    """Returns (session_name, phase, allow_entry, allow_trend, allow_reversion, force_exit, favor).

    Cached for performance - only 1440 possible minute combinations per day.
    """
    t = ist_hour * 60 + ist_minute  # minutes since midnight IST

    # Before market open
    if t < 555:  # before 09:15
        return ("PRE_MARKET", 0, False, False, False, False, "NEUTRAL")

    # Phase 1: Opening Noise (09:15–09:30)
    if t < 570:  # before 09:30
        return ("NSE_OPENING", 1, False, False, False, False, "NEUTRAL")

    # Phase 2: Primary Setup Window (09:30–11:30)
    if t < 690:  # before 11:30
        return ("NSE_PRIMARY", 2, True, True, True, False, "TREND_CONTINUATION")

    # Phase 3: Midday Consolidation (11:30–14:00)
    if t < 840:  # before 14:00
        return ("NSE_MIDDAY", 3, True, False, True, False, "MEAN_REVERSION")

    # Phase 4: Power Hour (14:00–15:15)
    if t < 915:  # before 15:15
        return ("NSE_POWER_HOUR", 4, True, True, True, False, "TREND_CONTINUATION")

    # Phase 5: Close Protection (15:15–15:30)
    if t < 930:  # before 15:30
        return ("NSE_CLOSE", 5, False, False, False, True, "NEUTRAL")

    # After market close
    return ("POST_MARKET", 0, False, False, False, False, "NEUTRAL")


# ---------------------------------------------------------------------------
# MCX Session Phases (IST)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=128)
def _get_mcx_phase(
    ist_hour: int, ist_minute: int
) -> tuple[str, int, bool, bool, bool, bool, str]:
    """Returns (session_name, phase, allow_entry, allow_trend, allow_reversion, force_exit, favor).

    Cached for performance - only 1440 possible minute combinations per day.
    """
    t = ist_hour * 60 + ist_minute

    if t < 540:  # before 09:00
        return ("MCX_PRE_MARKET", 0, False, False, False, False, "NEUTRAL")

    if t < 555:  # 09:00–09:15 pre-open
        return ("MCX_PRE_OPEN", 0, False, False, False, False, "NEUTRAL")

    if t < 840:  # 09:15–14:00 morning
        return ("MCX_MORNING", 1, True, True, True, False, "TREND_CONTINUATION")

    if t < 1080:  # 14:00–18:00 afternoon
        return ("MCX_AFTERNOON", 2, True, True, True, False, "TREND_CONTINUATION")

    if t < 1380:  # 18:00–23:00 evening (reduced liquidity)
        return ("MCX_EVENING", 3, True, True, True, False, "NEUTRAL")

    if t < 1410:  # 23:00–23:30 close
        return ("MCX_CLOSE", 4, False, False, False, True, "NEUTRAL")

    return ("MCX_POST_MARKET", 0, False, False, False, False, "NEUTRAL")


# ---------------------------------------------------------------------------
# Global/Crypto Session (UTC) — preserved for backward compatibility
# ---------------------------------------------------------------------------

_ASIA_START = 0
_ASIA_END = 8
_LONDON_START = 8
_LONDON_END = 16
_NY_START = 13
_NY_END = 21


def get_session(timestamp: str) -> str:
    """Return global session name for a UTC timestamp string."""
    from datetime import datetime as _dt

    if isinstance(timestamp, str):
        ts = _dt.fromisoformat(timestamp)
    else:
        ts = timestamp
    utc_hour = ts.hour
    name, _ = _get_global_session(utc_hour)
    return name


def _get_global_session(utc_hour: int) -> tuple[str, str]:
    """Returns (session_name, favor_strategy)."""
    in_london = _LONDON_START <= utc_hour < _LONDON_END
    in_ny = _NY_START <= utc_hour < _NY_END

    if in_london and in_ny:
        return ("OVERLAP", "TREND_CONTINUATION")
    if in_ny:
        return ("NEW_YORK", "TREND_CONTINUATION")
    if in_london:
        return ("LONDON", "MEAN_REVERSION")
    return ("ASIA", "NEUTRAL")


# ---------------------------------------------------------------------------
# Opening relation (shared across all markets)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=256)
def opening_relation(
    open_price: float,
    prior_vah: float,
    prior_val: float,
) -> str:
    """Determine where the market opened relative to yesterday's Value Area.

    Cached for performance - typically called with same values within a session.
    """
    if prior_val <= open_price <= prior_vah:
        return "IN_BALANCE"
    if open_price > prior_vah:
        return "OUT_ABOVE"
    return "OUT_BELOW"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_session_info(
    timestamp: str | datetime | None = None,
    open_price: float = 0.0,
    prior_vah: float = 0.0,
    prior_val: float = 0.0,
    market: str = "NSE",
) -> SessionInfo:
    """Full session context in one call.

    Args:
        market: "NSE" | "MCX" | "GLOBAL" (default: "NSE")
    """
    market = market.upper()

    if prior_vah > 0 and prior_val > 0 and open_price > 0:
        op_rel = opening_relation(open_price, prior_vah, prior_val)
    else:
        op_rel = "IN_BALANCE"

    if market == "NSE":
        ist_dt = _to_ist(timestamp)
        session_name, phase, allow_entry, allow_trend, allow_rev, force_exit, favor = (
            _get_nse_phase(ist_dt.hour, ist_dt.minute)
        )

        # Override favor based on opening relation
        if op_rel != "IN_BALANCE" and allow_trend:
            favor = "TREND_CONTINUATION"

        return SessionInfo(
            session=session_name,
            phase=phase,
            is_london=False,
            is_new_york=False,
            opening_relation=op_rel,
            favor_strategy=favor,
            allow_entry=allow_entry,
            allow_trend=allow_trend,
            allow_reversion=allow_rev,
            force_exit=force_exit,
            market="NSE",
        )

    elif market == "MCX":
        ist_dt = _to_ist(timestamp)
        session_name, phase, allow_entry, allow_trend, allow_rev, force_exit, favor = (
            _get_mcx_phase(ist_dt.hour, ist_dt.minute)
        )

        return SessionInfo(
            session=session_name,
            phase=phase,
            is_london=False,
            is_new_york=False,
            opening_relation=op_rel,
            favor_strategy=favor,
            allow_entry=allow_entry,
            allow_trend=allow_trend,
            allow_reversion=allow_rev,
            force_exit=force_exit,
            market="MCX",
        )

    else:  # GLOBAL / crypto
        if timestamp is None:
            dt = datetime.now(timezone.utc)
        elif isinstance(timestamp, str):
            try:
                dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                dt = datetime.now(timezone.utc)
        else:
            dt = timestamp
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)

        utc_hour = dt.astimezone(timezone.utc).hour
        session_name, favor = _get_global_session(utc_hour)

        is_london = session_name in ("LONDON", "OVERLAP")
        is_ny = session_name in ("NEW_YORK", "OVERLAP")

        if op_rel != "IN_BALANCE" and session_name in ("NEW_YORK", "OVERLAP"):
            favor = "TREND_CONTINUATION"

        return SessionInfo(
            session=session_name,
            phase=0,  # no phase concept for global
            is_london=is_london,
            is_new_york=is_ny,
            opening_relation=op_rel,
            favor_strategy=favor,
            allow_entry=session_name != "ASIA",  # Asia = reduced
            allow_trend=True,
            allow_reversion=True,
            force_exit=False,
            market="GLOBAL",
        )


# ---------------------------------------------------------------------------
# Gap Classification & Opening Inventory Bias
# ---------------------------------------------------------------------------


def classify_gap(open_price: float, prior_close: float, prior_range: float) -> str:
    """Classify opening gap size relative to prior session range.

    Returns "" (no gap), "SMALL", "MEDIUM", or "LARGE".
    """
    if prior_close <= 0 or prior_range <= 0:
        return ""
    gap_pct = abs(open_price - prior_close) / prior_range
    if gap_pct < 0.005:
        return ""
    elif gap_pct < 0.15:
        return "SMALL"
    elif gap_pct < 0.50:
        return "MEDIUM"
    else:
        return "LARGE"


# ---------------------------------------------------------------------------
# Session-Aware Time Stop Helpers
# ---------------------------------------------------------------------------


def is_expiry_day(trade_date: date) -> bool:
    """Check if the given date is an options expiry day.

    Weekly expiry: every Thursday.
    Monthly expiry: last Thursday of the month.
    Both are Thursdays, so any Thursday is an expiry day.
    """
    return trade_date.weekday() == 3  # Thursday = 3


def seconds_to_close(current_time: datetime, exchange: str = "NSE") -> float:
    """Return seconds remaining until market close.

    NSE close: 15:15 IST
    MCX close: 23:15 IST
    Returns 0.0 if market is already closed or exchange is unknown.
    """
    ist_dt = _to_ist(current_time)

    if exchange.upper() == "NSE":
        close_hour, close_minute = 15, 15
    elif exchange.upper() == "MCX":
        close_hour, close_minute = 23, 15
    else:
        return 0.0

    close_time = ist_dt.replace(
        hour=close_hour, minute=close_minute, second=0, microsecond=0
    )
    diff = (close_time - ist_dt).total_seconds()
    return max(0.0, diff)


def opening_inventory_bias(
    open_price: float, prior_vah: float, prior_val: float
) -> str:
    """Determine inventory bias from opening price vs prior session value area.

    Returns "" (invalid inputs), "LONG_BIAS", "SHORT_BIAS", or "NEUTRAL".
    """
    if prior_vah <= 0 or prior_val <= 0:
        return ""
    if open_price > prior_vah:
        return "LONG_BIAS"
    elif open_price < prior_val:
        return "SHORT_BIAS"
    else:
        return "NEUTRAL"
