"""Tests for OI Wall Detection."""

import pytest
from datetime import datetime

from shared.entities.models import Option, OptionChain, Instrument, Exchange
from backend.app.domain.services.oi_wall_detector import detect_oi_walls, get_key_levels, is_oi_wall_near_price, OIWall


class TestOIWallDetector:
    """Test OI wall detection logic."""

    @pytest.fixture
    def sample_option_chain(self):
        """Create a sample option chain with OI data."""
        underlying = Instrument(symbol="NIFTY", exchange=Exchange.NSE)
        expiry = datetime(2026, 5, 29)
        
        # Create options with varying OI - some forming walls
        calls = {}
        puts = {}
        
        # Wall strikes - need to be > 3x average OI
        # With ~20 strikes at ~150k avg, to get 3x we need > ~450k+
        wall_strike = 24500
        calls[wall_strike] = Option(
            symbol=f"NIFTY {wall_strike} CE",
            security_id="12345",
            strike=wall_strike,
            option_type="CE",
            expiry=expiry,
            ltp=150.0,
            oi=700000,  # 7 lakh OI - well above 3x average
            volume=100000
        )
        puts[wall_strike - 100] = Option(
            symbol=f"NIFTY {wall_strike-100} PE",
            security_id="12346",
            strike=wall_strike - 100,
            option_type="PE",
            expiry=expiry,
            ltp=120.0,
            oi=700000,  # 7 lakh OI - wall
            volume=80000
        )
        puts[wall_strike + 200] = Option(
            symbol=f"NIFTY {wall_strike+200} PE",
            security_id="12347",
            strike=wall_strike + 200,
            option_type="PE",
            expiry=expiry,
            ltp=80.0,
            oi=800000,  # 8 lakh OI - strongest wall
            volume=120000
        )
        
        # Normal OI strikes (100k-200k) - not walls
        for strike in range(wall_strike - 500, wall_strike + 501, 100):
            if strike not in calls:
                calls[strike] = Option(
                    symbol=f"NIFTY {strike} CE",
                    security_id="12348",
                    strike=strike,
                    option_type="CE",
                    expiry=expiry,
                    ltp=50.0,
                    oi=150000,  # Normal OI
                    volume=20000
                )
            if strike not in puts:
                puts[strike] = Option(
                    symbol=f"NIFTY {strike} PE",
                    security_id="12349",
                    strike=strike,
                    option_type="PE",
                    expiry=expiry,
                    ltp=60.0,
                    oi=120000,  # Normal OI
                    volume=15000
                )
        
        return OptionChain(
            underlying=underlying,
            expiry=expiry,
            spot_price=24450.0,
            atm_strike=wall_strike,
            step_size=100.0,
            calls=calls,
            puts=puts
        )

    def test_detect_call_wall(self, sample_option_chain):
        """Call wall detected when CE OI > 3x average."""
        analysis = detect_oi_walls(sample_option_chain)
        
        assert len(analysis.call_walls) >= 1
        assert analysis.max_ce_wall is not None
        assert analysis.max_ce_wall.strike == 24500
        assert analysis.max_ce_wall.option_type == 'CE'
        assert analysis.max_ce_wall.price_level == 'resistance'
        assert analysis.max_ce_wall.oi == 700000

    def test_detect_put_wall(self, sample_option_chain):
        """Put wall detected when PE OI > 3x average."""
        analysis = detect_oi_walls(sample_option_chain)
        
        assert len(analysis.put_walls) >= 1  # At least one strike with high PE OI
        assert analysis.max_pe_wall is not None
        assert analysis.max_pe_wall.option_type == 'PE'
        assert analysis.max_pe_wall.price_level == 'support'

    def test_wall_strength_calculation(self, sample_option_chain):
        """Wall strength is OI / average OI ratio."""
        analysis = detect_oi_walls(sample_option_chain)
        
        if analysis.max_ce_wall:
            assert analysis.max_ce_wall.strength > 3.0  # Above threshold

    def test_average_oi_calculated(self, sample_option_chain):
        """Average OI is calculated correctly."""
        analysis = detect_oi_walls(sample_option_chain)
        
        assert analysis.avg_ce_oi > 0
        assert analysis.avg_pe_oi > 0

    def test_get_key_levels(self, sample_option_chain):
        """Get key support/resistance levels."""
        levels = get_key_levels(sample_option_chain)
        
        # The max CE wall is at 24500, max PE wall is at 24700 (800k OI)
        assert levels['resistance'] == 24500  # Call wall strike
        assert levels['support'] == 24700  # Strongest PE wall (800k > 700k)

    def test_is_oi_wall_near_price(self, sample_option_chain):
        """Check if target strike is near OI wall."""
        # Near the call wall strike
        assert is_oi_wall_near_price(sample_option_chain, 24500, max_distance=50)
        
        # Far from walls
        assert not is_oi_wall_near_price(sample_option_chain, 23000, max_distance=50)

    def test_empty_chain_no_walls(self):
        """Empty option chain returns no walls."""
        chain = OptionChain(
            underlying=Instrument(symbol="NIFTY", exchange=Exchange.NSE),
            expiry=datetime.now(),
            spot_price=24000,
            atm_strike=24000,
            step_size=100,
            calls={},
            puts={}
        )
        
        analysis = detect_oi_walls(chain)
        
        assert len(analysis.call_walls) == 0
        assert len(analysis.put_walls) == 0
        assert analysis.avg_ce_oi == 0
        assert analysis.avg_pe_oi == 0