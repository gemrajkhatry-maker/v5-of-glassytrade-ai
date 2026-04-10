"""Pyramid Manager — structured position scaling for winning trades.

Fabio's pyramid rules:
- Max 2 add-ons per position
- Add only after price moves favorably by at least 1× ATR
- Move unified SL to breakeven after each add
- Each add is 50% of previous position size
- Never add at LVN zones
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from appv2.config import constants as C

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PyramidResult:
    can_add: bool
    add_size: int  # Lots to add
    new_stop_loss: float  # Unified SL after add
    reason: str


class PyramidManager:
    """Manages pyramid position scaling."""

    def __init__(
        self,
        max_adds: int = 2,
        add_size_ratio: float = 0.5,  # 50% of previous
        min_profit_atr: float = 1.0,  # Min profit in ATR multiples before add
    ):
        self._max_adds = max_adds
        self._add_ratio = add_size_ratio
        self._min_profit_atr = min_profit_atr
        self._adds: list[dict] = []  # Track each add

    def can_pyramid(
        self,
        current_price: float,
        entry_price: float,
        current_sl: float,
        atr: float,
        is_long: bool,
        lots: int,
        lvn_levels: list[float] | None = None,
    ) -> PyramidResult:
        """Check if position can be pyramided.

        Args:
            current_price: Current market price
            entry_price: Original entry price
            current_sl: Current stop-loss
            atr: Current ATR
            is_long: Trade direction
            lots: Current position size
            lvn_levels: LVN levels to avoid adding at
        """
        # Check max adds
        if len(self._adds) >= self._max_adds:
            return PyramidResult(
                can_add=False, add_size=0, new_stop_loss=0,
                reason=f"Max pyramid adds reached ({self._max_adds})",
            )

        # Check minimum profit (1× ATR in favor)
        if is_long:
            profit = current_price - entry_price
            if profit < atr * self._min_profit_atr:
                return PyramidResult(
                    can_add=False, add_size=0, new_stop_loss=0,
                    reason=f"Insufficient profit ({profit:.2f} < {atr * self._min_profit_atr:.2f})",
                )
        else:
            profit = entry_price - current_price
            if profit < atr * self._min_profit_atr:
                return PyramidResult(
                    can_add=False, add_size=0, new_stop_loss=0,
                    reason=f"Insufficient profit ({profit:.2f} < {atr * self._min_profit_atr:.2f})",
                )

        # Check not adding at LVN
        if lvn_levels:
            for lvn in lvn_levels:
                if abs(current_price - lvn) < atr * 0.5:
                    return PyramidResult(
                        can_add=False, add_size=0, new_stop_loss=0,
                        reason=f"Current price near LVN ({lvn:.2f}) — avoid adding",
                    )

        # Calculate add size (50% of previous position)
        if len(self._adds) == 0:
            add_size = int(lots * self._add_ratio)
        else:
            add_size = int(self._adds[-1]["lots"] * self._add_ratio)

        if add_size <= 0:
            return PyramidResult(
                can_add=False, add_size=0, new_stop_loss=0,
                reason="Add size too small",
            )

        # New unified SL = current SL or trailing SL (move to breakeven)
        if is_long:
            new_sl = max(current_sl, entry_price)
        else:
            new_sl = min(current_sl, entry_price) if current_sl > 0 else entry_price

        return PyramidResult(
            can_add=True,
            add_size=add_size,
            new_stop_loss=round(new_sl, 4),
            reason=f"Pyramid add #{len(self._adds) + 1}: {add_size} lots, SL to {new_sl:.2f}",
        )

    def record_add(
        self,
        add_price: float,
        add_lots: int,
        new_sl: float,
    ) -> None:
        """Record a pyramid add."""
        self._adds.append({
            "price": add_price,
            "lots": add_lots,
            "new_sl": new_sl,
        })
        logger.info(
            "PYRAMID ADD #%d: %d lots @ %.4f, new SL: %.4f",
            len(self._adds), add_lots, add_price, new_sl,
        )

    @property
    def add_count(self) -> int:
        return len(self._adds)

    @property
    def total_added_lots(self) -> int:
        return sum(a["lots"] for a in self._adds)

    def reset(self) -> None:
        self._adds.clear()
