"""Market Regime Detector — detects volatility and trend regimes.

Regimes:
- LOW_VOLATILITY: Tight range, low volume — avoid breakouts
- NORMAL: Standard conditions — all setups valid
- HIGH_VOLATILITY: Wide range, high volume — wider stops, smaller size
- TRENDING: Sustained directional movement — trend following
- CHOPPY: Directionless, overlapping candles — mean reversion only
- TRANSITION: Regime changing — reduced size, wait for clarity
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class Regime(str, Enum):
    LOW_VOLATILITY = "LOW_VOLATILITY"
    NORMAL = "NORMAL"
    HIGH_VOLATILITY = "HIGH_VOLATILITY"
    TRENDING = "TRENDING"
    CHOPPY = "CHOPPY"
    TRANSITION = "TRANSITION"


@dataclass(frozen=True)
class RegimeResult:
    regime: Regime
    atr_pct: float  # ATR as % of price
    trend_strength: float  # -1.0 to 1.0
    volume_ratio: float  # Current vs average
    efficiency_ratio: float  # Net move / total distance
    suggested_size_pct: float  # Recommended position size multiplier


class RegimeDetector:
    """Detects market regime from recent price action."""

    def __init__(
        self,
        lookback: int = 20,
        low_vol_threshold: float = 0.3,
        high_vol_threshold: float = 1.5,
        trend_threshold: float = 0.6,
    ):
        self._lookback = lookback
        self._low_vol_threshold = low_vol_threshold
        self._high_vol_threshold = high_vol_threshold
        self._trend_threshold = trend_threshold
        self._prices: list[float] = []
        self._volumes: list[float] = []
        self._ranges: list[float] = []
        self._prev_regime: Regime | None = None

    def update(
        self,
        open: float,
        high: float,
        low: float,
        close: float,
        volume: float,
    ) -> RegimeResult:
        """Update regime detector with new candle."""
        self._prices.append(close)
        self._volumes.append(volume)
        self._ranges.append(high - low)

        if len(self._prices) > self._lookback:
            self._prices.pop(0)
            self._volumes.pop(0)
            self._ranges.pop(0)

        return self._detect()

    def _detect(self) -> RegimeResult:
        """Detect current regime."""
        if len(self._prices) < 5:
            return RegimeResult(
                regime=Regime.TRANSITION,
                atr_pct=0.0,
                trend_strength=0.0,
                volume_ratio=1.0,
                efficiency_ratio=0.0,
                suggested_size_pct=0.5,
            )

        # ATR as % of price
        atr = sum(self._ranges[-self._lookback:]) / min(len(self._ranges), self._lookback)
        price = self._prices[-1]
        atr_pct = (atr / price * 100) if price > 0 else 0

        # Volume ratio
        avg_vol = sum(self._volumes) / len(self._volumes)
        vol_ratio = self._volumes[-1] / avg_vol if avg_vol > 0 else 1.0

        # Trend strength (linear regression slope normalized)
        trend_strength = self._calculate_trend_strength()

        # Efficiency ratio (net move / total distance traveled)
        efficiency = self._calculate_efficiency()

        # Determine regime
        regime = self._classify(atr_pct, trend_strength, vol_ratio, efficiency)

        # Suggested position size
        size_pct = self._suggested_size(regime, atr_pct)

        result = RegimeResult(
            regime=regime,
            atr_pct=round(atr_pct, 3),
            trend_strength=round(trend_strength, 3),
            volume_ratio=round(vol_ratio, 2),
            efficiency_ratio=round(efficiency, 3),
            suggested_size_pct=round(size_pct, 2),
        )

        self._prev_regime = regime
        return result

    def _calculate_trend_strength(self) -> float:
        """Calculate trend strength via linear regression (-1 to 1)."""
        n = len(self._prices)
        if n < 3:
            return 0.0

        xs = list(range(n))
        ys = self._prices

        x_mean = sum(xs) / n
        y_mean = sum(ys) / n

        num = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
        den_x = sum((x - x_mean) ** 2 for x in xs) ** 0.5
        den_y = sum((y - y_mean) ** 2 for y in ys) ** 0.5

        if den_x == 0 or den_y == 0:
            return 0.0

        return num / (den_x * den_y)

    def _calculate_efficiency(self) -> float:
        """Calculate efficiency ratio: net move / total distance (0-1)."""
        if len(self._prices) < 2:
            return 0.0

        net_move = abs(self._prices[-1] - self._prices[0])
        total_distance = sum(abs(self._prices[i] - self._prices[i-1]) for i in range(1, len(self._prices)))

        if total_distance == 0:
            return 0.0

        return min(1.0, net_move / total_distance)

    def _classify(
        self, atr_pct: float, trend: float, vol_ratio: float, efficiency: float
    ) -> Regime:
        """Classify regime from metrics."""
        # Check for transition (regime change)
        if self._prev_regime is not None:
            new_regime = self._classify_metrics(atr_pct, trend, vol_ratio, efficiency)
            if new_regime != self._prev_regime:
                return Regime.TRANSITION
            return new_regime
        return self._classify_metrics(atr_pct, trend, vol_ratio, efficiency)

    def _classify_metrics(
        self, atr_pct: float, trend: float, vol_ratio: float, efficiency: float
    ) -> Regime:
        """Core classification logic."""
        # Low volatility
        if atr_pct < self._low_vol_threshold:
            return Regime.LOW_VOLATILITY

        # High volatility
        if atr_pct > self._high_vol_threshold:
            return Regime.HIGH_VOLATILITY

        # Trending: strong trend + high efficiency
        if abs(trend) > self._trend_threshold and efficiency > 0.5:
            return Regime.TRENDING

        # Choppy: low efficiency, weak trend
        if efficiency < 0.2 and abs(trend) < 0.3:
            return Regime.CHOPPY

        return Regime.NORMAL

    def _suggested_size(self, regime: Regime, atr_pct: float) -> float:
        """Suggested position size multiplier."""
        base = 1.0
        if regime == Regime.LOW_VOLATILITY:
            base = 0.5  # Avoid breakouts in low vol
        elif regime == Regime.HIGH_VOLATILITY:
            base = 0.5  # Reduce size for wider stops
        elif regime == Regime.TRENDING:
            base = 1.0  # Full size for trends
        elif regime == Regime.CHOPPY:
            base = 0.25  # Minimal size in chop
        elif regime == Regime.TRANSITION:
            base = 0.5  # Wait for clarity
        return base

    @property
    def current_regime(self) -> Regime | None:
        return self._prev_regime

    def reset(self) -> None:
        self._prices.clear()
        self._volumes.clear()
        self._ranges.clear()
        self._prev_regime = None
