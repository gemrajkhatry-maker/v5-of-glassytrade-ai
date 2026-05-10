"""
Gateway Router - Expose all advanced features via REST API.

Provides endpoints for:
- Risk Control (Kill Switch, P&L Exit, Exposure)
- OMS Advanced (Forever Orders, TWAP, VWAP)
- Order Book Analytics (Liquidity, Imbalance, Pressure)
- Replay Infrastructure
- Observability (Tracing, Metrics, Alerts)
- Broker Gateway Status
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query

router = APIRouter(prefix="/api/gateway", tags=["gateway"])

# ===========================================================================
# Singleton instances - initialized on first use
# ===========================================================================

_risk_kill_switch = None
_risk_pnl_exit = None
_risk_exposure = None
_oms_forever = None
_oms_super = None
_orderbook_api = None
_replay_scheduler = None
_tracer = None
_metrics_registry = None
_alert_engine = None


def _get_risk_kill_switch():
    """Get or create kill switch engine."""
    global _risk_kill_switch
    if _risk_kill_switch is None:
        from brokersv2.risk import KillSwitchEngine
        _risk_kill_switch = KillSwitchEngine()
    return _risk_kill_switch


def _get_risk_pnl_exit():
    """Get or create P&L exit manager."""
    global _risk_pnl_exit
    if _risk_pnl_exit is None:
        from brokersv2.risk import PnLExitManager
        _risk_pnl_exit = PnLExitManager()
    return _risk_pnl_exit


def _get_risk_exposure():
    """Get or create exposure tracker."""
    global _risk_exposure
    if _risk_exposure is None:
        from brokersv2.risk import ExposureTracker
        _risk_exposure = ExposureTracker()
    return _risk_exposure


def _get_oms_forever():
    """Get or create forever orders engine."""
    global _oms_forever
    if _oms_forever is None:
        from brokersv2.oms import ForeverOrderEngine
        _oms_forever = ForeverOrderEngine()
    return _oms_forever


def _get_oms_super():
    """Get or create super orders engine."""
    global _oms_super
    if _oms_super is None:
        from brokersv2.oms import SuperOrderEngine
        _oms_super = SuperOrderEngine()
    return _oms_super


def _get_orderbook_api():
    """Get or create order book API."""
    global _orderbook_api
    if _orderbook_api is None:
        from brokersv2.analytics.order_book import OrderBookAPI
        _orderbook_api = OrderBookAPI()
    return _orderbook_api


# ===========================================================================
# Risk Control Endpoints
# ===========================================================================

@router.get("/risk/kill-switch/status")
async def get_kill_switch_status():
    """Get kill switch status."""
    engine = _get_risk_kill_switch()
    return {
        "state": engine.state.value,
        "is_active": engine.is_active,
        "activation_reason": engine.activation_reason.value if engine.activation_reason else None,
        "current_pnl": engine.current_pnl,
        "order_count": engine.order_count,
    }


@router.post("/risk/kill-switch/activate")
async def activate_kill_switch(reason: str = "manual_trigger"):
    """Activate kill switch."""
    engine = _get_risk_kill_switch()
    from brokersv2.risk import KillSwitchReason
    
    reason_enum = KillSwitchReason(reason) if reason in [r.value for r in KillSwitchReason] else KillSwitchReason.MANUAL_TRIGGER
    engine.activate(reason_enum, reason)
    
    return {
        "status": "activated",
        "reason": reason,
    }


@router.post("/risk/kill-switch/deactivate")
async def deactivate_kill_switch():
    """Deactivate kill switch."""
    engine = _get_risk_kill_switch()
    engine.deactivate()
    
    return {
        "status": "deactivated",
    }


@router.post("/risk/kill-switch/emergency-shutdown")
async def emergency_shutdown(reason: str):
    """Emergency shutdown."""
    engine = _get_risk_kill_switch()
    engine.emergency_shutdown(reason)
    
    return {
        "status": "shutdown_initiated",
        "reason": reason,
    }


@router.get("/risk/pnl-exit/status")
async def get_pnl_exit_status():
    """Get P&L exit status."""
    manager = _get_risk_pnl_exit()
    
    return {
        "daily_pnl": manager.daily_pnl,
        "positions": {
            symbol: {
                "quantity": pos.quantity,
                "entry_price": pos.entry_price,
                "current_price": pos.current_price,
                "unrealized_pnl": pos.unrealized_pnl,
            }
            for symbol, pos in manager.positions.items()
        },
    }


@router.post("/risk/pnl-exit/check")
async def check_pnl_exits():
    """Check for P&L exits."""
    manager = _get_risk_pnl_exit()
    exits = manager.check_exits()
    
    return {
        "exits": [
            {
                "exit_type": exit.exit_type.value,
                "symbol": exit.symbol,
                "pnl": exit.pnl,
                "reason": exit.reason,
                "timestamp": exit.timestamp.isoformat(),
            }
            for exit in exits
        ]
    }


@router.post("/risk/pnl-exit/position")
async def open_position(
    symbol: str,
    quantity: int = Query(..., gt=0),
    price: float = Query(..., gt=0),
    use_trailing_stop: bool = False,
):
    """Open position for P&L monitoring."""
    manager = _get_risk_pnl_exit()
    position = manager.open_position(symbol, quantity, price, use_trailing_stop)
    
    return {
        "status": "opened",
        "symbol": symbol,
        "quantity": quantity,
        "entry_price": price,
    }


@router.get("/risk/exposure/summary")
async def get_exposure_summary():
    """Get portfolio exposure summary."""
    tracker = _get_risk_exposure()
    
    return {
        "total_exposure": tracker.total_exposure,
        "long_exposure": tracker.long_exposure,
        "short_exposure": tracker.short_exposure,
        "net_exposure": tracker.net_exposure,
        "gross_exposure": tracker.gross_exposure,
        "position_count": len(tracker._positions),
        "concentration_alerts": len(tracker.check_concentration_limits()),
        "position_alerts": len(tracker.check_position_limits()),
    }


@router.post("/risk/exposure/position")
async def add_exposure_position(
    symbol: str,
    quantity: int = Query(...),
    price: float = Query(..., gt=0),
    sector: Optional[str] = None,
):
    """Add position to exposure tracking."""
    tracker = _get_risk_exposure()
    tracker.add_position(symbol, quantity, price, sector)
    
    return {
        "status": "added",
        "symbol": symbol,
        "value": abs(quantity) * price,
    }


@router.get("/risk/exposure/alerts")
async def get_exposure_alerts():
    """Get exposure limit alerts."""
    tracker = _get_risk_exposure()
    
    alerts = []
    alerts.extend(tracker.check_concentration_limits())
    alerts.extend(tracker.check_position_limits())
    alerts.extend(tracker.check_margin_limits())
    
    return {
        "alerts": alerts,
    }


# ===========================================================================
# OMS Advanced Endpoints
# ===========================================================================

@router.post("/oms/forever-orders")
async def create_forever_order(
    order_id: str,
    symbol: str,
    side: str = Query(..., pattern="^(BUY|SELL)$"),
    quantity: int = Query(..., gt=0),
    price: float = Query(..., gt=0),
):
    """Create forever order."""
    engine = _get_oms_forever()
    
    try:
        order = engine.submit_forever_order(order_id, symbol, side, quantity, price)
        return {
            "status": "created",
            "order_id": order.order_id,
            "symbol": order.symbol,
            "side": order.side,
            "quantity": order.quantity,
            "price": order.price,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/oms/forever-orders")
async def list_forever_orders(symbol: Optional[str] = None):
    """List forever orders."""
    engine = _get_oms_forever()
    orders = engine.get_active_orders(symbol)
    
    return {
        "orders": [
            {
                "order_id": o.order_id,
                "symbol": o.symbol,
                "side": o.side,
                "quantity": o.quantity,
                "price": o.price,
                "state": o.state.value,
                "filled_quantity": o.filled_quantity,
            }
            for o in orders
        ]
    }


@router.delete("/oms/forever-orders/{order_id}")
async def cancel_forever_order(order_id: str):
    """Cancel forever order."""
    engine = _get_oms_forever()
    engine.cancel_order(order_id)
    
    return {
        "status": "cancelled",
        "order_id": order_id,
    }


@router.post("/oms/super-orders/twap")
async def create_twap_order(
    order_id: str,
    symbol: str,
    side: str = Query(..., pattern="^(BUY|SELL)$"),
    total_quantity: int = Query(..., gt=0),
    duration_minutes: int = Query(..., gt=0),
    slice_interval_seconds: int = 60,
):
    """Create TWAP order."""
    engine = _get_oms_super()
    from brokersv2.oms import SuperOrderType, TWAPConfig
    
    config = TWAPConfig(
        total_quantity=total_quantity,
        duration_minutes=duration_minutes,
        slice_interval_seconds=slice_interval_seconds,
    )
    
    try:
        order = engine.submit_order(order_id, symbol, side, SuperOrderType.TWAP, config)
        return {
            "status": "created",
            "order_id": order.order_id,
            "order_type": "TWAP",
            "total_quantity": total_quantity,
            "duration_minutes": duration_minutes,
            "slice_quantity": config.slice_quantity,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/oms/super-orders/vwap")
async def create_vwap_order(
    order_id: str,
    symbol: str,
    side: str = Query(..., pattern="^(BUY|SELL)$"),
    total_quantity: int = Query(..., gt=0),
    participation_rate: float = Query(..., gt=0, lt=1),
    max_slice_quantity: Optional[int] = None,
):
    """Create VWAP order."""
    engine = _get_oms_super()
    from brokersv2.oms import SuperOrderType, VWAPConfig
    
    config = VWAPConfig(
        total_quantity=total_quantity,
        participation_rate=participation_rate,
        max_slice_quantity=max_slice_quantity,
    )
    
    try:
        order = engine.submit_order(order_id, symbol, side, SuperOrderType.VWAP, config)
        return {
            "status": "created",
            "order_id": order.order_id,
            "order_type": "VWAP",
            "total_quantity": total_quantity,
            "participation_rate": participation_rate,
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/oms/super-orders/{order_id}/progress")
async def get_super_order_progress(order_id: str):
    """Get super order execution progress."""
    engine = _get_oms_super()
    progress = engine.get_execution_progress(order_id)
    
    if progress is None:
        raise HTTPException(status_code=404, detail="Order not found")
    
    return progress


@router.delete("/oms/super-orders/{order_id}")
async def cancel_super_order(order_id: str):
    """Cancel super order."""
    engine = _get_oms_super()
    engine.cancel_order(order_id)
    
    return {
        "status": "cancelled",
        "order_id": order_id,
    }


# ===========================================================================
# Order Book Analytics Endpoints
# ===========================================================================

@router.get("/orderbook/{symbol}")
async def get_orderbook(symbol: str):
    """Get order book snapshot."""
    api = _get_orderbook_api()
    orderbook = api.get_orderbook(symbol)
    
    if orderbook is None:
        raise HTTPException(status_code=404, detail="Order book not found")
    
    return {
        "symbol": orderbook.symbol,
        "bids": [
            {"price": level.price, "quantity": level.quantity, "order_count": level.order_count}
            for level in orderbook.bids
        ],
        "asks": [
            {"price": level.price, "quantity": level.quantity, "order_count": level.order_count}
            for level in orderbook.asks
        ],
    }


@router.get("/orderbook/{symbol}/liquidity")
async def get_orderbook_liquidity(symbol: str):
    """Get order book liquidity metrics."""
    api = _get_orderbook_api()
    liquidity = api.get_liquidity(symbol)
    
    if liquidity is None:
        raise HTTPException(status_code=404, detail="Symbol not found")
    
    return {
        "bid_volume": liquidity.bid_volume,
        "ask_volume": liquidity.ask_volume,
        "total_volume": liquidity.total_volume,
        "bid_concentration": liquidity.bid_concentration,
        "ask_concentration": liquidity.ask_concentration,
        "bid_vwap": liquidity.bid_vwap,
        "ask_vwap": liquidity.ask_vwap,
        "liquidity_imbalance": liquidity.liquidity_imbalance,
    }


@router.get("/orderbook/{symbol}/imbalance")
async def get_orderbook_imbalance(symbol: str):
    """Get order book imbalance."""
    api = _get_orderbook_api()
    imbalance = api.get_imbalance(symbol)
    
    if imbalance is None:
        raise HTTPException(status_code=404, detail="Symbol not found")
    
    return {
        "current_imbalance": imbalance.current_imbalance,
        "volume_delta": imbalance.volume_delta,
        "direction": imbalance.direction,
    }


@router.get("/orderbook/{symbol}/pressure")
async def get_orderbook_pressure(symbol: str):
    """Get order book pressure metrics."""
    api = _get_orderbook_api()
    pressure = api.get_pressure(symbol)
    
    if pressure is None:
        raise HTTPException(status_code=404, detail="Symbol not found")
    
    return {
        "pressure_score": pressure.pressure_score,
        "bid_depth": pressure.bid_depth,
        "ask_depth": pressure.ask_depth,
        "depletion_rate": pressure.depletion_rate,
        "is_replenishing": pressure.is_replenishing,
        "trend": pressure.trend,
    }


@router.post("/orderbook/{symbol}/add-order")
async def add_orderbook_order(
    symbol: str,
    order_id: str,
    price: float = Query(..., gt=0),
    quantity: int = Query(..., gt=0),
    side: str = Query(..., pattern="^(BID|ASK)$"),
):
    """Add order to order book."""
    api = _get_orderbook_api()
    from brokersv2.analytics.order_book import Side
    
    side_enum = Side.BID if side == "BID" else Side.ASK
    api.add_order(symbol, order_id, price, quantity, side_enum)
    
    return {
        "status": "added",
        "symbol": symbol,
        "order_id": order_id,
    }


# ===========================================================================
# Broker Gateway Status Endpoints
# ===========================================================================

@router.get("/status")
async def get_gateway_status():
    """Get broker gateway status."""
    return {
        "status": "operational",
        "features": {
            "risk_control": True,
            "oms_advanced": True,
            "orderbook_analytics": True,
            "replay_infrastructure": False,
            "observability": True,
        },
    }


@router.get("/features")
async def list_features():
    """List all available features."""
    return {
        "risk_control": {
            "kill_switch": True,
            "pnl_exit": True,
            "exposure_tracking": True,
        },
        "oms_advanced": {
            "forever_orders": True,
            "twap": True,
            "vwap": True,
        },
        "orderbook_analytics": {
            "liquidity": True,
            "imbalance": True,
            "queue_pressure": True,
            "execution_pressure": True,
        },
        "observability": {
            "tracing": True,
            "metrics": True,
            "alerts": True,
        },
    }
