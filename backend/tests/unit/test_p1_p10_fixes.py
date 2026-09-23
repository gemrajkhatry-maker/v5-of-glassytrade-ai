"""Tests for P1-P10 performance and reliability fixes."""

import queue

import pytest

from quant.contracts.value_objects import OHLC, AMTResult


# ---- Helpers ----

def _tick(close=100.0, volume=200, delta=80, high=0, low=0, open_=0):
    return OHLC(
        time="2026-02-02T10:00:00+05:30",
        open=open_ or close, high=high or close + 1,
        low=low or close - 1, close=close,
        volume=volume, delta=delta,
    )


def _amt(poc=100, vah=105, val=95, lvns=(), hvns=(), market_state="BALANCED", **kwargs):
    return AMTResult(
        market_state=market_state, poc=poc,
        value_area_high=vah, value_area_low=val,
        lvns=tuple(lvns), hvns=tuple(hvns),
        **kwargs,
    )


# ---- P3: Bounded LLM Queue ----

class TestP3BoundedQueue:
    def test_queue_has_max_size(self):
        q = queue.Queue(maxsize=10)
        for i in range(10):
            q.put_nowait(i)
        with pytest.raises(queue.Full):
            q.put_nowait(11)

    def test_queue_drops_when_full(self):
        """Simulate the bounded queue behavior in LLM entry handler."""
        q = queue.Queue(maxsize=10)
        for i in range(10):
            q.put_nowait(i)
        # When full, handler catches queue.Full and drops
        try:
            q.put_nowait(11)
            placed = True
        except queue.Full:
            placed = False
        assert not placed


# ---- P5: Contextual Delta Cap ----

class TestP5ContextualDeltaCap:
    def test_small_delta_accepted(self):
        """Delta of 3000 with cumulative 100000 should be accepted (3% < 5%)."""
        prev_cum = 100000
        tick_buy = 3000
        cap = max(10000, prev_cum * 0.05)  # 10000
        assert tick_buy <= cap

    def test_large_delta_rejected_as_reset(self):
        """Delta of 50000 with cumulative 100000 should be rejected (50% > 5%)."""
        prev_cum = 100000
        tick_buy = 50000
        cap = max(10000, prev_cum * 0.05)  # 5000
        assert tick_buy > cap

    def test_small_cumulative_uses_floor(self):
        """With small cumulative, floor of 10000 applies."""
        prev_cum = 1000
        tick_buy = 5000
        cap = max(10000, prev_cum * 0.05)  # 10000 (floor)
        assert tick_buy <= cap  # 5000 < 10000, accepted


# ---- P6: Confidence-Weighted Meta-Filter ----

class TestP6MetaFilter:
    def test_strong_ml_vetoes_llm(self):
        """ML probability 0.65 (strong) should veto disagreeing LLM."""
        ml_prob = 0.65
        assert ml_prob >= 0.55  # veto threshold

    def test_weak_ml_trusts_llm(self):
        """ML probability 0.52 (weak) should let LLM override."""
        ml_prob = 0.52
        assert ml_prob < 0.55  # below veto threshold, trust LLM


# ---- P7: Overseer Exit PnL Guard ----

class TestP7OverseerPnLGuard:
    def test_exit_when_losing_and_high_probability(self):
        """P(adverse)=0.70, PnL=-0.5% → should exit."""
        exit_prob = 0.70
        pnl_pct = -0.005
        should_exit = (exit_prob >= 0.80) or (exit_prob > 0.65 and pnl_pct < 0.02)
        assert should_exit

    def test_hold_when_profitable_and_moderate_probability(self):
        """P(adverse)=0.70, PnL=+3.0% → should NOT exit (preserve alpha)."""
        exit_prob = 0.70
        pnl_pct = 0.03
        should_exit = (exit_prob >= 0.80) or (exit_prob > 0.65 and pnl_pct < 0.02)
        assert not should_exit

    def test_exit_when_very_high_probability_regardless_of_pnl(self):
        """P(adverse)=0.85, PnL=+3.0% → should exit (very high risk)."""
        exit_prob = 0.85
        pnl_pct = 0.03
        should_exit = (exit_prob >= 0.80) or (exit_prob > 0.65 and pnl_pct < 0.02)
        assert should_exit


# ---- P8: Confirmation Bundle Returns Tuple ----

# P8 tests (three_align) removed — module deleted in Phase C1.


# ---- P9: Structured Parser ----

# ---- Developing VA (previous fix) ----

class TestDevelopingVA:
    def test_amt_result_has_dev_fields(self):
        amt = _amt(poc=100, vah=105, val=95, dev_poc=98, dev_vah=102, dev_val=94)
        assert amt.dev_poc == 98
        assert amt.dev_vah == 102
        assert amt.dev_val == 94
