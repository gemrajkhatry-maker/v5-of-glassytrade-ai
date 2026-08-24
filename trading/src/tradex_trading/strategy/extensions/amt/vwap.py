"""Volume-weighted VWAP and standard-deviation bands."""

from __future__ import annotations

from decimal import Decimal


class VWAPAccumulator:
    def __init__(self) -> None:
        self.volume = Decimal("0")
        self.value_volume = Decimal("0")
        self.squared_deviation = Decimal("0")
        self.last_price = Decimal("0")

    def update(self, price: Decimal, volume: Decimal) -> tuple[Decimal, Decimal]:
        if volume < 0:
            raise ValueError("volume cannot be negative")
        if volume == 0:
            self.last_price = price
            return self.value, self.std
        previous = self.value if self.volume else price
        self.volume += volume
        self.value_volume += price * volume
        self.last_price = price
        value = self.value
        self.squared_deviation += volume * (price - previous) * (price - value)
        return value, self.std

    @property
    def value(self) -> Decimal:
        return self.value_volume / self.volume if self.volume else self.last_price

    @property
    def std(self) -> Decimal:
        if not self.volume:
            return Decimal("0")
        variance = self.squared_deviation / self.volume
        return variance.sqrt() if variance > 0 else Decimal("0")
