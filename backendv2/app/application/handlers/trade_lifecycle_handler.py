"""Trade lifecycle handler for backendv2."""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import TYPE_CHECKING, Callable

from app.domain.exit.model.exit_models import ExitSignal
from app.domain.exit.service import (
    ExitEngine,
    PartitionExitManagerV2 as PartitionExitManager,
    LossTracker,
    PyramidManager,
    TrailEngine,
)
from app.domain.exit.model.exit_models import ExitReason
from app.domain.trading.model.entities import Position
from app.domain.trading.model.enums import PositionStatus, Side
from app.domain.exit.service.exit_rules import check_spread_blowout

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class TradeLifecycleHandler:
    """Orchestrate exit evaluation and lifecycle state transitions."""

    def __init__(
        self,
        exit_engine: ExitEngine | None = None,
        on_stop_out: Callable[[float, str, str], None] | None = None,
        on_partial_exit: Callable[[str, str, float, float, float, float, float, str], None] | None = None,
        persist_fn=None,
        event_logger=None,
        on_trade_closed: Callable[[str, float, str], None] | None = None,
        trail_engine: TrailEngine | None = None,
        pyramid_manager: PyramidManager | None = None,
        partition_manager: PartitionExitManager | None = None,
    ) -> None:
        self._exit_engine = exit_engine or ExitEngine()
        self._partition_manager = partition_manager or PartitionExitManager()
        self._trail_engine = trail_engine or TrailEngine()
        self._pyramid_manager = pyramid_manager or PyramidManager()
        self._loss_tracker = LossTracker()
        self._partition_states: dict[str, object] = {}
        self._partition_symbols: dict[str, str] = {}
        self._on_stop_out = on_stop_out
        self._on_partial_exit = on_partial_exit
        self._on_trade_closed = on_trade_closed
        self._event_logger = event_logger
        self._persist_fn = persist_fn

    @property
    def exit_engine(self) -> ExitEngine:
        return self._exit_engine

    @property
    def trade_manager(self) -> ExitEngine:
        return self._exit_engine

    def check_exits(
        self,
        portfolio,
        current_price: float,
        *,
        symbol: str | None = None,
        cvd_divergence: str = "",
        time_to_close: float = 0.0,
        cvd_slope: float = 0.0,
        order_book=None,
        amt_result=None,
        imbalances=None,
        tick_low: float = 0.0,
        tick_high: float = 0.0,
    ) -> bool:
        del imbalances
        open_positions = [p for p in portfolio.positions if p.status == PositionStatus.OPEN]
        if not open_positions:
            return False

        for pos in list(open_positions):
            if pos.status != PositionStatus.OPEN:
                continue

            state_symbol = str(symbol or pos.symbol).upper()
            if state_symbol not in self._partition_states:
                self._partition_states.setdefault(pos.id, self._partition_manager._states.setdefault(pos.id, None))
            p_state = self._partition_manager._states.setdefault(pos.id, None)
            self._partition_symbols[pos.id] = state_symbol

            if state_symbol and pos.id not in self._partition_manager._states:
                self._partition_manager._states[pos.id] = None

            if self._check_spread_blowout(pos, current_price, order_book):
                portfolio.close_position(pos.id, current_price, str(ExitReason.SPREAD_BLOWOUT))
                self._record_close(pos)
                self._loss_tracker.record_exit_time(state_symbol)
                continue

            if self._check_partial_and_scaleouts(
                portfolio=portfolio,
                pos=pos,
                current_price=current_price,
                cvd_slope=cvd_slope,
                cvd_divergence=cvd_divergence,
                amt_result=amt_result,
            ):
                self._loss_tracker.record_exit_time(state_symbol)
                return True

            decision = self._exit_engine.evaluate(
                position=pos,
                current_price=current_price,
                tick_high=tick_high if tick_high else current_price,
                tick_low=tick_low if tick_low else current_price,
                hold_time_seconds=time_to_close,
                session_phase="MORNING",
                market_state=str(getattr(amt_result, "market_state", "BALANCED")),
                is_expiry=bool(getattr(pos, "is_expiry", False)),
            )
            if not decision:
                continue

            if decision.exit_type in ("PARTIAL", "TRAIL", "COUNTER_AGGRESSION", "PARTIAL_TAKE_PROFIT"):
                partial_realized = portfolio.partial_close_position(
                    pos.id,
                    decision.size_pct,
                    decision.price,
                    str(decision.reason),
                )
                if partial_realized != Decimal("0"):
                    if decision.new_stop:
                        pos.stop_loss = Decimal(str(decision.new_stop))
                    if self._on_partial_exit:
                        self._on_partial_exit(
                            pos.symbol,
                            pos.id,
                            float(pos.entry_price),
                            float(decision.price),
                            float(decision.size_pct),
                            float(partial_realized),
                            float(partial_realized),
                            str(decision.reason),
                        )
                if str(decision.reason).upper() in ("COUNTER_AGGRESSION", "TRAIL"):
                    if portfolio.close_position(pos.id, decision.price, str(decision.reason)):
                        self._record_close(pos)
                        self._loss_tracker.record_exit_time(state_symbol)
                        return True
                continue

            # Full exits for static exit engine decisions.
            if decision.exit_type == "FULL":
                closed = portfolio.close_position(pos.id, decision.price, str(decision.reason))
                if not closed:
                    continue
                if decision.reason == str(ExitReason.STOP_LOSS):
                    self._loss_tracker.record_loss(state_symbol, stop_price=decision.price)
                    if self._on_stop_out:
                        self._on_stop_out(float(pos.entry_price), pos.side.value, pos.symbol)
                self._record_close(pos)
                self._loss_tracker.record_exit_time(state_symbol)
                return True

        return False

    def _check_spread_blowout(self, pos: Position, current_price: float, order_book) -> bool:
        if not order_book or not getattr(order_book, "bids", None) or not getattr(order_book, "asks", None):
            return False
        bids = order_book.bids
        asks = order_book.asks
        if not bids or not asks:
            return False
        bid = float(getattr(bids[0], "price", 0.0))
        ask = float(getattr(asks[0], "price", 0.0))
        mid = (bid + ask) / 2 if bid and ask else current_price
        if mid <= 0:
            return False
        spread_pct = (ask - bid) / mid
        return check_spread_blowout(spread_pct)

    def _check_partial_and_scaleouts(
        self,
        portfolio,
        pos: Position,
        current_price: float,
        cvd_slope: float,
        cvd_divergence: str,
        amt_result,
    ) -> bool:
        # CVD opposing divergence short-circuit.
        if cvd_divergence:
            if pos.is_long and cvd_divergence.upper().startswith("BEARISH") and pos.tick_count >= 3:
                portfolio.close_position(pos.id, current_price, "CVD_KILL")
                self._record_close(pos)
                return True
            if (not pos.is_long) and cvd_divergence.upper().startswith("BULLISH") and pos.tick_count >= 3:
                portfolio.close_position(pos.id, current_price, "CVD_KILL")
                self._record_close(pos)
                return True

        # Breakeven transition on strong confirmation.
        if not pos.breakeven_set and abs(float(pos.cushion_state.value)) >= 0:
            if pos.is_long and cvd_slope > 0 and (not pos.breakeven_set):
                if abs(float(current_price) - float(pos.entry_price)) >= abs(float(pos.entry_price) - float(pos.stop_loss)):
                    pos.move_stop_to_breakeven()
            elif (not pos.is_long) and cvd_slope < 0 and (not pos.breakeven_set):
                if abs(float(current_price) - float(pos.entry_price)) >= abs(float(pos.initial_stop) - float(pos.entry_price)):
                    pos.move_stop_to_breakeven()

        # VWAP trailing: conservative variant for real-time drift.
        if getattr(amt_result, "session_vwap", 0.0):
            vwap = float(amt_result.session_vwap)
            if pos.is_long and current_price >= float(vwap):
                pos.stop_loss = max(float(pos.stop_loss), vwap)
            if (not pos.is_long) and current_price <= float(vwap):
                pos.stop_loss = min(float(pos.stop_loss), vwap)

        # Partition exits.
        p_state = self._partition_manager._states.setdefault(pos.id, None)
        if p_state is not None:
            self._check_partition_exits(portfolio, pos, p_state, current_price, cvd_slope, amt_result)

        # Pyramid check for winning longs/shorts.
        if self._check_pyramid_add(portfolio, pos, current_price, amt_result):
            pass

        return False

    def _check_partition_exits(
        self,
        portfolio,
        pos: Position,
        p_state,
        current_price: float,
        cvd_slope: float,
        amt_result,
    ) -> None:
        if pos.id not in self._partition_manager._states:
            return

        state = self._partition_manager._states[pos.id]
        if state is None:
            return
        current_market_state = str(getattr(amt_result, "market_state", "BALANCED"))
        signals = self._partition_manager.check_exits(
            entry_price=float(pos.entry_price),
            initial_stop=float(pos.initial_stop),
            take_profit=float(pos.take_profit),
            current_price=current_price,
            is_long=bool(pos.is_long),
            cvd_slope=cvd_slope,
            state=state,
            market_state=current_market_state,
        )
        for psig in signals:
            if psig.exit_type in ("COUNTER_AGGRESSION", "TRAIL"):
                closed = portfolio.close_position(pos.id, psig.price, psig.reason)
                if closed is not None:
                    if psig.exit_type == "COUNTER_AGGRESSION":
                        self._loss_tracker.record_loss(pos.symbol, stop_price=psig.price)
                    self._record_close(pos)
                self._partition_manager._states.pop(pos.id, None)
                continue
            if psig.exit_type in ("PARTITION_1", "PARTITION_2", "PARTITION_3"):
                realized = portfolio.partial_close_position(
                    pos.id,
                    psig.size_pct,
                    psig.price,
                    psig.exit_type,
                )
                if self._on_partial_exit:
                    self._on_partial_exit(
                        pos.symbol,
                        pos.id,
                        float(pos.entry_price),
                        float(psig.price),
                        float(psig.size_pct),
                        float(realized),
                        float(realized),
                        str(psig.reason),
                    )
                if psig.exit_type == "PARTITION_1":
                    self._check_pyramid_add(portfolio, pos, psig.price, amt_result)

        new_state = self._partition_manager._states.get(pos.id)
        if new_state and getattr(new_state, "trail_sl", 0.0):
            pos.stop_loss = max(pos.stop_loss, Decimal(str(new_state.trail_sl))) if pos.is_long else min(
                pos.stop_loss,
                Decimal(str(new_state.trail_sl)),
            )

    def _check_pyramid_add(
        self,
        portfolio,
        pos: Position,
        current_price: float,
        amt_result,
    ) -> bool:
        if not amt_result:
            return False
        aggression_score = float(getattr(amt_result, "aggression_score", 0.0) or 0.0)
        current_lvn = float(getattr(amt_result, "current_lvn", 0.0) or 0.0)
        if aggression_score < 3.0 or current_lvn <= 0:
            return False

        entry_lvns = list(getattr(pos, "entry_lvns", []))
        signal = self._pyramid_manager.check_pyramid(
            entry_price=float(pos.entry_price),
            current_price=current_price,
            is_long=bool(pos.is_long),
            aggression_score=aggression_score,
            add_count=len(entry_lvns),
            entry_lvns=entry_lvns,
            current_lvn=current_lvn,
            current_sl=float(pos.stop_loss),
        )
        if signal is None:
            return False

        if not portfolio.add_to_position(pos.id, signal.size_multiplier, current_price):
            return False
        pos.stop_loss = Decimal(str(signal.unified_sl))
        if current_lvn > 0 and current_lvn not in entry_lvns:
            if not hasattr(pos, "entry_lvns") or pos.entry_lvns is None:
                pos.entry_lvns = []
            pos.entry_lvns.append(current_lvn)
        return True

    def initialize_partition_state(self, position_id: str, symbol: str | None = None) -> None:
        self._partition_manager._states.setdefault(position_id, self._partition_manager._states.get(position_id))
        if symbol is not None:
            self._partition_symbols[position_id] = symbol

    def clear_partition_state(self, position_id: str) -> None:
        self._partition_manager._states.pop(position_id, None)
        self._partition_symbols.pop(position_id, None)

    def has_managed_positions(self, symbol: str, portfolio=None) -> bool:
        if not symbol:
            return len(self._partition_manager._states) > 0
        symbol = symbol.upper()
        if portfolio is not None:
            return any(
                p.status == PositionStatus.OPEN and p.symbol.upper() == symbol
                for p in portfolio.positions
            )
        for pid, managed_symbol in self._partition_symbols.items():
            if managed_symbol and str(managed_symbol).upper() == symbol:
                if pid in self._partition_manager._states:
                    return True
        return False

    def in_cooldown(self, symbol: str) -> bool:
        return self._loss_tracker.in_cooldown(symbol)

    def _record_close(self, pos: Position) -> None:
        self.clear_partition_state(pos.id)
        if self._on_trade_closed:
            try:
                self._on_trade_closed(pos.symbol, float(pos.pnl), pos.id)
            except Exception:
                self._on_trade_closed(pos.symbol, float(pos.pnl), pos.id)
