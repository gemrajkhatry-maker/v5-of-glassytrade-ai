"""Signal type enum."""

from __future__ import annotations

from enum import Enum


class SignalType(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class SetupType(str, Enum):
    """AMT setup classification."""
    VA_BOUNCE = "VA_BOUNCE"  # Bounce off VAH/VAL
    LVN_RETEST = "LVN_RETEST"  # Retest of LVN zone
    POC_SHIFT = "POC_SHIFT"  # POC migration signal
    IB_BREAK = "IB_BREAK"  # Initial Balance break
    DRIVE_CONTINUATION = "DRIVE_CONTINUATION"  # D2/D3 continuation
    DRIVE_REVERSAL = "DRIVE_REVERSAL"  # D3+ rejection reversal


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    SL = "SL"  # Stop loss limit
    SL_MARKET = "SL-M"  # Stop loss market
    BRACKET = "BRACKET"  # Bracket order


class OrderStatus(str, Enum):
    PENDING = "PENDING"
    PLACED = "PLACED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class TradeStatus(str, Enum):
    OPEN = "OPEN"
    PARTIALLY_CLOSED = "PARTIALLY_CLOSED"
    CLOSED = "CLOSED"
    STOPPED_OUT = "STOPPED_OUT"
