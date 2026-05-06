"""Phase Manager — handles session phase transitions and force-exit logic.

Extracted from trading_session.py to separate session phase concerns
from the main trading pipeline.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from app.core.async_boundary import ensure_sync_adapter_result
from app.shared.parsing import resolve_session_market
from app.domain.fabio_ai.services.entry_gates.three_align import cluster_aggressive_prints
from app.domain.constants import RECENT_DATA_WINDOW

log = logging.getLogger(__name__)


class PhaseManager:
    """Manages session phase transitions including Phase 5 force-exit logic."""

    def __init__(self, exchange: str, storage=None, alerts=None, lifecycle_handler=None, risk_coordinator=None, exit_coordinator=None):
        self._exchange = exchange
        self._storage = storage
        self._alerts = alerts
        self._lifecycle_handler = lifecycle_handler
        self._risk_coordinator = risk_coordinator
        self._exit_coordinator = exit_coordinator

    def check_and_handle_phase(self, event, session, cache) -> None:
        """Check session phase and force-exit positions if Phase 5 (15:15-15:30 IST)."""
        try:
            _market = resolve_session_market(self._exchange, event.symbol)
            from app.domain.fabio_ai.services.session_context import get_session_info as _get_si
            session_phase = _get_si(timestamp=event.tick.time, market=_market)
            cache.set_last_session_info(session_phase)
            
            if session_phase.force_exit:
                self._handle_force_exit(
                    event, session, cache
                )
        except Exception as e:
            log.critical(
                "Session phase check CRITICAL failure for %s — FORCING EXIT ALL POSITIONS",
                event.symbol,
                exc_info=True,
            )
            self._emergency_exit_all(event, session)

    def _handle_force_exit(self, event, session, cache) -> None:
        """Execute force-exit for Phase 5 positions."""
        from app.domain.trading.models.enums import MarketStateCodec
        
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

                if session and session.portfolio and self._risk_coordinator:
                    self._risk_coordinator.record_trade_result(
                        event.symbol, float(realized_pnl), session.portfolio
                    )
                if self._exit_coordinator:
                        self._exit_coordinator.on_position_closed(
                            event.symbol, pos, session=session
                        )

                # Clear partition state for the closed position
                if self._lifecycle_handler:
                    self._lifecycle_handler.clear_partition_state(pos.id)
                
                if self._storage:
                    try:
                        ensure_sync_adapter_result(
                            "storage.delete_open_position",
                            self._storage.delete_open_position,
                            pos.id,
                        )
                    except Exception as e:
                        log.error(
                            "Failed to delete open position %s: %s", pos.id, e
                        )
                log.info(
                    "Session Phase 5: force-closed position %s at %.2f (pnl=%.2f)",
                    pos.id,
                    _close_price,
                    realized_pnl,
                )

        self._save_session_profile_if_needed(event, cache, session)

    def _save_session_profile_if_needed(self, event, cache, session) -> None:
        """Save session profile if we have AMT data and haven't already saved."""
        from app.shared.timezones import IST
        from datetime import datetime
        
        if (
            self._storage
            and cache.get_latest_amt()
            and not getattr(session, "_profile_saved", False)
        ):
            try:
                session_date = datetime.now(IST).strftime("%Y-%m-%d")
                _agg_prints = cache.get_aggressive_prints()
                _print_clusters = (
                    cluster_aggressive_prints(tuple(_agg_prints))
                    if _agg_prints
                    else []
                )
                last_amt = cache.get_latest_amt()
                profile_data = {
                    "symbol": event.symbol,
                    "market": resolve_session_market(self._exchange, event.symbol),
                    "session_date": session_date,
                    "poc": last_amt.get("poc", 0),
                    "vah": last_amt.get("vah", 0),
                    "val": last_amt.get("val", 0),
                    "profile_shape": last_amt.get("profileShape", ""),
                    "total_volume": sum(d.volume for d in cache.get_data()[-RECENT_DATA_WINDOW:]),
                    "print_levels": [
                        {"price": p, "side": "MIXED"}
                        for p in _print_clusters[:5]
                    ],
                    "is_underlying": cache.has_underlying_data(),
                }
                ensure_sync_adapter_result(
                    "storage.save_session_profile",
                    self._storage.save_session_profile,
                    profile_data,
                )
                session._profile_saved = True
                log.info(
                    "Saved session profile for %s on %s",
                    event.symbol,
                    session_date,
                )
            except Exception as e:
                log.error(
                    "Failed to save session profile: %s", e, exc_info=True
                )

    def _emergency_exit_all(self, event, session) -> None:
        """Emergency exit all positions when phase check fails."""
        exit_price = getattr(event.tick, "close", None)
        with session._lock:
            for pos in list(session.portfolio.positions):
                try:
                    _ep = exit_price if exit_price is not None else 0
                    _er_pnl = (
                        (_ep - pos.entry_price) * pos.size
                        if pos.side.value == "LONG"
                        else (pos.entry_price - _ep) * pos.size
                    )

                    session.portfolio.close_position(
                        pos.id,
                        exit_price if exit_price is not None else 0,
                        "EMERGENCY_SESSION_PHASE",
                    )

                    if session and session.portfolio and self._risk_coordinator:
                        self._risk_coordinator.record_trade_result(
                            event.symbol, float(_er_pnl), session.portfolio
                        )
                    if self._exit_coordinator:
                        self._exit_coordinator.on_position_closed(
                            event.symbol, pos, session=session
                        )
                except Exception as close_err:
                    log.error(
                        "Failed to emergency close position %s: %s",
                        pos.id,
                        close_err,
                    )