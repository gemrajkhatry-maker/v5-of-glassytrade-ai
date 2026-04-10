"""Session Context — NSE 5-phase + MCX session tracking."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from functools import lru_cache
from dataclasses import dataclass
from appv2.domain.enums.session_phase import SessionPhase

# IST offset
IST = timezone(timedelta(hours=5, minutes=30))


@dataclass(frozen=True)
class SessionInfo:
    phase: SessionPhase
    allows_entry: bool
    allows_trend: bool
    allows_reversion: bool
    forces_exit: bool
    opening_relation: str  # "IN_BALANCE" | "OUT_ABOVE" | "OUT_BELOW"


def get_session_info(
    timestamp: str | datetime | None = None,
    open_price: float = 0.0,
    prior_vah: float = 0.0,
    prior_val: float = 0.0,
    exchange: str = "NSE",
) -> SessionInfo:
    """Full session context."""
    ist_dt = _to_ist(timestamp)
    exchange = exchange.upper()

    if exchange == "NSE":
        phase = _get_nse_phase(ist_dt.hour, ist_dt.minute)
    elif exchange == "MCX":
        phase = _get_mcx_phase(ist_dt.hour, ist_dt.minute)
    else:
        phase = SessionPhase.PRE_MARKET

    # Opening relation
    if prior_vah > 0 and prior_val > 0 and open_price > 0:
        if prior_val <= open_price <= prior_vah:
            opening = "IN_BALANCE"
        elif open_price > prior_vah:
            opening = "OUT_ABOVE"
        else:
            opening = "OUT_BELOW"
    else:
        opening = "IN_BALANCE"

    return SessionInfo(
        phase=phase,
        allows_entry=phase.allows_entry,
        allows_trend=phase.allows_trend,
        allows_reversion=phase.allows_reversion,
        forces_exit=phase.forces_exit,
        opening_relation=opening,
    )


@lru_cache(maxsize=1440)
def _get_nse_phase(h: int, m: int) -> SessionPhase:
    t = h * 60 + m
    if t < 555:  # before 09:15
        return SessionPhase.PRE_MARKET
    if t < 570:  # 09:15–09:30
        return SessionPhase.OPENING
    if t < 690:  # 09:30–11:30
        return SessionPhase.PRIMARY
    if t < 840:  # 11:30–14:00
        return SessionPhase.MIDDAY
    if t < 915:  # 14:00–15:15
        return SessionPhase.POWER_HOUR
    if t < 930:  # 15:15–15:30
        return SessionPhase.CLOSE
    return SessionPhase.POST_MARKET


@lru_cache(maxsize=1440)
def _get_mcx_phase(h: int, m: int) -> SessionPhase:
    t = h * 60 + m
    if t < 540:  # before 09:00
        return SessionPhase.PRE_MARKET
    if t < 555:  # 09:00–09:15
        return SessionPhase.PRE_OPEN
    if t < 840:  # 09:15–14:00
        return SessionPhase.MORNING
    if t < 1080:  # 14:00–18:00
        return SessionPhase.AFTERNOON
    if t < 1380:  # 18:00–23:00
        return SessionPhase.EVENING
    if t < 1410:  # 23:00–23:30
        return SessionPhase.CLOSE
    return SessionPhase.POST_MARKET


def _to_ist(ts: str | datetime | None) -> datetime:
    if ts is None:
        return datetime.now(IST)
    if isinstance(ts, str):
        try:
            stripped = ts.strip()
            if stripped.replace(".", "", 1).lstrip("-").isdigit() and "T" not in stripped:
                dt = datetime.fromtimestamp(float(stripped), tz=timezone.utc)
            else:
                dt = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            dt = datetime.now(IST)
    else:
        dt = ts
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST)
