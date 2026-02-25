"""Domain enumerations — type-safe constants for the trading domain."""

from __future__ import annotations

from enum import Enum


class Side(str, Enum):
    """Trade direction."""
    LONG = "LONG"
    SHORT = "SHORT"


class SignalType(str, Enum):
    """Signal direction."""
    BUY = "BUY"
    SELL = "SELL"


class Source(str, Enum):
    """Origin of a trade or signal."""
    AMT = "AMT"
    PREDICTION = "PREDICTION"
    RL = "RL"
    LLM = "LLM"
    AGENT = "AGENT"


class MarketState(str, Enum):
    """Auction Market Theory market state."""
    BALANCED = "BALANCED"
    IMBALANCED = "IMBALANCED"


class MarketStructureState(str, Enum):
    """5-state market structure classification."""
    BALANCE = "BALANCE"
    IMBALANCE = "IMBALANCE"
    TRANSITION = "TRANSITION"
    EXPANSION = "EXPANSION"
    CHOP = "CHOP"


class SetupType(str, Enum):
    """Trade setup classification."""
    TREND_MODEL = "TREND_MODEL"
    MEAN_REVERSION = "MEAN_REVERSION"
    PREDICTION_ENTRY = "PREDICTION_ENTRY"
    RL_ENTRY = "RL_ENTRY"


class PositionStatus(str, Enum):
    """Lifecycle status of a position."""
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class Sentiment(str, Enum):
    """AI model sentiment assessment."""
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class TrendDirection(str, Enum):
    """Long-term trend direction."""
    UP = "UP"
    DOWN = "DOWN"
    SIDEWAYS = "SIDEWAYS"


class MessageRole(str, Enum):
    """Chat message role."""
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"
