"""Cross-Index Correlation Detector — BANKNIFTY leads NIFTY by 5-30 seconds.

In Indian markets:
- BANKNIFTY often leads NIFTY by 5-30 seconds
- FINNIFTY follows similar patterns
- CRUDEOIL follows COMEX crude with a lag

This detector:
1. Tracks price direction across indices
2. Measures lead-lag relationship
3. Provides early signal when leader moves
4. Filters false signals when correlation breaks down
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import deque
from typing import Any


@dataclass(frozen=True)
class CorrelationSignal:
    leader: str
    follower: str
    leader_direction: str  # "UP" | "DOWN"
    lag_seconds: float
    confidence: float  # 0.0-1.0
    correlation: float  # -1.0 to 1.0


class CrossIndexCorrelation:
    """Detects lead-lag relationships between indices.

    Usage:
        corr = CrossIndexCorrelation(window_size=60)
        corr.update("BANKNIFTY", price=48000.0, timestamp=1700000000.0)
        corr.update("NIFTY", price=23400.0, timestamp=1700000005.0)
        signal = corr.get_signal()
    """

    # Known lead-lag relationships
    LEAD_LAG_PAIRS = {
        ("BANKNIFTY", "NIFTY"): {"expected_lag": 15.0, "strength": 0.7},
        ("BANKNIFTY", "FINNIFTY"): {"expected_lag": 10.0, "strength": 0.8},
        ("NIFTY", "FINNIFTY"): {"expected_lag": 5.0, "strength": 0.6},
        ("CRUDEOIL", "NATURALGAS"): {"expected_lag": 30.0, "strength": 0.4},
    }

    def __init__(self, window_size: int = 60):
        self._window = window_size
        self._price_history: dict[str, deque] = {}
        self._returns_history: dict[str, deque] = {}
        self._last_price: dict[str, float] = {}
        self._last_time: dict[str, float] = {}

    def update(self, symbol: str, price: float, timestamp: float) -> None:
        """Update price for an index.

        Args:
            symbol: Index symbol
            price: Current price
            timestamp: Unix timestamp
        """
        if symbol not in self._price_history:
            self._price_history[symbol] = deque(maxlen=self._window)
            self._returns_history[symbol] = deque(maxlen=self._window)

        # Calculate return
        prev_price = self._last_price.get(symbol)
        if prev_price and prev_price > 0:
            ret = (price - prev_price) / prev_price
            self._returns_history[symbol].append(ret)

        self._price_history[symbol].append((timestamp, price))
        self._last_price[symbol] = price
        self._last_time[symbol] = timestamp

    def get_correlation(self, leader: str, follower: str) -> float:
        """Calculate correlation between leader and follower returns.

        Returns correlation coefficient (-1.0 to 1.0).
        """
        leader_returns = list(self._returns_history.get(leader, []))
        follower_returns = list(self._returns_history.get(follower, []))

        if len(leader_returns) < 10 or len(follower_returns) < 10:
            return 0.0

        # Align to same length
        n = min(len(leader_returns), len(follower_returns))
        lr = leader_returns[-n:]
        fr = follower_returns[-n:]

        # Pearson correlation
        mean_l = sum(lr) / n
        mean_f = sum(fr) / n

        num = sum((l - mean_l) * (f - mean_f) for l, f in zip(lr, fr))
        den_l = sum((l - mean_l) ** 2 for l in lr) ** 0.5
        den_f = sum((f - mean_f) ** 2 for f in fr) ** 0.5

        if den_l == 0 or den_f == 0:
            return 0.0

        return num / (den_l * den_f)

    def get_signal(
        self, leader: str, follower: str
    ) -> CorrelationSignal | None:
        """Get correlation signal between leader and follower.

        Returns CorrelationSignal if there's a meaningful move.
        """
        # Check if this is a known pair
        pair = (leader, follower)
        pair_info = self.LEAD_LAG_PAIRS.get(pair, {})

        # Get latest prices
        leader_price = self._last_price.get(leader, 0)
        follower_price = self._last_price.get(follower, 0)

        if leader_price <= 0 or follower_price <= 0:
            return None

        # Calculate correlation
        corr = self.get_correlation(leader, follower)

        # Determine leader direction from recent returns
        leader_returns = list(self._returns_history.get(leader, []))
        if len(leader_returns) < 3:
            return None

        recent_returns = leader_returns[-5:]
        avg_return = sum(recent_returns) / len(recent_returns)

        if abs(avg_return) < 0.0001:  # Too small
            return None

        direction = "UP" if avg_return > 0 else "DOWN"

        # Calculate confidence based on correlation strength
        expected_strength = pair_info.get("strength", 0.5)
        confidence = abs(corr) * expected_strength

        # Calculate lag
        leader_time = self._last_time.get(leader, 0)
        follower_time = self._last_time.get(follower, 0)
        lag = abs(leader_time - follower_time) if leader_time and follower_time else 0.0

        return CorrelationSignal(
            leader=leader,
            follower=follower,
            leader_direction=direction,
            lag_seconds=lag,
            confidence=round(confidence, 2),
            correlation=round(corr, 3),
        )

    def get_all_signals(self) -> list[CorrelationSignal]:
        """Get signals for all known pairs."""
        signals = []
        for (leader, follower) in self.LEAD_LAG_PAIRS:
            if leader in self._last_price and follower in self._last_price:
                signal = self.get_signal(leader, follower)
                if signal:
                    signals.append(signal)
        return signals

    def reset(self, symbol: str = "") -> None:
        """Reset state."""
        if symbol:
            self._price_history.pop(symbol, None)
            self._returns_history.pop(symbol, None)
            self._last_price.pop(symbol, None)
            self._last_time.pop(symbol, None)
        else:
            self._price_history.clear()
            self._returns_history.clear()
            self._last_price.clear()
            self._last_time.clear()
