"""Layer 2 Compression Box Profile (spec §6.2).

Detects multi-bar consolidation boxes and builds isolated micro-profiles to locate
box micro-POC and micro-LVNs. Sits between Layer 1 (Session Profile) and Layer 3
(Impulse Leg Profile) in the 3-Layer volume profile architecture.
"""

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from quant.bars import Bar
from quant.amt.profile.volume_profile import (
    VolumeProfileSnapshot,
    build_snapshot,
    create_profile,
)


@dataclass(frozen=True)
class CompressionBox:
    start_time: str
    end_time: str
    bar_count: int
    high: float
    low: float
    range_span: float
    micro_profile: VolumeProfileSnapshot
    micro_poc: float
    micro_vah: float
    micro_val: float
    breakout_state: str  # "INSIDE" | "EXPANDING_UP" | "EXPANDING_DOWN"


class CompressionBoxDetector:
    """Detects multi-bar consolidation boxes and computes micro-profiles."""

    def __init__(
        self,
        min_bars: int = 5,
        max_box_range_ticks: int = 20,
        tick_size: float = 0.05,
    ) -> None:
        self.min_bars = min_bars
        self.max_box_range = max_box_range_ticks * tick_size
        self.tick_size = tick_size
        self._bars: list[Bar] = []
        self._current_box: Optional[CompressionBox] = None

    @property
    def current_box(self) -> Optional[CompressionBox]:
        return self._current_box

    def update(self, bar: Bar) -> Optional[CompressionBox]:
        self._bars.append(bar)
        if len(self._bars) > 50:
            self._bars.pop(0)

        if len(self._bars) < self.min_bars:
            return None

        # Check candidate window of last N bars
        for n in range(min(len(self._bars), 30), self.min_bars - 1, -1):
            window = self._bars[-n:]
            box_high = max(float(b.high) for b in window)
            box_low = min(float(b.low) for b in window)
            box_range = box_high - box_low

            if box_range <= self.max_box_range:
                # Valid compression box detected: build micro-profile
                prof = create_profile(window, tick_size=self.tick_size)
                micro_vp = build_snapshot(prof)

                last_close = float(bar.close)
                prior_high = self._current_box.high if self._current_box else box_high
                prior_low = self._current_box.low if self._current_box else box_low

                if last_close > prior_high:
                    breakout = "EXPANDING_UP"
                elif last_close < prior_low:
                    breakout = "EXPANDING_DOWN"
                else:
                    breakout = "INSIDE"

                self._current_box = CompressionBox(
                    start_time=window[0].time,
                    end_time=window[-1].time,
                    bar_count=n,
                    high=box_high,
                    low=box_low,
                    range_span=box_range,
                    micro_profile=micro_vp,
                    micro_poc=micro_vp.poc,
                    micro_vah=micro_vp.vah,
                    micro_val=micro_vp.val,
                    breakout_state=breakout,
                )
                return self._current_box

        return None
