"""Order Flow Detectors — Big trades, absorption, OFI, volume bubbles, footprint.

Each detector is independently testable.
"""

from __future__ import annotations

from dataclasses import dataclass
from appv2.config import constants as C


@dataclass
class BigTrade:
    detected: bool
    volume_ratio: float  # tick_volume / avg_volume


@dataclass
class Absorption:
    detected: bool
    side: str  # "BUY" or "SELL"
    range_ratio: float  # candle_range / atr
    vol_ratio: float  # candle_volume / avg_volume


@dataclass
class OFIResult:
    ofi: float  # Order Flow Imbalance (-1 to 1)


class BigTradeDetector:
    """Detects abnormally large trades."""

    def detect(self, candle, avg_volume: float) -> BigTrade | None:
        if avg_volume <= 0 or candle.volume <= 0:
            return None
        ratio = candle.volume / avg_volume
        if ratio >= 2.0:
            return BigTrade(detected=True, volume_ratio=ratio)
        return BigTrade(detected=False, volume_ratio=ratio)


class AbsorptionDetector:
    """Detects absorption: large range + large volume + small body.

    Indicates one side absorbing the other's orders without price moving.
    """

    def detect(self, candle, atr: float, avg_volume: float) -> Absorption:
        if atr <= 0 or avg_volume <= 0:
            return Absorption(detected=False, side="", range_ratio=0, vol_ratio=0)

        range_ratio = candle.range / atr
        vol_ratio = candle.volume / avg_volume
        body_to_range = candle.body / candle.range if candle.range > 0 else 1.0

        # Absorption: large range + large volume but small body
        detected = range_ratio > 1.5 and vol_ratio > 1.5 and body_to_range < 0.3

        side = ""
        if detected:
            # If candle closed near low → absorption of selling (buyers absorbing)
            if candle.close < (candle.high + candle.low) / 2:
                side = "BUY"
            else:
                side = "SELL"

        return Absorption(
            detected=detected,
            side=side,
            range_ratio=range_ratio,
            vol_ratio=vol_ratio,
        )


class OFICalculator:
    """Order Flow Imbalance calculator.

    OFI = (bid_volume - ask_volume) / (bid_volume + ask_volume)
    """

    def __init__(self):
        self._cum_ofi: float = 0.0

    def update(self, candle) -> OFIResult:
        """Approximate OFI from candle delta.

        For NSE (no order book delta): OFI ≈ delta / volume
        """
        if candle.volume <= 0:
            return OFIResult(ofi=0.0)

        ofi = candle.delta / candle.volume
        self._cum_ofi += ofi

        return OFIResult(ofi=ofi)

    @property
    def cumulative(self) -> float:
        return self._cum_ofi

    def reset(self) -> None:
        self._cum_ofi = 0.0


class BubbleDetector:
    """Detects volume bubbles near key levels."""

    def detect(self, candle, avg_volume: float = 0.0, threshold_mult: float = 1.5) -> dict:
        if avg_volume <= 0:
            return {"detected": False, "ratio": 0.0}

        ratio = candle.volume / avg_volume
        return {
            "detected": ratio >= threshold_mult,
            "ratio": ratio,
        }
