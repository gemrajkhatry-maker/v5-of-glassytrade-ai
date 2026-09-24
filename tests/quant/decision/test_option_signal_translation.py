# tests/quant/decision/test_option_signal_translation.py
"""Tests for Option Delta Translation and Risk per Unit (Task 5)."""

import pytest

from quant.execution.risk import SessionRisk


def test_delta_stop_mapping_scales_underlying_stop_to_option_stop():
    """Delta-mapped option stop sizes through the SSoT sizing authority.

    Underlying stop 20 pts x delta 0.50 -> 10-point option stop
    (the delta mapping itself is pinned by the translate tests below).
    SessionRisk.position_size is the single sizing authority:
    HMP CONSERVATIVE tier risks 0.25% of equity = Rs2,500;
    loss per lot = 10 pts * 50 = Rs500 -> 5 lots = 250 units.
    """
    risk = SessionRisk(starting_equity=1_000_000.0, day_of_week=1)
    qty = risk.position_size(entry=100.0, sl=90.0, lot_size=50)
    assert qty == 250.0


def test_expiry_day_caps_max_lots():
    """Expiry day sizes at most half the normal position (SSoT is_expiry)."""
    risk = SessionRisk(starting_equity=10_000_000.0, day_of_week=1)
    normal = risk.position_size(entry=100.0, sl=95.0, lot_size=50, is_expiry=False)
    expiry = risk.position_size(entry=100.0, sl=95.0, lot_size=50, is_expiry=True)
    assert expiry <= normal // 2


def test_translate_translates_underlying_signal_to_option():
    """A futures-scale entry (160646) vs option premium (~2837) translates cleanly
    using delta adjustment into option premium entry, SL, and TP."""
    from quant.decision.signal_builder import Signal
    from quant.amt.session.selector import OptionSelector

    sig = Signal(type="LONG", reason="r", entry=160646.0, sl=160299.9,
                 tp=161338.2, rr=2.0, model_label="Triple-A",
                 symbol="GOLDM SEP FUT", timestamp="t")
    out = OptionSelector().translate_underlying_signal_to_option(
        signal=sig, option_symbol="GOLDM CALL",
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
    sig = SignalBuilder().build(ctx, [GateResult(i, True) for i in range(1, 5)], model_label="Triple-A")
    assert sig is not None
    # SL = 2 ticks behind the print wall: 99.4 - 0.10
    assert sig.sl == pytest.approx(99.30)


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
    sig = SignalBuilder().build(ctx, [GateResult(i, True) for i in range(1, 5)], model_label="Triple-A")
    assert sig is not None
    assert sig.sl == pytest.approx(100.90)


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
    sig = SignalBuilder().build(ctx, [GateResult(i, True) for i in range(1, 5)], model_label="Triple-A")
    assert sig is not None
    # SL = 2 ticks behind broken VAL: 101.0 + 0.10
    assert sig.sl == pytest.approx(101.10), f"SL {sig.sl} anchored wrong"


def test_option_spread_policy_matches_amt_and_expiry_tightens_limit():
    from quant.bars import Bar
    from quant.decision.context import DecisionContext
    from quant.decision.gate_session_phase import gate_session_phase

    def context(is_expiry: bool) -> DecisionContext:
        return DecisionContext(
            bar=Bar(time="t0", open=50.0, high=50.2, low=49.8, close=50.0, volume=1.0),
            symbol="NIFTY 25000 CALL",
            session_open=True,
            warmup_complete=True,
            bid=49.30,
            ask=50.70,
            tick_size=0.05,
            is_expiry=is_expiry,
        )

    normal = gate_session_phase(context(False))
    expiry = gate_session_phase(context(True))

    assert normal.passed is True
    assert expiry.passed is False


def test_translation_rejects_option_stop_wider_than_thirty_percent_of_premium():
    from quant.amt.session.selector import OptionSelector
    from quant.decision.signal_builder import Signal

    signal = Signal(
        type="LONG", reason="Triple-A", entry=100.0, sl=60.0, tp=180.0,
        rr=2.0, model_label="Triple-A", symbol="NIFTY FUT", timestamp="t0",
    )

    result = OptionSelector().translate_underlying_signal_to_option(
        signal=signal,
        option_symbol="NIFTY 25000 CALL",
        option_ltp=100.0,
        delta=1.0,
        tick_size=0.05,
    )

    assert result is None


def test_translation_uses_option_premium_for_stop_cap():
    from quant.amt.session.selector import OptionSelector
    from quant.decision.signal_builder import Signal

    signal = Signal(
        type="LONG", reason="Triple-A", entry=100.0, sl=0.0, tp=300.0,
        rr=2.0, model_label="Triple-A", symbol="NIFTY FUT", timestamp="t0",
    )

    result = OptionSelector().translate_underlying_signal_to_option(
        signal=signal,
        option_symbol="NIFTY 25000 CALL",
        option_ltp=400.0,
        delta=1.0,
        tick_size=0.05,
    )

    assert result is not None
    assert result.sl == 300.0


def test_entry_and_exit_spread_use_the_same_mid_basis():
    from quant.bars import Bar
    from quant.decision.context import DecisionContext
    from quant.decision.gate_session_phase import gate_session_phase
    from quant.decision.signal_builder import Signal
    from quant.execution.exits import ExitEngine
    from quant.execution.order import Order, Position

    bid, ask = 999.75, 1000.25
    ctx = DecisionContext(
        bar=Bar(time="t0", open=bid, high=ask, low=bid, close=1.0, volume=1.0),
        symbol="NIFTY 25000 CALL",
        session_open=True,
        warmup_complete=True,
        bid=bid,
        ask=ask,
        tick_size=0.05,
    )
    assert gate_session_phase(ctx).passed is True

    signal = Signal(
        type="LONG", reason="test", entry=1000.0, sl=900.0, tp=1200.0,
        rr=2.0, model_label="test", symbol="NIFTY 25000 CALL", timestamp="t0",
    )
    position = Position(
        order=Order(signal, 1.0), open_price=1000.0, open_time="t0", size=1.0
    )
    decision = ExitEngine().evaluate(
        position,
        bar_close=1.0,
        bar_high=1000.0,
        bar_low=1000.0,
        best_bid=bid,
        best_ask=ask,
    )

    assert decision.reason != "SPREAD_BLOWOUT"
    assert decision.should_exit is False
