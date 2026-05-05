"""Domain enumerations — type-safe constants for the trading domain."""

from __future__ import annotations

from enum import Enum


class MarketStateCodec:
    """Normalize messy market-state strings to canonical values."""

    @staticmethod
    def is_tradeable(value: object) -> bool:
        s = str(value).upper()
        return s in ("BALANCED", "BALANCE", "IMBALANCED", "IMBALANCE")

    @staticmethod
    def is_balanced(value: object) -> bool:
        s = str(value).upper()
        return s in ("BALANCED", "BALANCE", "MARKETSTATE.BALANCED")

    @staticmethod
    def is_imbalanced(value: object) -> bool:
        s = str(value).upper()
        return s in ("IMBALANCED", "IMBALANCE", "MARKETSTATE.IMBALANCED")

    @staticmethod
    def is_no_trade(value: object) -> bool:
        return False

    @staticmethod
    def is_probing(value: object) -> bool:
        return False

    @staticmethod
    def encode(value: object) -> float:
        s = str(value).upper()
        if "IMBALANCED" in s or "IMBALANCE" in s:
            return 1.0
        return 0.0


class ProfileShapeCodec:
    """Normalize volume-profile shape codes."""

    _ALIASES: dict[str, str] = {
        "p-shape": "P",
        "top-heavy": "P",
        "distribution": "P",
        "b-shape": "b",
        "bottom-heavy": "b",
        "accumulation": "b",
        "d-shape": "D",
        "bell": "D",
        "balanced": "D",
        "normal": "D",
        "bimodal": "B",
        "double": "B",
    }

    @classmethod
    def normalize(cls, shape: str) -> str:
        s = shape.strip()
        if not s:
            return s
        if s in ("P", "b", "D", "B"):
            return s
        first = s[0]
        if first in ("P", "b", "D", "B"):
            return first
        return cls._ALIASES.get(s.lower(), s)

    @staticmethod
    def encode(shape: str) -> float:
        s = ProfileShapeCodec.normalize(shape)
        if s == "P":
            return 1.0
        if s == "b":
            return -1.0
        return 0.0


class Side(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class SignalType(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class Source(str, Enum):
    AMT = "AMT"
    PREDICTION = "PREDICTION"
    RL = "RL"
    LLM = "LLM"
    AGENT = "AGENT"


class MarketState(str, Enum):
    BALANCED = "BALANCED"
    IMBALANCED = "IMBALANCED"


class MarketStructureState(str, Enum):
    BALANCE = "BALANCE"
    IMBALANCE = "IMBALANCE"
    TRANSITION = "TRANSITION"
    EXPANSION = "EXPANSION"
    CHOP = "CHOP"


class SetupType(str, Enum):
    TREND_MODEL = "TREND_MODEL"
    MEAN_REVERSION = "MEAN_REVERSION"
    RESPONSIVE_FADE = "RESPONSIVE_FADE"
    PREDICTION_ENTRY = "PREDICTION_ENTRY"
    RL_ENTRY = "RL_ENTRY"


class PositionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class Sentiment(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    NEUTRAL = "NEUTRAL"


class TrendDirection(str, Enum):
    UP = "UP"
    DOWN = "DOWN"
    SIDEWAYS = "SIDEWAYS"


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class CushionState(str, Enum):
    """Position cushioning lifecycle: OPEN -> CUSHIONED -> TRAILING -> CLOSED."""
    OPEN = "OPEN"
    CUSHIONED = "CUSHIONED"
    TRAILING = "TRAILING"
    CLOSED = "CLOSED"
