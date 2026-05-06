"""LVN play detection service and one-shot tracking."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from app.domain.services.tick_utils import round_to_tick


logger = logging.getLogger(__name__)


@dataclass
class LVNQuality:
    """Quality scoring for a specific LVN candidate."""

    price: float
    quality: float
    thinness: float = 0.0
    proximity: float = 0.0
    volume: float = 0.0


@dataclass
class LVNPlay:
    """LVN play candidate / state."""

    lvn_price: float
    quality: float
    action: str
    cvd_direction: str
    reason: str


class LVNPlayEngine:
    """Detect and de-duplicate LVN play opportunities."""

    def __init__(self) -> None:
        self._played_lvns: set[float] = set()

    def check_lvn_play(
        self,
        price: float,
        lvns: list[float],
        lvn_qualities: list[LVNQuality],
        cvd_slope: float,
        tick_size: float,
        direction: str = "LONG",
    ) -> LVNPlay | None:
        if not lvns:
            return None

        nearest_lvn = min(lvns, key=lambda l: abs(price - l))
        distance = abs(price - nearest_lvn)
        distance_ticks = distance / tick_size if tick_size > 0 else 999

        bucket = round_to_tick(nearest_lvn, tick_size)
        if bucket in self._played_lvns:
            return None

        quality = 0.5
        for q in lvn_qualities:
            if abs(float(q.price) - nearest_lvn) <= tick_size:
                quality = float(q.quality)
                break

        if cvd_slope > 0.5:
            cvd_dir = "BULLISH"
        elif cvd_slope < -0.5:
            cvd_dir = "BEARISH"
        else:
            cvd_dir = "NEUTRAL"

        cvd_aligns = (direction == "LONG" and cvd_dir == "BULLISH") or (
            direction == "SHORT" and cvd_dir == "BEARISH"
        )

        if distance_ticks <= 3:
            if cvd_aligns:
                self._played_lvns.add(bucket)
                return LVNPlay(
                    lvn_price=float(nearest_lvn),
                    quality=float(quality),
                    action="CONFIRMED",
                    cvd_direction=cvd_dir,
                    reason=f"LVN at {nearest_lvn:.2f}, CVD {cvd_dir}, entry confirmed",
                )
            return LVNPlay(
                lvn_price=float(nearest_lvn),
                quality=float(quality),
                action="REJECTED",
                cvd_direction=cvd_dir,
                reason=f"LVN at {nearest_lvn:.2f}, CVD {cvd_dir} opposes, wait",
            )

        if distance_ticks <= 5:
            return LVNPlay(
                lvn_price=float(nearest_lvn),
                quality=float(quality),
                action="APPROACHING",
                cvd_direction=cvd_dir,
                reason=f"Approaching LVN at {nearest_lvn:.2f} ({distance_ticks:.0f} ticks away)",
            )

        return None

    def reset_session(self) -> None:
        """Clear one-shot LVN play history."""
        self._played_lvns.clear()
        logger.debug("LVN play engine reset (new session)")

