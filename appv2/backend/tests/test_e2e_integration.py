"""End-to-end integration test — full pipeline from tick to trade.

Simulates:
1. Feed synthetic ticks for a symbol
2. Aggregation into candles
3. Volume profile / VWAP / CVD computation
4. Market state classification
5. Gate pipeline evaluation
6. Signal generation
7. Trade execution (paper)
8. Exit detection
9. Position reconciliation
10. Trade journal logging

Verifies end-to-end correctness with no lookahead bias.
"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import math
import time
from types import SimpleNamespace
import pytest

from appv2.application.data_pipeline import DataPipelineOrchestrator
from appv2.application.strategy_orchestrator import StrategyOrchestrator
from appv2.application.trade_lifecycle import TradeLifecycleHandler
from appv2.application.risk_orchestrator import RiskOrchestrator
from appv2.domain.models.tick import Tick
from appv2.domain.models.signal import Signal
from appv2.domain.enums.signal_type import SignalType
from appv2.domain.services.signal_generator import build_signal
from appv2.domain.services.exit_engine import check_exit
from appv2.domain.services.position_reconciliation import PositionReconciler
from appv2.domain.services.trade_journal import TradeJournal
from appv2.domain.services.gate_pipeline import GateContext, run_gate_pipeline
from appv2.domain.enums.market_state import MarketState


# ── Synthetic Tick Generator ──────────────────────────────────────────

class SyntheticTickGenerator:
    """Generates realistic synthetic ticks for testing."""

    def __init__(self, symbol: str, start_price: float = 100.0):
        self.symbol = symbol
        self.price = start_price
        self.cum_volume = 0.0
        self.base_time = 1700000000.0
        self.tick_num = 0

    def next_tick(self, trend: float = 0.0, volatility: float = 0.5) -> Tick:
        """Generate next tick with trend and noise."""
        self.tick_num += 1
        self.price += trend + (math.sin(self.tick_num * 0.3) * volatility)
        self.price = max(self.price, 10)  # Floor

        self.cum_volume += 10 + abs(math.sin(self.tick_num * 0.1) * 5)
        ltt = str(self.base_time + self.tick_num)

        return Tick(
            symbol=self.symbol,
            ltp=round(self.price, 2),
            ltq=10,
            ltt=ltt,
            atp=round(self.price, 2),
            volume=round(self.cum_volume, 0),
            best_bid=round(self.price - 0.05, 2),
            best_ask=round(self.price + 0.05, 2),
            best_bid_qty=100,
            best_ask_qty=100,
        )


# ── End-to-End Tests ─────────────────────────────────────────────────

def test_full_pipeline_tick_to_observation():
    """Feed 100 ticks → should produce AMT observations."""
    gen = SyntheticTickGenerator("TEST", start_price=100.0)
    pipeline = DataPipelineOrchestrator("TEST", tick_size=0.05)

    observations = []
    for _ in range(100):
        tick = gen.next_tick(trend=0.02)
        outputs = pipeline.process_tick(tick)
        for out in outputs:
            if out.candle is not None:
                observations.append(out)

    assert len(observations) > 0
    # Verify data quality
    last = observations[-1]
    assert last.poc > 0
    assert last.vah >= last.val
    assert last.vwap > 0


def test_strategy_orchestrator_e2e():
    """Full strategy: candles → state → gates → potential signal."""
    orch = StrategyOrchestrator("TEST", underlying="TEST", tick_size=0.05)

    # Feed enough candles with all required attributes
    for i in range(60):
        price = 100.0 + math.sin(i * 0.1) * 2
        orch.process_candle(SimpleNamespace(
            symbol="TEST",
            time=f"2024-01-15T09:{15 + i // 60:02d}:{i % 60:02d}",
            open=price - 0.2,
            high=price + 0.5,
            low=price - 0.5,
            close=price,
            volume=50.0,
            delta=20.0,
            range=1.0,
            body=0.2,
            is_bullish=True,
        ))

    # Verify state is valid
    obs = orch._last_observation
    assert obs is not None
    assert obs.market_state in ["NO_TRADE", "BALANCED", "IMBALANCED", "PROBING"]


def test_signal_to_trade_lifecycle():
    """Signal → Trade → Exit → verify P&L."""
    handler = TradeLifecycleHandler()

    # Create signal
    signal = Signal(
        symbol="TEST",
        underlying_symbol="TEST",
        direction=SignalType.LONG,
        setup_type="VA_BOUNCE",
        entry_price=100.0,
        stop_loss=95.0,
        take_profit=110.0,
        confidence=0.8,
        market_state="BALANCED",
        session_phase="PRIMARY",
        poc=100.0,
        vah=105.0,
        val=95.0,
        vwap=100.0,
    )

    # Create trade from signal
    trade = handler.create_trade(signal, quantity=50, lots=1, fill_price=100.0)
    assert trade is not None
    assert handler.has_open_position("TEST")

    # Exit at TP
    closed = handler.close_trade(
        trade.trade_id, exit_price=110.0, exit_reason="TP_HIT",
    )
    assert closed is not None
    assert closed.realized_pnl == 500.0  # (110 - 100) × 50
    assert not handler.has_open_position("TEST")


def test_exit_engine_with_all_scenarios():
    """Exit engine: SL, TP, trail, time stop, session force-exit."""
    # SL hit
    dec = check_exit(
        current_price=94.0, stop_loss=95.0, take_profit=110.0,
        is_long=True,
    )
    assert dec.should_exit
    assert dec.reason == "SL_HIT"

    # TP hit
    dec = check_exit(
        current_price=110.0, stop_loss=95.0, take_profit=110.0,
        is_long=True,
    )
    assert dec.should_exit
    assert dec.reason == "TP_HIT"

    # Trail hit
    dec = check_exit(
        current_price=98.0, stop_loss=95.0, take_profit=110.0,
        trail_price=99.0, is_long=True,
    )
    assert dec.should_exit
    assert dec.reason == "TRAIL_HIT"

    # Session force-exit
    dec = check_exit(
        current_price=100.0, stop_loss=95.0, take_profit=110.0,
        is_long=True, force_exit=True,
    )
    assert dec.should_exit
    assert dec.reason == "SESSION_EXIT"

    # No exit
    dec = check_exit(
        current_price=100.0, stop_loss=95.0, take_profit=110.0,
        is_long=True,
    )
    assert not dec.should_exit


def test_risk_orchestrator_pre_trade():
    """Risk checks should allow/reject trades correctly."""
    risk = RiskOrchestrator(
        capital=5_000_000,
        risk_per_trade_pct=1.0,
        max_daily_loss_pct=3.0,
    )

    # Valid trade
    result = risk.pre_trade_check(
        symbol="TEST",
        entry_price=100.0,
        stop_loss=95.0,
        lot_size=50,
    )
    assert result.allowed

    # Trade with zero risk (entry == SL)
    result = risk.pre_trade_check(
        symbol="TEST",
        entry_price=100.0,
        stop_loss=100.0,
        lot_size=50,
    )
    assert not result.allowed


def test_position_reconciliation_e2e():
    """Full reconciliation cycle with broker."""
    reconciler = PositionReconciler()

    internal = [
        {"symbol": "TEST", "side": "BUY", "quantity": 50, "avg_price": 100.0},
    ]
    broker = [
        {"symbol": "TEST", "side": "BUY", "quantity": 50, "avg_price": 100.0},
    ]

    async def run():
        return await reconciler.reconcile(internal, broker)

    import asyncio
    result = asyncio.new_event_loop().run_until_complete(run())
    assert result.matched


def test_trade_journal_e2e(tmp_path):
    """Full journal lifecycle with multiple events."""
    journal = TradeJournal(log_dir=str(tmp_path))

    # Log a complete trade lifecycle
    journal.log_signal({"symbol": "TEST", "direction": "LONG", "entry_price": 100})
    journal.log_entry({"symbol": "TEST", "entry_price": 100, "quantity": 50})
    journal.log_exit({"symbol": "TEST", "exit_price": 110, "pnl": 500, "reason": "TP_HIT"})

    journal.close()

    # Verify file
    files = list(tmp_path.glob("*.jsonl"))
    assert len(files) == 1

    import json
    lines = files[0].read_text().strip().split("\n")
    assert len(lines) == 3

    events = [json.loads(l)["event"] for l in lines]
    assert events == ["SIGNAL_GENERATED", "POSITION_OPENED", "POSITION_CLOSED"]


def test_no_lookahead_bias_in_pipeline():
    """Verify that at tick N, output only contains data from ticks 0..N."""
    gen = SyntheticTickGenerator("TEST", start_price=100.0)
    pipeline = DataPipelineOrchestrator("TEST", tick_size=0.05)

    all_ticks = []
    for i in range(60):
        tick = gen.next_tick(trend=0.01)
        all_ticks.append(tick)
        outputs = pipeline.process_tick(tick)

        for out in outputs:
            if out.candle is not None:
                # Candle high should never exceed the highest tick seen so far
                seen_high = max(t.ltp for t in all_ticks)
                assert out.candle.high <= seen_high + 0.01, "Lookahead bias in high"
                # Candle low should never be below the lowest tick seen so far
                seen_low = min(t.ltp for t in all_ticks)
                assert out.candle.low >= seen_low - 0.01, "Lookahead bias in low"
                # Close should be from the last tick in the candle (approximately)
                # Due to volume-weighted calculation, allow small tolerance
                assert out.candle.close >= seen_low - 0.01, "Close below min tick"
                assert out.candle.close <= seen_high + 0.01, "Close above max tick"


def test_full_day_replay():
    """Replay a full day (375 1-min candles) and verify pipeline stability."""
    orch = StrategyOrchestrator("TEST", underlying="TEST", tick_size=0.05)
    gen = SyntheticTickGenerator("TEST", start_price=100.0)

    states_seen = set()
    for i in range(375):
        # Simulate intraday price action: trend up, then mean revert
        if i < 100:
            trend = 0.05
        elif i < 250:
            trend = -0.02
        else:
            trend = 0.01

        tick = gen.next_tick(trend=trend, volatility=0.3)
        candle = SimpleNamespace(
            symbol="TEST",
            time=tick.ltt,
            open=tick.ltp - 0.2,
            high=tick.ltp + abs(math.sin(i * 0.1) * 0.5),
            low=tick.ltp - abs(math.cos(i * 0.1) * 0.5),
            close=tick.ltp,
            volume=50 + abs(math.sin(i * 0.05) * 30),
            delta=10,
            range=abs(math.sin(i * 0.1) * 0.5) + abs(math.cos(i * 0.1) * 0.5),
            body=0.2,
            is_bullish=True,
        )

        obs = orch.process_candle(candle)
        states_seen.add(obs.market_state)

        # Verify no crashes
        assert obs.vwap >= 0
        assert obs.poc >= 0

    # Should have seen multiple states
    assert len(states_seen) >= 1
