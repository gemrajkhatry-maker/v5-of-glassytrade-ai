"""Trading model utilities — DRY helpers for common operations.

Eliminates duplicated patterns across the codebase:
- Side normalization (already has Side.normalize)
- Decimal-to-float conversion (4 locations)
- Market state mapping (3 locations)
"""

from __future__ import annotations

from typing import Any

from app.domain.trading.models.enums import Side


def safe_side(value: Any) -> str:
    """Normalize side value to string.

    Replaces the pattern: pos.side.value if hasattr(pos.side, 'value') else str(pos.side)
    """
    if value is None:
        return "FLAT"
    if hasattr(value, "value"):
        return value.value
    return str(value)


class ValueSerializer:
    """Utility class for value serialization.

    Handles the common pattern of converting Decimal/float/int values:
        float(x) if hasattr(x, '__float__') else x

    Usage:
        ValueSerializer.to_float(position.entry_price)  # Returns float
        ValueSerializer.to_int(position.size)            # Returns int
    """

    @staticmethod
    def to_float(value: Any, default: float = 0.0) -> float:
        """Convert value to float, handling Decimal, int, float, and None.

        Args:
            value: The value to convert.
            default: Default value if conversion fails or value is None.

        Returns:
            Float representation of the value.
        """
        if value is None:
            return default
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def to_int(value: Any, default: int = 0) -> int:
        """Convert value to int, handling Decimal, float, int, and None.

        Args:
            value: The value to convert.
            default: Default value if conversion fails or value is None.

        Returns:
            Int representation of the value.
        """
        if value is None:
            return default
        try:
            return int(value)
        except (TypeError, ValueError):
            return default


class MarketStateMapper:
    """Utility class for market state mapping.

    Handles the common pattern of mapping market state strings:
        "Trending" if MarketStateCodec.is_imbalanced(...)

    Usage:
        MarketStateMapper.display_name(amt_result.market_state)  # Returns "Trending" or "Balanced"
        MarketStateMapper.is_trending(amt_result.market_state)    # Returns True if IMBALANCED
    """

    @staticmethod
    def display_name(market_state: Any) -> str:
        """Convert market state enum to display string.

        Args:
            market_state: The market state (enum or string).

        Returns:
            "Trending" if IMBALANCED, "Balanced" otherwise.
        """
        state_str = str(market_state).upper()
        if "IMBALANCED" in state_str or "IMBALANCE" in state_str:
            return "Trending"
        return "Balanced"

    @staticmethod
    def is_trending(market_state: Any) -> bool:
        """Check if market state is trending (IMBALANCED)."""
        state_str = str(market_state).upper()
        return "IMBALANCED" in state_str or "IMBALANCE" in state_str

    @staticmethod
    def is_balanced(market_state: Any) -> bool:
        """Check if market state is balanced."""
        state_str = str(market_state).upper()
        return "BALANCED" in state_str or "BALANCE" in state_str