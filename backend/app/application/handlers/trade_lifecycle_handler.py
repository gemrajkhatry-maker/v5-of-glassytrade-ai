"""Trade Lifecycle Handler — deterministic position management."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from app.domain.fabio_ai.services.trade_manager import TradeManager, ExitReason
from app.domain.fabio_ai.services.partition_exit_manager import (
    PartitionExitManager,
    PartitionState,
)
from app.domain.trading.models.enums import SignalType, Source

if TYPE_CHECKING:
    from app.domain.trading.models.aggregates import Portfolio
    from app.domain.trading.models.entities import Signal, Position

logger = logging.getLogger(__name__)


class TradeLifecycleHandler:
    """Handles position exits via TradeManager (SL/TP/Trail/Time) + Partition Exits (P1/P2/P3)."""

    def __init__(
        self,
        on_stop_out: Callable[[float, str], None] | None = None,
        on_partial_exit: Callable[
            [str, str, float, float, float, float, float, str], None
        ]
        | None = None,
        persist_fn=None,
    ) -> None:
        self._trade_manager = TradeManager(persist_fn=persist_fn)
        self._partition_manager = PartitionExitManager()
        self._partition_states: dict[str, PartitionState] = {}
        self._on_stop_out = on_stop_out
        self._on_partial_exit = on_partial_exit

    @property
    def trade_manager(self) -> TradeManager:
        """Expose trade manager for RR filter and daily limit checks."""
        return self._trade_manager

    def check_exits(
        self,
        portfolio: Portfolio,
        current_price: float,
        cvd_divergence: str = "",
        time_to_close: float = 0.0,
        cvd_slope: float = 0.0,
        order_book=None,
        amt_result=None,
        imbalances=None,
    ) -> bool:
        """Check all open positions for exit conditions and scale-in triggers.

        Returns:
            True if a position was fully closed (so caller knows the slot is free).
        """
        consistency = self.ensure_position_consistency(portfolio)
        if consistency.unmanaged_open_ids:
            logger.error(
                "Unmanaged open positions detected; deterministic exits are degraded: %s",
                ",".join(consistency.unmanaged_open_ids),
            )
        open_positions = [p for p in portfolio.positions if p.status == "OPEN"]

        for pos in open_positions:
            # Skip positions already closed (e.g. by Portfolio.process_tick SL/TP)
            if pos.status != "OPEN":
                continue

            # Spread blowout check (Gap #15): exit if bid-ask > 3% of premium
            if (
                order_book
                and hasattr(order_book, "bids")
                and order_book.bids
                and order_book.asks
            ):
                blowout = self._trade_manager.check_spread_blowout(
                    pos.id,
                    order_book.bids[0].price,
                    order_book.asks[0].price,
                    premium=current_price,
                )
                if blowout:
                    portfolio.close_position(pos.id, blowout.exit_price, blowout.reason)
                    self._trade_manager.unregister_position(pos.id)
                    logger.info(
                        "Position %s closed: SPREAD BLOWOUT at %.2f",
                        pos.id,
                        blowout.exit_price,
                    )
                    return True

            # Scale-in check (Fabio Rule 4: 40/30/30)
            add_fraction = self._trade_manager.check_scale_in(pos.id, current_price)
            if add_fraction > 0:
                portfolio.add_to_position(pos.id, add_fraction, current_price)

            # CVD kill signal check (Fabio: exit when CVD diverges against position)
            # Grace period: skip CVD kill for first 3 ticks after entry
            metrics = self._trade_manager.get_position_metrics(pos.id)
            tick_count = int(metrics["tick_count"]) if metrics else -1
            if cvd_divergence and (metrics is None or tick_count >= 3):
                cvd_exit = self._trade_manager.apply_cvd_kill_signal(
                    pos.id, cvd_divergence, current_price
                )
                if cvd_exit:
                    portfolio.close_position(
                        pos.id, cvd_exit.exit_price, cvd_exit.reason
                    )
                    self._trade_manager.unregister_position(pos.id)
                    logger.info(
                        f"Position {pos.id} closed: CVD kill signal at {cvd_exit.exit_price:.2f}"
                    )
                    return True

            # CVD-based breakeven: move SL to entry when CVD confirms direction
            if cvd_slope != 0.0 and metrics is not None:
                self._trade_manager.apply_cvd_breakeven(pos.id, cvd_slope)

            # VWAP trail (Gap #9): trail SL to VWAP bands at 1.5R profit
            if amt_result and getattr(amt_result, "session_vwap", 0) > 0:
                self._trade_manager.apply_vwap_trail(
                    pos.id,
                    current_price,
                    amt_result.session_vwap,
                    getattr(amt_result, "vwap_upper_1", 0),
                    getattr(amt_result, "vwap_lower_1", 0),
                    getattr(amt_result, "vwap_upper_2", 0),
                    getattr(amt_result, "vwap_lower_2", 0),
                )

            # Imbalance tighten (Gap #2): tighten SL when stacked imbalances oppose position
            if imbalances:
                self._trade_manager.check_imbalance_tighten(
                    pos.id,
                    imbalances,
                    current_price,
                )

            # Partition Exit Manager (FR-08): P1/P2/P3 + BE + counter-aggression
            p_state = self._partition_states.get(pos.id)
            if p_state is not None:
                entry = float(pos.entry_price)
                sl = float(getattr(pos, "initial_stop", getattr(pos, "stop_loss", 0)))
                tp = float(getattr(pos, "take_profit", 0))
                is_long = (
                    pos.side.value == "LONG"
                    if hasattr(pos.side, "value")
                    else str(pos.side) == "LONG"
                )
                if sl > 0 and tp > 0 and entry > 0:
                    partition_signals = self._partition_manager.check_exits(
                        entry_price=entry,
                        initial_stop=sl,
                        take_profit=tp,
                        current_price=current_price,
                        is_long=is_long,
                        cvd_slope=cvd_slope,
                        state=p_state,
                    )
                    for psig in partition_signals:
                        if psig.exit_type in ("COUNTER_AGGRESSION", "TRAIL"):
                            # Full exit
                            portfolio.close_position(pos.id, psig.price, psig.exit_type)
                            self._trade_manager.unregister_position(pos.id)
                            self._partition_states.pop(pos.id, None)
                            logger.info(
                                "Position %s closed: %s at %.2f",
                                pos.id,
                                psig.exit_type,
                                psig.price,
                            )
                            return True
                        elif psig.exit_type in (
                            "PARTITION_1",
                            "PARTITION_2",
                            "PARTITION_3",
                        ):
                            # Partial exit
                            size_before = pos.size
                            realized_pnl = portfolio.partial_close_position(
                                pos.id,
                                psig.size_pct,
                                psig.price,
                                psig.exit_type,
                            )
                            logger.info(
                                "Position %s partial: %s %.0f%% at %.2f realized=%.2f",
                                pos.id,
                                psig.exit_type,
                                psig.size_pct * 100,
                                psig.price,
                                realized_pnl,
                            )

                # Apply partition manager's trail SL (breakeven/P3 trail) to trade manager
                p_state_after = self._partition_states.get(pos.id)
                if p_state_after and p_state_after.trail_sl is not None:
                    self._trade_manager.adjust_stop_loss(pos.id, p_state_after.trail_sl)

            exit_sig = self._trade_manager.check_position(
                pos.id,
                current_price,
                time_to_close=time_to_close,
            )
            if exit_sig:
                logger.info(
                    "Exit trigger: pos=%s reason=%s price=%.2f tick=%d",
                    pos.id,
                    exit_sig.reason,
                    exit_sig.exit_price,
                    tick_count,
                )
                if exit_sig.reason == ExitReason.PARTIAL_TAKE_PROFIT:
                    # Runner mode: close 75% at target, keep 25% trailing
                    # Standard partial: close 50%
                    metrics = self._trade_manager.get_position_metrics(pos.id)
                    if metrics and bool(metrics["runner_active"]):
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
                        side = (
                            pos.side.value
                            if hasattr(pos.side, "value")
                            else str(pos.side)
                        )
                        self._on_partial_exit(
                            pos.id,
                            side,
                            pos.entry_price,
                            exit_sig.exit_price,
                            partial_pct,
                            size_before * partial_pct,
                            pos.size,
                            realized_pnl,
                        )
                    # Do NOT unregister — position is still open with remaining size
                    return False
                else:
                    # Full close
                    portfolio.close_position(
                        pos.id, exit_sig.exit_price, exit_sig.reason
                    )
                    self._trade_manager.unregister_position(pos.id)
                    # Track daily losses on stop loss exits
                    if exit_sig.reason == ExitReason.STOP_LOSS:
                        self._trade_manager.record_loss(pos.symbol)
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

    def register_position(
        self, symbol: str, position: Position, signal: Signal
    ) -> None:
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
        # Ensure Decimal types are converted to float for trade_manager
        entry_price = (
            float(position.entry_price)
            if hasattr(position.entry_price, "__float__")
            else position.entry_price
        )
        stop_loss = (
            float(signal.stop_loss)
            if hasattr(signal.stop_loss, "__float__")
            else signal.stop_loss
        )
        take_profit = (
            float(signal.take_profit)
            if hasattr(signal.take_profit, "__float__")
            else signal.take_profit
        )

        self._trade_manager.register_position(
            position_id=position.id,
            symbol=symbol,
            side="LONG" if signal.type == SignalType.BUY else "SHORT",
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            allow_trail=allow_trail,
            market_state=market_state,
            enable_scale_in=scale_in,
            session_phase=session_phase,
            is_expiry=is_expiry,
        )
        # Initialize partition exit state for this position
        self._partition_states[position.id] = PartitionState()

    def has_managed_positions(self, symbol: str) -> bool:
        return self._trade_manager.has_managed_positions(symbol)

    def get_position_consistency(self, portfolio: Portfolio, symbol: str | None = None):
        """Return a comparison of portfolio-open positions vs lifecycle-managed positions."""
        open_ids = portfolio.open_position_ids()
        return self._trade_manager.get_position_consistency(open_ids, symbol=symbol)

    def reconcile_portfolio(
        self, portfolio: Portfolio, symbol: str | None = None
    ) -> tuple[str, ...]:
        """Reconcile managed lifecycle state with the portfolio's open positions."""
        open_ids = portfolio.open_position_ids()
        return self._trade_manager.sync_with_open_position_ids(open_ids, symbol=symbol)

    def ensure_position_consistency(
        self, portfolio: Portfolio, symbol: str | None = None
    ):
        """Reconcile stale manager state and return the resulting consistency view."""
        stale_ids = self.reconcile_portfolio(portfolio, symbol=symbol)
        consistency = self.get_position_consistency(portfolio, symbol=symbol)
        if stale_ids:
            logger.warning(
                "Reconciled stale managed positions for %s: %s",
                symbol or "ALL",
                ",".join(stale_ids),
            )
        return consistency

    def sync_closed(self, closed_positions: list) -> None:
        """Unregister positions that were closed by Portfolio (SL/TP hits).

        Prevents double-close when check_exits runs afterwards.
        """
        for pos in closed_positions:
            self._trade_manager.unregister_position(pos.id)

    def in_cooldown(self, symbol: str) -> bool:
        return self._trade_manager.in_cooldown(symbol)
