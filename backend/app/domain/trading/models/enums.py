"""Domain enumerations — type-safe constants for the trading domain."""

from __future__ import annotations

from enum import Enum


class MarketStateCodec:
    """Normalize messy market-state strings to canonical values.

    Handles legacy formats like "MarketState.BALANCED", mixed-case, and
    the "BALANCE"/"IMBALANCE" variants from MarketStructureState.
    Supports the 4-state model: NO_TRADE, BALANCED, IMBALANCED, PROBING.
    """

    @staticmethod
    def is_no_trade(value: object) -> bool:
        """Return True if *value* represents a no-trade dead zone."""
        s = str(value).upper()
        return s in ("NO_TRADE", "NOTRADE", "MARKETSTATE.NO_TRADE")

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
    def is_probing(value: object) -> bool:
        """Return True if *value* represents an unconfirmed break."""
        s = str(value).upper()
        return s in ("PROBING", "MARKETSTATE.PROBING")

    @staticmethod
    def is_tradeable(value: object) -> bool:
        """Return True if the state allows trading."""
        s = str(value).upper()
        return s in ("BALANCED", "BALANCE", "IMBALANCED", "IMBALANCE")

    @staticmethod
    def encode(value: object) -> float:
        """Return numeric encoding: IMBALANCED=1.0, BALANCED=0.0, PROBING=0.5, NO_TRADE=-1.0."""
        s = str(value).upper()
        if "IMBALANCED" in s or "IMBALANCE" in s:
            return 1.0
        if "PROBING" in s:
            return 0.5
        if "NO_TRADE" in s or "NOTRADE" in s:
            return -1.0
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
    """Auction Market Theory market state (4-state model per FR-04).

    NO_TRADE: Price within ±2 ticks of POC — dead zone, no edge.
    BALANCED: Price inside VAH-VAL range — rotational, mean-reverting.
    IMBALANCED: Price outside VA + displacement + acceptance — trending.
    PROBING: Price outside VA without displacement — unconfirmed break.
    """

    NO_TRADE = "NO_TRADE"
    BALANCED = "BALANCED"
    IMBALANCED = "IMBALANCED"
    PROBING = "PROBING"


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


class CushionState(str, Enum):
    """Position cushioning lifecycle state.

    The cushioning lifecycle follows a strict progression:
    OPEN → CUSHIONED → TRAILING → CLOSED
    """

    OPEN = "OPEN"        # Position open, no cushioning yet
    CUSHIONED = "CUSHIONED"  # Partial TP taken, SL moved to break-even
    TRAILING = "TRAILING"    # Trailing stop active (ATR or VWAP)
    CLOSED = "CLOSED"        # Position closed
