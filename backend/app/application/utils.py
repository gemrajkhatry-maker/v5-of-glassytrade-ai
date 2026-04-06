"""Shared application-layer utilities."""

import re
from datetime import datetime, timezone, timedelta, date, time as dtime
from zoneinfo import ZoneInfo
from app.shared.timezones import IST

IST_ZONE = ZoneInfo("Asia/Kolkata")


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

    # Build expiry date (NSE weekly: last Thursday of the month — approximate with day+month)
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

# NSE equity + options: Mon-Fri 09:15-15:15 IST
_NSE_OPENIST  = dtime(9, 15)
_NSE_CLOSEIST = dtime(15, 15)

# MCX commodity derivatives: Mon-Fri 09:00-23:15 IST
_MCX_OPENIST  = dtime(9, 0)
_MCX_CLOSEIST = dtime(23, 15)

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
      NSE / NSE_EQ / BSE / NFO : 09:15 – 15:15 IST
      MCX                       : 09:00 – 23:15 IST

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


def time_to_epoch(time_str: str) -> int:
    """Convert an IST ISO timestamp string to Unix epoch seconds.

    lightweight-charts expects UTCTimestamp (integer seconds since epoch).
    """
    try:
        dt = datetime.fromisoformat(time_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return int(dt.timestamp())
    except Exception:
        return 0
