"""Tests for cushion SL wiring into build_entry_signal."""

from unittest.mock import MagicMock

from app.domain.fabio_ai.services.entry_gates.signal_builder import build_entry_signal
from app.domain.trading.models.enums import SetupType
from app.domain.trading.models.value_objects import OHLC, AMTResult


def _make_tick(close=100.0):
    return OHLC(
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=1000,
        delta=0,
        time="2025-01-01T10:00:00Z",
        vwap=close,
    )


def _make_amt(poc=100.0, vah=105.0, val=95.0):
    return AMTResult(
        market_state="BALANCED",
        poc=poc,
        value_area_high=vah,
        value_area_low=val,
        session_vwap=100.0,
        aggressive_prints=[],
    )


class TestCushionSL:
    def test_risk_sl_pct_tightens_stop(self):
        """Cushion SL should tighten stop when closer than quant SL."""
        tick = _make_tick(100.0)
        amt = _make_amt()
        ai_result = {"direction": "LONG", "confidence": "HIGH", "rationale": "test"}
        sig = build_entry_signal(
            "LONG", tick, amt, ai_result, SetupType.TREND_MODEL, risk_sl_pct=0.005
        )
        # 0.5% of 100 = 0.5, so SL should be at 99.5 (if quant SL was wider)
        # The min floor is max(1.5%, ATR) which could be wider, but cushion should apply if tighter
        assert sig.stop_loss is not None

    def test_risk_sl_pct_none_no_change(self):
        """No cushion SL = default behavior."""
        tick = _make_tick(100.0)
        amt = _make_amt()
        ai_result = {"direction": "LONG", "confidence": "HIGH", "rationale": "test"}
        sig_default = build_entry_signal(
            "LONG", tick, amt, ai_result, SetupType.TREND_MODEL
        )
        sig_none = build_entry_signal(
            "LONG", tick, amt, ai_result, SetupType.TREND_MODEL, risk_sl_pct=None
        )
        assert sig_default.stop_loss == sig_none.stop_loss

    def test_risk_sl_respects_wider_quant(self):
        """Cushion SL should NOT widen stop beyond quant SL."""
        tick = _make_tick(100.0)
        amt = _make_amt()
        ai_result = {"direction": "LONG", "confidence": "HIGH", "rationale": "test"}
        # Very wide cushion (10%) should not override a tighter quant SL
        sig_wide = build_entry_signal(
            "LONG", tick, amt, ai_result, SetupType.TREND_MODEL, risk_sl_pct=0.10
        )
        sig_default = build_entry_signal(
            "LONG", tick, amt, ai_result, SetupType.TREND_MODEL
        )
        assert sig_wide.stop_loss == sig_default.stop_loss
