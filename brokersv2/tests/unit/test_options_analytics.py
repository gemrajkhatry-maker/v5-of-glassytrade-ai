"""Tests for Options Analytics - TDD Red-Green-Refactor."""

import pytest
import math
from datetime import datetime, timezone, timedelta
from brokersv2.analytics.options.events import (
    OptionContract,
    OptionType,
    Moneyness,
    StrikeLevel,
    OptionChainEvent,
    GreeksSnapshot,
    OIEvent,
    IVSurfaceEvent,
)
from brokersv2.analytics.options.chain import OptionChainEngine
from brokersv2.analytics.options.greeks import GreeksCalculator
from brokersv2.analytics.options.iv_surface import IVSurfaceEngine
from brokersv2.analytics.options.oi_analytics import OIAnalyzer, OIBuildupDetector


class TestOptionContract:
    """Test option contract data model."""

    def test_call_option_creation(self):
        """Test creating a call option."""
        expiry = datetime(2024, 2, 29, tzinfo=timezone.utc)
        call = OptionContract(
            symbol="NIFTY24FEB22000CE",
            underlying="NIFTY",
            strike=22000.0,
            expiry=expiry,
            option_type=OptionType.CALL,
            ltp=150.0,
        )
        
        assert call.option_type == OptionType.CALL
        assert call.strike == 22000.0
        assert call.ltp == 150.0

    def test_put_option_creation(self):
        """Test creating a put option."""
        expiry = datetime(2024, 2, 29, tzinfo=timezone.utc)
        put = OptionContract(
            symbol="NIFTY24FEB22000PE",
            underlying="NIFTY",
            strike=22000.0,
            expiry=expiry,
            option_type=OptionType.PUT,
            ltp=100.0,
        )
        
        assert put.option_type == OptionType.PUT

    def test_mid_price_calculation(self):
        """Test mid price between bid-ask."""
        option = OptionContract(
            symbol="TEST",
            underlying="NIFTY",
            strike=22000.0,
            expiry=datetime.now(timezone.utc),
            option_type=OptionType.CALL,
            bid=145.0,
            ask=155.0,
        )
        
        assert option.mid_price == 150.0

    def test_spread_calculation(self):
        """Test bid-ask spread."""
        option = OptionContract(
            symbol="TEST",
            underlying="NIFTY",
            strike=22000.0,
            expiry=datetime.now(timezone.utc),
            option_type=OptionType.CALL,
            bid=145.0,
            ask=155.0,
        )
        
        assert option.spread == 10.0

    def test_spread_percentage(self):
        """Test spread as percentage."""
        option = OptionContract(
            symbol="TEST",
            underlying="NIFTY",
            strike=22000.0,
            expiry=datetime.now(timezone.utc),
            option_type=OptionType.CALL,
            bid=95.0,
            ask=105.0,
        )
        
        assert option.spread_percentage == 10.0  # 10/100 * 100


