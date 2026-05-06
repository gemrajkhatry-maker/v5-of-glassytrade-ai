"""Unit tests for backendv2 OptionSelectionEngine."""
from __future__ import annotations

from app.domain.services.option_selection_engine import (
    OptionSelectionEngine,
    Moneyness,
    ContractType,
)


class TestOptionSelectionEngine:
    def _make_options(self, spot=24000, interval=50):
        options = []
        for offset in range(-5, 6):
            strike = spot + offset * interval
            options.append(
                {
                    "strike": strike,
                    "ltp": max(1, 100 - abs(offset) * 20),
                    "oi": 150_000,
                    "volume": 5000,
                    "spread": 2.0,
                    "delta": 0.5,
                    "theta": -5.0,
                    "expiry": "2026-04-03",
                }
            )
        return options

    def test_long_selects_ce(self):
        engine = OptionSelectionEngine()
        result = engine.select(
            direction="LONG",
            setup_type="AAA",
            underlying="NIFTY",
            spot_price=24000,
            strike_interval=50,
            available_options=self._make_options(),
        )
        assert result.allowed
        assert result.contract is not None
        assert result.contract.option_type == ContractType.CE

    def test_short_selects_pe(self):
        engine = OptionSelectionEngine()
        result = engine.select(
            direction="SHORT",
            setup_type="AAA",
            underlying="NIFTY",
            spot_price=24000,
            strike_interval=50,
            available_options=self._make_options(),
        )
        assert result.allowed
        assert result.contract is not None
        assert result.contract.option_type == ContractType.PE

    def test_aaa_selects_atm(self):
        engine = OptionSelectionEngine()
        result = engine.select(
            direction="LONG",
            setup_type="AAA",
            underlying="NIFTY",
            spot_price=24000,
            strike_interval=50,
            available_options=self._make_options(),
        )
        assert result.allowed
        assert result.contract is not None
        assert result.contract.moneyness == Moneyness.ATM

    def test_mr_selects_otm(self):
        engine = OptionSelectionEngine()
        result = engine.select(
            direction="LONG",
            setup_type="MR",
            underlying="NIFTY",
            spot_price=24000,
            strike_interval=50,
            available_options=self._make_options(),
        )
        assert result.allowed
        assert result.contract is not None
        assert result.contract.moneyness == Moneyness.OTM1

    def test_low_oi_rejected(self):
        engine = OptionSelectionEngine(min_oi=15000)
        options = self._make_options()
        for o in options:
            o["oi"] = 100
        result = engine.select(
            direction="LONG",
            setup_type="AAA",
            underlying="NIFTY",
            spot_price=24000,
            strike_interval=50,
            available_options=options,
        )
        assert not result.allowed
        assert result.rejection_rule == "LOW_OI"

    def test_high_spread_rejected(self):
        engine = OptionSelectionEngine(max_spread_pct=0.10)
        options = self._make_options()
        for o in options:
            o["spread"] = 200
        result = engine.select(
            direction="LONG",
            setup_type="AAA",
            underlying="NIFTY",
            spot_price=24000,
            strike_interval=50,
            available_options=options,
        )
        assert not result.allowed
        assert result.rejection_rule == "HIGH_SPREAD"

    def test_theta_kill(self):
        engine = OptionSelectionEngine(theta_edge_threshold=0.01)
        options = self._make_options()
        for o in options:
            o["theta"] = -100
        result = engine.select(
            direction="LONG",
            setup_type="AAA",
            underlying="NIFTY",
            spot_price=24000,
            strike_interval=50,
            available_options=options,
            expected_profit=100,
            expected_hold_minutes=30,
            lots=1,
            lot_size=75,
        )
        assert not result.allowed
        assert result.rejection_rule == "THETA_KILL"

    def test_no_candidates(self):
        engine = OptionSelectionEngine()
        result = engine.select(
            direction="LONG",
            setup_type="AAA",
            underlying="NIFTY",
            spot_price=24000,
            strike_interval=50,
            available_options=[],
        )
        assert not result.allowed
        assert result.rejection_rule == "NO_CANDIDATES"

