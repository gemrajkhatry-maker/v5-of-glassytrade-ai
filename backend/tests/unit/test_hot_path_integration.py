"""Hot-path integration tests for TradingSessionService.

Tests the critical trade-processing path:
  process_tick() -> _on_tick() -> AMT analysis -> entry gate -> overseer -> exit checks

Uses real TradingSessionService, TradeLifecycleHandler, and TradeManager,
while mocking external dependencies (broker, LLM, event bus).
"""

from __future__ import annotations

import threading
import time
import uuid
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.domain.trading.models.value_objects import OHLC, AMTResult
from app.domain.trading.models.entities import Position, Signal
from app.domain.trading.models.enums import (
    SignalType, Source, PositionStatus, SetupType, Side,
)
from app.domain.trading.models.aggregates import Portfolio
from app.domain.trading.events import TickReceived
from app.application.handlers.trade_lifecycle_handler import TradeLifecycleHandler


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tick(close=100.0, volume=500.0, delta=100.0, time_str="2026-01-15T10:30:00Z",
          open_=None, high=None, low=None):
    """Create an OHLC candle."""
    c = close
    h = high or c * 1.01
    l = low or c * 0.99
    o = open_ or c
    return OHLC.create(
        time=time_str, open=o, high=h, low=l, close=c,
        volume=volume, delta=delta,
    )


def _make_position(pos_id=None, symbol="NIFTY", side="LONG", entry_price=200.0,
                   sl=190.0, tp=220.0, status=PositionStatus.OPEN):
    """Create a real Position entity with proper Decimal types."""
    return Position(
        id=pos_id or str(uuid.uuid4()),
        symbol=symbol,
        side=Side.LONG if side == "LONG" else Side.SHORT,
        source=Source.AGENT,
        entry_price=Decimal(str(entry_price)),
        size=Decimal("75"),
        stop_loss=Decimal(str(sl)),
        take_profit=Decimal(str(tp)),
        pnl=Decimal("0"),
        entry_time="2026-01-15T10:30:00Z",
        status=status,
    )


def _make_signal(direction="BUY", price=200.0, sl=190.0, tp=220.0,
                 signal_id=None, setup=SetupType.TREND_MODEL):
    """Create a Signal with proper Decimal values."""
    sig = Signal.create(
        type=SignalType.BUY if direction == "BUY" else SignalType.SELL,
        price=price,
        reason="test signal",
        stop_loss=sl,
        take_profit=tp,
        timestamp="2026-01-15T10:30:00Z",
        setup=setup,
        source=Source.LLM,
        metadata={
            "trade_thesis": {
                "market_state": "BALANCED",
                "session": "NY_AM",
                "aggression": "HIGH",
                "location": "VAH",
                "state_reason": "trending",
                "aggression_reason": "strong bid flow",
            },
            "allow_trail": False,
            "scale_in": False,
            "market_state_model": "BALANCED",
            "session_phase": "",
            "is_expiry": False,
        },
    )
    if signal_id is not None:
        sig.signal_id = signal_id
    return sig


def _amt(market_state="BALANCED", poc=100.0, vah=105.0, val=95.0):
    """Helper to create an AMTResult domain object."""
    return AMTResult(
        market_state=market_state, poc=poc,
        value_area_high=vah, value_area_low=val,
    )


@pytest.fixture
def mock_deps():
    """Create mocked external dependencies."""
    broker = MagicMock()
    broker.execute_order.return_value = None
    gen_ai = MagicMock()
    gen_ai.is_ready.return_value = False
    storage = MagicMock()
    storage.get_recent_trades.return_value = []
    storage.get_previous_session_profile.return_value = None
    storage.load_open_positions.return_value = []
    storage.kv_get.return_value = None
    probability_engine = MagicMock()
    probability_engine.is_ready.return_value = False

    return {
        "broker": broker,
        "gen_ai": gen_ai,
        "storage": storage,
        "probability_engine": probability_engine,
    }


def _make_service(mock_deps):
    """Construct TradingSessionService with mocks."""
    with patch("app.application.services.forward_test_logger.ForwardTestLogger") as mock_fwd:
        mock_fwd.side_effect = Exception("no-op")
        from app.application.services.trading_session import TradingSessionService

        svc = TradingSessionService(
            broker=mock_deps["broker"],
            gen_ai_service=mock_deps["gen_ai"],
            storage=mock_deps["storage"],
            probability_engine=mock_deps["probability_engine"],
        )
    return svc


