from dataclasses import dataclass

from quant.bars import Bar
from quant.volume_profile import VolumeProfile


@dataclass(frozen=True)
class LocationState:
    ib_high: float
    ib_low: float
    ib_complete: bool
    zone: str           # "ABOVE_VA" | "BELOW_VA" | "INSIDE_VA" | "UNKNOWN"
    nearest_level: float   # nearest of {vah, val, poc} to last close
    distance_to_level: float


class LocationBuilder:
    def __init__(self, ib_bars: int = 6) -> None:
        self._ib_bars = ib_bars
        self._count = 0
        self._ib_high = float("-inf")
        self._ib_low = float("inf")

    def update(self, bar: Bar) -> None:
        if self._count < self._ib_bars:
            self._ib_high = max(self._ib_high, bar.high)
            self._ib_low = min(self._ib_low, bar.low)
        self._count += 1

    def snapshot(self, vp: VolumeProfile | None, last_close: float) -> LocationState:
        if vp is None:
            zone = "UNKNOWN"
            nearest = 0.0
            distance = 0.0
        else:
            if last_close > vp.vah:
                zone = "ABOVE_VA"
            elif last_close < vp.val:
                zone = "BELOW_VA"
            else:
                zone = "INSIDE_VA"
            levels = {"vah": vp.vah, "val": vp.val, "poc": vp.poc}
            nearest_key = min(levels, key=lambda k: abs(last_close - levels[k]))
            nearest = levels[nearest_key]
            distance = abs(last_close - nearest)
        return LocationState(
            ib_high=self._ib_high,
            ib_low=self._ib_low,
            ib_complete=self._count >= self._ib_bars,
            zone=zone,
            nearest_level=nearest,
            distance_to_level=distance,
        )
