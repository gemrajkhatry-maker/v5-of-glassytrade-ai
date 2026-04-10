"""Slippage Tracker — tracks expected vs actual fill prices.

Records slippage per trade and alerts when it exceeds thresholds.
Used for:
- Execution quality monitoring
- Broker performance comparison
- Strategy viability (high slippage kills edge)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from collections import deque


@dataclass(frozen=True)
class SlippageRecord:
    symbol: str
    side: str  # "BUY" or "SELL"
    expected_price: float
    actual_price: float
    slippage: float  # actual - expected (positive = worse for buyer)
    slippage_bps: float  # Basis points
    timestamp: float


class SlippageTracker:
    """Tracks execution slippage per symbol and overall."""

    def __init__(self, alert_bps: int = 20):
        self._alert_bps = alert_bps
        self._records: deque[SlippageRecord] = deque(maxlen=1000)
        self._symbol_avg: dict[str, float] = {}
        self._symbol_count: dict[str, int] = {}

    def record_fill(
        self,
        symbol: str,
        side: str,
        expected_price: float,
        actual_price: float,
        timestamp: float = 0.0,
    ) -> SlippageRecord:
        """Record a fill and compute slippage.

        For BUY: slippage = actual - expected (positive = paid more)
        For SELL: slippage = expected - actual (positive = received less)
        """
        if side == "BUY":
            slippage = actual_price - expected_price
        else:
            slippage = expected_price - actual_price

        slippage_bps = 0.0
        if expected_price > 0:
            slippage_bps = (abs(slippage) / expected_price) * 10_000

        record = SlippageRecord(
            symbol=symbol,
            side=side,
            expected_price=expected_price,
            actual_price=actual_price,
            slippage=round(slippage, 4),
            slippage_bps=round(slippage_bps, 1),
            timestamp=timestamp,
        )

        self._records.append(record)

        # Update per-symbol average
        prev_avg = self._symbol_avg.get(symbol, 0)
        count = self._symbol_count.get(symbol, 0)
        self._symbol_count[symbol] = count + 1
        self._symbol_avg[symbol] = (prev_avg * count + abs(slippage)) / (count + 1)

        return record

    def get_avg_slippage_bps(self, symbol: str = "") -> float:
        """Get average slippage in basis points.

        Args:
            symbol: Empty for overall average, specific for per-symbol.
        """
        if symbol:
            avg = self._symbol_avg.get(symbol, 0)
            # Convert to bps using average expected price
            records = [r for r in self._records if r.symbol == symbol]
            if records:
                avg_price = sum(r.expected_price for r in records) / len(records)
                if avg_price > 0:
                    return (avg / avg_price) * 10_000
            return 0.0

        if not self._records:
            return 0.0
        avg_slippage = sum(abs(r.slippage) for r in self._records) / len(self._records)
        avg_price = sum(r.expected_price for r in self._records) / len(self._records)
        if avg_price > 0:
            return (avg_slippage / avg_price) * 10_000
        return 0.0

    def exceeds_alert_threshold(self, symbol: str = "") -> bool:
        """Check if slippage exceeds the alert threshold."""
        return self.get_avg_slippage_bps(symbol) > self._alert_bps

    def get_recent_records(self, limit: int = 20) -> list[SlippageRecord]:
        """Get most recent slippage records."""
        return list(self._records)[-limit:]

    def get_symbol_stats(self) -> dict[str, dict]:
        """Get slippage stats per symbol."""
        stats = {}
        for symbol in set(r.symbol for r in self._records):
            records = [r for r in self._records if r.symbol == symbol]
            slips = [abs(r.slippage_bps) for r in records]
            stats[symbol] = {
                "count": len(records),
                "avg_bps": round(sum(slips) / len(slips), 1) if slips else 0,
                "max_bps": round(max(slips), 1) if slips else 0,
                "min_bps": round(min(slips), 1) if slips else 0,
            }
        return stats

    def reset(self, symbol: str = "") -> None:
        """Reset slippage tracking."""
        if symbol:
            self._records = deque(
                (r for r in self._records if r.symbol != symbol), maxlen=1000
            )
            self._symbol_avg.pop(symbol, None)
            self._symbol_count.pop(symbol, None)
        else:
            self._records.clear()
            self._symbol_avg.clear()
            self._symbol_count.clear()
