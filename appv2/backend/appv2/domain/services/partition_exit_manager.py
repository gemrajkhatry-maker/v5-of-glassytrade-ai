"""Partition Exit Manager — manages scale-out exits at +1R, +1.5R, etc.

Fabio's exit strategy:
1. First opposing order-flow signal → Scale out partial
2. +1R gain reached → Take partial profit (30-40%)
3. +1.5R gain → Trail stop to VWAP band
4. Allow runner only if day remains strongly trending
5. Full exit at prior balance POC (default target)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ExitStage(str, Enum):
    INITIAL = "INITIAL"
    PARTIAL_1R = "PARTIAL_1R"
    PARTIAL_15R = "PARTIAL_15R"
    TRAILING = "TRAILING"
    FULL_EXIT = "FULL_EXIT"


@dataclass
class PartitionExit:
    """A single exit tranche."""
    stage: ExitStage
    quantity_pct: float  # % of position to exit
    triggered: bool = False
    exit_price: float = 0.0
    pnl: float = 0.0
    reason: str = ""


@dataclass
class ExitPlan:
    """Complete exit plan with tranches."""
    entry_price: float
    stop_loss: float
    take_profit: float
    risk_per_unit: float
    tranches: list[PartitionExit]
    realized_pnl: float = 0.0
    remaining_pct: float = 100.0
    current_stage: ExitStage = ExitStage.INITIAL


class PartitionExitManager:
    """Manages staged exits for a position."""

    def __init__(
        self,
        partial_at_1r: float = 0.40,  # 40% at +1R
        partial_at_15r: float = 0.30,  # 30% at +1.5R
        trail_to_vwap: bool = True,
    ):
        self._partial_at_1r = partial_at_1r
        self._partial_at_15r = partial_at_15r
        self._trail_to_vwap = trail_to_vwap

    def create_plan(
        self,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
    ) -> ExitPlan:
        """Create exit plan for a new position."""
        risk = abs(entry_price - stop_loss)

        tranches = [
            PartitionExit(
                stage=ExitStage.PARTIAL_1R,
                quantity_pct=self._partial_at_1r * 100,
            ),
            PartitionExit(
                stage=ExitStage.PARTIAL_15R,
                quantity_pct=self._partial_at_15r * 100,
            ),
            PartitionExit(
                stage=ExitStage.FULL_EXIT,
                quantity_pct=100 - self._partial_at_1r * 100 - self._partial_at_15r * 100,
            ),
        ]

        return ExitPlan(
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            risk_per_unit=risk,
            tranches=tranches,
            remaining_pct=100.0,
        )

    def check_exits(
        self,
        plan: ExitPlan,
        current_price: float,
        is_long: bool,
        vwap: float = 0.0,
        opposing_signal: bool = False,
    ) -> list[PartitionExit]:
        """Check which exit tranches should be triggered.

        Returns list of newly triggered tranches.
        """
        triggered = []
        risk = plan.risk_per_unit
        entry = plan.entry_price

        for tranche in plan.tranches:
            if tranche.triggered:
                continue

            should_trigger = False
            exit_price = 0.0
            reason = ""

            # Check +1R partial
            if tranche.stage == ExitStage.PARTIAL_1R:
                target_1r = entry + risk if is_long else entry - risk
                if (is_long and current_price >= target_1r) or \
                   (not is_long and current_price <= target_1r):
                    should_trigger = True
                    exit_price = target_1r
                    reason = f"+1R target reached ({target_1r:.2f})"

            # Check +1.5R partial
            elif tranche.stage == ExitStage.PARTIAL_15R:
                target_15r = entry + risk * 1.5 if is_long else entry - risk * 1.5
                if (is_long and current_price >= target_15r) or \
                   (not is_long and current_price <= target_15r):
                    should_trigger = True
                    exit_price = target_15r
                    reason = f"+1.5R target reached ({target_15r:.2f})"

            # Check TP/full exit
            elif tranche.stage == ExitStage.FULL_EXIT:
                if opposing_signal:
                    should_trigger = True
                    exit_price = current_price
                    reason = "Opposing order-flow signal"
                elif (is_long and current_price >= plan.take_profit) or \
                     (not is_long and current_price <= plan.take_profit):
                    should_trigger = True
                    exit_price = plan.take_profit
                    reason = f"Take profit reached ({plan.take_profit:.2f})"
                elif vwap > 0 and self._trail_to_vwap:
                    # VWAP trail check
                    if is_long and current_price <= vwap:
                        should_trigger = True
                        exit_price = vwap
                        reason = f"VWAP trail hit ({vwap:.2f})"
                    elif not is_long and current_price >= vwap:
                        should_trigger = True
                        exit_price = vwap
                        reason = f"VWAP trail hit ({vwap:.2f})"

            if should_trigger:
                tranche.triggered = True
                tranche.exit_price = exit_price
                if is_long:
                    tranche.pnl = (exit_price - entry) * (tranche.quantity_pct / 100)
                else:
                    tranche.pnl = (entry - exit_price) * (tranche.quantity_pct / 100)
                tranche.reason = reason
                triggered.append(tranche)

                plan.remaining_pct -= tranche.quantity_pct
                plan.realized_pnl += tranche.pnl
                plan.current_stage = tranche.stage

        return triggered

    @property
    def remaining_pct(self) -> float:
        return sum(t.quantity_pct for t in self._partial_at_1r.tranches if not t.triggered) if hasattr(self, '_partial_at_1r') else 0
