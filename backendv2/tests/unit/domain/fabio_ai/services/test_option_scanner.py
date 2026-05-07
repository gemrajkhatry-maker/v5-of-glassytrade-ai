"""Tests for OptionScannerService and ContractSwitchGuard."""
from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.domain.fabio_ai.services.option_scanner import (
    ContractSwitchDecision,
    ContractSwitchGuard,
    OptionScannerService,
    ScanResult,
)


class _FakeOption:
    """Minimal option dataclass for testing."""
    def __init__(self, symbol: str, ltp: float, oi: int, volume: int, bid: float, ask: float, delta: float = 0.50, iv: float = 0.0):
        self.symbol = symbol
        self.ltp = ltp
        self.oi = oi
        self.volume = volume
        self.bid = bid
        self.ask = ask
        self.delta = delta
        self.iv = iv


class _FakeChain:
    """Minimal option chain for testing."""
    def __init__(self, atm_strike: float, calls: dict, puts: dict, expiry=None):
        self.atm_strike = atm_strike
        self.calls = calls
        self.puts = puts
        self.expiry = expiry or date.today().replace(day=date.today().day + 1)


def _make_option(symbol: str, ltp: float = 100, oi: int = 1000, volume: int = 500,
                 bid: float = 99, ask: float = 101, delta: float = 0.50, iv: float = 0.0) -> _FakeOption:
    return _FakeOption(symbol=symbol, ltp=ltp, oi=oi, volume=volume, bid=bid, ask=ask, delta=delta, iv=iv)


def _make_chain(atm: float, strike_interval: int = 50, oi: int = 60000, volume: int = 500) -> _FakeChain:
    calls = {}
    puts = {}
    for i in range(-2, 3):
        s = atm + i * strike_interval
        opt = _make_option(f"OPT_{int(s)}", oi=oi, volume=volume)
        calls[s] = opt
        puts[s] = opt
    # Use a datetime object so .date() works
    from datetime import datetime, timedelta
    future_dt = datetime.now() + timedelta(days=7)
    return _FakeChain(atm_strike=atm, calls=calls, puts=puts, expiry=future_dt)


class TestOptionScanner:
    """Test OptionScannerService."""

    def _make_scanner(self, chain: _FakeChain) -> OptionScannerService:
        broker = MagicMock()
        broker.get_option_chain.return_value = chain
        return OptionScannerService(broker, default_underlyings=["NIFTY"])

    def test_scan_top_n_returns_top_ranked_contracts(self):
        """scan_top_n() returns top ranked contracts."""
        chain = _make_chain(atm=22000, strike_interval=50, oi=60000, volume=500)
        scanner = self._make_scanner(chain)

        results = scanner.scan_top_n(n=3, underlyings=["NIFTY"], expiry_index=0, strikes_around_atm=2)

        assert isinstance(results, list)
        assert len(results) >= 1
        # Results should be ScanResult instances
        assert all(isinstance(r, ScanResult) for r in results)
        # Scores should be non-negative
        assert all(r.score >= 0 for r in results)

    def test_score_contract_atm_distance_penalty(self):
        """_score_contract() penalises far-from-ATM strikes."""
        atm = 22000
        interval = 50
        _, near_dist, _ = OptionScannerService._score_contract(
            strike=22000, atm=atm, interval=interval, oi=60000, vol=500,
            opt=_make_option("X"), ltp=100, bid=99, ask=101, underlying_upper="NIFTY",
        )
        _, far_dist, _ = OptionScannerService._score_contract(
            strike=22500, atm=atm, interval=interval, oi=60000, vol=500,
            opt=_make_option("X"), ltp=100, bid=99, ask=101, underlying_upper="NIFTY",
        )
        assert near_dist < far_dist

    def test_score_contract_zero_volume_returns_zero(self):
        """_score_contract() returns 0 when volume is zero."""
        score, _, _ = OptionScannerService._score_contract(
            strike=22000, atm=22000, interval=50, oi=60000, vol=0,
            opt=_make_option("X"), ltp=100, bid=99, ask=101, underlying_upper="NIFTY",
        )
        assert score == 0

    def test_score_contract_oi_bonus(self):
        """_score_contract() awards bonus for high open interest."""
        high_oi_score, _, _ = OptionScannerService._score_contract(
            strike=22000, atm=22000, interval=50, oi=100000, vol=500,
            opt=_make_option("X"), ltp=100, bid=99, ask=101, underlying_upper="NIFTY",
        )
        low_oi_score, _, _ = OptionScannerService._score_contract(
            strike=22000, atm=22000, interval=50, oi=1000, vol=500,
            opt=_make_option("X"), ltp=100, bid=99, ask=101, underlying_upper="NIFTY",
        )
        assert high_oi_score > low_oi_score

    def test_detect_momentum_bullish(self):
        """_detect_momentum() returns BULLISH when CE volume dominates."""
        ce_opts = {s: _make_option("CE", volume=600) for s in range(21900, 22100, 50)}
        pe_opts = {s: _make_option("PE", volume=100) for s in range(21900, 22100, 50)}
        chain = _FakeChain(atm_strike=22000, calls=ce_opts, puts=pe_opts)

        bias, bias_val, reason = OptionScannerService._detect_momentum(chain, atm=22000, interval=50)

        assert bias == "BULLISH"
        assert bias_val == 3
        assert "CE volume" in reason

    def test_detect_momentum_bearish(self):
        """_detect_momentum() returns BEARISH when PE volume dominates."""
        ce_opts = {s: _make_option("CE", volume=100) for s in range(21900, 22100, 50)}
        pe_opts = {s: _make_option("PE", volume=600) for s in range(21900, 22100, 50)}
        chain = _FakeChain(atm_strike=22000, calls=ce_opts, puts=pe_opts)

        bias, bias_val, reason = OptionScannerService._detect_momentum(chain, atm=22000, interval=50)

        assert bias == "BEARISH"
        assert bias_val == 3
        assert "PE volume" in reason

    def test_detect_momentum_neutral(self):
        """_detect_momentum() returns NEUTRAL when volumes are balanced."""
        ce_opts = {s: _make_option("CE", volume=200) for s in range(21900, 22100, 50)}
        pe_opts = {s: _make_option("PE", volume=200) for s in range(21900, 22100, 50)}
        chain = _FakeChain(atm_strike=22000, calls=ce_opts, puts=pe_opts)

        bias, bias_val, reason = OptionScannerService._detect_momentum(chain, atm=22000, interval=50)

        assert bias == "NEUTRAL"
        assert bias_val == 0
        assert "Balanced" in reason


