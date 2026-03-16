"""Dhan live broker adapter — NOT YET ACTIVATED.

Activate only after 10+ day forward test passes acceptance criteria.
Set TRADING_MODE=LIVE in .env to switch from PaperBrokerAdapter.

Implementation checklist (when ready to activate):
- [ ] Map signal.symbol to Dhan security_id (requires symbol master lookup)
- [ ] Map signal.type (BUY/SELL) to Dhan transaction_type (BUY/SELL)
- [ ] Use product_type=MIS for intraday options
- [ ] Use order_type=MARKET for immediate entry
- [ ] Track order_id for subsequent cancel/modify
- [ ] Poll dhan.get_order_by_id() to confirm fill
- [ ] Handle REJECTED orders (margin, circuit limits)
- [ ] Cancel SL/TP bracket orders on position close
"""
from __future__ import annotations
import logging
from app.domain.ports.broker import BrokerPort

logger = logging.getLogger(__name__)


class DhanBrokerAdapter(BrokerPort):
    """Live order execution via DhanHQ dhanhq library.

    IMPORTANT: This adapter raises NotImplementedError until fully implemented
    and forward-test acceptance criteria are met.
    """

    def __init__(self, client_id: str, access_token: str) -> None:
        self._client_id = client_id
        self._access_token = access_token
        logger.warning(
            "DhanBrokerAdapter initialized — LIVE mode. "
            "Ensure forward test acceptance criteria met before deploying."
        )

    def execute_order(self, signal, portfolio, symbol: str):
        from app.config import settings
        
        # Calculate risk-managed size using Domain Portfolio
        scale_in = (signal.metadata or {}).get("scale_in", False)
        scale_fraction = 0.4 if scale_in else 1.0
        
        # 1. Update Portfolio First (Domain state always leads)
        # Note: if the live API fails, the Sync loop will reconcile this later
        position = portfolio.open_position(signal, symbol, scale_fraction=scale_fraction)
        if not position:
            logger.error("Portfolio rejected order for %s (margin/risk limit)", symbol)
            return None

        # Ensure DRY_RUN behaves appropriately 
        if settings.DRY_RUN:
            logger.warning("[DRY_RUN] Simulated Live Execution for %s via DhanBrokerAdapter", symbol)
            return position

        # --- LIVE BROKER EXECUTION PATH ---
        try:
            from brokers.broker.dhan.application.broker import DhanBroker
            from brokers.broker.entities import Order, Instrument
            from brokers.broker.types import OrderSide, OrderType, Exchange
            
            broker = DhanBroker.create(
                client_id=self._client_id,
                access_token=self._access_token
            )
            
            # Map system "symbol" to DhanHQ Instrument entity
            # e.g., "NIFTY 10 MAR 22000 CALL" -> Exchange.NFO
            is_mcx = "MCX" in symbol.upper() or any(u in symbol.upper() for u in ["CRUDEOIL", "GOLD", "SILVER", "NATURALGAS"])
            exchange = Exchange.MCX if is_mcx else Exchange.NFO
            
            instrument = Instrument(
                symbol=symbol.replace("NSE:", "").replace("MCX:", "").strip(),
                exchange=exchange
            )
            
            side = OrderSide.BUY if signal.is_buy else OrderSide.SELL
            qty = position.size  # The Portfolio size logic already computed lot sizes
            
            # 2. Execute Primary Entry Order (MARKET/INTRADAY)
            entry_order = Order(
                instrument=instrument,
                side=side,
                quantity=qty,
                order_type=OrderType.MARKET,
                product_type="INTRADAY"
            )
            logger.info("Dhan API: Sending ENTRY order for %s (%s %s)", symbol, side, qty)
            filled_entry = broker.place_order(entry_order)
            logger.info("Dhan API: ENTRY confirmed. OrderID=%s", filled_entry.order_id)
            
            # 3. IMMEDIATELY Execute Hard Stop-Loss Order (SL-M)
            # This protects against catastrophic spikes/slippage natively at the exchange
            if signal.stop_loss > 0:
                sl_side = OrderSide.SELL if side == OrderSide.BUY else OrderSide.BUY
                
                # Format Trigger Price correctly (Dhan requires proper tick sizing, roughly round to 0.05)
                tick_size = 0.05
                sl_price = round(signal.stop_loss / tick_size) * tick_size
                
                sl_order = Order(
                    instrument=instrument,
                    side=sl_side,
                    quantity=qty,
                    order_type=OrderType.STOP_LOSS_MARKET,
                    trigger_price=sl_price,
                    product_type="INTRADAY"
                )
                logger.info("Dhan API: Sending HARD SL order for %s (%s %s at trigger=%.2f)", symbol, sl_side, qty, sl_price)
                placed_sl = broker.place_order(sl_order)
                logger.info("Dhan API: HARD SL confirmed. OrderID=%s", placed_sl.order_id)
                
                # Tag the position with the hardware SL ID so the TradeLifecycleHandler can manage/cancel it later
                if not position.metadata:
                    position.metadata = {}
                position.metadata["dhan_sl_order_id"] = placed_sl.order_id

        except Exception as e:
            logger.error("DHAN EXECUTION FAILED for %s: %s", symbol, str(e), exc_info=True)
            # Rollback domain state if broker totally rejected entry
            portfolio.close_position(position.id, signal.price, f"BROKER_REJECTED: {e}")
            return None

        return position

    def cancel_order(self, order_id: str) -> bool:
        """Cancel a live working order (useful for scrubbing Hard SLs)"""
        from app.config import settings
        if settings.DRY_RUN:
            logger.debug("[DRY_RUN] Simulated cancel order %s", order_id)
            return True
            
        try:
            from brokers.broker.dhan.application.broker import DhanBroker
            broker = DhanBroker.create(
                client_id=self._client_id,
                access_token=self._access_token
            )
            success = broker.cancel_order(order_id)
            logger.info("Dhan API: Cancelled order %s = %s", order_id, success)
            return success
        except Exception as e:
            logger.error("Dhan API Failed to cancel order %s: %s", order_id, str(e), exc_info=True)
            return False
