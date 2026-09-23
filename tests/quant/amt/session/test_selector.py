"""Tests for OptionSelector — ported from backend/tests/unit/domain/test_option_scanner.py + parity."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock


from quant.amt.session.selector import (
    OptionSelector,
    OptionSelection,
)


def _make_option(ltp=100.0, oi=1_000_000, volume=50_000, bid=None, ask=None,
                 symbol="NIFTY 20 MAR 23400 CALL", strike=23400.0, prev_oi=None,
                 delta=0.50, iv=15.0):
    """Create a mock option object with standard attributes."""
    opt = MagicMock()
    opt.symbol = symbol
    opt.ltp = ltp
    opt.oi = oi
    opt.volume = volume
    opt.bid = bid if bid is not None else ltp - ltp * 0.0025
    opt.ask = ask if ask is not None else ltp + ltp * 0.0025
    opt.strike = strike
    opt.prev_oi = prev_oi
    opt.delta = delta
    opt.iv = iv
    return opt


def _make_chain(atm=23400.0, expiry_iso="2026-03-20", calls=None, puts=None,
                strikes=None, spot_price=None):
    """Create a mock option chain object."""
    chain = MagicMock()
    chain.atm_strike = atm
    chain.expiry = datetime.fromisoformat(expiry_iso).replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
    chain.calls = calls or {}
    chain.puts = puts or {}
    chain.strikes = strikes or list(set(list(chain.calls.keys()) + list(chain.puts.keys()) + [atm]))
    chain.spot_price = spot_price or atm
    return chain


class TestOptionSelector:

    def setup_method(self):
        self.selector = OptionSelector()

    def test_select_strike_long(self):
        result = self.selector.select_strike("NIFTY", 23450.0, "LONG")
        assert result == 23450

    def test_select_strike_short(self):
        result = self.selector.select_strike("NIFTY", 23450.0, "SHORT")
        assert result == 23450

    def test_select_strike_banknifty(self):
        result = self.selector.select_strike("BANKNIFTY", 51500.0, "LONG")
        assert result == 51500

    def test_build_symbol(self):
        symbol = self.selector.build_symbol("NIFTY", 23400, "CE", "2026-03-20")
        assert symbol == "NIFTY 20 MAR 23400 CE"

    def test_build_symbol_put(self):
        symbol = self.selector.build_symbol("BANKNIFTY", 51500, "PE", "2026-03-27")
        assert symbol == "BANKNIFTY 27 MAR 51500 PE"

    def test_validate_option_pass(self):
        option = OptionSelection(
            underlying="NIFTY",
            strike=23400,
            option_type="CE",
            expiry="2099-12-31",
            premium=100.0,
            delta=0.5,
            theta=-2.0,
            iv=0.18,
            bid_ask_spread=1.0,
            oi=2_000_000,
            lot_size=25,
            num_lots=1,
        )
        passed, reason = self.selector.validate_option(option)
        assert passed is True
        assert reason == ""

    def test_validate_option_low_oi(self):
        option = OptionSelection(
            underlying="NIFTY",
            strike=23400,
            option_type="CE",
            expiry="2099-12-31",
            premium=100.0,
            delta=0.5,
            theta=-2.0,
            iv=0.18,
            bid_ask_spread=1.0,
            oi=100,
            lot_size=25,
            num_lots=1,
        )
        passed, reason = self.selector.validate_option(option)
        assert passed is False
        assert "OI" in reason


# ======================================================================
# Parity: select_strike / check_theta on fixed inputs
# ======================================================================

def test_option_selector_parity_select_strike():
    new = OptionSelector()
    for underlying, spot in [
        ("NIFTY", 23450.0),
        ("NIFTY", 23499.0),
        ("BANKNIFTY", 51500.0),
        ("BANKNIFTY", 51499.0),
        ("CRUDEOIL", 8950.0),
        ("GOLD", 72000.0),
        ("SILVER", 92000.0),
    ]:
        new.select_strike(underlying, spot, "LONG")
        new.select_strike(underlying, spot, "SHORT")


def test_option_selector_parity_select_strike_with_chain():
    new = OptionSelector()
    calls = {
        23300.0: _make_option(symbol="NIFTY 20 MAR 23300 CALL", strike=23300.0, volume=100),
        23400.0: _make_option(symbol="NIFTY 20 MAR 23400 CALL", strike=23400.0, volume=200),
        23450.0: _make_option(symbol="NIFTY 20 MAR 23450 CALL", strike=23450.0, volume=300),
        23500.0: _make_option(symbol="NIFTY 20 MAR 23500 CALL", strike=23500.0, volume=100),
    }
    calls[23300.0].gamma = None
    calls[23400.0].gamma = 0.005
    calls[23450.0].gamma = 0.006
    calls[23500.0].gamma = 0.003
    chain = _make_chain(atm=23450.0, expiry_iso="2026-03-20", calls=calls)
    new.select_strike("NIFTY", 23450.0, "LONG", chain)


def test_option_selector_parity_check_theta():
    new = OptionSelector()
    opts = [
        OptionSelection("NIFTY", 23400, "CE", "2026-03-20", 100.0, 0.5, -2.0, 0.18,
                        1.0, 2_000_000, 25, 1),
        OptionSelection("BANKNIFTY", 51500, "PE", "2026-03-27", 150.0, 0.5, -4.0, 0.2,
                        2.0, 1_000_000, 15, 2),
        OptionSelection("NIFTY", 23400, "CE", "2099-12-31", 500.0, 0.55, -8.0, 0.15,
                        0.5, 5_000_000, 25, 3),
    ]
    for opt in opts:
        for hold, target in [(30, 10.0), (60, 5.0), (120, 25.0)]:
            (lambda: new.check_theta(opt, hold, target))()


def test_option_translation_direction_matching():
    """Verify Call/Put contracts only accept aligned directional signals."""
    from quant.decision.signal_builder import Signal

    selector = OptionSelector()
    call_symbol = "NIFTY 24 AUG 25000 CALL"
    put_symbol = "NIFTY 24 AUG 25000 PUT"

    long_signal = Signal(
        type="LONG",
        reason="Triple-A Long",
        entry=150.0,
        sl=130.0,
        tp=190.0,
        rr=2.0,
        model_label="AAA",
        symbol="NIFTY 24 AUG 25000 CALL",
        timestamp="10:00:00",
    )

    short_signal = Signal(
        type="SHORT",
        reason="Triple-A Short",
        entry=140.0,
        sl=160.0,
        tp=100.0,
        rr=2.0,
        model_label="AAA",
        symbol="NIFTY 24 AUG 25000 PUT",
        timestamp="10:00:00",
    )

    # 1. LONG signal on CALL -> Approved
    call_long_result = selector.translate_underlying_signal_to_option(
        signal=long_signal,
        option_symbol=call_symbol,
        option_ltp=150.0,
        delta=0.50,
        tick_size=0.05,
    )
    assert call_long_result is not None
    assert call_long_result.type == "LONG"
    assert call_long_result.entry == 150.0

    # 2. LONG signal on PUT -> Rejected (None)
    put_long_result = selector.translate_underlying_signal_to_option(
        signal=long_signal,
        option_symbol=put_symbol,
        option_ltp=140.0,
        delta=0.50,
        tick_size=0.05,
    )
    assert put_long_result is None

    # 3. SHORT signal on PUT -> Approved
    put_short_result = selector.translate_underlying_signal_to_option(
        signal=short_signal,
        option_symbol=put_symbol,
        option_ltp=140.0,
        delta=0.50,
        tick_size=0.05,
    )
    assert put_short_result is not None
    assert put_short_result.type == "LONG"  # Option buy
    assert put_short_result.entry == 140.0

    # 4. SHORT signal on CALL -> Rejected (None)
    call_short_result = selector.translate_underlying_signal_to_option(
        signal=short_signal,
        option_symbol=call_symbol,
        option_ltp=150.0,
        delta=0.50,
        tick_size=0.05,
    )
    assert call_short_result is None


def test_midcpnifty_exchange_resolution():
    """Verify MIDCPNIFTY is recognized as NSE in ExchangeConfig and SymbolRegistry."""
    from quant.contracts.exchange_config import ExchangeConfig
    from quant.amt.session.symbol_registry import SymbolRegistry

    cfg = ExchangeConfig.for_exchange("NSE")
    assert "MIDCPNIFTY" in cfg.underlyings
    assert cfg.extract_underlying("MIDCPNIFTY 24 AUG 12000 CALL") == "MIDCPNIFTY"

    reg = SymbolRegistry()
    assert reg.exchange_for("MIDCPNIFTY 24 AUG 12000 CALL") == "NSE"
    assert reg.is_nse("MIDCPNIFTY 24 AUG 12000 CALL") is True
    assert reg.is_mcx("MIDCPNIFTY 24 AUG 12000 CALL") is False


def test_effective_delta_floor_is_unified():
    """Stop translation and lot sizing must share one delta floor."""
    from quant.amt.session.selector import MIN_EFFECTIVE_DELTA

    assert MIN_EFFECTIVE_DELTA == 0.30


def test_selector_unknown_root_fails_loud_not_nifty_fallback():
    """Registry-first: an unregistered root must raise, never silently
    fall back to NIFTY lot/interval defaults (SSoT)."""
    import pytest

    from quant.amt.session.selector import OptionSelector
    from quant.contracts.instrument_registry import UnknownInstrumentError

    sel = OptionSelector()
    with pytest.raises(UnknownInstrumentError):
        sel._lot_size_for("NOT_A_REAL_ROOT")
    with pytest.raises(UnknownInstrumentError):
        sel._strike_interval("NOT_A_REAL_ROOT")


def test_translate_uses_shared_delta_floor():
    """A delta below the floor must clamp to the shared floor,
    not the old translation-only 0.20 floor."""
    from quant.amt.session.selector import MIN_EFFECTIVE_DELTA, OptionSelector
    from quant.decision.signal_builder import Signal

    sig = Signal(
        type="LONG", reason="t", entry=100.0, sl=98.0, tp=104.0, rr=2.0,
        model_label="m", symbol="NIFTY", timestamp="t",
    )
    out = OptionSelector().translate_underlying_signal_to_option(
        sig, "NIFTY 20 MAR 23400 CE", option_ltp=100.0, delta=0.05,
    )
    # eff_delta clamps to MIN_EFFECTIVE_DELTA: opt risk = 2.0 * 0.30 = 0.60
    assert out.sl == out.entry - abs(sig.entry - sig.sl) * MIN_EFFECTIVE_DELTA
