"""All-gates-pass-but-builder-drops must carry an explainable reason."""

import pytest
from unittest.mock import patch

from quant.bars import Bar
from quant.contracts.enums import MarketState
from quant.decision.context import DecisionContext
from quant.decision.decision_service import DecisionService
from quant.decision.signal_builder import SignalBuilder


def _bar(close=100.0, open_offset=0.0):
    """Create a bar with optional open offset for body.
    
    For LONG direction, we need close > open (bullish body).
    Default creates a doji (open=close) which fails candle acceptance.
    """
    open_px = close + open_offset
    high = max(open_px, close) + 1.0
    low = min(open_px, close) - 1.0
    return Bar(time="t", open=open_px, high=high, low=low, close=close, volume=100.0)


@pytest.fixture
def minimal_ctx_factory():
    def _factory(entry=100.0, anchor_distance_pct=None, inverted=False):
        # Create a strong bullish candle to pass Gate 3 candle acceptance:
        # - Body must be >= 60% of range (full body min ratio)
        # - Close must be in outer 25% of range (near the high for LONG)
        # Example: open=98, close=100, high=100.5, low=97.5
        #   body = 2, span = 3, body_ratio = 67% ✓
        #   (close - low) / span = 2.5 / 3 = 83% ✓
        bar = _bar(close=entry, open_offset=-2.0)  # open=98, close=100
        # Adjust high/low to make close near the high
        bar = Bar(
            time="t",
            open=entry - 2.0,  # 98
            high=entry + 0.5,  # 100.5
            low=entry - 2.5,   # 97.5
            close=entry,       # 100
            volume=100.0,
        )
        if anchor_distance_pct is not None:
            # razor stop: VAL very close to entry so is_stop_too_thin triggers
            # e.g. 0.01% on 100 => val 99.99 => sl 99.95 => distance 0.05 < 0.1 => thin
            val = entry * (1 - anchor_distance_pct / 100.0)
            vah = entry + 2.0  # keep vah above entry so anchor resolves to val
            poc = entry
        else:
            # default healthy stop values; for inverted we still need valid base
            # need val far enough for healthy but test will mock tp to invert
            val = 98.0 if entry == 100 else entry * 0.98
            vah = val + 2.0 if not inverted else entry + 2.0
            poc = entry
        ctx = DecisionContext(
            state=None,
            bar=bar,
            symbol="SYM",
            time_str="t",
            agent_direction="LONG",
            agent_probability=0.7,
            market_state=MarketState.IMBALANCED,
            poc=poc,
            vah=vah,
            val=val,
            bid=entry - 0.05,
            ask=entry + 0.05,
            tick_size=0.05,
            cvd_slope=1.0,
            session_vwap=entry - 0.5,
            absorption_side="SELL_ABSORBED",
            absorption_cluster_low=entry - 1.0,
            absorption_cluster_high=entry - 0.5,
            triple_a_phase="AGGRESSION",
            triple_a_signal="LONG",
            leg_lvn=entry,  # Fabio Trend Model: pullback to the impulse LVN
            session_open=True,
            warmup_complete=True,
            position_open=False,
            cooldown_remaining_sec=0,
            allow_trend=True,
            allow_reversion=True,
        )
        return ctx

    return _factory


def test_thin_stop_drop_reports_reason(minimal_ctx_factory):
    ctx = minimal_ctx_factory(entry=100.0, anchor_distance_pct=0.01)  # razor stop
    # The anchor now walks to a deeper structural level when the nearest is
    # noise. Force the guard by demanding an implausibly wide minimum stop so
    # even the deepest anchor is rejected as thin noise.
    sig, why = SignalBuilder(min_stop_distance_pct=500.0).build_or_reason(ctx, [], "TEST")
    assert sig is None
    assert why == "thin stop"


def test_inverted_levels_drop_reports_reason(minimal_ctx_factory):
    ctx = minimal_ctx_factory(inverted=True)
    # Force inverted TP: LONG expects tp > entry, return below entry to trigger monotonic fail
    with patch.object(SignalBuilder, "_structural_tp", return_value=float(ctx.bar.close) - 5.0):
        sig, why = SignalBuilder().build_or_reason(ctx, [], "TEST")
        assert sig is None
        assert why.startswith("inverted signal")


def test_service_block_reason_includes_builder_drop(minimal_ctx_factory):
    """GATE_REJECTED with empty block_reasons was unauditable (cert E5)."""
    svc = DecisionService()
    ctx = minimal_ctx_factory(entry=100.0, anchor_distance_pct=0.01)
    # Force the builder drop so the assertion tests DecisionService's
    # block_reasons wiring, independent of anchor/stop-distance policy.
    with patch.object(SignalBuilder, "build_or_reason", return_value=(None, "forced drop")):
        dec = svc.evaluate(ctx)
    assert dec.reason == "GATE_REJECTED"
    assert any(r.startswith("SIGNAL_BUILDER:") for r in dec.block_reasons)
