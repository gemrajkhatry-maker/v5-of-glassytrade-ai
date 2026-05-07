"""Footprint Aggregator."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

from brokersv2.analytics.delta.events import (
    FootprintCandle,
    FootprintLevel,
    TradeSide,
)


class FootprintAggregator:
    """
    Aggregate trades into footprint charts.
    
    Features:
    - Volume at each price level
    - Bid/ask volume separation
    - Delta per price level
    - Point of Control (POC)
    - Imbalance ratios
    """

    def __init__(self, symbol: str):
        self.symbol = symbol
        self._price_levels: Dict[float, Dict] = {}

    def add_trade(self, price: float, quantity: float, side: TradeSide) -> None:
        """Add trade to footprint."""
        if price not in self._price_levels:
            self._price_levels[price] = {
                "bid_volume": 0.0,
                "ask_volume": 0.0,
            }
        
        level = self._price_levels[price]
        if side == TradeSide.BUY:
            level["ask_volume"] += quantity  # Buy hits ask
        else:
            level["bid_volume"] += quantity  # Sell hits bid

    def get_volume_at_price(self, price: float) -> float:
        """Get total volume at price level."""
        if price not in self._price_levels:
            return 0.0
        level = self._price_levels[price]
        return level["bid_volume"] + level["ask_volume"]

    def get_delta_at_price(self, price: float) -> float:
        """Get delta at price level (ask - bid)."""
        if price not in self._price_levels:
            return 0.0
        level = self._price_levels[price]
        return level["ask_volume"] - level["bid_volume"]

    def get_imbalance_ratio(self, price: float) -> float:
        """Get imbalance ratio at price level."""
        if price not in self._price_levels:
            return 0.0
        level = self._price_levels[price]
        bid = level["bid_volume"]
        ask = level["ask_volume"]
        total = bid + ask
        if total == 0:
            return 0.0
        return (ask - bid) / total

    def get_point_of_control(self) -> Optional[float]:
        """Get price level with highest volume (POC)."""
        if not self._price_levels:
            return None
        
        max_volume = 0.0
        poc_price = None
        
        for price, level in self._price_levels.items():
            volume = level["bid_volume"] + level["ask_volume"]
            if volume > max_volume:
                max_volume = volume
                poc_price = price
        
        return poc_price

    def build_candle(self, timestamp: Optional[datetime] = None) -> FootprintCandle:
        """Build footprint candle from aggregated data."""
        if timestamp is None:
            timestamp = datetime.now(timezone.utc)
        
        levels = []
        total_volume = 0.0
        total_delta = 0.0
        poc_price = self.get_point_of_control() or 0.0
        
        for price, level_data in sorted(self._price_levels.items()):
            bid_vol = level_data["bid_volume"]
            ask_vol = level_data["ask_volume"]
            delta = ask_vol - bid_vol
            
            footprint_level = FootprintLevel(
                price=price,
                bid_volume=bid_vol,
                ask_volume=ask_vol,
                delta=delta,
            )
            levels.append(footprint_level)
            
            total_volume += bid_vol + ask_vol
            total_delta += delta
        
        return FootprintCandle(
            timestamp=timestamp,
            levels=levels,
            total_volume=total_volume,
            total_delta=total_delta,
            poc_price=poc_price,
        )

    def reset(self) -> None:
        """Reset aggregator."""
        self._price_levels.clear()