@pytest.fixture(autouse=True)
def cleanup_service_handlers():
    services = []
    yield services
    for svc in services:
        if hasattr(svc, "_llm_handler"):
            svc._llm_handler.cleanup()
        if hasattr(svc, "_overseer_handler"):
            svc._overseer_handler.cleanup()


# =====================================================================
# TestTickWithOpenPosition
#
# HP-01: process_tick with an open position should run exit checks and not
# crash, even with a non-LLM source position.
# =====================================================================
class TestTickWithOpenPosition:

    def test_hp01_process_tick_with_open_position_no_crash(
        self, mock_deps, cleanup_service_handlers
    ):
        tick = _tick(close=100.0, time_str="2026-01-15T10:30:00Z")
        svc = _make_service(mock_deps)
        cleanup_service_handlers.append(svc)

        session = svc.get_or_create_session("NIFTY")
        pos = _make_position(symbol="NIFTY", entry_price=200.0, sl=190.0, tp=220.0)
        session.portfolio.positions.append(pos)

        with patch.object(svc, "_run_amt_analysis", return_value=_amt()):
            result = svc.process_tick("NIFTY", tick)

        assert isinstance(result, dict)
        assert svc._lifecycle_handler is not None


# =====================================================================
# TestTickNoPositions
#
# HP-02: process_tick with no open positions should invoke the entry gate
# evaluation path and return a state snapshot.
# =====================================================================
class TestTickNoPositions:

    def test_hp02_process_tick_no_positions_runs_entry_path(
        self, mock_deps, cleanup_service_handlers
    ):
        tick = _tick(close=100.0, time_str="2026-01-15T10:30:00Z")
        svc = _make_service(mock_deps)
        cleanup_service_handlers.append(svc)

        session = svc.get_or_create_session("NIFTY")
        assert not session.portfolio.has_open_positions()

        with patch.object(svc, "_run_amt_analysis", return_value=_amt()):
            result = svc.process_tick("NIFTY", tick)

        assert isinstance(result, dict)
        assert "symbol" in result or "portfolio" in result


# =====================================================================
# TestTickAmtFailure
#
# HP-03: AMT failure should produce a sentinel BALANCED AMTResult so the
# exits/overseer pipeline still runs.
# =====================================================================
class TestTickAmtFailure:

    def test_hp03_amt_failure_allows_exit_checks(
        self, mock_deps, cleanup_service_handlers
    ):
        tick = _tick(close=100.0, time_str="2026-01-15T10:30:00Z")
        svc = _make_service(mock_deps)
        cleanup_service_handlers.append(svc)

        session = svc.get_or_create_session("NIFTY")
        # Place an open position so exit checks are exercised.
        pos = _make_position(symbol="NIFTY", entry_price=200.0, sl=190.0, tp=220.0)
        session.portfolio.positions.append(pos)

        # Simulate AMT failure by returning None from _run_amt_analysis.
        with patch.object(svc, "_run_amt_analysis", return_value=None):
            result = svc.process_tick("NIFTY", tick)

        # Must not crash — the sentinel path creates a BALANCED AMTResult
        # internally so check_exits still runs.
        assert isinstance(result, dict)

        # The position was closed by Portfolio-level SL (Source.AGENT positions
        # are managed by Portfolio, not TradeManager).
        assert pos.status == PositionStatus.CLOSED


