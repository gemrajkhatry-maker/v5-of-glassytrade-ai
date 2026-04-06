"""Drive Decay — Time/Price rotation enforcement per Fabio AMT spec.

Between Drive 1 and Drive 2, require that price has either rotated away
by at least 3-4 ticks OR that at least 3 minutes have passed.

Usage:
    decay = DriveDecay(min_ticks=3, min_minutes=3)
    decay.record_drive_1(level, direction, timestamp)
    result = decay.validate_drive_2(current_price, current_time)
    if result.valid:
        # Drive 2 is valid — time/price decay satisfied
        return DriveResult(drive_number=2, entry_valid=True)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger(__name__)

from app.shared.timezones import IST


@dataclass
class DriveDecayResult:
    """Result of drive decay validation."""

    valid: bool
    time_decay_met: bool
    price_decay_met: bool
    reason: str


class DriveDecay:
    """Time/price rotation enforcement between Drive 1 and Drive 2.

    Per Fabio: "A 1-tick pullback inside a 1-minute candle should not
    count as a Drive 2 retest. Require significant price rotation or time decay."

    Rules:
    - Between Drive 1 and Drive 2, require:
      1. Price rotated away by ≥ 3-4 ticks (configurable)
      2. OR at least 3 minutes have passed since Drive 1
    - Prevents false Drive 2 signals from micro-pullbacks
    """

    def __init__(self, min_ticks: int = 3, min_minutes: int = 3):
        """
        Args:
            min_ticks: Minimum price rotation away from level (default 3 ticks).
            min_minutes: Minimum time between drives (default 3 minutes).
        """
        self._min_ticks = min_ticks
        self._min_minutes = min_minutes
        self._drive_1_records: dict[float, dict] = {}  # level -> drive 1 info

    def record_drive_1(
        self,
        level: float,
        direction: str,
        timestamp: datetime,
        tick_size: float,
    ) -> None:
        """Record Drive 1 touch for decay validation.

        Args:
            level: The key level being tested.
            direction: "LONG" or "SHORT".
            timestamp: Time of Drive 1.
            tick_size: Instrument tick size.
        """
        from app.domain.services.tick_utils import round_to_tick

        bucket = round_to_tick(level, tick_size)
        self._drive_1_records[bucket] = {
            "level": level,
            "direction": direction,
            "timestamp": timestamp,
            "tick_size": tick_size,
            "max_rotation": 0.0,
        }

    def update_rotation(self, current_price: float) -> None:
        """Update maximum price rotation away from Drive 1 level.

        Args:
            current_price: Current market price.
        """
        for bucket, record in self._drive_1_records.items():
            rotation = abs(current_price - record["level"])
            if rotation > record["max_rotation"]:
                record["max_rotation"] = rotation

    def validate_drive_2(
        self,
        level: float,
        current_price: float,
        current_time: datetime,
    ) -> DriveDecayResult:
        """Validate that Drive 2 meets time/price decay requirements.

        Args:
            level: The key level being tested for Drive 2.
            current_price: Current market price.
            current_time: Current time.

        Returns:
            DriveDecayResult with validity and details.
        """
        from app.domain.services.tick_utils import round_to_tick

        bucket = round_to_tick(level, tick_size)
        record = self._drive_1_records.get(bucket)

        if record is None:
            return DriveDecayResult(
                valid=False,
                time_decay_met=False,
                price_decay_met=False,
                reason="No Drive 1 recorded for this level",
            )

        # Time decay: check if enough time has passed since Drive 1
        time_since_drive1 = (current_time - record["timestamp"]).total_seconds()
        time_decay_met = time_since_drive1 >= (self._min_minutes * 60)

        # Price decay: check if price rotated away enough
        # Use max rotation seen since Drive 1
        min_rotation = self._min_ticks * record["tick_size"]
        price_decay_met = record["max_rotation"] >= min_rotation

        # Drive 2 is valid if EITHER time OR price decay is met
        valid = time_decay_met or price_decay_met

        if valid:
            reasons = []
            if time_decay_met:
                reasons.append(
                    f"time: {time_since_drive1 / 60:.1f}min >= {self._min_minutes}min"
                )
            if price_decay_met:
                reasons.append(
                    f"price rotation: {record['max_rotation']:.1f} >= {min_rotation:.1f}"
                )
            reason = f"Drive 2 valid: {', '.join(reasons)}"
        else:
            remaining_time = (self._min_minutes * 60) - time_since_drive1
            reason = (
                f"Drive 2 blocked: time {time_since_drive1 / 60:.1f}min < {self._min_minutes}min, "
                f"rotation {record['max_rotation']:.1f} < {min_rotation:.1f} ticks"
            )

        logger.info(
            "Drive decay: level=%.2f time_decay=%s price_decay=%s valid=%s",
            level,
            time_decay_met,
            price_decay_met,
            valid,
        )

        return DriveDecayResult(
            valid=valid,
            time_decay_met=time_decay_met,
            price_decay_met=price_decay_met,
            reason=reason,
        )

    def clear_level(self, level: float) -> None:
        """Clear Drive 1 record for a level (e.g., on session reset)."""
        from app.domain.services.tick_utils import round_to_tick

        bucket = round_to_tick(level, tick_size)
        self._drive_1_records.pop(bucket, None)

    def reset(self) -> None:
        """Reset all drive decay records for new session."""
        self._drive_1_records.clear()
