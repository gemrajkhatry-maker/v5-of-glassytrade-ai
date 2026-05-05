"""orderflow detectors — AMT analysis service.

Based on amt_docs section 2.4:
- Absorption: High volume with compressed range and delta confirmation
- Big Trade: Large prints >= 5x average within 2 ticks
- OFI: Order Flow Imbalance calculation
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING
from typing import Tuple

from app.domain.constants import (
    ABSORPTION_RANGE_ATR,
    ABSORPTION_VOL_MULT,
    BIG_TRADE_MULTIPLIER,
    BIG_TRADE_CLUSTER_COUNT,
    BIG_TRADE_CLUSTER_TICKS,
    OFI_WINDOW,
    VOLUME_BUBBLE_SIGMA,
)
from app.domain.trading.model.value_objects import OHLC

from app.domain.amt.model.amt_models import Absorption

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Phase 2.3: AbsorptionDetector
# ---------------------------------------------------------------------------

def detect_absorptions(
    bars: list[dict],
    avg_volume_multiplier: float = 1.5,
    range_threshold: float = 0.5,
    min_bars: int = 20,
    sigma_threshold: float = 2.5,
) -> list[Absorption]:
    """
    Detect absorption patterns from bars.

    Absorption criteria:
    1. Volume > avg_volume * multiplier (2.5σ filter)
    2. Range (high-low) < threshold (compressed)
    3. Delta confirms direction (buyVol > sellVol for BUY absorption)

    Args:
        bars: List of bar dictionaries with high, low, close, volume, buyVolume, sellVolume
        avg_volume_multiplier: Volume must exceed this multiple of average
        range_threshold: Maximum range as fraction of average range (0.5 = 50%)
        min_bars: Minimum bars required for detection
        sigma_threshold: Must be at least 2.5σ spike

    Returns:
        List of detected absorptions
    """
    if len(bars) < min_bars:
        return []

    # Calculate average volume and range
    volumes = [b.get("volume", 0) for b in bars]
    ranges = [b.get("high", 0) - b.get("low", 0) for b in bars]

    avg_volume = sum(volumes) / len(volumes) if volumes else 0
    avg_range = sum(ranges) / len(ranges) if ranges else 0

    if avg_volume == 0:
        return []

    absorptions = []

    for i, bar in enumerate(bars):
        vol = bar.get("volume", 0)
        buy_vol = bar.get("buyVolume", vol / 2)
        sell_vol = bar.get("sellVolume", vol / 2)
        bar_range = bar.get("high", 0) - bar.get("low", 0)

        # Check volume threshold (2.5σ)
        if vol <= avg_volume * avg_volume_multiplier:
            continue

        # Check range compression
        if bar_range > avg_range * range_threshold:
            continue

        # Determine absorption side
        delta = buy_vol - sell_vol
        strength = min(1.0, vol / (avg_volume * 3))  # Normalize strength

        if delta > 0:
            absorptions.append(Absorption(
                bar_index=i,
                price=bar.get("close", 0),
                volume=vol,
                side="BUY",
                strength=strength,
            ))
        elif delta < 0:
            absorptions.append(Absorption(
                bar_index=i,
                price=bar.get("close", 0),
                volume=vol,
                side="SELL",
                strength=strength,
            ))

    return absorptions


# ---------------------------------------------------------------------------
# Phase 2.14: BigTradeDetector
# ---------------------------------------------------------------------------

@dataclass
class BigTrade:
    """Detected big trade."""
    price: float
    volume: float
    timestamp: int
    is_cluster: bool = False


class BigTradeDetector:
    """Detect large trades (>= 5x average within 2 ticks)."""

    def __init__(self, volume_multiplier: float = 5.0, tick_tolerance: int = 2):
        self.volume_multiplier = volume_multiplier
        self.tick_tolerance = tick_tolerance
        self._avg_volume: float = 0.0
        self._detection_count: int = 0

    def _from_ohcl(self, candle: OHLC, avg_candle_vol: float):
        if avg_candle_vol <= 0:
            return None

        vol_ratio = float(candle.volume) / avg_candle_vol
        if vol_ratio < max(0.0, self.volume_multiplier * 0.5):
            return None
        delta = float(candle.delta)
        if delta > 0:
            side = "BUY"
        elif delta < 0:
            side = "SELL"
        else:
            side = "MIXED"
        return BigTrade(
            price=float((float(candle.high) + float(candle.low)) / 2),
            volume=float(candle.volume),
            timestamp=0,
        )

    def update_avg_volume(self, volume: float) -> None:
        """Update rolling average volume."""
        self._detection_count += 1
        if self._detection_count == 1:
            self._avg_volume = volume
        else:
            self._avg_volume = self._avg_volume * 0.9 + volume * 0.1

    def detect(
        self,
        candle_or_price: float | OHLC,
        volume: float | None = None,
        timestamp: int = 0,
    ) -> BigTrade | None:
        """Detect if this is a big trade."""
        # Legacy v1 API: detect(candle, avg_candle_vol)
        if isinstance(candle_or_price, OHLC):
            return self._from_ohcl(candle_or_price, volume or 0.0)

        # v2 API: detect(price, volume, timestamp)
        price = float(candle_or_price)
        if volume is None:
            return None
        if self._avg_volume <= 0:
            self.update_avg_volume(volume)
            return None

        if volume >= self.volume_multiplier * self._avg_volume:
            return BigTrade(
                price=price,
                volume=volume,
                timestamp=timestamp,
            )
        return None


# ---------------------------------------------------------------------------
# Phase 2.14: OFICalculator
# ---------------------------------------------------------------------------


def calculate_ofi(bar: dict) -> float:
    """
    Calculate Order Flow Imbalance.

    OFI = (bid_vol - ask_vol) / (bid_vol + ask_vol)
    Positive = more buying, Negative = more selling
    """
    bid_vol = bar.get("buyVolume", bar.get("volume", 0) / 2)
    ask_vol = bar.get("sellVolume", bar.get("volume", 0) / 2)
    total = bid_vol + ask_vol
    if total == 0:
        return 0.0
    return (bid_vol - ask_vol) / total


def ofi_aligned_signal(ofi: float, threshold: float = 0.10) -> str:
    """Determine alignment from OFI."""
    if ofi > threshold:
        return "LONG"
    elif ofi < -threshold:
        return "SHORT"
    return "NONE"


@dataclass
class BubbleResult:
    """Detected volume bubble."""
    detected: bool
    direction: str
    sigma: float
    candle_time: str


@dataclass
class OFIResult:
    """Order Flow Imbalance result."""
    ofi: float
    window: int


@dataclass
class AbsorptionResult:
    """Absorption detection result."""
    detected: bool
    side: str
    range_ratio: float
    vol_ratio: float


class BubbleDetector:
    """Volume-bubble detector compatible with the Phase-D API."""

    def __init__(self, lookback: int = 21) -> None:
        self._history: deque[float] = deque(maxlen=lookback)

    def detect(self, candle: OHLC) -> BubbleResult:
        vol = float(candle.volume)
        self._history.append(vol)

        if len(self._history) < 5:
            return BubbleResult(False, "NEUTRAL", 0.0, candle.time)

        vols = list(self._history)
        mean_vol = sum(vols) / len(vols)
        variance = sum((v - mean_vol) ** 2 for v in vols) / len(vols)
        std_vol = math.sqrt(variance) if variance > 0 else 0.0
        if std_vol <= 0:
            return BubbleResult(False, "NEUTRAL", 0.0, candle.time)

        sigma = (vol - mean_vol) / std_vol
        if sigma < VOLUME_BUBBLE_SIGMA:
            return BubbleResult(False, "NEUTRAL", sigma, candle.time)

        delta = float(candle.delta)
        direction = "BUY" if delta > 0 else "SELL" if delta < 0 else "NEUTRAL"
        return BubbleResult(True, direction, sigma, candle.time)


class OFICalculator:
    """Rolling OFI wrapper for v1 compatibility."""

    def __init__(self, window: int = OFI_WINDOW) -> None:
        self._window = window
        self._deltas: deque[float] = deque(maxlen=window)
        self._volumes: deque[float] = deque(maxlen=window)

    def update(self, candle: OHLC) -> OFIResult:
        delta = float(candle.delta)
        volume = float(candle.volume)
        if volume <= 0:
            return OFIResult(ofi=0.0, window=len(self._deltas))

        if abs(delta) > volume:
            logger.warning(
                "OFI delta (%.0f) exceeds volume (%.0f) — normalizing",
                delta,
                volume,
            )
            delta = volume if delta > 0 else -volume

        self._deltas.append(delta)
        self._volumes.append(volume)
        total_vol = sum(self._volumes)
        if total_vol <= 0:
            return OFIResult(ofi=0.0, window=len(self._deltas))

        total_delta = sum(self._deltas)
        ofi = max(-1.0, min(1.0, total_delta / total_vol))
        if abs(ofi) > 0.001 and abs(ofi % 1.0) < 0.001:
            logger.warning("OFI suspiciously round: %.3f — possible calc issue", ofi)
        return OFIResult(ofi=ofi, window=len(self._deltas))

    def reset(self) -> None:
        self._deltas.clear()
        self._volumes.clear()


class AbsorptionDetector:
    """Compat detection for v1-style absorption signatures."""

    def __init__(self) -> None:
        self._pending_candle: OHLC | None = None
        self._pending_side = ""
        self._pending_range_ratio = 0.0
        self._pending_vol_ratio = 0.0
        self._candles_since_pending = 0

    def detect(self, candle: OHLC, atr: float, avg_vol: float) -> AbsorptionResult:
        if self._pending_candle is not None:
            self._candles_since_pending += 1
            displaced_bullish = float(candle.close) > float(self._pending_candle.high)
            displaced_bearish = float(candle.close) < float(self._pending_candle.low)
            if self._pending_side == "SELL_ABSORBED" and displaced_bullish:
                result = AbsorptionResult(
                    True,
                    "SELL_ABSORBED",
                    self._pending_range_ratio,
                    self._pending_vol_ratio,
                )
                self._clear_pending()
                return result
            if self._pending_side == "BUY_ABSORBED" and displaced_bearish:
                result = AbsorptionResult(
                    True,
                    "BUY_ABSORBED",
                    self._pending_range_ratio,
                    self._pending_vol_ratio,
                )
                self._clear_pending()
                return result
            if (
                self._candles_since_pending >= 2
                or (self._pending_side == "SELL_ABSORBED" and displaced_bearish)
                or (self._pending_side == "BUY_ABSORBED" and displaced_bullish)
            ):
                self._clear_pending()

        candle_range = float(candle.high - candle.low)
        candle_vol = float(candle.volume)
        if atr <= 0 or avg_vol <= 0:
            return AbsorptionResult(False, "", 0.0, 0.0)

        range_ratio = candle_range / atr
        vol_ratio = candle_vol / avg_vol
        if range_ratio < ABSORPTION_RANGE_ATR and vol_ratio >= ABSORPTION_VOL_MULT:
            delta = float(candle.delta)
            if delta > 0:
                self._pending_side = "SELL_ABSORBED"
            elif delta < 0:
                self._pending_side = "BUY_ABSORBED"
            else:
                return AbsorptionResult(False, "", range_ratio, vol_ratio)

            self._pending_candle = candle
            self._pending_range_ratio = range_ratio
            self._pending_vol_ratio = vol_ratio
            self._candles_since_pending = 0
        return AbsorptionResult(False, "", range_ratio, vol_ratio)

    def _clear_pending(self) -> None:
        self._pending_candle = None
        self._pending_side = ""
        self._pending_range_ratio = 0.0
        self._pending_vol_ratio = 0.0
        self._candles_since_pending = 0

