"""Tests for production-grade services."""

import sys
import asyncio
from pathlib import Path
_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import pytest
from appv2.domain.services.position_reconciliation import PositionReconciler
from appv2.domain.services.signal_ttl_manager import SignalTTLManager, SignalState
from appv2.domain.services.post_trade_analytics import PostTradeAnalytics
from appv2.domain.services.trade_journal import TradeJournal
from appv2.domain.models.signal import Signal
from appv2.domain.enums.signal_type import SignalType, SetupType
from types import SimpleNamespace


@pytest.mark.asyncio
async def test_position_reconciliation_match():
    """Matched positions should return no discrepancies."""
    reconciler = PositionReconciler()
    internal = [
        {"symbol": "NIFTY", "side": "BUY", "quantity": 50, "avg_price": 100.0},
    ]
    broker = [
        {"symbol": "NIFTY", "side": "BUY", "quantity": 50, "avg_price": 100.0},
    ]

    result = await reconciler.reconcile(internal, broker)
    assert result.matched
    assert len(result.discrepancies) == 0


@pytest.mark.asyncio
async def test_position_reconciliation_mismatch():
    """Mismatched quantities should be detected."""
    reconciler = PositionReconciler()
    internal = [
        {"symbol": "NIFTY", "side": "BUY", "quantity": 50, "avg_price": 100.0},
    ]
    broker = [
        {"symbol": "NIFTY", "side": "BUY", "quantity": 75, "avg_price": 100.0},
    ]

    result = await reconciler.reconcile(internal, broker)
    assert not result.matched
    assert len(result.discrepancies) == 1


@pytest.mark.asyncio
async def test_position_reconciliation_missing():
    """Position in internal but not broker should be detected."""
    reconciler = PositionReconciler()
    internal = [
        {"symbol": "NIFTY", "side": "BUY", "quantity": 50, "avg_price": 100.0},
    ]

    result = await reconciler.reconcile(internal, [])
    assert not result.matched
    assert "MISSING" in result.discrepancies[0]


@pytest.mark.asyncio
async def test_consecutive_mismatch_halt():
    """3 consecutive mismatches should trigger halt."""
    reconciler = PositionReconciler()
    reconciler._max_mismatches_before_halt = 3

    internal = [{"symbol": "T", "side": "BUY", "quantity": 50, "avg_price": 100}]
    broker = [{"symbol": "T", "side": "BUY", "quantity": 75, "avg_price": 100}]

    await reconciler.reconcile(internal, broker)
    await reconciler.reconcile(internal, broker)
    await reconciler.reconcile(internal, broker)

    assert reconciler.should_halt_trading


def test_signal_ttl_manager_basic():
    """Signal should be retrievable while within TTL."""
    mgr = SignalTTLManager(ttl_seconds=600)
    signal = Signal(
        symbol="TEST",
        underlying_symbol="TEST",
        direction=SignalType.LONG,
        setup_type=SetupType.VA_BOUNCE,
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        confidence=0.8,
        market_state="BALANCED",
        session_phase="PRIMARY",
    )

    assert mgr.add_signal(signal)
    retrieved = mgr.get_pending_signal("TEST")
    assert retrieved is not None
    assert retrieved.symbol == "TEST"


def test_signal_ttl_dedup():
    """Duplicate signals should be rejected."""
    mgr = SignalTTLManager(ttl_seconds=600)
    signal = Signal(
        symbol="TEST",
        underlying_symbol="TEST",
        direction=SignalType.LONG,
        setup_type=SetupType.VA_BOUNCE,
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        confidence=0.8,
        market_state="BALANCED",
        session_phase="PRIMARY",
    )

    assert mgr.add_signal(signal)
    assert not mgr.add_signal(signal)  # Duplicate


def test_post_trade_analytics():
    """Analytics should compute correct metrics."""
    analyzer = PostTradeAnalytics()

    trades = [
        {"realized_pnl": 500, "entry_price": 100, "stop_loss": 95, "quantity": 50, "duration_minutes": 15},
        {"realized_pnl": -200, "entry_price": 100, "stop_loss": 96, "quantity": 50, "duration_minutes": 10},
        {"realized_pnl": 300, "entry_price": 100, "stop_loss": 97, "quantity": 50, "duration_minutes": 20},
        {"realized_pnl": -100, "entry_price": 100, "stop_loss": 98, "quantity": 50, "duration_minutes": 5},
    ]

    for t in trades:
        analyzer.add_trade(t)

    stats = analyzer.compute_stats()

    assert stats.total_trades == 4
    assert stats.wins == 2
    assert stats.losses == 2
    assert stats.win_rate == 0.5
    assert stats.gross_profit == 800  # 500 + 300
    assert stats.gross_loss == 300    # 200 + 100
    assert stats.expectancy > 0       # (0.5 * 400) - (0.5 * 150) = 125
    # W, L, W, L pattern → max consecutive wins = 1, losses = 1
    assert stats.max_consecutive_wins == 1
    assert stats.max_consecutive_losses == 1


def test_trade_journal(tmp_path):
    """Journal should write valid JSONL."""
    journal = TradeJournal(log_dir=str(tmp_path))

    journal.log_signal({"symbol": "TEST", "direction": "LONG"})
    journal.log_gate_rejection("TEST", "RiskHalt", "Daily loss limit")
    journal.log_entry({"symbol": "TEST", "entry_price": 100.0})
    journal.log_exit({"symbol": "TEST", "exit_price": 105.0, "pnl": 250.0})

    journal.close()

    # Read and verify
    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1
    lines = files[0].read_text().strip().split("\n")
    assert len(lines) == 4

    # Verify first line
    import json
    first = json.loads(lines[0])
    assert first["event"] == "SIGNAL_GENERATED"
    assert first["symbol"] == "TEST"