class TestOptionChainEngine:
    """Test option chain normalization and processing."""

    def test_empty_chain(self):
        """Test empty option chain."""
        engine = OptionChainEngine("NIFTY")
        assert engine.underlying == "NIFTY"
        assert engine.strike_count == 0

    def test_add_option_contract(self):
        """Test adding option to chain."""
        engine = OptionChainEngine("NIFTY")
        
        expiry = datetime(2024, 2, 29, tzinfo=timezone.utc)
        call = OptionContract(
            symbol="NIFTY24FEB22000CE",
            underlying="NIFTY",
            strike=22000.0,
            expiry=expiry,
            option_type=OptionType.CALL,
            ltp=150.0,
        )
        
        engine.add_option(call)
        assert engine.strike_count == 1

    def test_build_strike_levels(self):
        """Test building strike levels from contracts."""
        engine = OptionChainEngine("NIFTY")
        
        expiry = datetime(2024, 2, 29, tzinfo=timezone.utc)
        call = OptionContract(
            symbol="NIFTY24FEB22000CE",
            underlying="NIFTY",
            strike=22000.0,
            expiry=expiry,
            option_type=OptionType.CALL,
            ltp=150.0,
            open_interest=5000,
        )
        put = OptionContract(
            symbol="NIFTY24FEB22000PE",
            underlying="NIFTY",
            strike=22000.0,
            expiry=expiry,
            option_type=OptionType.PUT,
            ltp=100.0,
            open_interest=4000,
        )
        
        engine.add_option(call)
        engine.add_option(put)
        engine.build_chain(underlying_price=22050.0)
        
        assert engine.strike_count == 1
        level = engine.get_strike_level(22000.0)
        assert level is not None
        assert level.call_oi == 5000
        assert level.put_oi == 4000

    def test_atm_strike_detection(self):
        """Test ATM strike identification."""
        engine = OptionChainEngine("NIFTY")
        
        strikes = [21800, 21900, 22000, 22100, 22200]
        expiry = datetime(2024, 2, 29, tzinfo=timezone.utc)
        
        for strike in strikes:
            call = OptionContract(
                symbol=f"NIFTY24FEB{strike}CE",
                underlying="NIFTY",
                strike=float(strike),
                expiry=expiry,
                option_type=OptionType.CALL,
            )
            put = OptionContract(
                symbol=f"NIFTY24FEB{strike}PE",
                underlying="NIFTY",
                strike=float(strike),
                expiry=expiry,
                option_type=OptionType.PUT,
            )
            engine.add_option(call)
            engine.add_option(put)
        
        engine.build_chain(underlying_price=22030.0)
        
        assert engine.atm_strike == 22000.0

    def test_strike_sorting(self):
        """Test strikes are sorted ascending."""
        engine = OptionChainEngine("NIFTY")
        
        strikes = [22200, 21800, 22000, 21900]
        expiry = datetime(2024, 2, 29, tzinfo=timezone.utc)
        
        for strike in strikes:
            call = OptionContract(
                symbol=f"NIFTY24FEB{strike}CE",
                underlying="NIFTY",
                strike=float(strike),
                expiry=expiry,
                option_type=OptionType.CALL,
            )
            engine.add_option(call)
        
        engine.build_chain(underlying_price=22000.0)
        
        strike_levels = engine.get_all_strikes()
        assert strike_levels == sorted(strike_levels)

    def test_total_oi_calculation(self):
        """Test total OI across chain."""
        engine = OptionChainEngine("NIFTY")
        
        expiry = datetime(2024, 2, 29, tzinfo=timezone.utc)
        for strike in [22000, 22100]:
            call = OptionContract(
                symbol=f"NIFTY24FEB{strike}CE",
                underlying="NIFTY",
                strike=float(strike),
                expiry=expiry,
                option_type=OptionType.CALL,
                open_interest=1000,
            )
            engine.add_option(call)
        
        engine.build_chain(underlying_price=22050.0)
        
        assert engine.total_call_oi == 2000

    def test_chain_pcr_calculation(self):
        """Test chain-wide put-call ratio."""
        engine = OptionChainEngine("NIFTY")
        
        expiry = datetime(2024, 2, 29, tzinfo=timezone.utc)
        
        # Add call with 1000 OI
        call = OptionContract(
            symbol="NIFTY24FEB22000CE",
            underlying="NIFTY",
            strike=22000.0,
            expiry=expiry,
            option_type=OptionType.CALL,
            open_interest=1000,
        )
        
        # Add put with 1500 OI
        put = OptionContract(
            symbol="NIFTY24FEB22000PE",
            underlying="NIFTY",
            strike=22000.0,
            expiry=expiry,
            option_type=OptionType.PUT,
            open_interest=1500,
        )
        
        engine.add_option(call)
        engine.add_option(put)
        engine.build_chain(underlying_price=22050.0)
        
        assert engine.chain_pcr == 1.5

    def test_expiry_dates(self):
        """Test getting available expiry dates."""
        engine = OptionChainEngine("NIFTY")
        
        expiry1 = datetime(2024, 2, 29, tzinfo=timezone.utc)
        expiry2 = datetime(2024, 3, 28, tzinfo=timezone.utc)
        
        call1 = OptionContract(
            symbol="NIFTY24FEB22000CE",
            underlying="NIFTY",
            strike=22000.0,
            expiry=expiry1,
            option_type=OptionType.CALL,
        )
        call2 = OptionContract(
            symbol="NIFTY24MAR22000CE",
            underlying="NIFTY",
            strike=22000.0,
            expiry=expiry2,
            option_type=OptionType.CALL,
        )
        
        engine.add_option(call1)
        engine.add_option(call2)
        
        expiries = engine.get_expiry_dates()
        assert len(expiries) == 2
        assert expiry1 in expiries
        assert expiry2 in expiries

    def test_filter_by_expiry(self):
        """Test filtering chain by expiry date."""
        engine = OptionChainEngine("NIFTY")
        
        expiry1 = datetime(2024, 2, 29, tzinfo=timezone.utc)
        expiry2 = datetime(2024, 3, 28, tzinfo=timezone.utc)
        
        for strike in [22000, 22100]:
            for expiry in [expiry1, expiry2]:
                call = OptionContract(
                    symbol=f"NIFTY{strike}CE",
                    underlying="NIFTY",
                    strike=float(strike),
                    expiry=expiry,
                    option_type=OptionType.CALL,
                )
                engine.add_option(call)
        
        filtered = engine.filter_by_expiry(expiry1)
        assert filtered.strike_count == 2


