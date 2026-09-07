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