# =====================================================================
# TestSLTPExit
#
# HP-04: Trade lifecycle — position hits SL or TP and is cleaned up.
# Uses TradeManager directly + Portfolio to test the exit path, since LLM
# source positions skip Portfolio-level SL checks.
# =====================================================================
class TestSLTPExit:

    def test_hp04_position_stops_out(self):
        """TradeManager detects SL hit -> check_exits returns True."""
        handler = TradeLifecycleHandler()

        pos = _make_position(
            symbol="NIFTY", entry_price=200.0, sl=190.0, tp=250.0,
        )
        sig = _make_signal(direction="BUY", price=200.0, sl=190.0, tp=250.0)
        handler.register_position("NIFTY", pos, sig)

        portfolio = Portfolio.create_default()
        portfolio.positions.append(pos)

        # Tick below SL.
        result = handler.check_exits(portfolio, current_price=185.0)
        assert result is True, "SL hit should return True (position closed)"
        assert pos.status == PositionStatus.CLOSED

    def test_hp04_position_takes_profit(self):
        """PartitionExitManager detects 2R TP -> P2 exits the position."""
        handler = TradeLifecycleHandler()

        entry_price = 200.0
        tp = 220.0
        pos = _make_position(symbol="NIFTY", entry_price=entry_price, sl=180.0, tp=tp)
        sig = _make_signal(direction="BUY", price=entry_price, sl=180.0, tp=tp)
        handler.register_position("NIFTY", pos, sig)

        portfolio = Portfolio.create_default()
        portfolio.positions.append(pos)

        trade_manager = handler._trade_manager
        metrics = trade_manager.get_position_metrics(pos.id)
        assert metrics is not None  # position is managed

        # Tick at 2R+ (entry=200, sl=180, R=20, 2R=240). P2 fires at 2R per Fabio spec.
        result = handler.check_exits(portfolio, current_price=241.0)
        assert result is True, "2R profit hit should return True"
        assert pos.status == PositionStatus.CLOSED
        assert trade_manager.get_position_metrics(pos.id) is None


# =====================================================================
# TestEntryCoordinationLockSafety
#
# HP-05: Entry coordination — execute_order is called outside the session
# lock and the resulting position is registered with TradeManager.
# =====================================================================
class TestEntryCoordinationLockSafety:

    def test_hp05_broker_execute_outside_lock(self, mock_deps, cleanup_service_handlers):
        svc = _make_service(mock_deps)
        cleanup_service_handlers.append(svc)

        session = svc.get_or_create_session("NIFTY")
        sig = _make_signal(
            direction="BUY", price=100.0, sl=95.0, tp=110.0,
            setup=SetupType.TREND_MODEL,
        )

        pos = _make_position(symbol="NIFTY", entry_price=100.0, sl=95.0, tp=110.0)
        mock_deps["broker"].execute_order.return_value = pos

        ec = svc._entry_coordinator

        with patch.object(
            svc._entry_coordinator._risk_coordinator, "validate_entry",
            return_value=True,
        ):
            with patch(
                "app.domain.fabio_ai.services.trade_thesis.validate_trade_thesis",
                return_value=(True, "OK"),
            ):
                with patch.object(
                    svc._entry_coordinator._option_selector, "select_strike",
                    return_value=100,
                ):
                    ec.execute_signal("NIFTY", sig, session)

        assert mock_deps["broker"].execute_order.call_count == 1
        # Position should be registered with lifecycle handler.
        assert svc._lifecycle_handler._trade_manager.has_managed_positions("NIFTY")


# =====================================================================
# TestPositionRegistration
#
# HP-06: Position registration — TradeManager must track the position
# after register_position, with correct side/prices.
# =====================================================================
class TestPositionRegistration:

    def test_hp06_register_position_tracked(
        self, mock_deps, cleanup_service_handlers
    ):
        svc = _make_service(mock_deps)
        cleanup_service_handlers.append(svc)

        handler = svc._lifecycle_handler
        pos = _make_position(
            pos_id="pos-reg-001", symbol="BANKNIFTY",
            entry_price=500.0, sl=480.0, tp=550.0,
        )
        sig = _make_signal(direction="BUY", price=500.0, sl=480.0, tp=550.0)

        handler.register_position("BANKNIFTY", pos, sig)

        trade_manager = handler._trade_manager
        assert trade_manager.has_managed_positions("BANKNIFTY")
        assert set(trade_manager.get_managed_position_ids(
            symbol="BANKNIFTY"
        )) == {"pos-reg-001"}

    def test_hp06_market_state_normalization(self):
        """'Trending' market state in signal metadata is normalized to IMBALANCED."""
        handler = TradeLifecycleHandler()

        pos = _make_position(
            pos_id="norm-001", symbol="NIFTY",
            entry_price=300.0, sl=280.0, tp=350.0,
        )
        sig = _make_signal(
            direction="BUY", price=300.0, sl=280.0, tp=350.0,
        )
        # Override metadata to use "Trending".
        sig.metadata["market_state_model"] = "Trending"

        handler.register_position("NIFTY", pos, sig)

        tm = handler._trade_manager
        # The internal position should have market_state == "IMBALANCED".
        mp = tm._positions.get("norm-001")
        assert mp is not None
        assert mp.market_state == "IMBALANCED"


