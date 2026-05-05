"""Trade Lifecycle Handler — thin mediator between Portfolio and ExitEngine.

This handler orchestrates exit logic by:
1. Delegating to ExitEngine for stateless exit checks
2. Managing PartitionExitManager state for P1/P2/P3 exits
3. Firing callbacks for stop-outs, partial exits, and trade closures

All position lifecycle state is stored on Position entities directly.
No dual-state management needed — ExitEngine is stateless.
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import TYPE_CHECKING, Callable

from app.domain.fabio_ai.services.exit_engine import ExitEngine, ExitReason, ExitSignal
from app.domain.fabio_ai.services.partition_exit_manager import (
    PartitionExitManager,
    PartitionState,
)
from app.domain.trading.models.enums import CushionState, Side

if TYPE_CHECKING:
    from app.domain.trading.models.aggregates import Portfolio
    from app.domain.trading.models.entities import Signal, Position
    from app.domain.trading.models.value_objects import OHLC

logger = logging.getLogger(__name__)


class TradeLifecycleHandler:
    """Thin mediator between Portfolio and ExitEngine.

    The handler:
    - Does NOT maintain a position registry (ExitEngine is stateless)
    - Does NOT have dual-state consistency issues
    - Keeps PartitionState dict for P1/P2/P3 exit tracking
    - Delegates all exit logic to ExitEngine

    Methods removed (no longer needed with stateless ExitEngine):
    - register_position() — Position entity has lifecycle fields
    - ensure_position_consistency() — no dual state
    - reconcile_portfolio() — no dual state
    - sync_closed() — no registry to sync
    - get_position_consistency() — no dual state
    """

    def __init__(
        self,
        exit_engine: ExitEngine | None = None,
        on_stop_out: Callable[[float, str, str], None] | None = None,
        on_partial_exit: Callable[
            [str, str, float, float, float, float, float, str], None
        ]
        | None = None,
        persist_fn=None,
        event_logger=None,
        on_trade_closed: Callable[[str, float], None] | None = None,
    ) -> None:
        self._exit_engine = exit_engine or ExitEngine(persist_fn=persist_fn)
        self._partition_manager = PartitionExitManager()
        self._partition_states: dict[str, PartitionState] = {}
        self._partition_symbols: dict[str, str] = {}
        self._on_stop_out = on_stop_out
        self._on_partial_exit = on_partial_exit
        self._event_logger = event_logger
        self._on_trade_closed = on_trade_closed

    @property
    def exit_engine(self) -> ExitEngine:
        """Expose exit engine for RR filter and daily limit checks."""
        return self._exit_engine

    # Backward compatibility alias
    @property
    def trade_manager(self) -> ExitEngine:
        """Backward compatibility alias for exit_engine."""
        return self._exit_engine

    def check_exits(
        self,
        portfolio: Portfolio,
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
        """Check all open positions for exit conditions and scale-in triggers.

        Returns:
            True if a position was fully closed (so caller knows the slot is free).
        """
        open_positions = [p for p in portfolio.positions if p.status == "OPEN"]
        if not open_positions:
            return False

        # Iterate over a snapshot — close_position mutates portfolio.positions
        for pos in list(open_positions):
            # Skip positions already closed
            if pos.status != "OPEN":
                continue

            is_long = pos.side == Side.LONG or (
                hasattr(pos.side, "value") and pos.side.value == "LONG"
            )

            # 1. Spread blowout check (Gap #15): exit if bid-ask > 3% of premium
            if (
                order_book
                and hasattr(order_book, "bids")
                and order_book.bids
                and order_book.asks
            ):
                blowout = self._exit_engine.check_spread_blowout(
                    pos,
                    order_book.bids[0].price,
                    order_book.asks[0].price,
                    premium=current_price,
                )
                if blowout:
                    portfolio.close_position(pos.id, blowout.exit_price, blowout.reason)
                    self._record_close(pos)
                    self._exit_engine.record_exit_time(pos.symbol)
                    logger.info(
                        "Position %s closed: SPREAD BLOWOUT at %.2f",
                        pos.id,
                        blowout.exit_price,
                    )
                    return True

            # 2. Scale-in check (Fabio Rule 4: 40/30/30)
            add_fraction = self._exit_engine.check_scale_in(pos, current_price)
            if add_fraction > 0:
                portfolio.add_to_position(pos.id, add_fraction, current_price)

            # 2b. Pyramid add check (FR-09: LVN-based scaling with aggression ≥ 3.0)
            if amt_result and getattr(amt_result, "aggression_score", 0) >= 3.0:
                entry_lvns = getattr(pos, "entry_lvns", [])
                current_lvn = getattr(amt_result, "current_lvn", 0.0)
                pyramid = None
                if current_lvn > 0:
                    pyramid = self._exit_engine.check_pyramid(
                        pos,
                        current_price,
                        getattr(amt_result, "aggression_score", 0),
                        entry_lvns,
                        current_lvn,
                    )
                if pyramid:
                    size_mult, new_sl = pyramid
                    portfolio.add_to_position(pos.id, size_mult, current_price)
                    pos.stop_loss = new_sl  # Unified stop for all entries
                    # Record the LVN used for this add
                    if not hasattr(pos, "entry_lvns"):
                        pos.entry_lvns = []
                    if current_lvn > 0:
                        pos.entry_lvns.append(current_lvn)

            # 3. CVD kill signal check (grace period: skip first 3 ticks)
            if cvd_divergence and pos.tick_count >= 3:
                cvd_exit = self._exit_engine.apply_cvd_kill_signal(
                    pos, cvd_divergence, current_price
                )
                if cvd_exit:
                    portfolio.close_position(
                        pos.id, cvd_exit.exit_price, cvd_exit.reason
                    )
                    self._record_close(pos)
                    self._exit_engine.record_exit_time(pos.symbol)
                    logger.info(
                        f"Position {pos.id} closed: CVD kill signal at {cvd_exit.exit_price:.2f}"
                    )
                    return True

            # 4. CVD-based breakeven: move SL to entry when CVD confirms direction
            if cvd_slope != 0.0:
                if self._exit_engine.apply_cvd_breakeven(pos, cvd_slope):
                    if self._event_logger:
                        time_in_trade = 0.0
                        if pos.exit_time and pos.entry_time:
                            try:
                                from datetime import datetime as _dt

                                _exit = _dt.fromisoformat(pos.exit_time.replace("Z", "+00:00"))
                                _entry = _dt.fromisoformat(pos.entry_time.replace("Z", "+00:00"))
                                time_in_trade = (_exit - _entry).total_seconds()
                            except Exception:
                                time_in_trade = pos.tick_count * 0.5
                        self._event_logger.log_break_even_triggered(
                            symbol=symbol or pos.symbol,
                            position=pos,
                            pnl=float(pos.pnl or 0),
                            time_in_trade_s=time_in_trade,
                            reason=f"CVD slope {cvd_slope:.2f} confirmed {('LONG' if is_long else 'SHORT')}",
                        )

            # 5. VWAP trail (Gap #9): trail SL to VWAP bands at 1.5R profit
            if amt_result and getattr(amt_result, "session_vwap", 0) > 0:
                self._exit_engine.apply_vwap_trail(
                    pos,
                    current_price,
                    amt_result.session_vwap,
                    getattr(amt_result, "vwap_upper_1", 0),
                    getattr(amt_result, "vwap_lower_1", 0),
                    getattr(amt_result, "vwap_upper_2", 0),
                    getattr(amt_result, "vwap_lower_2", 0),
                )

            # 6. Imbalance tighten (Gap #2): tighten SL when stacked imbalances oppose
            if imbalances:
                self._exit_engine.check_imbalance_tighten(
                    pos,
                    imbalances,
                    current_price,
                )

            # 7. Partition Exit Manager (FR-08): P1/P2/P3 + BE + counter-aggression
            p_state = self._partition_states.get(pos.id)
            if p_state is not None:
                self._check_partition_exits(
                    portfolio, pos, p_state, current_price, cvd_slope, amt_result
                )

            # 8. Core exit check (SL, ATR trail, time stop, scratch)
            sl_price = self._resolve_stop_price(pos, tick_low, tick_high)
            exit_sig = self._exit_engine.check_position(
                pos,
                current_price,
                current_time=time.time(),
                time_to_close=time_to_close,
                cvd_slope=cvd_slope,
                stop_price=sl_price,
            )
            if exit_sig:
                logger.info(
                    "Exit trigger: pos=%s reason=%s price=%.2f tick=%d",
                    pos.id,
                    exit_sig.reason,
                    exit_sig.exit_price,
                    pos.tick_count,
                )
                # Full close
                portfolio.close_position(
                    pos.id, exit_sig.exit_price, exit_sig.reason
                )
                self._record_close(pos)
                self._exit_engine.record_exit_time(pos.symbol)
                if exit_sig.reason == ExitReason.STOP_LOSS:
                    self._exit_engine.record_loss(pos.symbol, exit_sig.exit_price)
                    if self._on_stop_out:
                        side = "LONG" if is_long else "SHORT"
                        self._on_stop_out(float(pos.entry_price), side, pos.symbol)
                logger.info(
                    f"Position {pos.id} closed: {exit_sig.reason} "
                    f"at {exit_sig.exit_price:.2f}"
                )
                return True

        return False

    def _check_partition_exits(
        self,
        portfolio: Portfolio,
        pos: Position,
        p_state: PartitionState,
        current_price: float,
        cvd_slope: float,
        amt_result,
    ) -> None:
        """Check partition exits (P1/P2/P3) for a position."""
        entry = float(pos.entry_price)
        sl = float(getattr(pos, "initial_stop", getattr(pos, "stop_loss", 0)))
        tp = float(getattr(pos, "take_profit", 0))
        is_long = (
            pos.side.value == "LONG"
            if hasattr(pos.side, "value")
            else str(pos.side) == "LONG"
        )

        if sl <= 0 or tp <= 0 or entry <= 0:
            return

        # Get current market state from AMT analysis or position metadata
        current_market_state = "BALANCED"
        if amt_result and hasattr(amt_result, "market_state"):
            current_market_state = getattr(amt_result, "market_state", "BALANCED")
            if not current_market_state:
                current_market_state = "BALANCED"

        partition_signals = self._partition_manager.check_exits(
            entry_price=entry,
            initial_stop=sl,
            take_profit=tp,
            current_price=current_price,
            is_long=is_long,
            cvd_slope=cvd_slope,
            state=p_state,
            market_state=current_market_state,
        )

        for psig in partition_signals:
            if psig.exit_type in ("COUNTER_AGGRESSION", "TRAIL"):
                # Full exit
                portfolio.close_position(pos.id, psig.price, psig.exit_type)
                self._record_close(pos)
                self._exit_engine.record_exit_time(pos.symbol)
                self._partition_states.pop(pos.id, None)
                logger.info(
                    "Position %s closed: %s at %.2f",
                    pos.id,
                    psig.exit_type,
                    psig.price,
                )
                return  # Exit after full close

            elif psig.exit_type in ("PARTITION_1", "PARTITION_2", "PARTITION_3"):
                # Partial exit
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
                # Fabio: partial PnL must feed into risk system
                self._exit_engine.add_realized_pnl(float(realized_pnl))
                if realized_pnl < 0:
                    self._exit_engine.record_loss(pos.symbol, float(pos.entry_price))

                # Fabio FR-09: After P1 exit (1R hit), check for pyramid add
                if psig.exit_type == "PARTITION_1":
                    self._check_pyramid_add(
                        portfolio=portfolio,
                        pos=pos,
                        current_price=current_price,
                        amt_result=amt_result,
                    )

        # Apply partition manager's trail SL (breakeven/P3 trail) to position
        p_state_after = self._partition_states.get(pos.id)
        if p_state_after and p_state_after.trail_sl and p_state_after.trail_sl > 0:
            self._exit_engine.adjust_stop_loss(pos, p_state_after.trail_sl)

    def initialize_partition_state(self, position_id: str, symbol: str | None = None) -> None:
        """Initialize partition exit state for a newly opened position."""
        self._partition_states[position_id] = PartitionState()
        if symbol:
            self._partition_symbols[position_id] = symbol

    def clear_partition_state(self, position_id: str) -> None:
        """Clear partition state when a position is closed."""
        self._partition_states.pop(position_id, None)
        self._partition_symbols.pop(position_id, None)

    def has_managed_positions(self, symbol: str, portfolio: Portfolio | None = None) -> bool:
        """Check if there are open positions for the symbol.

        Since ExitEngine is stateless, we just check partition states.
        This is used by LLM handler to decide if overseer should run.
        """
        if portfolio is not None:
            return any(
                p.is_open and getattr(p, "symbol", "") == symbol
                for p in portfolio.positions
            )

        # Partition states track positions we're managing, but when portfolio
        # is not supplied, fall back to recorded symbol ownership.
        if not symbol:
            return len(self._partition_states) > 0

        return any(
            pid.startswith(f"{symbol}:") or self._partition_symbols.get(pid) == symbol
            for pid in self._partition_states
        )

    def in_cooldown(self, symbol: str) -> bool:
        """Check if the symbol is in cooldown after an exit."""
        return self._exit_engine.in_cooldown(symbol)

    def _record_close(self, pos: Position) -> None:
        """Invoke the on_trade_closed callback after a full close."""
        self.clear_partition_state(pos.id)
        if self._on_trade_closed and hasattr(pos, "pnl") and pos.pnl is not None:
            self._on_trade_closed(pos.symbol, float(pos.pnl), pos.id)

    @staticmethod
    def _resolve_stop_price(pos: Position, tick_low: float, tick_high: float) -> float | None:
        """Return tick.low for LONG, tick.high for SHORT, or None if extremes unavailable."""
        if tick_low <= 0 and tick_high <= 0:
            return None
        is_long = (
            pos.side.value == "LONG"
            if hasattr(pos.side, "value")
            else str(pos.side) == "LONG"
        )
        return tick_low if is_long else tick_high

    def _check_pyramid_add(
        self,
        portfolio: Portfolio,
        pos: Position,
        current_price: float,
        amt_result,
    ) -> None:
        """Evaluate FR-09 pyramid add after PARTITION_1 partial exit."""
        if amt_result is None:
            return

        aggression_score = getattr(amt_result, "aggression_score", 0) or 0
        current_lvn = float(getattr(amt_result, "current_lvn", 0.0) or 0.0)
        if aggression_score < 3.0 or current_lvn <= 0:
            return

        entry_lvns = list(getattr(pos, "entry_lvns", []))
        pyramid = self._exit_engine.check_pyramid(
            pos,
            current_price,
            aggression_score,
            entry_lvns,
            current_lvn,
        )
        if pyramid is None:
            return

        size_mult, new_sl = pyramid
        if not portfolio.add_to_position(pos.id, size_mult, current_price):
            return

        pos.stop_loss = Decimal(str(new_sl))
        if current_lvn > 0 and current_lvn not in entry_lvns:
            pos.entry_lvns.append(current_lvn)

        logger.info(
            "Pyramid add executed for %s at %.2f size_mult=%.2f unified_sl=%.2f",
            pos.id,
            current_price,
            size_mult,
            new_sl,
        )
