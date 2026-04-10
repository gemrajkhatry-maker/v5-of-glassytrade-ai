"""Tests for new infrastructure and application components."""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import pytest
import asyncio
from appv2.infrastructure.stream_manager import StreamManager, StreamHealth
from appv2.infrastructure.tick_processor import TickProcessor, OIState, DepthState, RangeBarData
from appv2.application.session_state_manager import SessionStateManager, SymbolSessionState
from appv2.application.entry_coordinator import EntryCoordinator, ExecutionResult
from appv2.application.exit_coordinator import ExitCoordinator
from appv2.application.trade_lifecycle import TradeLifecycleHandler
from appv2.application.risk_orchestrator import RiskOrchestrator
from appv2.domain.services.signal_ttl_manager import SignalTTLManager
from appv2.domain.services.mobile_alerts import MobileAlertSystem, AlertLevel
from appv2.api.state_broadcaster import GameStateBroadcaster
from appv2.domain.models.tick import Tick
from appv2.domain.models.signal import Signal
from appv2.domain.enums.signal_type import SignalType, SetupType


def test_tick_processor_oi_tracking():
    """OI changes should be tracked."""
    proc = TickProcessor()

    tick1 = Tick(symbol="T", ltp=100, volume=100, ltt="1", oi=10000)
    tick2 = Tick(symbol="T", ltp=101, volume=200, ltt="2", oi=10500)

    r1 = proc.process_tick(tick1)
    r2 = proc.process_tick(tick2)

    assert r1["oi"] is not None
    assert r1["oi"].current_oi == 10000
    assert r2["oi"] is not None
    assert r2["oi"].oi_change == 500  # 10500 - 10000


def test_tick_processor_depth():
    """Depth should be computed from bid/ask."""
    proc = TickProcessor()

    tick = Tick(
        symbol="T", ltp=100,
        best_bid=99.95, best_ask=100.05,
        best_bid_qty=100, best_ask_qty=150,
    )

    result = proc.process_tick(tick)
    assert result["depth"] is not None
    assert abs(result["depth"].spread - 0.10) < 0.001
    assert result["depth"].bid_qty == 100
    assert result["depth"].ask_qty == 150


def test_tick_processor_range_bar():
    """Range bar should complete when price moves by range_size."""
    proc = TickProcessor(range_size=1.0)

    # Ticks within range
    for price in [100, 100.3, 100.5, 100.7]:
        tick = Tick(symbol="T", ltp=price, volume=10, ltt="1")
        proc.process_tick(tick)

    bar = proc.get_current_range_bar("T")
    assert bar is not None
    assert not bar.is_complete  # Range = 0.7 < 1.0

    # Push over threshold
    tick = Tick(symbol="T", ltp=101.2, volume=20, ltt="2")
    result = proc.process_tick(tick)

    assert result["range_bar"] is not None
    assert result["range_bar"].is_complete


def test_session_state_manager():
    """Session state should persist per symbol."""
    mgr = SessionStateManager()

    state1 = mgr.get_or_create("NIFTY", "NIFTY")
    state2 = mgr.get_or_create("BANKNIFTY", "BANKNIFTY")

    assert state1.symbol == "NIFTY"
    assert state2.symbol == "BANKNIFTY"

    # Should be different instances
    state1.daily_pnl = 1000
    assert mgr.get_or_create("BANKNIFTY").daily_pnl == 0

    # Reset should clear
    mgr.reset("NIFTY")
    assert len(mgr.get_or_create("NIFTY").candles) == 0


def test_signal_ttl_in_entry_pipeline():
    """Entry pipeline should reject expired signals."""
    trade_lifecycle = TradeLifecycleHandler()
    risk = RiskOrchestrator(capital=5_000_000, risk_per_trade_pct=1.0)
    ttl = SignalTTLManager(ttl_seconds=600)

    coordinator = EntryCoordinator(trade_lifecycle, risk, ttl)

    # Create expired signal
    import time
    signal = Signal(
        symbol="TEST", underlying_symbol="TEST",
        direction=SignalType.LONG, setup_type=SetupType.VA_BOUNCE,
        entry_price=100, stop_loss=95, take_profit=110,
        confidence=0.8, market_state="BALANCED", session_phase="PRIMARY",
        timestamp=time.time() - 700,  # 700s ago > 600s TTL
    )

    async def run():
        return await coordinator.execute_signal(signal)

    result = asyncio.new_event_loop().run_until_complete(run())
    assert not result.success
    assert "expired" in result.reason.lower()


def test_exit_coordinator_basic():
    """Exit coordinator should detect SL/TP hits."""
    trade_lifecycle = TradeLifecycleHandler()
    risk = RiskOrchestrator()
    coordinator = ExitCoordinator(trade_lifecycle, risk)

    # Create a trade
    signal = Signal(
        symbol="TEST", underlying_symbol="TEST",
        direction=SignalType.LONG, setup_type=SetupType.VA_BOUNCE,
        entry_price=100, stop_loss=95, take_profit=110,
        confidence=0.8, market_state="BALANCED", session_phase="PRIMARY",
    )
    trade = trade_lifecycle.create_trade(signal, quantity=50, lots=1, fill_price=100)

    # Check exits with price at SL
    closed = coordinator.check_exits("TEST", current_price=94.0)
    assert len(closed) == 1
    assert closed[0].exit_reason == "SL_HIT"


def test_mobile_alert_system_disabled():
    """Alert system should be disabled without credentials."""
    alerts = MobileAlertSystem()
    assert not alerts._enabled

    # send() should return False when disabled
    result = asyncio.new_event_loop().run_until_complete(
        alerts.send("test")
    )
    assert result is False


def test_state_broadcaster_generation():
    """Broadcaster should increment generation on each update."""
    broadcaster = GameStateBroadcaster()

    async def run():
        await broadcaster.broadcast_state({"key": "value"})
        return broadcaster.generation

    gen = asyncio.new_event_loop().run_until_complete(run())
    assert gen == 1

    asyncio.new_event_loop().run_until_complete(
        broadcaster.broadcast_state({"key": "value2"})
    )
    assert broadcaster.generation == 2
