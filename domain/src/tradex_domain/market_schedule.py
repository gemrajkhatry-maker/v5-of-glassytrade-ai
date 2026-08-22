"""Canonical NSE market-schedule and paper-trading default constants.

These are behavioral values that were previously hardcoded independently in
the broker layer (``dhan/_marketdata``), the runtime calendar, the datalake
(phantom post-market bar cutoff), and the paper/backtest engines. Living in
:mod:`tradex_domain` makes them importable from both the broker layer
(domain <- brokers) and the trading layer, so every consumer reads one source
of truth instead of a copy-pasted literal.

NSE cash/index sessions run 09:15–15:30 IST.  Dhan (and some other feeds)
emit phantom post-market bars up to 20:00 IST which must be stripped on
ingest — that cutoff is a Dhan feed behavior, but it is encoded here as the
single shared constant so the datalake and any cleaning routine agree.
"""

from __future__ import annotations

from datetime import time
from decimal import Decimal

#: NSE cash/index session open (IST).
MARKET_OPEN = time(9, 15)
#: NSE cash/index session close (IST).
MARKET_CLOSE = time(15, 30)

#: String forms used by broker feeds / filtering (HH:MM / HH:MM:SS).
SESSION_OPEN_STR = "09:15:00"
SESSION_CLOSE_STR = "15:30:00"

#: Dhan phantom post-market cutoff — bars at/after this time are not real.
#: Dhan emits bars up to 20:00 IST after the 15:30 close; everything past the
#: session close should be treated as phantom and stripped on ingest.
PHANTOM_BAR_CUTOFF_STR = "20:00:00"

#: Default starting cash for the paper broker and backtest engines (₹).
DEFAULT_PAPER_STARTING_CASH = Decimal("100000")

#: Baseline currency for domestic paper/backtest accounting (INR).
DEFAULT_CURRENCY = "INR"

#: Default NSE cash/index/futures tick size (₹), used when the instrument
#: master does not carry a real tick.
NSE_DEFAULT_TICK_SIZE = 0.05


__all__ = [
    "DEFAULT_CURRENCY",
    "DEFAULT_PAPER_STARTING_CASH",
    "MARKET_CLOSE",
    "MARKET_OPEN",
    "NSE_DEFAULT_TICK_SIZE",
    "PHANTOM_BAR_CUTOFF_STR",
    "SESSION_CLOSE_STR",
    "SESSION_OPEN_STR",
]
