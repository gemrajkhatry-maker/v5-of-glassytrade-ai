"""LVN Play Engine — LVN retest detection + CVD confirmation per Fabio AMT spec.

LVN Play Logic:
1. Price pulls back toward a previously identified LVN
2. On retest: check CVD direction
   - CVD aligns with trade direction → entry signal
   - CVD opposes → wait for confirmation
3. LVN is "played" only once per session (no repeated entries at same LVN)

Signals:
  LVN_RETEST_APPROACHING: Price within 5 ticks of LVN (alert)
  LVN_RETEST_CONFIRMED: Price at LVN + CVD aligns (entry)
  LVN_RETEST_REJECTED: Price at LVN + CVD opposes (wait)
  LVN_PLAYED: LVN already used this session (skip)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.domain.trading.models.value_objects import VolumeProfileLevel
from app.domain.fabio_ai.services.lvn_quality_scorer import LVNQuality

logger = logging.getLogger(__name__)


@dataclass
class LVNPlay:
    """A detected LVN play opportunity."""

    lvn_price: float
    quality: float
    action: str  # "APPROACHING" | "CONFIRMED" | "REJECTED" | "PLAYED"
    cvd_direction: str  # "BULLISH" | "BEARISH" | "NEUTRAL"
    reason: str


class LVNPlayEngine:
    """Detects and manages LVN retest plays."""

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
        """Check if current price is at an LVN for a play.

        Args:
            price: Current market price.
            lvns: List of LVN price levels.
            lvn_qualities: Scored LVN quality list (from rank_lvns).
            cvd_slope: Current CVD slope.
            tick_size: Minimum price increment.
            direction: Intended trade direction.

        Returns:
            LVNPlay if an opportunity exists, None otherwise.
        """
        if not lvns:
            return None

        # Find nearest LVN
        nearest_lvn = min(lvns, key=lambda l: abs(price - l))
        distance = abs(price - nearest_lvn)
        distance_ticks = distance / tick_size if tick_size > 0 else 999

        # Already played this LVN?
        lvn_bucket = round(nearest_lvn, 1)
        if lvn_bucket in self._played_lvns:
            return None

        # Get quality
        quality = 0.5
        for q in lvn_qualities:
            if abs(q.price - nearest_lvn) <= tick_size:
                quality = q.quality
                break

        # CVD direction
        if cvd_slope > 0.5:
            cvd_dir = "BULLISH"
        elif cvd_slope < -0.5:
            cvd_dir = "BEARISH"
        else:
            cvd_dir = "NEUTRAL"

        # Check alignment
        cvd_aligns = (direction == "LONG" and cvd_dir == "BULLISH") or (
            direction == "SHORT" and cvd_dir == "BEARISH"
        )

        # Action based on distance
        if distance_ticks <= 3:
            if cvd_aligns:
                self._played_lvns.add(lvn_bucket)
                return LVNPlay(
                    lvn_price=nearest_lvn,
                    quality=quality,
                    action="CONFIRMED",
                    cvd_direction=cvd_dir,
                    reason=f"LVN at {nearest_lvn:.2f}, CVD {cvd_dir}, entry confirmed",
                )
            else:
                return LVNPlay(
                    lvn_price=nearest_lvn,
                    quality=quality,
                    action="REJECTED",
                    cvd_direction=cvd_dir,
                    reason=f"LVN at {nearest_lvn:.2f}, CVD {cvd_dir} opposes, wait",
                )
        elif distance_ticks <= 5:
            return LVNPlay(
                lvn_price=nearest_lvn,
                quality=quality,
                action="APPROACHING",
                cvd_direction=cvd_dir,
                reason=f"Approaching LVN at {nearest_lvn:.2f} ({distance_ticks:.0f} ticks away)",
            )

        return None

    def reset_session(self) -> None:
        """Reset played LVNs at session open."""
        self._played_lvns.clear()
        logger.debug("LVN play engine reset (new session)")
