"""Session context helpers for market phase and opening relation."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Literal

from app.shared.timezones import IST


@dataclass(frozen=True)
class SessionInfo:
    session: str
    phase: int
    is_london: bool
    is_new_york: bool
    opening_relation: str
    favor_strategy: str
    allow_entry: bool
    allow_trend: bool
    allow_reversion: bool
    force_exit: bool
    market: str


def _to_ist(ts: str | datetime | None) -> datetime:
    if ts is None:
        dt = datetime.now(IST)
    elif isinstance(ts, datetime):
        dt = ts
    else:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(IST)


def _get_nse_phase(h: int, m: int) -> tuple[str, int, bool, bool, bool, bool, str]:
    t = h * 60 + m
    if t < 555:
        return ("PRE_MARKET", 0, False, False, False, False, "NEUTRAL")
    if t < 570:
        return ("NSE_OPENING", 1, False, False, False, False, "NEUTRAL")
    if t < 690:
        return ("NSE_PRIMARY", 2, True, True, True, False, "TREND_CONTINUATION")
    if t < 840:
        return ("NSE_MIDDAY", 3, True, False, True, False, "MEAN_REVERSION")
    if t < 915:
        return ("NSE_POWER_HOUR", 4, True, True, True, False, "TREND_CONTINUATION")
    if t < 930:
        return ("NSE_CLOSE", 5, False, False, False, True, "NEUTRAL")
    return ("POST_MARKET", 0, False, False, False, False, "NEUTRAL")


def _get_mcx_phase(h: int, m: int) -> tuple[str, int, bool, bool, bool, bool, str]:
    t = h * 60 + m
    if t < 540:
        return ("MCX_PRE_MARKET", 0, False, False, False, False, "NEUTRAL")
    if t < 555:
        return ("MCX_PRE_OPEN", 0, False, False, False, False, "NEUTRAL")
    if t < 840:
        return ("MCX_MORNING", 1, True, True, True, False, "TREND_CONTINUATION")
    if t < 1080:
        return ("MCX_AFTERNOON", 2, True, True, True, False, "TREND_CONTINUATION")
    if t < 1380:
        return ("MCX_EVENING", 3, True, True, True, False, "NEUTRAL")
    if t < 1410:
        return ("MCX_CLOSE", 4, False, False, False, True, "NEUTRAL")
    return ("MCX_POST_MARKET", 0, False, False, False, False, "NEUTRAL")


def _get_global_session(utc_hour: int) -> tuple[str, str]:
    if 8 <= utc_hour < 16 and 13 <= utc_hour < 21:
        return ("OVERLAP", "TREND_CONTINUATION")
    if 13 <= utc_hour < 21:
        return ("NEW_YORK", "TREND_CONTINUATION")
    if 8 <= utc_hour < 16:
        return ("LONDON", "MEAN_REVERSION")
    return ("ASIA", "NEUTRAL")


def opening_relation(open_price: float, prior_vah: float, prior_val: float) -> str:
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
    market: str = "NSE",
) -> SessionInfo:
    market = (market or "NSE").upper()
    if prior_vah > 0 and prior_val > 0 and open_price > 0:
        rel = opening_relation(open_price, prior_vah, prior_val)
    else:
        rel = "IN_BALANCE"

    if market == "NSE":
        dt = _to_ist(timestamp)
        session, phase, allow_entry, allow_trend, allow_rev, force_exit, favor = _get_nse_phase(dt.hour, dt.minute)
        return SessionInfo(
            session=session,
            phase=phase,
            is_london=False,
            is_new_york=False,
            opening_relation=rel,
            favor_strategy="TREND_CONTINUATION" if rel != "IN_BALANCE" else favor,
            allow_entry=allow_entry,
            allow_trend=allow_trend,
            allow_reversion=allow_rev,
            force_exit=force_exit,
            market="NSE",
        )

    if market == "MCX":
        dt = _to_ist(timestamp)
        session, phase, allow_entry, allow_trend, allow_rev, force_exit, favor = _get_mcx_phase(dt.hour, dt.minute)
        return SessionInfo(
            session=session,
            phase=phase,
            is_london=False,
            is_new_york=False,
            opening_relation=rel,
            favor_strategy=favor,
            allow_entry=allow_entry,
            allow_trend=allow_trend,
            allow_reversion=allow_rev,
            force_exit=force_exit,
            market="MCX",
        )

    # GLOBAL / crypto fallback
    dt = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00")) if timestamp else datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    session_name, favor = _get_global_session(dt.astimezone(timezone.utc).hour)
    return SessionInfo(
        session=session_name,
        phase=0,
        is_london=session_name in {"LONDON", "OVERLAP"},
        is_new_york=session_name in {"NEW_YORK", "OVERLAP"},
        opening_relation=rel,
        favor_strategy=favor,
        allow_entry=session_name != "ASIA",
        allow_trend=True,
        allow_reversion=True,
        force_exit=False,
        market="GLOBAL",
    )


def classify_gap(open_price: float, prior_close: float, prior_range: float) -> str:
    if prior_close <= 0 or prior_range <= 0:
        return ""
    gap_pct = abs(open_price - prior_close) / prior_range
    if gap_pct < 0.005:
        return ""
    if gap_pct < 0.15:
        return "SMALL"
    if gap_pct < 0.50:
        return "MEDIUM"
    return "LARGE"


def is_expiry_day(trade_date: date) -> bool:
    week_day = trade_date.weekday()
    return week_day == 4


SessionTag = Literal["PRE_MARKET", "POST_MARKET", "NSE_OPENING", "NSE_PRIMARY", "NSE_MIDDAY", "NSE_POWER_HOUR", "NSE_CLOSE", "MCX_PRE_MARKET", "MCX_MORNING", "MCX_AFTERNOON", "MCX_EVENING", "MCX_CLOSE"]