class TestGreeksCalculator:
    """Test options Greeks calculations."""

    def test_delta_call_option(self):
        """Test delta calculation for call option."""
        calc = GreeksCalculator()
        
        delta = calc.delta(
            underlying_price=22000.0,
            strike=22000.0,
            time_to_expiry=30.0,
            volatility=0.15,
            risk_free_rate=0.05,
            option_type=OptionType.CALL,
        )
        
        # ATM call should have delta ~0.5
        assert 0.45 < delta < 0.55

    def test_delta_put_option(self):
        """Test delta calculation for put option."""
        calc = GreeksCalculator()
        
        delta = calc.delta(
            underlying_price=22000.0,
            strike=22000.0,
            time_to_expiry=30.0,
            volatility=0.15,
            risk_free_rate=0.05,
            option_type=OptionType.PUT,
        )
        
        # ATM put should have delta ~-0.5
        assert -0.55 < delta < -0.45

    def test_gamma_atm(self):
        """Test gamma is highest for ATM options."""
        calc = GreeksCalculator()
        
        gamma_atm = calc.gamma(
            underlying_price=22000.0,
            strike=22000.0,
            time_to_expiry=30.0,
            volatility=0.15,
            risk_free_rate=0.05,
        )
        
        gamma_otm = calc.gamma(
            underlying_price=22000.0,
            strike=23000.0,  # Far OTM
            time_to_expiry=30.0,
            volatility=0.15,
            risk_free_rate=0.05,
        )
        
        assert gamma_atm > gamma_otm

    def test_theta_decay(self):
        """Test theta is negative (time decay)."""
        calc = GreeksCalculator()
        
        theta = calc.theta(
            underlying_price=22000.0,
            strike=22000.0,
            time_to_expiry=30.0,
            volatility=0.15,
            risk_free_rate=0.05,
            option_type=OptionType.CALL,
        )
        
        assert theta < 0  # Time decay is negative

    def test_vega_positive(self):
        """Test vega is positive."""
        calc = GreeksCalculator()
        
        vega = calc.vega(
            underlying_price=22000.0,
            strike=22000.0,
            time_to_expiry=30.0,
            volatility=0.15,
            risk_free_rate=0.05,
        )
        
        assert vega > 0

    def test_all_greeks_snapshot(self):
        """Test getting all Greeks in one snapshot."""
        calc = GreeksCalculator()
        
        snapshot = calc.calculate_all_greeks(
            symbol="NIFTY24FEB22000CE",
            underlying_price=22000.0,
            strike=22000.0,
            time_to_expiry=30.0,
            volatility=0.15,
            risk_free_rate=0.05,
            option_type=OptionType.CALL,
        )
        
        assert snapshot is not None
        assert isinstance(snapshot, GreeksSnapshot)
        assert -0.55 < snapshot.delta < 0.55
        assert snapshot.gamma > 0
        assert snapshot.theta < 0
        assert snapshot.vega > 0