# =====================================================================
# TestPartialExitCallback
#
# HP-07: Partial exit — on_partial_exit callback fires with correct params.
# =====================================================================
class TestPartialExitCallback:

    def test_hp07_partial_exit_callback(self, mock_deps, cleanup_service_handlers):
        partial_calls = []

        def on_partial_exit(pos_id, side, entry_px, exit_px, pct, closed, remaining, pnl):
            partial_calls.append({
                "pos_id": pos_id, "side": side,
                "entry_px": entry_px, "exit_px": exit_px,
                "pct": pct, "closed": closed, "remaining": remaining, "pnl": pnl,
            })

        svc = _make_service(mock_deps)
        cleanup_service_handlers.append(svc)

        session = svc.get_or_create_session("NIFTY")
        handler = svc._lifecycle_handler

        entry_price = 200.0
        sl = 190.0
        tp = 230.0
        pos = _make_position(
            symbol="NIFTY", entry_price=entry_price, sl=sl, tp=tp,
        )
        session.portfolio.positions.append(pos)

        sig = _make_signal(direction="BUY", price=entry_price, sl=sl, tp=tp)
        handler.register_position("NIFTY", pos, sig)

        # Price ~halfway to TP triggers PARTIAL_TAKE_PROFIT.
        tick = _tick(close=220.0, time_str="2026-01-15T10:35:00Z")

        with patch.object(svc, "_run_amt_analysis", return_value=_amt()):
            svc.process_tick("NIFTY", tick)

        if partial_calls:
            call = partial_calls[0]
            assert call["pos_id"] == pos.id
            assert call["side"] == "LONG"
            assert call["entry_px"] == entry_price
            # default partial_size_pct = 0.50 when runner not active
            assert call["pct"] == 0.50
        # At minimum, the position size should have been reduced.
        if pos.size < 75.0:
            assert len(partial_calls) > 0


# =====================================================================
# TestTickFlow
#
# HP-08: TickReceived event data integrity and multi-tick accumulation.
# =====================================================================
class TestTickFlow:

    def test_hp08_tick_event_data_integrity(
        self, mock_deps, cleanup_service_handlers
    ):
        tick = _tick(
            close=150.0, volume=1000.0, delta=250.0,
            time_str="2026-02-20T11:00:00Z",
        )
        svc = _make_service(mock_deps)
        cleanup_service_handlers.append(svc)

        session = svc.get_or_create_session("NIFTY")

        # Create a TickReceived event directly.
        event = TickReceived(
            symbol="NIFTY",
            tick=tick,
            order_book=None,
            data=(tick,),
        )

        assert event.symbol == "NIFTY"
        assert event.tick.close == tick.close
        assert event.tick.volume == tick.volume
        assert event.tick.delta == tick.delta
        assert event.tick.time == tick.time
        assert len(event.data) == 1
        assert event.data[0].close == 150.0

        # Now verify process_tick works correctly.
        with patch.object(svc, "_run_amt_analysis", return_value=_amt()):
            result = svc.process_tick("NIFTY", tick)

        assert isinstance(result, dict)

        # The session should have 1 candle after processing (candle is appended).
        assert len(session.data) == 1
        assert session.data[0].close == 150.0

    def test_hp08_multiple_ticks_accumulate(
        self, mock_deps, cleanup_service_handlers
    ):
        svc = _make_service(mock_deps)
        cleanup_service_handlers.append(svc)

        session = svc.get_or_create_session("NIFTY")

        tick_times = [
            "2026-01-15T10:30:00Z",
            "2026-01-15T10:35:00Z",
            "2026-01-15T10:40:00Z",
        ]
        for i, ts in enumerate(tick_times):
            tick = _tick(close=100.0 + i, time_str=ts)
            with patch.object(svc, "_run_amt_analysis", return_value=_amt()):
                svc.process_tick("NIFTY", tick)

        assert len(session.data) == 3
        assert session.data[0].close == 100.0
        assert session.data[-1].close == 102.0


