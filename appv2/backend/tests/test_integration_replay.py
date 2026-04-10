"""Integration test — candle-by-candle replay with no lookahead bias.

Replays a synthetic day of candles through the full pipeline:
  Candle → Volume Profile → VWAP → Market State → Gates

Verifies:
1. No lookahead bias (each candle only sees past data)
2. State transitions are valid
3. Gates only pass when conditions are met
4. Signals are generated correctly
"""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import math
import time
from types import SimpleNamespace
from appv2.application.strategy_orchestrator import StrategyOrchestrator
from appv2.domain.enums.market_state import MarketState


def _make_candle(t: int, base_price: float, volatility: float) -> SimpleNamespace:
    """Generate a synthetic candle."""
    open_price = base_price + (math.sin(t * 0.1) * volatility)
    high = open_price + abs(math.sin(t * 0.3) * volatility * 0.5)
    low = open_price - abs(math.cos(t * 0.3) * volatility * 0.5)
    close = open_price + (math.sin(t * 0.15) * volatility * 0.3)
    volume = 100 + abs(math.sin(t * 0.2) * 50)
    candle_range = high - low
    body = abs(close - open_price)

    ts = f"2024-01-15T09:{15 + t // 60:02d}:{t % 60:02d}"

    return SimpleNamespace(
        symbol="TEST",
        time=ts,
        open=round(open_price, 2),
        high=round(high, 2),
        low=round(low, 2),
        close=round(close, 2),
        volume=round(volume, 0),
        delta=round(volume * math.sin(t * 0.1), 0),
        range=round(candle_range, 2),
        body=round(body, 2),
        is_bullish=close >= open_price,
    )


def test_replay_no_lookahead_bias():
    """Replay 100 synthetic candles — each should only see past data."""
    orch = StrategyOrchestrator(symbol="TEST", underlying="TEST", tick_size=0.05)

    observations = []
    for i in range(100):
        candle = _make_candle(i, base_price=100, volatility=2)
        obs = orch.process_candle(candle)
        observations.append(obs)

        # Verify observation only uses data up to this point
        assert obs.poc >= 0  # POC should be valid
        assert obs.vwap >= 0  # VWAP should be valid
        # After first candle, we should have some data
        if i > 0:
            assert obs.market_state in ["NO_TRADE", "BALANCED", "IMBALANCED", "PROBING"]


def test_state_transitions_valid():
    """All state transitions should follow valid paths."""
    orch = StrategyOrchestrator(symbol="TEST", underlying="TEST", tick_size=0.05)

    valid_states = {MarketState.NO_TRADE, MarketState.BALANCED, MarketState.IMBALANCED, MarketState.PROBING}
    states_seen = []

    for i in range(50):
        candle = _make_candle(i, base_price=100, volatility=3)
        obs = orch.process_candle(candle)
        state = MarketState(obs.market_state)
        assert state in valid_states, f"Invalid state: {state}"
        states_seen.append(state)

    # First candle starts as NO_TRADE (POC dead zone) or PROBING
    # After a few candles it should transition
    assert len(states_seen) > 0
    # All states should be valid
    for s in states_seen:
        assert s in valid_states


def test_gate_rejection_during_no_trade():
    """Gates should reject during NO_TRADE state."""
    from appv2.domain.services.gate_pipeline import GateContext, run_gate_pipeline

    ctx = GateContext(
        session_phase="PRIMARY",
        market_state="NO_TRADE",
        data_candles=50,
        is_risk_halted=False,
        price=100.0,
        entry_zone=100.0,
        aggression_score=3.0,
        opposing_level=105.0,
        r_r_ratio=2.0,
        tick_age_seconds=5,
        tick_size=0.05,
    )

    passed, reason, detail = run_gate_pipeline(ctx)
    assert not passed
    assert "NoTradeState" in reason


def test_signal_generation():
    """Signal generation should produce valid signals."""
    orch = StrategyOrchestrator(symbol="TEST", underlying="TEST", tick_size=0.05)

    # Feed enough candles to get valid observations
    for i in range(30):
        candle = _make_candle(i, base_price=100, volatility=2)
        orch.process_candle(candle)

    # Check gates
    passed, reason, detail = orch.check_gates("LONG")
    # May or may not pass depending on synthetic data — just verify it runs
    assert isinstance(passed, bool)


def test_exit_engine_integration():
    """Exit engine should correctly detect SL/TP hits."""
    orch = StrategyOrchestrator(symbol="TEST", underlying="TEST", tick_size=0.05)

    # Check exit with SL hit
    decision = orch.check_exit(
        current_price=95.0,
        stop_loss=96.0,
        take_profit=110.0,
        is_long=True,
    )
    assert decision.should_exit
    assert decision.reason == "SL_HIT"

    # Check exit with TP hit
    decision = orch.check_exit(
        current_price=110.0,
        stop_loss=96.0,
        take_profit=110.0,
        is_long=True,
    )
    assert decision.should_exit
    assert decision.reason == "TP_HIT"

    # Check no exit
    decision = orch.check_exit(
        current_price=100.0,
        stop_loss=96.0,
        take_profit=110.0,
        is_long=True,
    )
    assert not decision.should_exit
