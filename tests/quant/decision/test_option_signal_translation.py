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


def test_translate_translates_underlying_signal_to_option():
    """A futures-scale entry (160646) vs option premium (~2837) translates cleanly
    using delta adjustment into option premium entry, SL, and TP."""
    from quant.decision.signal_builder import Signal
    from quant.amt.session.selector import OptionSelector

    sig = Signal(type="LONG", reason="r", entry=160646.0, sl=160299.9,
                 tp=161338.2, rr=2.0, model_label="Triple-A",
                 symbol="GOLDM SEP FUT", timestamp="t")
    out = OptionSelector().translate_underlying_signal_to_option(
        signal=sig, option_symbol="GOLDM 28 AUG 159500 CALL",
        option_ltp=2837.0, delta=0.5, tick_size=0.05,
    )
    assert out is not None
    assert out.entry == 2837.0
    # Underlying risk = 346.1 * 0.50 delta = 173.05 -> SL = 2663.95
    assert out.sl == pytest.approx(2837.0 - 173.05, abs=0.1)


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


def test_opposing_stacked_imbalance_blocks_entry():
    """C1: stacked SELL imbalance must block a LONG entry (Fabio volume
    bubble guard — institutional size fighting the trade)."""
    from quant.decision.context import DecisionContext
    from quant.decision.gates_edge import gate_triple_a_edge
    from quant.bars import Bar

    bar = Bar(time="t", open=100, high=101, low=99, close=100.5, volume=10)
    ctx = DecisionContext(
        bar=bar, symbol="S", agent_direction="LONG",
        stacked_imbalance_direction="SELL", stacked_imbalance_magnitude=4,
        stacked_imbalance_price_low=99.0, stacked_imbalance_price_high=100.0,
    )
    res = gate_triple_a_edge(ctx)
    assert not res.passed
    assert "Opposing stacked SELL" in (res.reason or "")


def test_aligned_stacked_imbalance_does_not_block():
    """Aligned stacked flow must NOT block the entry."""
    from quant.decision.context import DecisionContext
    from quant.decision.gates_edge import gate_triple_a_edge
    from quant.bars import Bar

    bar = Bar(time="t", open=100, high=101, low=99, close=100.5, volume=10)
    ctx = DecisionContext(
        bar=bar, symbol="S", agent_direction="LONG",
        stacked_imbalance_direction="BUY", stacked_imbalance_magnitude=4,
        stacked_imbalance_price_low=100.0, stacked_imbalance_price_high=101.0,
    )
    # Gate may fail for other reasons but must NOT cite opposing imbalance.
    res = gate_triple_a_edge(ctx)
    assert "Opposing stacked" not in (res.reason or "")


def test_print_wall_anchors_sl_for_long():
    """Gap #10: a big BUY print below price becomes SL support — the wall
    beats VA/LVN in anchor priority."""
    from dataclasses import replace as _dc_replace
    from quant.decision.context import DecisionContext
    from quant.decision.signal_builder import SignalBuilder
    from quant.decision.result import GateResult
    from quant.bars import Bar

    bar = Bar(time="t", open=100.0, high=100.1, low=99.9, close=100.0, volume=10)
    ctx = DecisionContext(
        bar=bar, symbol="S", agent_direction="LONG",
        val=98.0, vah=102.0, poc=100.0, tick_size=0.05,
        nearest_buy_print_below=99.4,  # big BUY print at 99.4
    )
    sig = SignalBuilder().build(ctx, [GateResult(i, True) for i in range(1, 5)])
    assert sig is not None
    # SL = 2 ticks inside the print wall: 99.4 + 0.10
    assert sig.sl == pytest.approx(99.50)


def test_print_wall_anchors_sl_for_short():
    """A big SELL print above price is short-side resistance anchor."""
    from quant.decision.context import DecisionContext
    from quant.decision.signal_builder import SignalBuilder
    from quant.decision.result import GateResult
    from quant.bars import Bar

    bar = Bar(time="t", open=100.0, high=100.1, low=99.9, close=100.0, volume=10)
    ctx = DecisionContext(
        bar=bar, symbol="S", agent_direction="SHORT",
        val=98.0, vah=102.0, poc=100.0, tick_size=0.05,
        nearest_sell_print_above=100.8,
    )
    sig = SignalBuilder().build(ctx, [GateResult(i, True) for i in range(1, 5)])
    assert sig is not None
    assert sig.sl == pytest.approx(100.70)


def test_contested_bubble_zone_blocks_entry():
    """Fabio contested zone: both BUY and SELL stacked imbalances recently =
    neither side has control = FLAT is the only trade."""
    from quant.decision.context import DecisionContext
    from quant.decision.gates_edge import gate_triple_a_edge
    from quant.bars import Bar

    bar = Bar(time="t", open=100, high=101, low=99, close=100.5, volume=10)
    ctx = DecisionContext(
        bar=bar, symbol="S", agent_direction="LONG",
        contested_bubble_zone=True,
    )
    res = gate_triple_a_edge(ctx)
    assert not res.passed
    assert "Contested bubble zone" in (res.reason or "")


def test_short_sl_anchors_to_broken_val_not_session_vah():
    """Fix: on a downside break below VAL, the short SL anchors to the
    BROKEN VAL (tight, overhead) — not session VAH which sits 3-5x further."""
    from quant.decision.context import DecisionContext
    from quant.decision.signal_builder import SignalBuilder
    from quant.decision.result import GateResult
    from quant.bars import Bar

    # Price 100 broke below VAL=101 (VAL now overhead); session VAH=105 far above.
    bar = Bar(time="t", open=102, high=102.1, low=99.9, close=100.0, volume=10)
    ctx = DecisionContext(
        bar=bar, symbol="S", agent_direction="SHORT",
        val=101.0, vah=105.0, poc=103.0, tick_size=0.05,
    )
    sig = SignalBuilder().build(ctx, [GateResult(i, True) for i in range(1, 5)])
    assert sig is not None
    # SL = 2 ticks inside broken VAL: 101.0 - 0.10
    assert sig.sl == pytest.approx(100.90), f"SL {sig.sl} anchored wrong"
