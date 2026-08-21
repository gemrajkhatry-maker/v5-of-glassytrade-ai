# tests/quant/decision/test_option_signal_translation.py
"""Tests for Option Delta Translation and Risk per Unit (Task 5)."""

import pytest
from quant.amt.session.selector import OptionSelector, OptionSelectorConfig


def test_delta_stop_mapping_scales_underlying_stop_to_option_stop():
    selector = OptionSelector()
    equity = 1_000_000.0
    risk_pct = 0.005  # 0.5% = ₹5,000
    underlying_stop_points = 20.0
    delta = 0.50
    lot_size = 50  # NIFTY lot
    
    lots = selector.compute_option_lot_size(
        account_equity=equity,
        risk_pct=risk_pct,
        underlying_stop_points=underlying_stop_points,
        option_delta=delta,
        lot_size=lot_size,
    )
    # Option stop = 20 * 0.5 = 10 points
    # Loss per lot = 10 * 50 = ₹500
    # Lots = 5000 / 500 = 10 lots
    assert lots == 10


def test_cushion_adds_portion_of_session_profit():
    selector = OptionSelector()
    equity = 1_000_000.0
    risk_pct = 0.005  # ₹5,000 base
    session_profit = 10_000.0  # +20% = +₹2,000 -> ₹7,000 total risk
    underlying_stop_points = 20.0
    delta = 0.50  # 10 option points
    lot_size = 50  # ₹500/lot
    
    lots = selector.compute_option_lot_size(
        account_equity=equity,
        risk_pct=risk_pct,
        underlying_stop_points=underlying_stop_points,
        option_delta=delta,
        lot_size=lot_size,
        session_profit=session_profit,
    )
    # Total risk = ₹7,000 / ₹500 = 14 lots
    assert lots == 14


def test_expiry_day_caps_max_lots():
    selector = OptionSelector()
    equity = 10_000_000.0
    risk_pct = 0.05
    underlying_stop_points = 5.0
    delta = 0.50
    lot_size = 50
    
    normal_lots = selector.compute_option_lot_size(
        account_equity=equity,
        risk_pct=risk_pct,
        underlying_stop_points=underlying_stop_points,
        option_delta=delta,
        lot_size=lot_size,
        max_lots_cap=50,
        is_expiry=False,
    )
    expiry_lots = selector.compute_option_lot_size(
        account_equity=equity,
        risk_pct=risk_pct,
        underlying_stop_points=underlying_stop_points,
        option_delta=delta,
        lot_size=lot_size,
        max_lots_cap=50,
        is_expiry=True,
    )
    assert expiry_lots <= normal_lots // 2


def test_translate_rejects_cross_scale_signal():
    """A futures-scale entry (160646) vs option premium (~2837) must be
    rejected with None — never mistranslated (phantom P&L guard)."""
    from quant.decision.signal_builder import Signal
    from quant.amt.session.selector import OptionSelector

    sig = Signal(type="LONG", reason="r", entry=160646.0, sl=160299.9,
                 tp=161338.2, rr=2.0, model_label="Triple-A",
                 symbol="GOLDM SEP FUT", timestamp="t")
    out = OptionSelector().translate_underlying_signal_to_option(
        signal=sig, option_symbol="GOLDM 28 AUG 159500 CALL",
        option_ltp=2837.0, delta=0.5, tick_size=0.05,
    )
    assert out is None


def test_translate_accepts_near_scale_signal():
    """Same-scale (futures->futures-priced option context) signals translate."""
    from quant.decision.signal_builder import Signal
    from quant.amt.session.selector import OptionSelector

    sig = Signal(type="LONG", reason="r", entry=100.0, sl=99.0,
                 tp=102.0, rr=2.0, model_label="Triple-A", symbol="U", timestamp="t")
    out = OptionSelector().translate_underlying_signal_to_option(
        signal=sig, option_symbol="OPT CALL", option_ltp=45.0,
        delta=0.5, tick_size=0.05,
    )
    assert out is not None and out.entry == pytest.approx(45.0)
