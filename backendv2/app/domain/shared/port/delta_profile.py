"""Port definitions for delta-profile services."""

from __future__ import annotations

from abc import ABC, abstractmethod


class DeltaBucket:
    """Compatibility tuple-like delta bucket payload."""

    def __init__(self, price: float, buy_delta: int, sell_delta: int, net_delta: int, total_volume: int):
        self.price = price
        self.buy_delta = buy_delta
        self.sell_delta = sell_delta
        self.net_delta = net_delta
        self.total_volume = total_volume


class DeltaProfile(dict):
    """Compatibility type alias used by higher layers."""


class IDeltaProfile(ABC):
    """Delta-profile abstraction expected by AMT/analysis components."""

    @abstractmethod
    def update(self, price: float, ask_vol: int, bid_vol: int) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_profile(self) -> list[DeltaBucket]:
        raise NotImplementedError

    @abstractmethod
    def get_high_delta_zones(self, direction: str, sigma_mult: float = 2.5) -> list[float]:
        raise NotImplementedError

    @abstractmethod
    def get_delta_at_price(self, price: float) -> tuple[int, int, int]:
        raise NotImplementedError

    @abstractmethod
    def reset(self) -> None:
        raise NotImplementedError

    @property
    @abstractmethod
    def bucket_size(self) -> float:
        raise NotImplementedError

    @property
    @abstractmethod
    def bucket_count(self) -> int:
        raise NotImplementedError

    @property
    @abstractmethod
    def total_volume(self) -> int:
        raise NotImplementedError
