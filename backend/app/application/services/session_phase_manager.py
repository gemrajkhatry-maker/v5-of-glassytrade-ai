"""Session phase management - extracted from trading_session.py.

Handles session phase checks and force-exit logic.
"""

from __future__ import annotations

import logging
from datetime import datetime

from app.core.async_boundary import ensure_sync_adapter_result
from app.shared.timezones import IST
from app.shared.parsing import resolve_session_market
from app.domain.trading.models.enums import Source
from app.domain.trading.events import TickReceived

log = logging.getLogger(__name__)


def check_session_phase(
    event: TickReceived,
    session,
    cache,
    exchange: str,
    exit_coordinator,
    risk_coordinator,
    storage,
    lifecycle_handler,
) -> None:
    """Check session phase and force-exit positions if Phase 5 (15:15-15:30 IST)."""
    try:
        _market = resolve_session_market(exchange, event.symbol)
        session_phase = get_session_info(
            timestamp=event.tick.time, market=_market
        )
        cache.set_last_session_info(session_phase)
        
        if not session_phase.force_exit:
            return
        
        with session._lock:
            open_positions = [
                p for p in session.portfolio.positions if p.status == "OPEN"
            ]
            
            for pos in open_positions:
                _close_price = event.tick.close
                realized_pnl = (
                    (_close_price - pos.entry_price) * pos.size
                    if pos.side.value == "LONG"
                    else (pos.entry_price - _close_price) * pos.size
                )
                
                session.portfolio.close_position(
                    pos.id,
                    _close_price,
                    "SESSION_CLOSE (Phase 5: 15:15 IST)",
                )
                
                if session and session.portfolio:
                    risk_coordinator.record_trade_result(
                        event.symbol, float(realized_pnl), session.portfolio
                    )
                
                exit_coordinator.on_position_closed(event.symbol, pos, session=session)
                lifecycle_handler.clear_partition_state(pos.id)
                
                if storage:
                    try:
                        ensure_sync_adapter_result(
                            "storage.delete_open_position",
                            storage.delete_open_position,
                            pos.id,
                        )
                    except Exception as e:
                        log.error(
                            "Failed to delete open position %s: %s", pos.id, e
                        )
                
                log.info(
                    "Session Phase 5: force-closed position %s at %.2f (pnl=%.2f)",
                    pos.id, _close_price, realized_pnl,
                )
        
        # Save session profile
        if (
            storage
            and cache.get_latest_amt()
            and not getattr(session, "_profile_saved", False)
        ):
            session_date = datetime.now(IST).strftime("%Y-%m-%d")
            save_session_profile(
                event.symbol, _market, session_date,
                cache.get_latest_amt(), cache.get_aggressive_prints(),
                cache.get_data(), storage
            )
    except Exception as e:
        log.critical(
            "Session phase check CRITICAL failure for %s — FORCING EXIT ALL POSITIONS",
            event.symbol, exc_info=True
        )
        force_close_all_positions(session, event.tick.close)


def get_session_info(timestamp, market):
    """Get session info for given timestamp."""
    from app.domain.fabio_ai.services.session_context import get_session_info as _get_si
    return _get_si(timestamp=timestamp, market=market)


def force_close_all_positions(session, price: float) -> None:
    """Emergency close all positions."""
    if not session:
        return
    with session._lock:
        for pos in list(session.portfolio.positions):
            if pos.status == "OPEN":
                session.portfolio.close_position(pos.id, price, "EMERGENCY")


def save_session_profile(
    symbol: str,
    market: str,
    session_date: str,
    last_amt: dict,
    aggressive_prints: list,
    data,
    storage,
) -> None:
    """Save session profile to storage."""
    from app.domain.fabio_ai.services.entry_gates.three_align import (
        cluster_aggressive_prints
    )
    from app.domain.constants import RECENT_DATA_WINDOW
    
    try:
        _print_clusters = (
            cluster_aggressive_prints(tuple(aggressive_prints))
            if aggressive_prints
            else []
        )
        
        profile_data = {
            "symbol": symbol,
            "market": market,
            "session_date": session_date,
            "poc": last_amt.get("poc", 0),
            "vah": last_amt.get("vah", 0),
            "val": last_amt.get("val", 0),
            "profile_shape": last_amt.get("profileShape", ""),
            "total_volume": sum(d.volume for d in data[-RECENT_DATA_WINDOW:]),
            "print_levels": [
                {"price": p, "side": "MIXED"}
                for p in _print_clusters[:5]
            ],
            "is_underlying": True,
        }
        ensure_sync_adapter_result(
            "storage.save_session_profile",
            storage.save_session_profile,
            profile_data,
        )
        log.info("Saved session profile for %s on %s", symbol, session_date)
    except Exception as e:
        log.error("Failed to save session profile: %s", e, exc_info=True)