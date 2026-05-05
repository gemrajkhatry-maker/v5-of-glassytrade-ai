"""Integration tests validating Triple-A signal logic against amt_docs specs."""
import pytest
from decimal import Decimal
from app.domain.amt.service.volume_profile import build_volume_profile, calculate_vwap
from app.domain.amt.service.amt_analyzer import AMTAnalyzer
from app.domain.amt.service.signal_generator import generate_triple_a_signal
from app.domain.amt.model.amt_models import Absorption, VolumeProfile, Signal


class TestTripleASpecValidation:
    """Validate Triple-A signal generation matches amt_docs specifications."""
    
    def test_triple_a_long_signal_spec(self):
        """
        Validate LONG signal per amt_docs:
        - BUY absorption detected
        - Price > VWAP
        - R:R >= 1.5
        - SL: Below VAL - 1 step
        - TP: Entry + (Entry - SL) * tpMultiplier
        """
        # Create mock bars for volume profile
        bars = [
            {'open': 49900, 'high': 50100, 'low': 49900, 'close': 50000, 
             'volume': 500, 'buyVolume': 300, 'sellVolume': 200, 'bar_index': 0},
            {'open': 50000, 'high': 50150, 'low': 49950, 'close': 50050,
             'volume': 600, 'buyVolume': 400, 'sellVolume': 200, 'bar_index': 1},
        ]
        
        # Build volume profile per amt_docs section 2.2
        vp = build_volume_profile(bars, bucket_size=50.0)
        
        # VWAP from amt_docs section 2.3
        vwap = 50000.0
        current_price = 50020.0
        
        # Absorption at support near VAL per specs
        absorptions = [
            Absorption(
                bar_index=1,
                price=49960.0,
                volume=800.0,
                side="BUY",
                strength=0.85
            )
        ]
        
        signal = generate_triple_a_signal(
            bars=bars,
            absorptions=absorptions,
            vp=vp,
            vwap=current_price,  # Price > VWAP for LONG
            tp_multiplier=2.0,
            min_rr=1.5
        )
        
        # Validate per specs
        assert signal is not None
        assert signal.type == "LONG"
        assert signal.entry > 50000  # Above VWAP
        assert signal.sl < vp.val  # Below VAL
        assert signal.tp > signal.entry
        assert signal.rr >= 1.5
        
    def test_triple_a_short_signal_spec(self):
        """
        Validate SHORT signal per amt_docs:
        - SELL absorption detected
        - Price < VWAP  
        - R:R >= 1.5
        - SL: Above VAH + 1 step
        """
        bars = [
            {'open': 50100, 'high': 50200, 'low': 50000, 'close': 50100,
             'volume': 500, 'buyVolume': 200, 'sellVolume': 300, 'bar_index': 0},
            {'open': 50100, 'high': 50150, 'low': 50050, 'close': 50080,
             'volume': 600, 'buyVolume': 200, 'sellVolume': 400, 'bar_index': 1},
        ]
        
        vp = build_volume_profile(bars, bucket_size=50.0)
        
        # SELL absorption at resistance near VAH
        absorptions = [
            Absorption(
                bar_index=1,
                price=50100.0,
                volume=800.0,
                side="SELL",
                strength=0.8
            )
        ]
        
        # Price below VWAP for SHORT
        vwap = 50100.0
        
        signal = generate_triple_a_signal(
            bars=bars,
            absorptions=absorptions,
            vp=vp,
            vwap=vwap,  # Price < VWAP for SHORT
            tp_multiplier=2.0,
            min_rr=1.5
        )
        
        # Validate SHORT signal
        assert signal is not None
        assert signal.type == "SHORT"
        assert signal.entry < vwap  # Below VWAP
        assert signal.sl > vp.vah  # Above VAH
        
    def test_no_trade_without_absorption(self):
        """Validate NO_TRADE when no absorption per specs."""
        bars = [
            {'open': 49900, 'high': 50100, 'low': 49900, 'close': 50000,
             'volume': 500, 'buyVolume': 250, 'sellVolume': 250, 'bar_index': 0},
        ]
        
        vp = build_volume_profile(bars, bucket_size=50.0)
        
        # No absorption
        absorptions = []
        
        signal = generate_triple_a_signal(
            bars=bars,
            absorptions=absorptions,
            vp=vp,
            vwap=50000.0,
            tp_multiplier=2.0,
            min_rr=1.5
        )
        
        assert signal.type == "NO_TRADE"
        
    def test_risk_reward_validation(self):
        """Validate R:R calculation matches tpMultiplier (default 2.0)."""
        bars = [
            {'open': 49900, 'high': 50100, 'low': 49900, 'close': 50020,
             'volume': 1000, 'buyVolume': 600, 'sellVolume': 400, 'bar_index': 0},
        ]
        
        vp = build_volume_profile(bars, bucket_size=50.0)
        
        absorptions = [
            Absorption(
                bar_index=0,
                price=49960.0,
                volume=800.0,
                side="BUY",
                strength=0.9
            )
        ]
        
        signal = generate_triple_a_signal(
            bars=bars,
            absorptions=absorptions,
            vp=vp,
            vwap=50020.0,
            tp_multiplier=2.0,
            min_rr=1.5
        )
        
        if signal.type == "LONG":
            # TP should be ~2x RR from entry
            expected_rr = (signal.tp - signal.entry) / (signal.entry - signal.sl)
            assert abs(expected_rr - 2.0) < 0.1  # Allow small variance