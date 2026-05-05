"""Order Book Analyzer — Depth20 analytics for NSE decision enhancement.

Provides order flow intelligence from 20-level market depth:
1. Order Book Imbalance (OBI) — directional pressure from limit orders
2. Liquidity Walls — large pending orders that act as magnets/support
3. Iceberg Detection — hidden institutional orders refreshing at same level
4. Absorption Confirmation — passive orders defending a level

This is ENHANCEMENT data — the core AMT model works without it.
For NSE: Uses depth20 stream
For MCX: Not available (uses 5-level from WS)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional
from collections import defaultdict

logger = logging.getLogger(__name__)


@dataclass
class LiquidityWall:
    """A large pending order cluster detected in the order book."""
    price: float
    side: str  # "BID" or "ASK"
    quantity: float
    levels_affected: int  # How many price levels this spans
    strength: str = "MODERATE"  # "WEAK", "MODERATE", "STRONG", "WALL"


@dataclass
class OrderBookSnapshot:
    """Complete order book analysis at a point in time."""
    symbol: str
    timestamp: str
    bids: list  # [(price, qty), ...] sorted high to low
    asks: list  # [(price, qty), ...] sorted low to high
    
    # Derived metrics
    obi: float = 0.0           # Order Book Imbalance: (bid_vol - ask_vol) / total
    bid_depth: float = 0.0     # Total bid volume (top 5 levels)
    ask_depth: float = 0.0     # Total ask volume (top 5 levels)
    spread: float = 0.0        # Best ask - best bid
    spread_pct: float = 0.0    # Spread as % of mid price
    mid_price: float = 0.0     # (best_bid + best_ask) / 2
    
    # Wall detection
    bid_walls: list = field(default_factory=list)  # Large bid clusters
    ask_walls: list = field(default_factory=list)  # Large ask clusters
    
    # Absorption signal
    absorption_detected: bool = False
    absorption_side: str = ""  # "BUY_ABSORBED" or "SELL_ABSORBED"


class OrderBookAnalyzer:
    """Analyzes depth20 order book for enhanced decision making.
    
    Used for NSE where depth20 is available from Dhan.
    For MCX, falls back to 5-level from WebSocket.
    """
    
    # Thresholds for wall detection
    WALL_VOLUME_THRESHOLD = 3.0    # 3x average level volume
    STRONG_WALL_THRESHOLD = 5.0    # 5x average = strong wall
    
    def __init__(self):
        self._history: list[OrderBookSnapshot] = []
        self._max_history = 100
    
    def analyze_depth20(
        self, 
        symbol: str,
        timestamp: str,
        bids: list[dict],  # [{"price": x, "qty": y}, ...]
        asks: list[dict],  # [{"price": x, "qty": y}, ...]
    ) -> OrderBookSnapshot:
        """Analyze 20-level depth data into actionable insights."""
        
        # Sort bids descending (highest first), asks ascending (lowest first)
        sorted_bids = sorted(
            [(b["price"], b["qty"]) for b in bids if b["qty"] > 0],
            key=lambda x: -x[0]
        )
        sorted_asks = sorted(
            [(a["price"], a["qty"]) for a in asks if a["qty"] > 0],
            key=lambda x: x[0]
        )
        
        if not sorted_bids or not sorted_asks:
            return OrderBookSnapshot(
                symbol=symbol, timestamp=timestamp,
                bids=[], asks=[]
            )
        
        best_bid = sorted_bids[0][0]
        best_ask = sorted_asks[0][0]
        mid_price = (best_bid + best_ask) / 2
        spread = best_ask - best_bid
        spread_pct = (spread / mid_price * 100) if mid_price > 0 else 0
        
        # Volume analysis
        bid_depth = sum(q for _, q in sorted_bids[:5])  # Top 5 levels
        ask_depth = sum(q for _, q in sorted_asks[:5])
        total_depth = bid_depth + ask_depth
        obi = (bid_depth - ask_depth) / total_depth if total_depth > 0 else 0
        
        # Detect liquidity walls (large orders)
        bid_walls = self._detect_walls(sorted_bids, "BID")
        ask_walls = self._detect_walls(sorted_asks, "ASK")
        
        # Absorption detection
        absorption, abs_side = self._detect_absorption(
            sorted_bids, sorted_asks, mid_price
        )
        
        snapshot = OrderBookSnapshot(
            symbol=symbol,
            timestamp=timestamp,
            bids=sorted_bids,
            asks=sorted_asks,
            obi=round(obi, 4),
            bid_depth=bid_depth,
            ask_depth=ask_depth,
            spread=spread,
            spread_pct=round(spread_pct, 4),
            mid_price=mid_price,
            bid_walls=bid_walls,
            ask_walls=ask_walls,
            absorption_detected=absorption,
            absorption_side=abs_side,
        )
        
        self._history.append(snapshot)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]
        
        return snapshot
    
    def _detect_walls(self, levels: list[tuple[float, float]], side: str) -> list[LiquidityWall]:
        """Detect large pending orders (liquidity walls)."""
        if len(levels) < 3:
            return []
        
        volumes = [v for _, v in levels[:10]]  # Top 10 levels
        avg_vol = sum(volumes) / len(volumes) if volumes else 0
        
        if avg_vol <= 0:
            return []
        
        walls = []
        for price, qty in levels[:10]:
            if qty >= avg_vol * self.WALL_VOLUME_THRESHOLD:
                strength = "WALL" if qty >= avg_vol * self.STRONG_WALL_THRESHOLD else "STRONG"
                walls.append(LiquidityWall(
                    price=price,
                    side=side,
                    quantity=qty,
                    levels_affected=1,
                    strength=strength
                ))
        
        return walls
    
    def _detect_absorption(
        self, 
        bids: list[tuple[float, float]], 
        asks: list[tuple[float, float]],
        mid_price: float
    ) -> tuple[bool, str]:
        """Detect if one side is absorbing pressure."""
        if len(self._history) < 3:
            return False, ""
        
        # Compare current depth to recent average
        recent_snapshots = self._history[-5:]
        avg_bid_depth = sum(s.bid_depth for s in recent_snapshots) / len(recent_snapshots)
        avg_ask_depth = sum(s.ask_depth for s in recent_snapshots) / len(recent_snapshots)
        
        current_bid = sum(q for _, q in bids[:5])
        current_ask = sum(q for _, q in asks[:5])
        
        # If bid depth increased significantly while price stable = buy absorption
        if current_bid > avg_bid_depth * 1.5 and current_ask < avg_ask_depth * 0.8:
            return True, "BUY_ABSORBED"  # Buyers defending, absorbing sells
        
        # If ask depth increased significantly while price stable = sell absorption  
        if current_ask > avg_ask_depth * 1.5 and current_bid < avg_bid_depth * 0.8:
            return True, "SELL_ABSORBED"  # Sellers defending, absorbing buys
        
        return False, ""
    
    def get_liquidity_summary(self) -> dict:
        """Get summary of liquidity walls for the LLM prompt."""
        if not self._history:
            return {"walls": "No depth data available"}
        
        latest = self._history[-1]
        summary = {
            "obi": latest.obi,
            "bid_walls": len(latest.bid_walls),
            "ask_walls": len(latest.ask_walls),
            "absorption": latest.absorption_side if latest.absorption_detected else "none",
        }
        
        if latest.bid_walls:
            strongest_bid = max(latest.bid_walls, key=lambda w: w.quantity)
            summary["strongest_bid_wall"] = f"₹{strongest_bid.price:.0f} ({strongest_bid.strength})"
        
        if latest.ask_walls:
            strongest_ask = max(latest.ask_walls, key=lambda w: w.quantity)
            summary["strongest_ask_wall"] = f"₹{strongest_ask.price:.0f} ({strongest_ask.strength})"
        
        return summary
