"""Trade Lifecycle Handler — deterministic position management."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from app.domain.fabio_ai.services.trade_manager import TradeManager, ExitReason
from app.domain.trading.models.enums import SignalType, Source

if TYPE_CHECKING:
    from app.domain.trading.models.aggregates import Portfolio
    from app.domain.trading.models.entities import Signal, Position

logger = logging.getLogger(__name__)


class TradeLifecycleHandler:
    """Handles position exits via TradeManager (SL/TP/Trail/Time)."""

    def __init__(
        self,
        on_stop_out: Callable[[float, str], None] | None = None,
        on_partial_exit: Callable[[str, str, float, float, float, float, float, str], None] | None = None,
    ) -> None:
        self._trade_manager = TradeManager()
        self._on_stop_out = on_stop_out
        self._on_partial_exit = on_partial_exit  # (pos_id, side, entry_price, exit_price, partial_pct, size_closed, realized_pnl, reason)

    @property
    def trade_manager(self) -> TradeManager:
        """Expose trade manager for RR filter and daily limit checks."""
        return self._trade_manager

    def check_exits(
        self, portfolio: Portfolio, current_price: float,
        cvd_divergence: str = "", time_to_close: float = 0.0,
        cvd_slope: float = 0.0,
    ) -> bool:
        """Check all open positions for exit conditions and scale-in triggers.

        Returns:
            True if a position was fully closed (so caller knows the slot is free).
        """
        open_positions = [p for p in portfolio.positions if p.status == "OPEN"]

        for pos in open_positions:
            # Skip positions already closed (e.g. by Portfolio.process_tick SL/TP)
            if pos.status != "OPEN":
                continue

            # Scale-in check (Fabio Rule 4: 40/30/30)
            add_fraction = self._trade_manager.check_scale_in(pos.id, current_price)
            if add_fraction > 0:
                portfolio.add_to_position(pos.id, add_fraction, current_price)

            # CVD kill signal check (Fabio: exit when CVD diverges against position)
            # Grace period: skip CVD kill for first 3 ticks after entry
            mp = self._trade_manager._positions.get(pos.id)
            if cvd_divergence and (mp is None or mp.tick_count >= 3):
                cvd_exit = self._trade_manager.apply_cvd_kill_signal(
                    pos.id, cvd_divergence, current_price
                )
                if cvd_exit:
                    portfolio.close_position(pos.id, cvd_exit.exit_price, cvd_exit.reason)
                    self._trade_manager.unregister_position(pos.id)
                    logger.info(f"Position {pos.id} closed: CVD kill signal at {cvd_exit.exit_price:.2f}")
                    return True

            # CVD-based breakeven: move SL to entry when CVD confirms direction
            if cvd_slope != 0.0 and mp is not None:
                self._trade_manager.apply_cvd_breakeven(pos.id, cvd_slope)

            exit_sig = self._trade_manager.check_position(
                pos.id, current_price, time_to_close=time_to_close,
            )
            if exit_sig:
                logger.info("Exit trigger: pos=%s reason=%s price=%.2f tick=%d",
                            pos.id, exit_sig.reason, exit_sig.exit_price,
                            mp.tick_count if mp else -1)
                if exit_sig.reason == ExitReason.PARTIAL_TAKE_PROFIT:
                    # Runner mode: close 75% at target, keep 25% trailing
                    # Standard partial: close 50%
                    mp = self._trade_manager._positions.get(pos.id)
                    if mp and mp.runner_active:
                        partial_pct = self._trade_manager.config.runner_close_pct
                    else:
                        partial_pct = self._trade_manager.config.partial_size_pct
                    size_before = pos.size
                    realized_pnl = portfolio.partial_close_position(
                        pos.id, partial_pct, exit_sig.exit_price, exit_sig.reason
                    )
                    logger.info(
                        f"Position {pos.id} partial close: {exit_sig.reason} "
                        f"at {exit_sig.exit_price:.2f}, realized PnL={realized_pnl:.2f}, "
                        f"size {size_before:.0f} → {pos.size:.0f}"
                    )
                    # Notify journal/forward logger
                    if self._on_partial_exit:
                        side = pos.side.value if hasattr(pos.side, 'value') else str(pos.side)
                        self._on_partial_exit(
                            pos.id, side, pos.entry_price, exit_sig.exit_price,
                            partial_pct, size_before * partial_pct, pos.size, realized_pnl,
                        )
                    # Do NOT unregister — position is still open with remaining size
                    return False
                else:
                    # Full close
                    portfolio.close_position(pos.id, exit_sig.exit_price, exit_sig.reason)
                    self._trade_manager.unregister_position(pos.id)
                    # Track daily losses on stop loss exits
                    if exit_sig.reason == ExitReason.STOP_LOSS:
                        self._trade_manager.record_loss()
                        # Record stop-out for Rule 11 re-entry blocking
                        if self._on_stop_out:
                            side = "LONG" if pos.side.value == "LONG" else "SHORT"
                            self._on_stop_out(pos.entry_price, side)
                    logger.info(
                        f"Position {pos.id} closed: {exit_sig.reason} "
                        f"at {exit_sig.exit_price:.2f}"
                    )
                    return True
        return False

    def register_position(self, position: Position, signal: Signal) -> None:
        """Register a new position with TradeManager for exit monitoring.

        All signal sources (LLM, AGENT, AMT, etc.) must be registered so the
        overseer can manage the position.
        """
        meta = signal.metadata or {}
        allow_trail = meta.get("allow_trail", False)
        scale_in = meta.get("scale_in", False)
        market_state = meta.get("market_state_model", "BALANCED")
        session_phase = meta.get("session_phase", "")
        is_expiry = meta.get("is_expiry", False)
        # Normalize: "Trending" -> "IMBALANCED"
        if "trend" in market_state.lower() or "imbalance" in market_state.lower():
            market_state = "IMBALANCED"
        else:
            market_state = "BALANCED"
        self._trade_manager.register_position(
            position_id=position.id,
            side="LONG" if signal.type == SignalType.BUY else "SHORT",
            entry_price=position.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            allow_trail=allow_trail,
            market_state=market_state,
            enable_scale_in=scale_in,
            session_phase=session_phase,
            is_expiry=is_expiry,
        )

    @property
    def has_managed_positions(self) -> bool:
        return self._trade_manager.has_managed_positions

    def sync_closed(self, closed_positions: list) -> None:
        """Unregister positions that were closed by Portfolio (SL/TP hits).

        Prevents double-close when check_exits runs afterwards.
        """
        for pos in closed_positions:
            self._trade_manager.unregister_position(pos.id)

    def in_cooldown(self) -> bool:
        return self._trade_manager.in_cooldown()
