"""Option translation must use Greek delta, not candle order-flow delta."""

from quant.amt.session.selector import OptionSelector
from quant.decision.signal_builder import Signal


def _signal():
    return Signal(
        type="LONG",
        reason="Triple-A",
        entry=25000.0,
        sl=24980.0,
        tp=25040.0,
        rr=2.0,
        model_label="Triple-A",
        symbol="NIFTY FUT",
        timestamp="t0",
    )


def test_translation_requires_explicit_greek_delta():
    result = OptionSelector().translate_underlying_signal_to_option(
        signal=_signal(),
        option_symbol="NIFTY 30 SEP 25000 CE",
        option_ltp=100.0,
        delta=None,
        tick_size=0.05,
    )

    assert result is None


def test_translation_preserves_explicit_greek_delta():
    result = OptionSelector().translate_underlying_signal_to_option(
        signal=_signal(),
        option_symbol="NIFTY 30 SEP 25000 CE",
        option_ltp=100.0,
        delta=0.65,
        tick_size=0.05,
    )

    assert result is not None
    assert result.sl == 87.0


def test_option_delta_is_a_documented_default_not_a_chain_greek():
    """D-6 (corrected): no chain-Greek producer exists, so option_delta is
    always the documented ATM default. Assert that plainly so a future reader
    (or a future chain integration) cannot mistake it for a real Greek."""
    from types import SimpleNamespace

    from quant.decision.context_builder import DecisionContextBuilder

    bar = SimpleNamespace(close=150.0, open=149.0, high=151.0, low=148.0,
                          volume=100, time="2026-09-10T10:00:00+05:30")
    risk = SimpleNamespace(halted=False, consecutive_losses=0,
                           equity=1_000_000.0, risk_per_trade_pct=0.05)

    ctx = DecisionContextBuilder().build(
        bar=bar, symbol="NIFTY 24600 CALL", market="NSE", contract_expiry=None,
        tick_size=0.05, bar_index=20, warm_bars=0, cooldown_remaining_sec=0.0,
        risk_state=risk, amt_dto={},
    )
    # Options get the conservative ATM default; futures get None.
    assert ctx.option_delta == 0.50

    ctx_fut = DecisionContextBuilder().build(
        bar=bar, symbol="NIFTY FUT", market="NSE", contract_expiry=None,
        tick_size=0.05, bar_index=20, warm_bars=0, cooldown_remaining_sec=0.0,
        risk_state=risk, amt_dto={},
    )
    assert ctx_fut.option_delta is None
