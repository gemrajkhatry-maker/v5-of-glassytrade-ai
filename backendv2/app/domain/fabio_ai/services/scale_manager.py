"""Scale-in manager for structured position addition."""
from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from app.domain.trading.model.enums import Side

if TYPE_CHECKING:
    from app.domain.trading.model.entities import Position


class ScaleManager:
    SCALE_STEP_2_FRACTION = 0.30
    SCALE_STEP_3_FRACTION = 0.30

    def check_scale_in(self, position: "Position", current_price: float) -> float:
        if getattr(position, "scale_step", 1) >= 3:
            return 0.0

        is_long = str(getattr(position, "side", "")).upper() == Side.LONG.value
        entry_price = float(getattr(position, "entry_price", 0.0))
        initial_stop = float(getattr(position, "initial_stop", 0.0))
        risk = abs(entry_price - initial_stop)
        if risk > 0:
            if is_long and current_price < entry_price:
                return 0.0
            if (not is_long) and current_price > entry_price:
                return 0.0

        confirm_price = float(getattr(position, "scale_confirm_price", 0.0))
        breakout_price = float(getattr(position, "scale_breakout_price", 0.0))
        scale_step = int(getattr(position, "scale_step", 1))

        if scale_step == 1 and confirm_price > 0 and ((is_long and current_price >= confirm_price) or ((not is_long) and current_price <= confirm_price)):
            setattr(position, "scale_step", 2)
            return self.SCALE_STEP_2_FRACTION
        if scale_step == 2 and breakout_price > 0 and ((is_long and current_price >= breakout_price) or ((not is_long) and current_price <= breakout_price)):
            setattr(position, "scale_step", 3)
            return self.SCALE_STEP_3_FRACTION
        return 0.0

    def get_scale_status(self, position: "Position") -> dict:
        step = int(getattr(position, "scale_step", 1))
        return {
            "scale_step": step,
            "scale_confirm_price": float(getattr(position, "scale_confirm_price", 0.0)),
            "scale_breakout_price": float(getattr(position, "scale_breakout_price", 0.0)),
            "remaining_fraction": self._remaining_fraction(step),
        }

    def _remaining_fraction(self, scale_step: int) -> float:
        if scale_step >= 3:
            return 0.0
        if scale_step == 2:
            return self.SCALE_STEP_3_FRACTION
        return self.SCALE_STEP_2_FRACTION + self.SCALE_STEP_3_FRACTION

    def initialize_scale_prices(self, position: "Position", confirm_price: float, breakout_price: float) -> None:
        setattr(position, "scale_confirm_price", Decimal(str(confirm_price)))
        setattr(position, "scale_breakout_price", Decimal(str(breakout_price)))
        setattr(position, "scale_step", 1)

    def reset_scale_state(self, position: "Position") -> None:
        setattr(position, "scale_step", 1)
        setattr(position, "scale_confirm_price", Decimal("0"))
        setattr(position, "scale_breakout_price", Decimal("0"))
