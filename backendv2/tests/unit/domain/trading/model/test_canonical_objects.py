"""Tests for canonical value objects."""
from __future__ import annotations

import pytest

from app.domain.trading.model.canonical_objects import (
    TradingSignal,
    SignalDirection,
    ConfidenceLevel,
    VWAPBias,
    SetupType,
    VWAPProfile,
    VWAPBand,
)


class TestTradingSignal:
    """Contract tests for TradingSignal."""

    def test_defaults(self):
        signal = TradingSignal(symbol="NIFTY")
        assert signal.symbol == "NIFTY"
        assert signal.direction == SignalDirection.NEUTRAL
        assert signal.confidence == ConfidenceLevel.LOW
        assert signal.grade == 0

    def test_immutability(self):
        signal = TradingSignal(symbol="NIFTY", direction=SignalDirection.LONG)
        with pytest.raises(Exception):
            signal.direction = SignalDirection.SHORT  # type: ignore

    def test_is_valid_requires_direction(self):
        signal = TradingSignal(
            symbol="NIFTY", direction=SignalDirection.LONG, grade=7,
            risk_reward_ratio=2.0, entry_price=100.0,
        )
        assert signal.is_valid() is True

    def test_is_valid_rejects_neutral(self):
        signal = TradingSignal(symbol="NIFTY", direction=SignalDirection.NEUTRAL, grade=7)
        assert signal.is_valid() is False

    def test_is_valid_requires_min_grade(self):
        signal = TradingSignal(
            symbol="NIFTY", direction=SignalDirection.LONG, grade=3,
            risk_reward_ratio=2.0, entry_price=100.0,
        )
        assert signal.is_valid() is False

    def test_is_valid_requires_rr(self):
        signal = TradingSignal(
            symbol="NIFTY", direction=SignalDirection.LONG, grade=7,
            risk_reward_ratio=1.0, entry_price=100.0,
        )
        assert signal.is_valid() is False

    def test_is_valid_requires_entry_price(self):
        signal = TradingSignal(
            symbol="NIFTY", direction=SignalDirection.LONG, grade=7,
            risk_reward_ratio=2.0, entry_price=0.0,
        )
        assert signal.is_valid() is False

    def test_from_amt_result_long(self):
        amt = {
            "direction": "LONG", "confidence": "HIGH", "grade": 8,
            "aggression_score": 3.5, "session_phase": "MORNING",
            "vwap_bias": "ABOVE", "entry_price": 150.0,
            "stop_loss": 145.0, "take_profit": 160.0,
            "setup_type": "AAA", "absorption_strength": 0.85,
            "footprint_alignment": "ALIGNED", "risk_reward_ratio": 2.0,
        }
        signal = TradingSignal.from_amt_result("NIFTY", amt)
        assert signal.symbol == "NIFTY"
        assert signal.direction == SignalDirection.LONG
        assert signal.confidence == ConfidenceLevel.HIGH
        assert signal.grade == 8
        assert signal.entry_price == 150.0
        assert signal.stop_loss == 145.0
        assert signal.take_profit == 160.0

    def test_from_amt_result_short(self):
        amt = {
            "direction": "SHORT", "confidence": "MEDIUM", "grade": 6,
            "aggression_score": 2.0, "entry_price": 200.0,
            "stop_loss": 205.0, "take_profit": 190.0,
            "risk_reward_ratio": 2.0, "setup_type": "VA_FADE",
        }
        signal = TradingSignal.from_amt_result("BANKNIFTY", amt)
        assert signal.symbol == "BANKNIFTY"
        assert signal.direction == SignalDirection.SHORT
        assert signal.setup_type == SetupType.VA_FADE

    def test_from_amt_result_defaults(self):
        signal = TradingSignal.from_amt_result("SYM", {})
        assert signal.direction == SignalDirection.NEUTRAL
        assert signal.grade == 0

    def test_can_serialize(self):
        signal = TradingSignal(
            symbol="NIFTY", direction=SignalDirection.LONG,
            entry_price=100.0, stop_loss=99.0, take_profit=102.0,
        )
        d = signal.to_dict()
        assert d["symbol"] == "NIFTY"
        assert d["direction"] == "LONG"
        assert d["entry"] == 100.0

    def test_complete_signal_carries_all_fields(self):
        signal = TradingSignal(
            symbol="NIFTY", direction=SignalDirection.LONG,
            confidence=ConfidenceLevel.HIGH, grade=9, aggression_score=4.2,
            session_phase="MORNING", vwap_bias=VWAPBias.ABOVE,
            entry_price=100.0, stop_loss=97.0, take_profit=106.0,
            setup_type=SetupType.AAA, absorption_strength=0.9,
            footprint_alignment="BULLISH_ALIGNED", risk_reward_ratio=3.0,
        )
        assert signal.symbol == "NIFTY"
        assert signal.is_valid()
        assert signal.aggression_score == 4.2
        assert signal.vwap_bias == VWAPBias.ABOVE
        assert signal.footprint_alignment == "BULLISH_ALIGNED"


class TestVWAPProfile:
    """Contract tests for VWAPProfile."""

    def test_basic_bands(self):
        profile = VWAPProfile(
            price=100.0,
            bands=(VWAPBand(sigma=1, upper=102.0, lower=98.0),
                   VWAPBand(sigma=2, upper=104.0, lower=96.0)),
            bias=VWAPBias.AT,
        )
        assert profile.price == 100.0
        assert len(profile.bands) == 2

    def test_band_lookup(self):
        profile = VWAPProfile(
            price=100.0,
            bands=(VWAPBand(sigma=1, upper=102.0, lower=98.0),
                   VWAPBand(sigma=2, upper=104.0, lower=96.0)),
            bias=VWAPBias.AT,
        )
        b1 = profile.band(1)
        assert b1 is not None
        assert b1.upper == 102.0
        assert b1.lower == 98.0
        assert profile.band(3) is None

    def test_is_price_above(self):
        profile = VWAPProfile(
            price=103.0,
            bands=(VWAPBand(sigma=1, upper=102.0, lower=98.0),),
            bias=VWAPBias.ABOVE,
        )
        assert profile.is_price_above(1) is True

    def test_is_price_below(self):
        profile = VWAPProfile(
            price=97.0,
            bands=(VWAPBand(sigma=1, upper=102.0, lower=98.0),),
            bias=VWAPBias.BELOW,
        )
        assert profile.is_price_below(1) is True

    def test_distance_from_band_above(self):
        profile = VWAPProfile(
            price=105.0,
            bands=(VWAPBand(sigma=2, upper=104.0, lower=96.0),),
            bias=VWAPBias.ABOVE,
        )
        assert profile.distance_from_band(2) == 1.0

    def test_distance_from_band_below(self):
        profile = VWAPProfile(
            price=95.0,
            bands=(VWAPBand(sigma=2, upper=104.0, lower=96.0),),
            bias=VWAPBias.BELOW,
        )
        assert profile.distance_from_band(2) == 1.0

    def test_distance_zero_when_inside(self):
        profile = VWAPProfile(
            price=100.0,
            bands=(VWAPBand(sigma=1, upper=102.0, lower=98.0),),
            bias=VWAPBias.AT,
        )
        assert profile.distance_from_band(1) == 0.0

    def test_immutability(self):
        profile = VWAPProfile(
            price=100.0,
            bands=(VWAPBand(sigma=1, upper=102.0, lower=98.0),),
            bias=VWAPBias.AT,
        )
        with pytest.raises(Exception):
            profile.price = 105.0  # type: ignore