class TestContractSwitchGuard:
    """Test ContractSwitchGuard."""

    def test_prevents_switch_during_open_trade(self):
        """evaluate_switch() prevents switching when open trade exists."""
        guard = ContractSwitchGuard()
        guard._current_contract = "NIFTY_CE_22000"
        guard._current_score = 50.0
        guard.set_open_trade(True)

        decision = guard.evaluate_switch("NIFTY_CE_22100", 80.0, current_time=1000.0)

        assert decision.accepted is False
        assert decision.has_open_trade is True
        assert decision.reason == "open_trade_blocks_switch"

    def test_allows_switch_when_no_open_trade(self):
        """should_switch() allows switching when no trades are open."""
        guard = ContractSwitchGuard()
        guard._current_contract = "NIFTY_CE_22000"
        guard._current_score = 50.0
        guard._last_score_time = 0.0
        guard.set_open_trade(False)

        result = guard.should_switch("NIFTY_CE_22100", 80.0, current_time=1000.0)

        assert result is True
        assert guard.current_contract == "NIFTY_CE_22100"

    def test_initial_contract_accepted(self):
        """First contract selection is always accepted."""
        guard = ContractSwitchGuard()
        decision = guard.evaluate_switch("NIFTY_CE_22000", 50.0, current_time=0.0)

        assert decision.accepted is True
        assert decision.reason == "initial_contract"

    def test_same_contract_rejected(self):
        """Switching to the same contract is rejected."""
        guard = ContractSwitchGuard()
        guard._current_contract = "NIFTY_CE_22000"
        guard._current_score = 50.0
        guard._last_score_time = 0.0

        decision = guard.evaluate_switch("NIFTY_CE_22000", 55.0, current_time=1000.0)

        assert decision.accepted is False
        assert decision.reason == "same_contract"

    def test_cooldown_prevents_rapid_switch(self):
        """Cooldown window prevents rapid switching."""
        guard = ContractSwitchGuard()
        guard._current_contract = "NIFTY_CE_22000"
        guard._current_score = 50.0
        guard._last_score_time = 900.0  # recent

        decision = guard.evaluate_switch("NIFTY_CE_22100", 80.0, current_time=950.0)

        assert decision.accepted is False
        assert decision.reason == "cooldown_active"
        assert decision.cooldown_remaining > 0

    def test_large_score_delta_allows_switch(self):
        """Score delta > 15 allows switch after cooldown."""
        guard = ContractSwitchGuard()
        guard._current_contract = "NIFTY_CE_22000"
        guard._current_score = 50.0
        guard._last_score_time = 0.0  # old enough

        decision = guard.evaluate_switch("NIFTY_CE_22100", 80.0, current_time=1000.0)

        assert decision.accepted is True
        assert decision.reason == "score_delta_exceeded"
        assert decision.score_delta == 30.0

    def test_snapshot_returns_state(self):
        """snapshot() returns current state as dict."""
        guard = ContractSwitchGuard()
        guard._current_contract = "NIFTY_CE_22000"
        guard._current_score = 50.0
        guard._last_score_time = 100.0
        guard.set_open_trade(False)

        snap = guard.snapshot()

        assert snap["current_contract"] == "NIFTY_CE_22000"
        assert snap["current_score"] == 50.0
        assert snap["last_score_time"] == 100.0
        assert snap["has_open_trade"] is False