class TestIVSurfaceEngine:
    """Test implied volatility surface construction."""

    def test_add_iv_point(self):
        """Test adding IV data point."""
        engine = IVSurfaceEngine("NIFTY")
        
        engine.add_iv_point(
            strike=22000.0,
            expiry=datetime(2024, 2, 29, tzinfo=timezone.utc),
            implied_vol=0.15,
            underlying_price=22050.0,
        )
        
        assert engine.data_point_count == 1

    def test_iv_skew(self):
        """Test IV skew calculation."""
        engine = IVSurfaceEngine("NIFTY")
        
        # OTM puts have higher IV (skew)
        engine.add_iv_point(
            strike=21000.0,  # OTM put
            expiry=datetime(2024, 2, 29, tzinfo=timezone.utc),
            implied_vol=0.20,
            underlying_price=22000.0,
        )
        engine.add_iv_point(
            strike=22000.0,  # ATM
            expiry=datetime(2024, 2, 29, tzinfo=timezone.utc),
            implied_vol=0.15,
            underlying_price=22000.0,
        )
        engine.add_iv_point(
            strike=23000.0,  # OTM call
            expiry=datetime(2024, 2, 29, tzinfo=timezone.utc),
            implied_vol=0.13,
            underlying_price=22000.0,
        )
        
        skew = engine.calculate_skew(
            expiry=datetime(2024, 2, 29, tzinfo=timezone.utc),
            underlying_price=22000.0,
        )
        
        # Negative skew (puts have higher IV)
        assert skew < 0

    def test_term_structure(self):
        """Test IV term structure."""
        engine = IVSurfaceEngine("NIFTY")
        
        engine.add_iv_point(
            strike=22000.0,
            expiry=datetime(2024, 2, 29, tzinfo=timezone.utc),
            implied_vol=0.12,
            underlying_price=22000.0,
        )
        engine.add_iv_point(
            strike=22000.0,
            expiry=datetime(2024, 3, 29, tzinfo=timezone.utc),
            implied_vol=0.15,
            underlying_price=22000.0,
        )
        
        term = engine.get_term_structure(
            strike=22000.0,
            underlying_price=22000.0,
        )
        
        assert len(term) == 2

    def test_atm_iv_interpolation(self):
        """Test getting ATM IV."""
        engine = IVSurfaceEngine("NIFTY")
        
        engine.add_iv_point(
            strike=22000.0,
            expiry=datetime(2024, 2, 29, tzinfo=timezone.utc),
            implied_vol=0.15,
            underlying_price=22000.0,
        )
        
        atm_iv = engine.get_atm_iv(
            underlying_price=22000.0,
            expiry=datetime(2024, 2, 29, tzinfo=timezone.utc),
        )
        
        assert atm_iv == 0.15


class TestOIAnalytics:
    """Test open interest analytics."""

    def test_pcr_calculation(self):
        """Test put-call ratio calculation."""
        analyzer = OIAnalyzer("NIFTY")
        
        analyzer.update_oi(
            strike=22000.0,
            option_type=OptionType.CALL,
            open_interest=5000,
        )
        analyzer.update_oi(
            strike=22000.0,
            option_type=OptionType.PUT,
            open_interest=7500,
        )
        
        pcr = analyzer.get_pcr(22000.0)
        assert pcr == 1.5

    def test_max_poi_strike(self):
        """Test finding max pain/open interest strike."""
        analyzer = OIAnalyzer("NIFTY")
        
        analyzer.update_oi(22000.0, OptionType.CALL, 10000)
        analyzer.update_oi(22100.0, OptionType.CALL, 5000)
        analyzer.update_oi(21900.0, OptionType.PUT, 8000)
        
        max_call_strike = analyzer.get_max_oi_strike(OptionType.CALL)
        assert max_call_strike == 22000.0

    def test_oi_change_detection(self):
        """Test detecting OI changes."""
        analyzer = OIAnalyzer("NIFTY")
        
        # Initial OI
        analyzer.update_oi(22000.0, OptionType.CALL, 5000)
        
        # Update with new OI
        analyzer.update_oi(22000.0, OptionType.CALL, 6000)
        
        change = analyzer.get_oi_change(22000.0, OptionType.CALL)
        assert change == 1000

    def test_oi_buildup_detection(self):
        """Test OI buildup detection."""
        detector = OIBuildupDetector(threshold=2000)
        
        detector.track_oi_change(
            strike=22000.0,
            option_type=OptionType.CALL,
            oi_change=3000,
            price_change=1.5,
        )
        
        buildup = detector.get_buildups()
        assert len(buildup) == 1
        assert buildup[0].strike == 22000.0

    def test_long_buildup(self):
        """Test long buildup (OI up, price up)."""
        detector = OIBuildupDetector(threshold=2000)
        
        detector.track_oi_change(
            strike=22000.0,
            option_type=OptionType.CALL,
            oi_change=3000,
            price_change=2.0,  # Price up
        )
        
        long_buildups = detector.get_long_buildups()
        assert len(long_buildups) == 1

    def test_short_buildup(self):
        """Test short buildup (OI up, price down)."""
        detector = OIBuildupDetector(threshold=2000)
        
        detector.track_oi_change(
            strike=22000.0,
            option_type=OptionType.CALL,
            oi_change=3000,
            price_change=-2.0,  # Price down
        )
        
        short_buildups = detector.get_short_buildups()
        assert len(short_buildups) == 1

    def test_unwinding_detection(self):
        """Test OI unwinding detection."""
        detector = OIBuildupDetector(threshold=2000)
        
        detector.track_oi_change(
            strike=22000.0,
            option_type=OptionType.CALL,
            oi_change=-3000,  # OI decreasing
            price_change=1.0,
        )
        
        unwindings = detector.get_unwindings()
        assert len(unwindings) == 1
