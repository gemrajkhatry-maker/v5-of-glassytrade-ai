"""UnderlyingProfileRouter — Routes ticks to the correct UNDERLYING's profile engine.

All volume profiles, LVNs, VAH/VAL are built on UNDERLYING spot price.
Option contract is used ONLY for: position sizing, expiry selection, OI check.

Key design decisions:
- O(1) per tick incremental update (no full rebuild)
- Factory pattern for creating per-underlying profile engines
- Lazy initialization: engine created on first tick for each underlying
- Thread-safe dict access (single-threaded tick loop guarantees ordering)

Usage:
    router = UnderlyingProfileRouter(profile_factory=factory)
    router.update("CRUDEOIL", underlying_price=6100.0, volume=500, delta=120.0)
    engine = router.get_engine("CRUDEOIL")
    profile = engine.get_profile()
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.domain.fabio_ai.services.amt_analyzer import IncrementalVolumeProfile
from app.domain.trading.models.value_objects import OHLC

if TYPE_CHECKING:
    from app.domain.fabio_ai.services.profile_factory import IncrementalProfileFactory

logger = logging.getLogger(__name__)


def _extract_underlying(symbol: str) -> str:
    """Extract the underlying asset from an option symbol.

    Examples:
        "CRUDEOIL 17 MAR 6100 CALL" -> "CRUDEOIL"
        "NSE:NIFTY26MAR25000CE" -> "NIFTY"
        "GOLD" -> "GOLD"

    Falls back to the raw symbol if parsing fails.
    """
    # Remove exchange prefix
    clean = symbol.replace("NSE:", "").replace("MCX:", "").replace("BSE:", "").strip()

    # Handle hyphenated format: "CRUDEOIL-6100-CE"
    if "-" in clean:
        parts = clean.split("-")
        return parts[0].strip()

    # Handle spaced format: "CRUDEOIL 17 MAR 6100 CALL"
    parts = clean.split()
    if parts:
        return parts[0]

    return clean


class UnderlyingProfileRouter:
    """Routes ticks to the correct UNDERLYING's profile engine.

    All volume profiles, LVNs, VAH/VAL are built on underlying price.
    Option contract is used only for: position sizing, expiry selection, OI check.

    DI pattern: injected into ServiceGraph, consumed by engine.py and AMTHandler.
    """

    def __init__(self, profile_factory: "IncrementalProfileFactory") -> None:
        self._engines: dict[str, IncrementalVolumeProfile] = {}
        self._factory = profile_factory
        self._tick_counts: dict[str, int] = {}

    def get_engine(self, underlying: str) -> IncrementalVolumeProfile:
        """Get or create the profile engine for an underlying.

        Lazy initialization: engine is created on first access.

        Args:
            underlying: Underlying asset symbol (e.g., "CRUDEOIL").

        Returns:
            The IncrementalVolumeProfile engine for this underlying.
        """
        if underlying not in self._engines:
            self._engines[underlying] = self._factory.create(underlying)
            self._tick_counts[underlying] = 0
            logger.info("UnderlyingProfileRouter: new engine for %s", underlying)
        return self._engines[underlying]

    def update(
        self,
        underlying: str,
        underlying_price: float,
        volume: int | float,
        delta: float = 0.0,
    ) -> None:
        """Update the underlying's profile with a synthetic tick from option chain data.

        Creates a synthetic OHLC candle at the underlying price point.
        This is O(1) per tick — incremental bucket update.

        Args:
            underlying: Underlying asset symbol.
            underlying_price: Current spot price of the underlying.
            volume: Trade volume at this price level.
            delta: Signed delta (buy_volume - sell_volume).
        """
        if underlying_price <= 0 or volume <= 0:
            return

        engine = self.get_engine(underlying)

        # Compute buy/sell volumes from delta
        vol = float(volume)
        buy_vol = max(0.0, (vol + delta) / 2.0)

        # Create synthetic OHLC tick at underlying price
        synthetic_tick = OHLC(
            time="",  # time not needed for profile bucketing
            open=underlying_price,
            high=underlying_price,
            low=underlying_price,
            close=underlying_price,
            volume=vol,
            taker_buy_volume=buy_vol,
            delta=delta,
        )

        engine.update(synthetic_tick)
        self._tick_counts[underlying] = self._tick_counts.get(underlying, 0) + 1

    def update_from_candle(self, underlying: str, candle: OHLC) -> None:
        """Update the underlying's profile with a full OHLC candle.

        Use this when you have real underlying candle data (not synthetic from option chain).

        Args:
            underlying: Underlying asset symbol.
            candle: Full OHLC candle of the underlying price.
        """
        if candle.close <= 0 or candle.volume <= 0:
            return

        engine = self.get_engine(underlying)
        engine.update(candle)
        self._tick_counts[underlying] = self._tick_counts.get(underlying, 0) + 1

    def get_tick_count(self, underlying: str) -> int:
        """Return the number of ticks processed for an underlying."""
        return self._tick_counts.get(underlying, 0)

    def has_engine(self, underlying: str) -> bool:
        """Check if an engine exists for the given underlying."""
        return underlying in self._engines

    @property
    def active_underlyings(self) -> list[str]:
        """Return list of underlyings with active profile engines."""
        return list(self._engines.keys())

    @property
    def engine_count(self) -> int:
        """Return total number of active engines."""
        return len(self._engines)

    def clear(self, underlying: str | None = None) -> None:
        """Clear profile state for one or all underlyings.

        Args:
            underlying: If provided, clear only this underlying. Otherwise clear all.
        """
        if underlying:
            self._engines.pop(underlying, None)
            self._tick_counts.pop(underlying, None)
            logger.info("UnderlyingProfileRouter: cleared engine for %s", underlying)
        else:
            self._engines.clear()
            self._tick_counts.clear()
            logger.info("UnderlyingProfileRouter: cleared all engines")