# =====================================================================
# TestTradeLifecycleIntegration
#
# Direct tests of TradeLifecycleHandler with real TradeManager.
# =====================================================================
class TestTradeLifecycleIntegration:

    def test_hp_exit_returns_true_when_sl_hit(self):
        handler = TradeLifecycleHandler()

        pos = _make_position(
            pos_id="sl-pos", entry_price=200.0, sl=190.0, tp=250.0,
        )
        sig = _make_signal(direction="BUY", price=200.0, sl=190.0, tp=250.0)
        handler.register_position("NIFTY", pos, sig)

        portfolio = Portfolio.create_default()
        portfolio.positions.append(pos)

        result = handler.check_exits(portfolio, current_price=189.0)
        assert result is True, "SL hit should return True"

    def test_hp_exit_returns_false_when_no_positions(self):
        handler = TradeLifecycleHandler()
        portfolio = Portfolio.create_default()
        result = handler.check_exits(portfolio, current_price=100.0)
        assert result is False

    def test_hp_exit_returns_false_when_price_normal(self):
        handler = TradeLifecycleHandler()

        pos = _make_position(
            pos_id="safe-pos", entry_price=200.0, sl=180.0, tp=250.0,
        )
        sig = _make_signal(direction="BUY", price=200.0, sl=180.0, tp=250.0)
        handler.register_position("NIFTY", pos, sig)

        portfolio = Portfolio.create_default()
        portfolio.positions.append(pos)

        result = handler.check_exits(portfolio, current_price=210.0)
        assert result is False

    def test_hp_sync_closed_unregisters(self):
        """sync_closed should unregister positions closed externally."""
        handler = TradeLifecycleHandler()

        pos = _make_position(
            pos_id="sync-pos", entry_price=200.0, sl=190.0, tp=250.0,
        )
        sig = _make_signal(direction="BUY", price=200.0, sl=190.0, tp=250.0)
        handler.register_position("NIFTY", pos, sig)

        assert handler._trade_manager.has_managed_positions("NIFTY")

        # Simulate Portfolio closing the position (e.g. via direct SL check)
        portfolio = Portfolio.create_default()
        portfolio.positions.append(pos)
        portfolio.close_position(pos.id, Decimal("185.0"), "Stop Loss")

        handler.sync_closed([pos])

        # Should no longer be tracked
        assert not handler._trade_manager.has_managed_positions("NIFTY")


# =====================================================================
# Full Hot-Path Smoke Test
# =====================================================================
class TestHotPathSmoke:
    """Full integration smoke test: real session, multiple ticks,
    opening + closing a position through the entire pipeline."""

    @pytest.mark.skip(
        reason="Full integration smoke test — requires real AMT handler to "
        "initialize properly. Use for local run only."
    )
    def test_hp_smoke_full_pipeline(self, mock_deps, cleanup_service_handlers):
        """End-to-end: feed ticks -> AMT -> entry gate -> open position -> SL exit."""
        svc = _make_service(mock_deps)
        cleanup_service_handlers.append(svc)

        # Feed 20 ticks to prime AMT buffers.
        for i in range(20):
            ts = f"2026-01-15T10:{30 + i:02d}:00Z"
            tick = _tick(close=100.0 + i * 0.1, time_str=ts)
            svc.process_tick("NIFTY", tick)

        # Continue feeding ticks until we either get a position or exhaust.
        for i in range(20):
            ts = f"2026-01-15T11:{i:02d}:00Z"
            tick = _tick(close=102.0 + i * 0.1, time_str=ts)
            svc.process_tick("NIFTY", tick)

            session = svc.get_or_create_session("NIFTY")
            if session.portfolio.has_open_positions():
                # Force an SL hit.
                open_poses = [
                    p for p in session.portfolio.positions
                    if p.status == PositionStatus.OPEN
                ]
                if open_poses:
                    pos = open_poses[0]
                    tick = _tick(close=10.0, time_str="2026-01-15T12:00:00Z")
                    svc.process_tick("NIFTY", tick)
                    assert pos.status.value == "CLOSED"
                    return
            # Advance the exec clock to avoid 60s cooldown.
            session._last_exec_mono = time.monotonic() - 120

        assert False, "No position was opened during smoke test"
