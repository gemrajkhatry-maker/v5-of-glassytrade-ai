"""ExitEngine — deterministic exit logic operating on Position objects.

Ported from backend/app/domain/fabio_ai/services/exit_engine.py.
Delegates to: exit_rules, trail_engine, partition_exit_manager, loss_tracker.
LLM trains on entry only. Trade management = rule-based + deterministic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

from app.domain.exit.model.exit_decision import ExitDecision
from app.domain.exit.model.exit_models import ExitReason
from app.domain.exit.service.exit_rules import (
    check_time_stop,
    check_spread_blowout,
)
from app.domain.trading.model.entities import Position
from app.domain.trading.model.enums import CushionState

logger = logging.getLogger(name=__name__)


@dataclass
class TradeManagerConfig:
    stop_loss_pct: float = 0.005
    time_stop_enabled: bool = True
    trail_enabled: bool = True
    partition_enabled: bool = True
    max_hold_seconds: float = 7200


class ExitEngine:
    """Stateless exit engine. Receives Position, returns ExitDecision."""

    def __init__(self, config: TradeManagerConfig | None = None):
        self._config = config or TradeManagerConfig()

    @staticmethod
    def _exit_decision(**kwargs: object):
        return ExitDecision(**kwargs)

    def evaluate(
        self, position: Position, current_price: float, tick_high: float, tick_low: float,
        hold_time_seconds: float = 0, session_phase: str = "MORNING",
        market_state: str = "BALANCED", is_expiry: bool = False,
    ) -> ExitDecision | None:
        """Evaluate whether position should be closed.

        Priority: SL → TP → time stop → trail → partition
        """
        if position.status != position.status.OPEN:
            return None

        # 1. Stop loss (use wick extremes)
        should_close, reason = self._check_sl_tp(position, current_price, tick_high, tick_low)
        if should_close:
            return self._exit_decision(
                exit_type="FULL", size_pct=1.0, price=current_price,
                reason=reason, new_stop=None,
            )

        # 2. Time stop
        if self._config.time_stop_enabled:
            if check_time_stop(hold_time_seconds, session_phase, market_state, is_expiry):
                return self._exit_decision(
                    exit_type="FULL", size_pct=1.0, price=current_price,
                    reason=ExitReason.TIME_STOP, new_stop=None,
                )

        # 3. Spread blowout
        try:
            spread_pct = self._get_spread_pct(position, current_price)
        except NotImplementedError:
            spread_pct = None
        if spread_pct is not None and check_spread_blowout(spread_pct):
            return self._exit_decision(
                exit_type="FULL", size_pct=1.0, price=current_price,
                reason=ExitReason.SPREAD_BLOWOUT, new_stop=None,
            )

        # 4. Trailing stop (delegate)
        if self._config.trail_enabled:
            trail_sl = self._check_trail(position, current_price)
            if trail_sl and self._is_sl_hit(position, trail_sl, current_price, tick_high, tick_low):
                return self._exit_decision(
                    exit_type="FULL", size_pct=1.0, price=current_price,
                    reason=ExitReason.TRAILING_STOP, new_stop=trail_sl,
                )

        # 5. Partition exit (delegate)
        if self._config.partition_enabled:
            partition = self._check_partition(position, current_price)
            if partition:
                return partition

        return None

    def _check_sl_tp(self, pos: Position, price: float, tick_high: float, tick_low: float) -> tuple[bool, str]:
        """Check SL/TP using wick extremes. SL uses adverse wick, TP uses favorable wick."""
        if pos.is_long:
            # SL: tick low breaches stop
            if tick_low <= float(pos.stop_loss):
                return True, ExitReason.STOP_LOSS
            # TP: tick high reaches target
            if tick_high >= float(pos.take_profit):
                return True, ExitReason.TAKE_PROFIT
        else:
            if tick_high >= float(pos.stop_loss):
                return True, ExitReason.STOP_LOSS
            if tick_low <= float(pos.take_profit):
                return True, ExitReason.TAKE_PROFIT
        return False, ""

    def _check_trail(self, pos: Position, price: float) -> float | None:
        """Compute trailing stop. Returns new SL price or None."""
        if pos.cushion_state == CushionState.OPEN:
            # Move to breakeven after 1R profit
            risk = abs(float(pos.entry_price) - float(pos.initial_stop))
            if risk > 0:
                if pos.is_long and price >= float(pos.entry_price) + risk:
                    pos.advance_cushion_state(CushionState.CUSHIONED)
                    return float(pos.entry_price)
                elif pos.is_short and price <= float(pos.entry_price) - risk:
                    pos.advance_cushion_state(CushionState.CUSHIONED)
                    return float(pos.entry_price)
        return None

    def _is_sl_hit(self, pos: Position, trail_sl: float, price: float, tick_high: float, tick_low: float) -> bool:
        if pos.is_long:
            return tick_low <= trail_sl
        else:
            return tick_high >= trail_sl

    def _check_partition(self, pos: Position, price: float) -> ExitDecision | None:
        """Check partition exit (P1 at 1R, P2 at 2R, P3 trail)."""
        if pos.is_long:
            risk = float(pos.entry_price) - float(pos.initial_stop)
            if risk <= 0:
                return None
            r_multiple = (price - float(pos.entry_price)) / risk
        else:
            risk = float(pos.initial_stop) - float(pos.entry_price)
            if risk <= 0:
                return None
            r_multiple = (float(pos.entry_price) - price) / risk

        if not pos.partial_taken and r_multiple >= 1.0:
            pos.set_partial_taken(True)
            return self._exit_decision(
                exit_type="PARTIAL", size_pct=0.3,
                price=price, reason=ExitReason.PARTIAL_TAKE_PROFIT,
                new_stop=float(pos.entry_price),
            )
        elif pos.partial_taken and not pos.runner_active and r_multiple >= 2.0:
            pos.runner_active = True
            pos.advance_cushion_state(CushionState.TRAILING)
            return self._exit_decision(
                exit_type="PARTIAL", size_pct=0.4,
                price=price, reason=ExitReason.PARTIAL_TAKE_PROFIT,
                new_stop=float(pos.entry_price),
            )

        return None

    def _get_spread_pct(self, pos: Position, price: float) -> float:
        raise NotImplementedError("Spread is not wired yet for ExitEngine")


class TrailEngine:
    """Trailing stop logic — ATR, VWAP, CVD breakeven."""

    def __init__(self, atr_trail_activation_r: float = 1.0, atr_trail_step_pct: float = 0.2):
        self._atr_activation = atr_trail_activation_r
        self._atr_step_pct = atr_trail_step_pct

    def apply_atr_trail(self, pos: Position, current_price: float, atr: float, entry_price: float) -> float | None:
        """ATR trailing stop. Activate after 1R profit, trail at ATR step."""
        if atr <= 0:
            return None
        risk = abs(entry_price - float(pos.initial_stop))
        if risk <= 0:
            return None

        if pos.is_long:
            profit = current_price - entry_price
            if profit >= risk * self._atr_activation:
                return current_price - atr * self._atr_step_pct
        else:
            profit = entry_price - current_price
            if profit >= risk * self._atr_activation:
                return current_price + atr * self._atr_step_pct
        return None


class PartitionExitManager:
    """P1/P2/P3 partition exits. Fabio FR-08."""

    P1_SIZE = 0.30
    P2_SIZE = 0.40
    P3_SIZE = 0.30
    P1_R = 1.0
    P2_R = 2.0

    def __init__(self):
        self._states: dict[str, dict] = {}

    @staticmethod
    def _exit_decision(**kwargs: object):
        return ExitDecision(**kwargs)

    def check(self, pos: Position, current_price: float) -> ExitDecision | None:
        state = self._states.get(pos.id)
        if state is None:
            state = {"p1": False, "p2": False, "p3": False, "be": False}
            self._states[pos.id] = state

        risk = abs(float(pos.entry_price) - float(pos.initial_stop))
        if risk <= 0:
            return None

        if pos.is_long:
            r = (current_price - float(pos.entry_price)) / risk
        else:
            r = (float(pos.entry_price) - current_price) / risk

        if not state["p1"] and r >= self.P1_R:
            state["p1"] = True
            return self._exit_decision(
                exit_type="PARTIAL",
                size_pct=self.P1_SIZE,
                price=current_price,
                reason="P1 at 1R",
                new_stop=float(pos.entry_price),
            )
        if state["p1"] and not state["p2"] and r >= self.P2_R:
            state["p2"] = True
            return self._exit_decision(
                exit_type="PARTIAL",
                size_pct=self.P2_SIZE,
                price=current_price,
                reason="P2 at 2R",
                new_stop=float(pos.entry_price),
            )
        if state["p2"] and not state["p3"]:
            state["p3"] = True

        return None
