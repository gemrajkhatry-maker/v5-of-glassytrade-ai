"""Exposure Monitor — tracks total exposure across all symbols.

Monitors:
- Total exposure (sum of position values across all symbols)
- Max exposure per symbol
- Max exposure as % of capital
- Blocks new trades if limits exceeded
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ExposureState:
    total_exposure: float
    exposure_by_symbol: dict[str, float]
    exposure_pct: float  # % of capital
    max_single_symbol_exposure: float
    max_single_symbol_pct: float
    is_within_limits: bool


class ExposureMonitor:
    """Monitors total exposure across all open positions."""

    def __init__(
        self,
        capital: float,
        max_exposure_pct: float = 30.0,  # Max 30% of capital deployed
        max_single_symbol_pct: float = 10.0,  # Max 10% in single symbol
    ):
        self._capital = capital
        self._max_exposure_pct = max_exposure_pct
        self._max_single_symbol_pct = max_single_symbol_pct
        self._positions: dict[str, dict] = {}  # symbol → {quantity, avg_price}

    def add_position(self, symbol: str, quantity: int, avg_price: float) -> None:
        """Track a new position."""
        self._positions[symbol] = {
            "quantity": quantity,
            "avg_price": avg_price,
        }

    def remove_position(self, symbol: str) -> None:
        """Remove a closed position."""
        self._positions.pop(symbol, None)

    def update_position(self, symbol: str, quantity: int, avg_price: float) -> None:
        """Update position (for scaling)."""
        if quantity <= 0:
            self.remove_position(symbol)
        else:
            self._positions[symbol] = {
                "quantity": quantity,
                "avg_price": avg_price,
            }

    def get_state(self) -> ExposureState:
        """Get current exposure state."""
        exposure_by_symbol = {}
        total = 0.0

        for sym, pos in self._positions.items():
            value = pos["quantity"] * pos["avg_price"]
            exposure_by_symbol[sym] = value
            total += value

        exposure_pct = (total / self._capital * 100) if self._capital > 0 else 0
        max_single = max(exposure_by_symbol.values()) if exposure_by_symbol else 0
        max_single_pct = (max_single / self._capital * 100) if self._capital > 0 else 0

        is_ok = (
            exposure_pct <= self._max_exposure_pct
            and max_single_pct <= self._max_single_symbol_pct
        )

        return ExposureState(
            total_exposure=round(total, 2),
            exposure_by_symbol=exposure_by_symbol,
            exposure_pct=round(exposure_pct, 1),
            max_single_symbol_exposure=round(max_single, 2),
            max_single_symbol_pct=round(max_single_pct, 1),
            is_within_limits=is_ok,
        )

    def can_open_position(
        self,
        symbol: str,
        quantity: int,
        price: float,
    ) -> tuple[bool, str]:
        """Check if opening a new position would exceed limits."""
        new_exposure = quantity * price
        current_state = self.get_state()

        # Check total exposure
        new_total = current_state.total_exposure + new_exposure
        new_total_pct = (new_total / self._capital * 100) if self._capital > 0 else 0
        if new_total_pct > self._max_exposure_pct:
            return False, (
                f"Total exposure would be {new_total_pct:.1f}% > {self._max_exposure_pct}% limit"
            )

        # Check single symbol exposure
        current_sym_exposure = current_state.exposure_by_symbol.get(symbol, 0)
        new_sym_exposure = current_sym_exposure + new_exposure
        new_sym_pct = (new_sym_exposure / self._capital * 100) if self._capital > 0 else 0
        if new_sym_pct > self._max_single_symbol_pct:
            return False, (
                f"Symbol {symbol} exposure would be {new_sym_pct:.1f}% > "
                f"{self._max_single_symbol_pct}% limit"
            )

        return True, ""

    @property
    def total_exposure(self) -> float:
        return self.get_state().total_exposure

    def reset(self) -> None:
        self._positions.clear()
