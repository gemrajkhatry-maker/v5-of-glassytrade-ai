"""Option translation must use Greek delta, not candle order-flow delta."""

import pytest

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
        option_symbol="NIFTY 25000 CE",
        option_ltp=100.0,
        delta=None,
        tick_size=0.05,
    )

    assert result is None


def test_translation_preserves_explicit_greek_delta():
    result = OptionSelector().translate_underlying_signal_to_option(
        signal=_signal(),
        option_symbol="NIFTY 25000 CE",
        option_ltp=100.0,
        delta=0.65,
        tick_size=0.05,
    )

    assert result is not None
    assert result.sl == 87.0


@pytest.mark.parametrize("delta", ["not-a-number", True, 0.0, 1.5, float("nan"), object()])
def test_translation_rejects_malformed_or_invalid_delta(delta):
    result = OptionSelector().translate_underlying_signal_to_option(
        signal=_signal(),
        option_symbol="NIFTY 25000 CE",
        option_ltp=100.0,
        delta=delta,
        tick_size=0.05,
    )

    assert result is None


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


def test_scanner_missing_delta_is_none_and_contract_is_not_scored():
    from types import SimpleNamespace

    from quant.amt.session.scanner import OptionScannerService

    scanner = OptionScannerService(SimpleNamespace())
    option = SimpleNamespace(
        symbol="NIFTY 25000 CALL",
        ltp=50.0,
        oi=10_000,
        volume=1_000,
        bid=49.0,
        ask=51.0,
        delta=None,
        iv=15.0,
    )

    score = OptionScannerService._score_contract(
        strike=100,
        atm=100,
        interval=50,
        oi=10_000,
        vol=1_000,
        opt=option,
        ltp=50.0,
        bid=49.0,
        ask=51.0,
        underlying_upper="NIFTY",
    )

    assert score[0] == 0.0
    assert score[2] is None
    assert scanner._process_contract(
        u="NIFTY",
        opt_type="CE",
        strike=100,
        atm=100,
        interval=50,
        option_map={100.0: option},
        bullish_only=False,
        bias="BULLISH",
        bias_reason="test",
        chain=SimpleNamespace(),
        is_mcx=False,
    ) is None


def test_scanner_fallback_skips_missing_delta():
    from datetime import timedelta
    from types import SimpleNamespace

    from quant.amt.session.scanner import OptionScannerService
    from quant.contracts.timezones import today_ist

    option = SimpleNamespace(
        symbol="NIFTY 25000 CALL",
        ltp=100.0,
        oi=10_000,
        volume=1_000,
        bid=99.0,
        ask=101.0,
        delta=None,
        iv=15.0,
    )
    chain = SimpleNamespace(
        expiry=today_ist() + timedelta(days=7),
        atm_strike=100.0,
        calls={100.0: option},
        puts={},
        spot_price=100.0,
    )
    scanner = OptionScannerService(SimpleNamespace())

    assert scanner._fallback_atm(["NIFTY"], 0, chains={"NIFTY": chain}) == []


@pytest.mark.parametrize("delta", ["not-a-number", True, 0.0, 1.5, float("nan"), object()])
def test_scanner_rejects_malformed_or_invalid_delta(delta):
    from types import SimpleNamespace

    from quant.amt.session.scanner import OptionScannerService

    option = SimpleNamespace(
        symbol="NIFTY 25000 CALL",
        ltp=100.0,
        oi=10_000,
        volume=1_000,
        bid=99.0,
        ask=101.0,
        delta=delta,
        iv=15.0,
    )
    score = OptionScannerService._score_contract(
        strike=100,
        atm=100,
        interval=50,
        oi=10_000,
        vol=1_000,
        opt=option,
        ltp=100.0,
        bid=99.0,
        ask=101.0,
        underlying_upper="NIFTY",
    )

    assert score[0] == 0.0
    assert score[2] is None
    scanner = OptionScannerService(SimpleNamespace())
    assert scanner._process_contract(
        u="NIFTY",
        opt_type="CE",
        strike=100,
        atm=100,
        interval=50,
        option_map={100.0: option},
        bullish_only=False,
        bias="BULLISH",
        bias_reason="test",
        chain=SimpleNamespace(),
        is_mcx=False,
    ) is None


def test_timesfm_option_scoring_rejects_missing_delta():
    from types import SimpleNamespace

    from quant.decision.timesfm_option_selector import simulate_contract_payoff

    option = SimpleNamespace(
        ltp=100.0,
        bid=99.0,
        ask=101.0,
        oi=100_000,
        volume=10_000,
        delta=None,
    )

    assert simulate_contract_payoff(
        opt=option,
        strike=24600,
        option_type="CE",
        underlying="NIFTY",
        expiry_str="2099-12-31",
        forecast=None,
        direction="LONG",
    ) is None

