"""Session gating — exchange-aware session phase logic.

Pure functions that determine whether new entries are allowed and whether
existing positions must be force-exited based on the session clock.

Extracted from QuantEngine to improve locality: session rules are a single
concern with no engine state dependency.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
import re

from quant.amt.session.context import get_session_info
from quant.contracts.timezones import IST

logger = logging.getLogger(__name__)

# IST offset: UTC+5:30
_IST = IST  # canonical — see contracts/timezones


def bar_epoch_ms(bar_time: str) -> int:
    """Parse bar.time into epoch milliseconds.

    History bars carry IST ISO strings (``2026-08-07T22:46:12+05:30``);
    live gateway bars carry epoch seconds as strings. Returns 0 when the
    value cannot be parsed.
    """
    if not bar_time:
        return 0
    try:
        dt = datetime.fromisoformat(bar_time.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=_IST)
        return int(dt.timestamp() * 1000)
    except (TypeError, ValueError):
        pass
    try:
        return int(float(bar_time) * 1000)
    except (TypeError, ValueError):
        return 0


def ist_dt(bar_time) -> datetime | None:
    """Parse bar_time to an IST datetime, or None when unparseable.

    Accepts epoch-seconds strings (live gateway) and ISO timestamps
    (history bars); synthetic/replay times ("t300") return None so the
    deterministic traces never depend on wall-clock gating.
    """
    ts_ms = bar_epoch_ms(bar_time)
    if not ts_ms:
        return None
    return datetime.fromtimestamp(ts_ms / 1000.0, tz=_IST)


def parse_contract_expiry(symbol: str) -> date | None:
    """Parse the option contract's expiry date from its symbol.

    Handles spaced ``CRUDEOIL 17 AUG 7450 CALL``, compact ``NIFTY23FEB18000CE``,
    and hyphenated ``NIFTY-27FEB-25500-CE``. Returns None when no day+month
    is embedded (bare underlyings, month-only futures).
    """
    months = {
        "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
        "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
    }
    text = str(symbol or "").upper()
    tokens = text.split()
    day = month = None
    if len(tokens) >= 3 and tokens[1].isdigit():
        month = months.get(tokens[2])
        if month is not None:
            day = int(tokens[1])
    if day is None:
        compact = re.search(
            r"(\d{1,2})(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)(\d{2,4})?",
            text,
        )
        if compact:
            day = int(compact.group(1))
            month = months[compact.group(2)]
    if day is None or month is None:
        return None
    today = datetime.now(tz=_IST).date()
    try:
        parsed = date(today.year, month, day)
    except ValueError:
        return None
    if parsed < today:
        parsed = date(today.year + 1, month, day)
    return parsed


def session_allow_entry(
    bar_time, market: str = "NSE", contract_expiry: date | None = None
) -> bool:
    """Fabio session gate: new entries only in phases 2-4.

    Exchange-aware (NSE/MCX/GLOBAL): blocks the opening-noise window
    (Phase 1), the close-protection window (Phase 5) and pre/post market.
    MCX trades until 23:30, so 16:45 IST is an open MCX afternoon but a
    closed NSE post-market.

    ``contract_expiry``: on the contract's own expiry day, new entries
    close early — MCX at 21:00 IST (option buying stops at 22:00, and a
    fresh option in the last hour risks the devolvement window) and NSE at
    14:00 IST (Tuesday NIFTY expiry — the final hour's gamma/theta
    distortion corrupts orderflow signals). The NSE square-off at 15:15 is
    already enforced by the phase table (Phase 5 close-protection).
    Unparseable (synthetic/replay) timestamps default to open so the
    deterministic unit/replay traces never depend on wall-clock time;
    live bars always carry parseable epoch-seconds or ISO timestamps.
    """
    if not bar_time:
        return True
    text = str(bar_time).strip()
    is_epoch = (
        text.replace(".", "", 1).lstrip("-").isdigit()
        and len(text) >= 9
        and "T" not in text
    )
    is_iso = "T" in text or "+" in text or ":" in text
    if not (is_epoch or is_iso):
        return True
    try:
        allowed = bool(get_session_info(bar_time, market=market).allow_entry)
    except Exception:
        logger.error(
            "session phase lookup failed for %r — refusing entry",
            bar_time,
            exc_info=True,
        )
        return False
    if not allowed:
        return False
    if contract_expiry is not None:
        ist = ist_dt(bar_time)
        if ist is not None and ist.date() == contract_expiry:
            if str(market).upper() == "MCX" and ist.hour >= 21:
                # MCX expiry day: option buying stops 22:00 IST.
                return False
            if str(market).upper() == "NSE" and ist.hour >= 14:
                # NSE expiry day (Tuesday for NIFTY): the final hour's
                # gamma/theta distortion corrupts orderflow signals — no
                # fresh entries after 14:00 IST.
                return False
    return True


def session_force_exit(
    bar_time, market: str = "NSE", contract_expiry: date | None = None
) -> bool:
    """True only when the session table says flatten (Phase 5, post-market).

    Opening-noise (allow_entry=False, force_exit=False) must not flatten a
    position that was already open. PRE/POST_MARKET set force_exit=True.

    ``contract_expiry`` (MCX only): on the contract's own expiry day, an
    open position is force-squared from 21:30 IST — an ITM option left
    open at expiry devolves into a futures position with margin.
    """
    if not bar_time:
        return False
    text = str(bar_time).strip()
    is_epoch = (
        text.replace(".", "", 1).lstrip("-").isdigit()
        and len(text) >= 9
        and "T" not in text
    )
    is_iso = "T" in text or "+" in text or ":" in text
    if not (is_epoch or is_iso):
        return False
    try:
        info = get_session_info(bar_time, market=market)
    except Exception:
        logger.error(
            "session force-exit lookup failed for %r — forcing exit",
            bar_time,
            exc_info=True,
        )
        return True
    force = bool(info.force_exit)
    if not force and str(market).upper() == "MCX" and contract_expiry is not None:
        ist = ist_dt(bar_time)
        if (
            ist is not None
            and ist.date() == contract_expiry
            and (ist.hour, ist.minute) >= (21, 30)
        ):
            force = True
    return force
