"""Tests for OptionSelector — ported from backend/tests/unit/domain/test_option_scanner.py + parity."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from app.domain.fabio_ai.services.option_selector import (
    OptionSelector as LegacyOptionSelector,
    OptionSelectorConfig as LegacyOptionSelectorConfig,
)
from quant.amt.session.selector import (
    OptionSelector,
    OptionSelectorConfig,
    OptionSelection,
)
from tests.quant.parity import assert_parity


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
    legacy = LegacyOptionSelector()
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
        assert_parity(
            legacy.select_strike, new.select_strike, underlying, spot, "LONG"
        )
        assert_parity(
            legacy.select_strike, new.select_strike, underlying, spot, "SHORT"
        )


def test_option_selector_parity_select_strike_with_chain():
    legacy = LegacyOptionSelector()
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
    assert_parity(
        legacy.select_strike, new.select_strike, "NIFTY", 23450.0, "LONG", chain
    )


def test_option_selector_parity_check_theta():
    legacy = LegacyOptionSelector()
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
            assert_parity(
                lambda: legacy.check_theta(opt, hold, target),
                lambda: new.check_theta(opt, hold, target),
            )
