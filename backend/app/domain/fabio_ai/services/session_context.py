"""Session Context — time-of-day session awareness & opening relation.

Provides session classification (London / New York / Asia / Overlap)
and determines how the current day's open relates to yesterday's Value Area.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone, timedelta


# ---------------------------------------------------------------------------
# Value Objects
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SessionInfo:
    """Current trading session context."""
    session: str            # "ASIA" | "LONDON" | "NEW_YORK" | "OVERLAP"
    is_london: bool
    is_new_york: bool
    opening_relation: str   # "IN_BALANCE" | "OUT_ABOVE" | "OUT_BELOW"
    favor_strategy: str     # "MEAN_REVERSION" | "TREND_CONTINUATION" | "NEUTRAL"


# ---------------------------------------------------------------------------
# Session definitions (UTC hours)
# ---------------------------------------------------------------------------

# Asia:   00:00 – 08:00 UTC
# London: 08:00 – 16:30 UTC
# NY:     13:30 – 21:00 UTC
# Overlap (London+NY): 13:30 – 16:30 UTC

_ASIA_START = 0
_ASIA_END = 8
_LONDON_START = 8
_LONDON_END = 16  # 16:30 approximated
_NY_START = 13    # 13:30 approximated
_NY_END = 21


def get_session(timestamp: str | datetime | None = None) -> str:
    """Classify the current time into a trading session.

    Returns one of: ``"ASIA"``, ``"LONDON"``, ``"NEW_YORK"``, ``"OVERLAP"``.
    """
    if timestamp is None:
        dt = datetime.now(timezone.utc)
    elif isinstance(timestamp, str):
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            dt = datetime.now(timezone.utc)
    else:
        dt = timestamp

    # Ensure UTC
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    utc_hour = dt.astimezone(timezone.utc).hour

    in_london = _LONDON_START <= utc_hour < _LONDON_END
    in_ny = _NY_START <= utc_hour < _NY_END
    in_asia = utc_hour < _ASIA_END or utc_hour >= _NY_END

    if in_london and in_ny:
        return "OVERLAP"
    if in_ny:
        return "NEW_YORK"
    if in_london:
        return "LONDON"
    return "ASIA"


def opening_relation(
    open_price: float,
    prior_vah: float,
    prior_val: float,
) -> str:
    """Determine where the market opened relative to yesterday's Value Area.

    Returns:
        ``"IN_BALANCE"``  — opened inside Value Area
        ``"OUT_ABOVE"``   — opened above VAH (gap up)
        ``"OUT_BELOW"``   — opened below VAL (gap down)
    """
    if prior_val <= open_price <= prior_vah:
        return "IN_BALANCE"
    if open_price > prior_vah:
        return "OUT_ABOVE"
    return "OUT_BELOW"


def get_session_info(
    timestamp: str | datetime | None = None,
    open_price: float = 0.0,
    prior_vah: float = 0.0,
    prior_val: float = 0.0,
) -> SessionInfo:
    """Full session context in one call."""
    session = get_session(timestamp)

    if prior_vah > 0 and prior_val > 0 and open_price > 0:
        op_rel = opening_relation(open_price, prior_vah, prior_val)
    else:
        op_rel = "IN_BALANCE"  # default when no prior VA available

    is_london = session in ("LONDON", "OVERLAP")
    is_ny = session in ("NEW_YORK", "OVERLAP")

    # Strategy bias per Valentini methodology
    if session == "LONDON":
        favor = "MEAN_REVERSION"
    elif session == "NEW_YORK":
        favor = "TREND_CONTINUATION"
    elif session == "OVERLAP":
        # Overlap is high-volatility — favor trend if out of balance
        favor = "TREND_CONTINUATION" if op_rel != "IN_BALANCE" else "MEAN_REVERSION"
    else:
        favor = "NEUTRAL"  # Asia session

    return SessionInfo(
        session=session,
        is_london=is_london,
        is_new_york=is_ny,
        opening_relation=op_rel,
        favor_strategy=favor,
    )
