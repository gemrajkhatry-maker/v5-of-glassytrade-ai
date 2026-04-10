"""Scale Manager — 40/30/30 scale-in management.

Splits a full position into 3 entries:
  Scale 1: 40% of position (initial entry)
  Scale 2: 30% of position (add on pullback)
  Scale 3: 30% of position (add on continuation)

Each scale has independent SL/TP.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ScalePhase(Enum):
    INITIAL = 1  # 40% entry
    ADD_ON = 2   # 30% add-on
    FINAL = 3    # 30% final add-on


@dataclass(frozen=True)
class ScaleLevel:
    phase: ScalePhase
    size_pct: float  # % of full position
    filled: bool
    fill_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    quantity: int = 0  # Actual lot count


class ScaleManager:
    """Manages 3-scale position building (40/30/30)."""

    SCALE_SIZES = [0.40, 0.30, 0.30]

    def __init__(self):
        self._scales: list[ScaleLevel] = []
        self._total_filled_pct: float = 0.0
        self._avg_entry_price: float = 0.0

    def initialize(
        self,
        direction: str,  # "LONG" or "SHORT"
        full_quantity: int,
        entry_price: float,
        base_sl: float,
        base_tp: float,
    ) -> list[ScaleLevel]:
        """Initialize scale levels.

        Args:
            direction: Trade direction
            full_quantity: Total lots for full position
            entry_price: Initial entry price
            base_sl: Base stop-loss for Scale 1
            base_tp: Base take-profit
        """
        self._scales = []
        self._total_filled_pct = 0.0
        self._avg_entry_price = 0.0

        for i, size_pct in enumerate(self.SCALE_SIZES):
            qty = int(full_quantity * size_pct)
            if i == 0:
                # Scale 1: initial entry at base levels
                sl = base_sl
                tp = base_tp
            else:
                # Scale 2/3: same SL/TP initially, adjusted on fill
                sl = base_sl
                tp = base_tp

            self._scales.append(ScaleLevel(
                phase=ScalePhase(i + 1),
                size_pct=size_pct,
                filled=(i == 0),  # Scale 1 filled immediately
                fill_price=entry_price if i == 0 else 0.0,
                stop_loss=sl,
                take_profit=tp,
                quantity=qty,
            ))

        self._total_filled_pct = self.SCALE_SIZES[0]
        self._avg_entry_price = entry_price
        return self._scales

    def can_add_scale(self) -> bool:
        """Check if next scale can be added."""
        for scale in self._scales:
            if not scale.filled:
                return True
        return False

    def get_next_unfilled(self) -> ScaleLevel | None:
        """Get the next unfilled scale level."""
        for scale in self._scales:
            if not scale.filled:
                return scale
        return None

    def fill_scale(
        self,
        price: float,
        sl_adjustment: float = 0.0,
    ) -> ScaleLevel | None:
        """Fill the next available scale level.

        Args:
            price: Fill price
            sl_adjustment: SL adjustment for new scale (tighten SL)

        Returns:
            Filled ScaleLevel or None if no more scales.
        """
        scale = self.get_next_unfilled()
        if scale is None:
            return None

        # Update average entry
        total_qty = sum(s.quantity for s in self._scales if s.filled)
        new_qty = scale.quantity
        if total_qty > 0:
            self._avg_entry_price = (
                (self._avg_entry_price * total_qty + price * new_qty) /
                (total_qty + new_qty)
            )
        else:
            self._avg_entry_price = price

        # Fill the scale
        filled_scale = ScaleLevel(
            phase=scale.phase,
            size_pct=scale.size_pct,
            filled=True,
            fill_price=price,
            stop_loss=scale.stop_loss + sl_adjustment,
            take_profit=scale.take_profit,
            quantity=new_qty,
        )

        idx = self._scales.index(scale)
        self._scales[idx] = filled_scale
        self._total_filled_pct += scale.size_pct

        return filled_scale

    def get_avg_entry(self) -> float:
        return self._avg_entry_price

    def get_total_filled_pct(self) -> float:
        return self._total_filled_pct

    def is_full(self) -> bool:
        return self._total_filled_pct >= 0.99

    def get_scales(self) -> list[ScaleLevel]:
        return list(self._scales)

    def reset(self) -> None:
        self._scales.clear()
        self._total_filled_pct = 0.0
        self._avg_entry_price = 0.0
