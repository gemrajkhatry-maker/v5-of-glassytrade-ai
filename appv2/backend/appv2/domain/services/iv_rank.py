"""IV Rank Tracker — tracks implied volatility rank and percentile.

IV Rank = (Current IV - 52-week Low IV) / (52-week High IV - 52-week Low IV)
IV Percentile = % of days in past year where IV was below current IV

Used for:
- Entry timing (low IV rank = favorable for buying options)
- IV crush detection (post-event IV drop)
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


@dataclass(frozen=True)
class IVState:
    current_iv: float
    iv_rank: float  # 0-100
    iv_percentile: float  # 0-100
    iv_high_52w: float
    iv_low_52w: float
    is_iv_crush: bool  # IV dropped significantly


class IVRankTracker:
    """Tracks IV rank and percentile over a rolling window."""

    def __init__(self, window_days: int = 30):
        self._window = window_days
        self._iv_history: deque[float] = deque(maxlen=window_days)
        self._current_iv: float = 0.0
        self._prev_iv: float = 0.0
        self._iv_crush_threshold: float = 0.15  # 15% IV drop = crush

    def update(self, iv: float) -> IVState:
        """Update with current IV value.

        Args:
            iv: Current implied volatility (e.g., 0.20 for 20%)
        """
        if iv > 0:
            self._prev_iv = self._current_iv
            self._current_iv = iv
            self._iv_history.append(iv)

        return self._compute_state()

    def _compute_state(self) -> IVState:
        history = list(self._iv_history)

        if not history:
            return IVState(
                current_iv=self._current_iv,
                iv_rank=0, iv_percentile=0,
                iv_high_52w=0, iv_low_52w=0,
                is_iv_crush=False,
            )

        iv_high = max(history)
        iv_low = min(history)
        iv_range = iv_high - iv_low

        # IV Rank
        iv_rank = 0.0
        if iv_range > 0:
            iv_rank = ((self._current_iv - iv_low) / iv_range) * 100

        # IV Percentile: % of history below current
        below_count = sum(1 for v in history if v < self._current_iv)
        iv_percentile = (below_count / len(history)) * 100 if history else 0

        # IV Crush detection
        is_crush = False
        if self._prev_iv > 0 and self._current_iv > 0:
            iv_change = (self._prev_iv - self._current_iv) / self._prev_iv
            if iv_change >= self._iv_crush_threshold:
                is_crush = True

        return IVState(
            current_iv=self._current_iv,
            iv_rank=max(0, min(100, iv_rank)),
            iv_percentile=max(0, min(100, iv_percentile)),
            iv_high_52w=iv_high,
            iv_low_52w=iv_low,
            is_iv_crush=is_crush,
        )

    def reset(self) -> None:
        self._iv_history.clear()
        self._current_iv = 0.0
        self._prev_iv = 0.0
