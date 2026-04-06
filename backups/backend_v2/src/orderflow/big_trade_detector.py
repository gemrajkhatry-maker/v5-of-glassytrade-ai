"""
Big trade detector — institutional print cluster detection.

Detects 3+ institutional prints (≥ 5× avg) within 2 ticks of each other.
"""

from dataclasses import dataclass
from typing import List, Optional

from src.config.engine_config import CFG
from src.core.tick_processor import Tick


@dataclass
class BigTradeCluster:
    """Big trade cluster detection result."""

    detected: bool
    price: float
    trade_count: int
    total_volume: int
    avg_size: float
    side: str  # "BUY", "SELL", "NEUTRAL"


class BigTradeDetector:
    """
    Detect institutional big trade clusters.
    """

    def __init__(self, multiplier: float = CFG.big_trade_multiplier):
        self._multiplier = multiplier
        self._recent_trades: List[Tick] = []

    def detect(
        self,
        ticks: List[Tick],
        avg_trade_size: float,
    ) -> Optional[BigTradeCluster]:
        """
        Find clusters of big trades.

        Args:
            ticks: Recent ticks to analyze
            avg_trade_size: Average trade size for comparison

        Returns:
            BigTradeCluster if detected, otherwise None.
        """
        if avg_trade_size <= 0:
            return None

        threshold = avg_trade_size * self._multiplier

        # Find big trades
        big_trades = [t for t in ticks if t.trade_size >= threshold]

        if len(big_trades) < CFG.big_trade_cluster_count:
            return None

        # Check for clusters (within 2 ticks of each other)
        clusters = self._find_clusters(big_trades)

        if not clusters:
            return None

        # Return the largest cluster
        largest = max(clusters, key=lambda c: c.total_volume)
        return largest

    def _find_clusters(self, big_trades: List[Tick]) -> List[BigTradeCluster]:
        """
        Find clusters of big trades within proximity.
        """
        if len(big_trades) < CFG.big_trade_cluster_count:
            return []

        clusters = []
        used = set()

        for i, trade in enumerate(big_trades):
            if i in used:
                continue

            # Find nearby trades
            cluster_trades = [trade]
            used.add(i)

            for j, other in enumerate(big_trades):
                if j in used or j == i:
                    continue

                # Check proximity (within 2 ticks)
                price_diff = abs(trade.price - other.price)
                if price_diff <= CFG.big_trade_cluster_ticks * 0.10:  # Assuming 0.10 tick size
                    cluster_trades.append(other)
                    used.add(j)

            # Check if cluster meets minimum count
            if len(cluster_trades) >= CFG.big_trade_cluster_count:
                # Calculate cluster stats
                total_vol = sum(t.trade_size for t in cluster_trades)
                avg_size = total_vol / len(cluster_trades)
                avg_price = sum(t.price for t in cluster_trades) / len(cluster_trades)

                # Determine side
                buy_vol = sum(t.ask_vol for t in cluster_trades)
                sell_vol = sum(t.bid_vol for t in cluster_trades)

                if buy_vol > sell_vol * 1.5:
                    side = "BUY"
                elif sell_vol > buy_vol * 1.5:
                    side = "SELL"
                else:
                    side = "NEUTRAL"

                clusters.append(BigTradeCluster(
                    detected=True,
                    price=avg_price,
                    trade_count=len(cluster_trades),
                    total_volume=total_vol,
                    avg_size=avg_size,
                    side=side,
                ))

        return clusters

    def reset(self) -> None:
        """Reset for new session."""
        self._recent_trades.clear()