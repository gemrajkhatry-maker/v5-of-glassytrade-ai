"""Unit tests for OptionSelector and OptionScannerService."""
from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import MagicMock

import pytest

from app.domain.fabio_ai.services.option_selector import (
    OptionSelector,
    OptionSelectorConfig,
    OptionSelection,
)
from app.domain.fabio_ai.services.option_scanner import OptionScannerService, ScanResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_option(ltp=100.0, oi=1_000_000, volume=50_000, bid=None, ask=None,
                 symbol="NIFTY 20 MAR 23400 CALL", strike=23400.0, prev_oi=None,
                 delta=0.50, iv=15.0):
    """Create a mock option object with standard attributes.
    Default bid/ask gives ~0.5% spread (tight, suitable for scalping).
    """
    opt = MagicMock()
    opt.symbol = symbol
    opt.ltp = ltp
    opt.oi = oi
    opt.volume = volume
    opt.bid = bid if bid is not None else ltp - ltp * 0.0025  # 0.25% below
    opt.ask = ask if ask is not None else ltp + ltp * 0.0025  # 0.25% above
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


# ---------------------------------------------------------------------------
# OptionSelector tests
# ---------------------------------------------------------------------------

class TestOptionSelector:

    def setup_method(self):
        self.selector = OptionSelector()

    def test_select_strike_long(self):
        """NIFTY 23450 LONG should return ATM strike (23450) for max gamma."""
        result = self.selector.select_strike("NIFTY", 23450.0, "LONG")
        assert result == 23450

    def test_select_strike_short(self):
        """NIFTY 23450 SHORT should return ATM strike (23450) for max gamma."""
        result = self.selector.select_strike("NIFTY", 23450.0, "SHORT")
        assert result == 23450

    def test_select_strike_banknifty(self):
        """BANKNIFTY 51500 LONG should return ATM (51500) for max gamma."""
        result = self.selector.select_strike("BANKNIFTY", 51500.0, "LONG")
        assert result == 51500

    def test_build_symbol(self):
        """build_symbol should format Dhan-style CE symbol correctly."""
        symbol = self.selector.build_symbol("NIFTY", 23400, "CE", "2026-03-20")
        assert symbol == "NIFTY 20 MAR 23400 CE"

    def test_build_symbol_put(self):
        """build_symbol should format Dhan-style PE symbol for BANKNIFTY."""
        symbol = self.selector.build_symbol("BANKNIFTY", 51500, "PE", "2026-03-27")
        assert symbol == "BANKNIFTY 27 MAR 51500 PE"

    def test_validate_option_pass(self):
        """A well-formed option with good OI and DTE should pass validation."""
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
        """An option with OI=100 should fail the OI check."""
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


# ---------------------------------------------------------------------------
# OptionScannerService tests
# ---------------------------------------------------------------------------

class TestOptionScannerService:

    def _make_scanner(self, broker=None):
        return OptionScannerService(broker or MagicMock())

    def _full_calls(self, atm=23400.0, interval=50):
        """Build calls for ATM ±2 strikes so scanner has candidates."""
        calls = {}
        for i in range(-2, 3):
            s = atm + i * interval
            calls[s] = _make_option(
                ltp=max(10, 120 - abs(i) * 30), oi=600_000 - abs(i) * 100_000,
                volume=10_000, symbol=f"NIFTY 20 MAR {int(s)} CALL",
                strike=s, delta=max(0.2, 0.50 - i * 0.10),
            )
        return calls

    def _full_puts(self, atm=23400.0, interval=50):
        """Build puts for ATM ±2 strikes."""
        puts = {}
        for i in range(-2, 3):
            s = atm + i * interval
            puts[s] = _make_option(
                ltp=max(10, 85 - abs(i) * 20), oi=700_000 - abs(i) * 100_000,
                volume=8_000, symbol=f"NIFTY 20 MAR {int(s)} PUT",
                strike=s, delta=max(0.2, 0.50 + i * 0.10),
            )
        return puts

    def test_scanner_returns_result(self):
        """Mock broker returning a chain with ATM calls should give a ScanResult."""
        calls = self._full_calls()
        chain = _make_chain(atm=23400.0, expiry_iso="2026-03-20", calls=calls)
        broker = MagicMock()
        broker.get_option_chain.return_value = chain

        scanner = self._make_scanner(broker)
        result = scanner.scan(underlying="NIFTY", preferred_option_type="CE")

        assert result is not None
        assert result.underlying == "NIFTY"
        assert result.option_type == "CE"
        assert "NIFTY" in result.symbol
        assert "CALL" in result.symbol

    def test_scanner_returns_put(self):
        """preferred_option_type='PE' should scan puts chain."""
        puts = self._full_puts()
        chain = _make_chain(atm=23400.0, expiry_iso="2026-03-20", puts=puts)
        broker = MagicMock()
        broker.get_option_chain.return_value = chain

        scanner = self._make_scanner(broker)
        result = scanner.scan(underlying="NIFTY", preferred_option_type="PE")

        assert result is not None
        assert result.option_type == "PE"
        assert "PUT" in result.symbol

    def test_scanner_none_on_empty_chain(self):
        """Broker returning None should cause scan() to return None."""
        broker = MagicMock()
        broker.get_option_chain.return_value = None

        scanner = self._make_scanner(broker)
        result = scanner.scan(underlying="NIFTY")

        assert result is None

    def test_scanner_none_on_exception(self):
        """Broker raising an exception should be caught and scan() returns None."""
        broker = MagicMock()
        broker.get_option_chain.side_effect = RuntimeError("Network error")

        scanner = self._make_scanner(broker)
        result = scanner.scan(underlying="NIFTY")

        assert result is None

    def test_scan_best_picks_highest_score(self):
        """scan_best should return the contract with the highest score."""
        # NIFTY: high OI + high volume = higher score
        nifty_calls = {}
        for i in range(-2, 3):
            s = 23400.0 + i * 50
            nifty_calls[s] = _make_option(ltp=100.0, oi=5_000_000, volume=500_000,
                                           strike=s, symbol=f"NIFTY 20 MAR {int(s)} CALL")
        nifty_chain = _make_chain(atm=23400.0, calls=nifty_calls)

        bnf_calls = {}
        for i in range(-2, 3):
            s = 51500.0 + i * 100
            bnf_calls[s] = _make_option(ltp=200.0, oi=1_000_000, volume=10_000,
                                         strike=s, symbol=f"BANKNIFTY 20 MAR {int(s)} CALL")
        bnf_chain = _make_chain(atm=51500.0, calls=bnf_calls)

        broker = MagicMock()

        def get_chain(underlying, exchange, expiry_index=0):
            if underlying == "NIFTY":
                return nifty_chain
            if underlying == "BANKNIFTY":
                return bnf_chain
            return None

        broker.get_option_chain.side_effect = get_chain

        from unittest.mock import patch
        import app.config as app_config
        with patch.object(app_config.settings, "SCANNER_MODE", "nse_options"):
            scanner = self._make_scanner(broker)
            result = scanner.scan_best(underlyings=["NIFTY", "BANKNIFTY"], preferred_option_type="CE")

        assert result is not None
        # NIFTY has higher volume (500K vs 10K) → higher score
        assert result.underlying == "NIFTY"

    def test_scanner_passes_exchange_string(self):
        """Scanner should pass exchange as string to broker.get_option_chain."""
        broker = MagicMock()
        broker.get_option_chain.return_value = None

        scanner = self._make_scanner(broker)
        scanner.scan(underlying="NIFTY", exchange="MCX")

        _, kwargs = broker.get_option_chain.call_args
        assert kwargs["exchange"] == "MCX"
