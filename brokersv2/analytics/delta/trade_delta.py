"""Trade Delta Calculator."""

from __future__ import annotations

from typing import List, Optional

from brokersv2.analytics.delta.events import TradeEvent


class TradeDeltaCalculator:
    """
    Calculate trade-level delta metrics.
    
    Tracks:
    - Total delta (buy volume - sell volume)
    - Buy/sell volume separation
    - Trade counting
    - Delta percentages
    """

    def __init__(self, symbol: str):
        self.symbol = symbol
        self._trades: List[TradeEvent] = []
        self._total_delta = 0.0
        self._buy_volume = 0.0
        self._sell_volume = 0.0

    @property
    def total_delta(self) -> float:
        """Total delta (buy volume - sell volume)."""
        return self._total_delta

    @property
    def buy_volume(self) -> float:
        """Total buy volume."""
        return self._buy_volume

    @property
    def sell_volume(self) -> float:
        """Total sell volume."""
        return self._sell_volume

    @property
    def trade_count(self) -> int:
        """Total number of trades."""
        return len(self._trades)

    @property
    def delta_per_trade(self) -> float:
        """Average delta per trade."""
        if self.trade_count == 0:
            return 0.0
        return self.total_delta / self.trade_count

    @property
    def buy_sell_ratio(self) -> Optional[float]:
        """Buy volume / Sell volume ratio."""
        if self.sell_volume == 0:
            return None
        return self.buy_volume / self.sell_volume

    @property
    def delta_percentage(self) -> float:
        """Delta as percentage of total volume."""
        total_volume = self.buy_volume + self.sell_volume
        if total_volume == 0:
            return 0.0
        return (self.total_delta / total_volume) * 100.0

    @property
    def trade_history(self) -> List[TradeEvent]:
        """Trade history."""
        return self._trades

    def process_trade(self, trade: TradeEvent) -> None:
        """
        Process a single trade.
        
        Updates delta, buy/sell volume, and trade history.
        """
        self._trades.append(trade)
        
        if trade.side.value == "buy":
            self._buy_volume += trade.quantity
            self._total_delta += trade.quantity
        elif trade.side.value == "sell":
            self._sell_volume += trade.quantity
            self._total_delta -= trade.quantity

    def reset(self) -> None:
        """Reset all counters."""
        self._trades.clear()
        self._total_delta = 0.0
        self._buy_volume = 0.0
        self._sell_volume = 0.0
