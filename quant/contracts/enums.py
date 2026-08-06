"""Domain enumerations — type-safe constants for the trading domain."""

from __future__ import annotations

from enum import Enum
from typing import Any


class MarketStateCodec:
    """Normalize messy market-state strings to canonical values.

    Handles legacy formats like "MarketState.BALANCED", mixed-case, and
    the "BALANCE"/"IMBALANCE" variants from MarketStructureState.
    Supports Fabio's 2-state model: BALANCED, IMBALANCED.
    """

    @staticmethod
    def is_tradeable(value: object) -> bool:
        """Return True if the state allows trading (both states are tradeable)."""
        s = str(value).upper()
        return s in ("BALANCED", "BALANCE", "IMBALANCED", "IMBALANCE")

    @staticmethod
    def is_balanced(value: object) -> bool:
        """Return True if *value* represents a balanced/range market."""
        s = str(value).upper()
        return s in ("BALANCED", "BALANCE", "MARKETSTATE.BALANCED")

    @staticmethod
    def is_imbalanced(value: object) -> bool:
        """Return True if *value* represents an imbalanced/trending market."""
        s = str(value).upper()
        return s in ("IMBALANCED", "IMBALANCE", "MARKETSTATE.IMBALANCED")

    @staticmethod
    def is_no_trade(value: object) -> bool:
        """Legacy method - NO_TRADE state no longer exists in 2-state model."""
        return False

    @staticmethod
    def is_probing(value: object) -> bool:
        """Legacy method - PROBING state no longer exists in 2-state model."""
        return False

    @staticmethod
    def encode(value: object) -> float:
        """Return numeric encoding: IMBALANCED=1.0, BALANCED=0.0."""
        s = str(value).upper()
        if "IMBALANCED" in s or "IMBALANCE" in s:
            return 1.0
        return 0.0


class ProfileShapeCodec:
    """Normalize volume-profile shape codes.

    Canonical single-char codes: "D" (bell/balanced), "P" (top-heavy),
    "b" (bottom-heavy), "B" (bimodal).
    """

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
        """Return canonical single-char shape code, or the original if unknown.

        Handles:
        - Single chars: "P", "b", "D", "B" — returned as-is
        - Descriptive strings starting with a shape code: "P-shape (top-heavy)",
          "b-shape (bottom-heavy)" — first character extracted
        - Short aliases: "p-shape", "top-heavy", "accumulation" — alias table
        """
        s = shape.strip()
        if not s:
            return s
        if s in ("P", "b", "D", "B"):
            return s
        # Extract first char from descriptive strings like "P-shape (top-heavy)"
        first = s[0]
        if first in ("P", "b", "D", "B"):
            return first
        return cls._ALIASES.get(s.lower(), s)

    @staticmethod
    def encode(shape: str) -> float:
        """Return numeric ML feature: P=1.0, b=-1.0, D=0.0, B=0.0."""
        s = ProfileShapeCodec.normalize(shape)
        if s == "P":
            return 1.0
        if s == "b":
            return -1.0
        return 0.0


class Side(str, Enum):
    """Trade direction."""

    LONG = "LONG"
    SHORT = "SHORT"

    @staticmethod
    def normalize(side: Any) -> str:
        """Normalize side to "LONG", "SHORT", or "FLAT"."""
        if side is None:
            return "FLAT"
        if hasattr(side, "value"):
            return str(side.value).upper()
        return str(side).upper()

    @classmethod
    def is_long(cls, side: Any) -> bool:
        """Check if a side is LONG."""
        return cls.normalize(side) == cls.LONG

    @classmethod
    def is_short(cls, side: Any) -> bool:
        """Check if a side is SHORT."""
        return cls.normalize(side) == cls.SHORT

    @classmethod
    def opposite(cls, side: Any) -> str:
        """Return opposite side as string."""
        normalized = cls.normalize(side)
        if normalized == cls.LONG:
            return cls.SHORT
        if normalized == cls.SHORT:
            return cls.LONG
        return "FLAT"


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
    """Fabio's 2-state model (simplified from FR-04 for alignment).
    
    BALANCED: Price inside VAH-VAL — rotational, mean-reverting.
    IMBALANCED: Price outside VA + displacement + acceptance — trending.
    """

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
    RESPONSIVE_FADE = "RESPONSIVE_FADE"
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


class CushionState(str, Enum):
    """Position cushioning lifecycle state.

    The cushioning lifecycle follows a strict progression:
    OPEN → CUSHIONED → TRAILING → CLOSED
    """

    OPEN = "OPEN"        # Position open, no cushioning yet
    CUSHIONED = "CUSHIONED"  # Partial TP taken, SL moved to break-even
    TRAILING = "TRAILING"    # Trailing stop active (ATR or VWAP)
    CLOSED = "CLOSED"        # Position closed
