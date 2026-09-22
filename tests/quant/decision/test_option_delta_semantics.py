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


def test_option_delta_is_none_without_greeks_port():
    """Money-path: missing GreeksPort → option_delta is None (never invent 0.50)."""
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
    assert ctx.option_delta is None

    ctx_fut = DecisionContextBuilder().build(
        bar=bar, symbol="NIFTY FUT", market="NSE", contract_expiry=None,
        tick_size=0.05, bar_index=20, warm_bars=0, cooldown_remaining_sec=0.0,
        risk_state=risk, amt_dto={},
    )
    assert ctx_fut.option_delta is None


def test_option_delta_keys_off_contract_not_eval_symbol():
    """P0-3: underlying eval_symbol + contract_symbol + GreeksPort → delta set."""
    from types import SimpleNamespace

    from quant.contracts.ports.greeks import DictGreeks
    from quant.decision.context_builder import DecisionContextBuilder

    bar = SimpleNamespace(close=25000.0, open=24990.0, high=25010.0, low=24980.0,
                          volume=100, time="2026-09-10T10:00:00+05:30")
    risk = SimpleNamespace(halted=False, consecutive_losses=0,
                           equity=1_000_000.0, risk_per_trade_pct=0.05)
    greeks = DictGreeks({"NIFTY 24600 CALL": 0.55})

    ctx = DecisionContextBuilder(greeks=greeks).build(
        bar=bar, symbol="NIFTY FUT", market="NSE", contract_expiry=None,
        tick_size=0.05, bar_index=20, warm_bars=0, cooldown_remaining_sec=0.0,
        risk_state=risk, amt_dto={},
        contract_symbol="NIFTY 24600 CALL",
    )
    assert ctx.option_delta == 0.55


def test_greeks_port_supplies_option_delta():
    from types import SimpleNamespace

    from quant.decision.context_builder import DecisionContextBuilder

    class _Greeks:
        def delta(self, symbol: str) -> float | None:
            return 0.42

    bar = SimpleNamespace(close=150.0, open=149.0, high=151.0, low=148.0,
                          volume=100, time="2026-09-10T10:00:00+05:30")
    risk = SimpleNamespace(halted=False, consecutive_losses=0,
                           equity=1_000_000.0, risk_per_trade_pct=0.05)

    ctx = DecisionContextBuilder(greeks=_Greeks()).build(
        bar=bar, symbol="NIFTY 24600 CALL", market="NSE", contract_expiry=None,
        tick_size=0.05, bar_index=20, warm_bars=0, cooldown_remaining_sec=0.0,
        risk_state=risk, amt_dto={},
    )
    assert ctx.option_delta == 0.42

