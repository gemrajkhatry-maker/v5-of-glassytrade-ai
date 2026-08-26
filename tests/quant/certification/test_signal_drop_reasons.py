"""All-gates-pass-but-builder-drops must carry an explainable reason."""

import pytest
from unittest.mock import patch

from quant.bars import Bar
from quant.contracts.enums import MarketState
from quant.decision.context import DecisionContext
from quant.decision.decision_service import DecisionService
from quant.decision.signal_builder import SignalBuilder


def _bar(close=100.0):
    return Bar(time="t", open=close, high=close + 1.0, low=close - 1.0, close=close, volume=100.0)


@pytest.fixture
def minimal_ctx_factory():
    def _factory(entry=100.0, anchor_distance_pct=None, inverted=False):
        bar = _bar(close=entry)
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
            tick_size=0.05,
            cvd_slope=1.0,
            triple_a_phase="AGGRESSION",
            triple_a_signal="LONG",
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
    sig, why = SignalBuilder().build_or_reason(ctx, [])
    assert sig is None
    assert why == "thin stop"


def test_inverted_levels_drop_reports_reason(minimal_ctx_factory):
    ctx = minimal_ctx_factory(inverted=True)
    # Force inverted TP: LONG expects tp > entry, return below entry to trigger monotonic fail
    with patch.object(SignalBuilder, "_structural_tp", return_value=float(ctx.bar.close) - 5.0):
        sig, why = SignalBuilder().build_or_reason(ctx, [])
        assert sig is None
        assert why.startswith("inverted signal")


def test_service_block_reason_includes_builder_drop(minimal_ctx_factory):
    """GATE_REJECTED with empty block_reasons was unauditable (cert E5)."""
    svc = DecisionService()
    ctx = minimal_ctx_factory(entry=100.0, anchor_distance_pct=0.01)
    dec = svc.evaluate(ctx)
    assert dec.reason == "GATE_REJECTED"
    assert any(r.startswith("SIGNAL_BUILDER:") for r in dec.block_reasons)
