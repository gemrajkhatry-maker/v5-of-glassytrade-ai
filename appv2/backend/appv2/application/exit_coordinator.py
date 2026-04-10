"""Exit Coordinator — monitors open positions, decides exits, executes.

Pipeline:
  Tick → Check Exit Conditions → Log → Execute Exit → Update State
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from appv2.domain.models.trade import Trade
from appv2.domain.services.exit_engine import check_exit
from appv2.domain.services.trail_engine import TrailEngine
from appv2.application.trade_lifecycle import TradeLifecycleHandler
from appv2.application.risk_orchestrator import RiskOrchestrator
from appv2.domain.services.trade_journal import TradeJournal
from appv2.domain.services.post_trade_analytics import PostTradeAnalytics

logger = logging.getLogger(__name__)


class ExitCoordinator:
    """Monitors and executes position exits."""

    def __init__(
        self,
        trade_lifecycle: TradeLifecycleHandler,
        risk: RiskOrchestrator,
        journal: TradeJournal | None = None,
        analytics: PostTradeAnalytics | None = None,
        broker=None,
    ):
        self._trade_lifecycle = trade_lifecycle
        self._risk = risk
        self._journal = journal
        self._analytics = analytics
        self._broker = broker
        self._trail_engine = TrailEngine()

    def check_exits(
        self,
        symbol: str,
        current_price: float,
        atr: float = 0.0,
        vwap: float = 0.0,
        cvd_slope: float = 0.0,
        force_exit: bool = False,
    ) -> list[Trade]:
        """Check all open positions for a symbol and exit if needed.

        Returns:
            List of closed trades.
        """
        closed_trades = []
        trades = self._trade_lifecycle.get_open_trades(symbol)

        for trade in trades:
            is_long = trade.side.value == "BUY"

            # 1. Check trailing stop
            if atr > 0 or vwap > 0:
                trail_result = self._trail_engine.update(
                    trade_id=trade.trade_id,
                    is_long=is_long,
                    current_price=current_price,
                    current_sl=trade.stop_loss,
                    entry_price=trade.entry_price,
                    atr=atr,
                    vwap=vwap,
                    cvd_slope=cvd_slope,
                )
                if trail_result.new_stop_loss > 0:
                    trade.stop_loss = trail_result.new_stop_loss

            # 2. Check exit conditions
            exit_decision = check_exit(
                current_price=current_price,
                stop_loss=trade.stop_loss,
                take_profit=trade.take_profit,
                trail_price=trade.trail_price,
                is_long=is_long,
                force_exit=force_exit,
            )

            if exit_decision.should_exit:
                # 3. Execute exit
                closed = self._execute_exit(trade, exit_decision.exit_price, exit_decision.reason)
                if closed:
                    closed_trades.append(closed)

        return closed_trades

    def _execute_exit(
        self,
        trade: Trade,
        exit_price: float,
        reason: str,
    ) -> Trade | None:
        """Execute trade exit."""
        # Execute via broker if live
        if self._broker:
            try:
                # Square off position
                self._broker.square_off_position(trade.symbol)
            except Exception as e:
                logger.error("Exit execution error for %s: %s", trade.symbol, e)

        # Close trade in lifecycle
        closed = self._trade_lifecycle.close_trade(
            trade_id=trade.trade_id,
            exit_price=exit_price,
            exit_reason=reason,
        )

        if closed:
            # Record in journal
            if self._journal:
                self._journal.log_exit(closed.to_dict())

            # Record in analytics
            if self._analytics:
                self._analytics.add_trade(closed.to_dict())

            # Update risk
            is_win = closed.realized_pnl > 0
            self._risk.post_trade_update(closed.symbol, closed.realized_pnl, is_win)
            self._risk.position_closed(closed.symbol)

            logger.info(
                "EXIT: %s | %s | Entry: %.4f | Exit: %.4f | PnL: ₹%.2f | Reason: %s",
                trade.symbol, trade.side.value,
                trade.entry_price, exit_price,
                closed.realized_pnl, reason,
            )

        return closed

    def partial_exit(
        self,
        trade: Trade,
        quantity: int,
        exit_price: float,
        reason: str = "PARTIAL_EXIT",
    ) -> Trade | None:
        """Exit partial position (for scale-in trades)."""
        # For partial exits, we close part of the position
        pnl = 0.0
        if trade.side.value == "BUY":
            pnl = (exit_price - trade.entry_price) * quantity
        else:
            pnl = (trade.entry_price - exit_price) * quantity

        trade.scale_count += 1
        trade.scale_in_prices.append(trade.entry_price)
        trade.realized_pnl += pnl

        logger.info(
            "PARTIAL EXIT: %s | %d lots @ %.4f | Partial PnL: ₹%.2f",
            trade.symbol, quantity, exit_price, pnl,
        )

        return trade
