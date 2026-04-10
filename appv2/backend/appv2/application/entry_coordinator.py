"""Entry Coordinator — validates signals, enriches with options, executes orders.

Pipeline:
  Signal → Validate → Enrich (options) → Risk Check → Execute → Persist
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from appv2.domain.models.signal import Signal
from appv2.domain.models.trade import Trade
from appv2.domain.enums.signal_type import OrderSide, OrderType
from appv2.application.trade_lifecycle import TradeLifecycleHandler
from appv2.application.risk_orchestrator import RiskOrchestrator
from appv2.domain.services.signal_ttl_manager import SignalTTLManager
from appv2.domain.services.strike_selector import select_strike
from appv2.domain.services.order_router import OrderRouter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExecutionResult:
    success: bool
    trade: Trade | None = None
    signal: Signal | None = None
    reason: str = ""
    order_id: str = ""


class EntryCoordinator:
    """Coordinates entry from signal to trade execution."""

    def __init__(
        self,
        trade_lifecycle: TradeLifecycleHandler,
        risk: RiskOrchestrator,
        signal_ttl: SignalTTLManager,
        broker=None,
        option_chain_fetcher=None,
    ):
        self._trade_lifecycle = trade_lifecycle
        self._risk = risk
        self._signal_ttl = signal_ttl
        self._broker = broker
        self._option_chain_fetcher = option_chain_fetcher
        self._order_router = OrderRouter()

    async def execute_signal(
        self,
        signal: Signal,
        lot_size: int = 50,
        is_live: bool = False,
    ) -> ExecutionResult:
        """Execute a signal through the full entry pipeline.

        Args:
            signal: Generated signal
            lot_size: Lot size for the contract
            is_live: If True, place live order; if False, paper trade
        """
        # 1. Validate signal (TTL, not duplicate)
        if signal.is_expired:
            return ExecutionResult(False, reason="Signal expired")

        if not self._signal_ttl.add_signal(signal):
            return ExecutionResult(False, reason="Duplicate signal")

        # 2. Option enrichment (select strike)
        enriched_signal = signal
        if self._option_chain_fetcher and signal.option_type == "":
            # Auto-select strike
            chain = await self._option_chain_fetcher.fetch_chain(
                signal.underlying_symbol
            )
            if chain:
                selection = select_strike(
                    chain=chain,
                    direction=signal.direction.value,
                    underlying_price=signal.entry_price,
                )
                if selection:
                    enriched_signal = Signal(
                        symbol=selection.contract.symbol,
                        underlying_symbol=signal.underlying_symbol,
                        direction=signal.direction,
                        setup_type=signal.setup_type,
                        entry_price=selection.contract.ltp or signal.entry_price,
                        stop_loss=signal.stop_loss,
                        take_profit=signal.take_profit,
                        confidence=signal.confidence,
                        market_state=signal.market_state,
                        session_phase=signal.session_phase,
                        strike_price=selection.contract.strike_price,
                        option_type=selection.contract.option_type,
                        expiry_date=selection.contract.expiry_date,
                        delta=selection.contract.delta,
                        theta=selection.contract.theta,
                    )

        # 3. Risk check
        risk_result = self._risk.pre_trade_check(
            symbol=enriched_signal.symbol,
            entry_price=enriched_signal.entry_price,
            stop_loss=enriched_signal.stop_loss,
            lot_size=lot_size,
        )
        if not risk_result.allowed:
            self._signal_ttl.mark_rejected(enriched_signal.symbol, risk_result.reason)
            return ExecutionResult(
                False, reason=f"Risk check failed: {risk_result.reason}",
            )

        # 4. Calculate position size
        from appv2.domain.services.position_sizer import calculate_position_size
        lots, actual_risk = calculate_position_size(
            capital=self._risk._capital,
            risk_per_trade_pct=self._risk._risk_pct,
            entry_price=enriched_signal.entry_price,
            stop_loss=enriched_signal.stop_loss,
            lot_size=lot_size,
        )
        if lots <= 0:
            return ExecutionResult(False, reason="Position size calculation failed")

        # 5. Execute order
        order_id = ""
        fill_price = enriched_signal.entry_price

        if self._broker and is_live:
            # Live order
            side = OrderSide.BUY if enriched_signal.direction.value == "LONG" else OrderSide.SELL
            routed = self._order_router.route(
                enriched_signal.symbol,
                side.value,
                "MARKET",
                lots,
            )
            try:
                order_id = await self._broker.place_order(
                    symbol=routed.symbol,
                    side=routed.side,
                    order_type=routed.order_type,
                    quantity=routed.quantity,
                    price=routed.price,
                    trigger_price=routed.trigger_price,
                )
                fill_price = routed.price  # Will be updated by fill
            except Exception as e:
                logger.error("Order execution failed: %s", e)
                return ExecutionResult(
                    False, reason=f"Execution error: {e}", signal=enriched_signal,
                )
        else:
            # Paper trade
            order_id = f"PAPER-{int(time.time())}"
            fill_price = enriched_signal.entry_price

        # 6. Create trade
        trade = self._trade_lifecycle.create_trade(
            signal=enriched_signal,
            quantity=lots * lot_size,
            lots=lots,
            fill_price=fill_price,
        )

        # 7. Mark signal filled
        self._signal_ttl.mark_filled(enriched_signal.symbol, order_id)

        # 8. Update risk
        self._risk.position_opened(enriched_signal.symbol)

        logger.info(
            "ENTRY EXECUTED: %s %s @ %.4f | Lots: %d | SL: %.4f | TP: %.4f | Order: %s",
            enriched_signal.symbol, enriched_signal.direction.value,
            fill_price, lots, enriched_signal.stop_loss,
            enriched_signal.take_profit, order_id,
        )

        return ExecutionResult(
            success=True, trade=trade, signal=enriched_signal, order_id=order_id,
        )
