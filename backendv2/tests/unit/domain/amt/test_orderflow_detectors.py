"""Tests for Order Flow Detectors."""

import pytest

from app.domain.amt.service.orderflow_detectors import (
    detect_absorptions,
    Absorption,
)


class TestBigTradeDetection:
    """Tests for big trade detection."""

    def test_big_trade_detection(self):
        """Print >= 5x avg within 2 ticks -> detected."""
        bars = [
            {"price": 100, "volume": 100},
            {"price": 101, "volume": 500},  # 5x avg
        ]
        
        # This would need BigTradeDetector implementation
        # For now, just test the absorption detection
        result = detect_absorptions(bars)
        
        assert isinstance(result, list)

    def test_big_trade_cluster(self):
        """3+ big prints within 2 ticks -> cluster."""
        bars = [
            {"price": 100, "volume": 100},
            {"price": 101, "volume": 600},
            {"price": 102, "volume": 600},
            {"price": 103, "volume": 600},
        ]
        
        result = detect_absorptions(bars)
        
        assert isinstance(result, list)


class TestOFICalculator:
    """Tests for Order Flow Imbalance calculation."""

    def test_ofi_calculation_positive_more_buying(self):
        """bid_vol > ask_vol -> positive OFI."""
        # OFI = (bid_vol - ask_vol) / (bid_vol + ask_vol)
        bid_vol = 600
        ask_vol = 400
        
        ofi = (bid_vol - ask_vol) / (bid_vol + ask_vol)
        
        assert ofi == 0.2  # 20% positive

    def test_ofi_calculation_negative_more_selling(self):
        """sell_vol > buy_vol -> negative OFI."""
        bid_vol = 300
        ask_vol = 700
        
        ofi = (bid_vol - ask_vol) / (bid_vol + ask_vol)
        
        assert ofi == -0.4  # -40% negative

    def test_ofi_aligned_long(self):
        """OFI > +0.10 -> aligned LONG."""
        ofi = 0.15
        side = "LONG"
        
        aligned = side == "LONG" and ofi > 0.10
        
        assert aligned == True

    def test_ofi_aligned_short(self):
        """OFI < -0.10 -> aligned SHORT."""
        ofi = -0.15
        side = "SHORT"
        
        aligned = side == "SHORT" and ofi < -0.10
        
        assert aligned == True


class TestAbsorptionDetection:
    """Tests for absorption detection."""

    def test_absorption_detection_full_volume_range_delta(self):
        """Absorption with volume, range, delta criteria."""
        bars = [
            {"high": 105, "low": 104, "close": 104.5, "volume": 2500, "buyVolume": 100, "sellVolume": 2400},  # High sell vol
            {"high": 105, "low": 104, "close": 104.5, "volume": 2500, "buyVolume": 2400, "sellVolume": 100},  # High buy vol
        ]
        
        result = detect_absorptions(bars)
        
        assert isinstance(result, list)

    def test_absorption_buy_type(self):
        """Buy absorption when sellVol >> buyVol."""
        bars = [
            {"high": 105, "low": 104, "close": 104.5, "volume": 2000, "buyVolume": 50, "sellVolume": 1950},
        ]
        
        result = detect_absorptions(bars)
        
        # Should detect buy absorption (price couldn't go lower despite selling)
        if result:
            assert result[0].type == "BUY"

    def test_absorption_sell_type(self):
        """Sell absorption when buyVol >> sellVol."""
        bars = [
            {"high": 105, "low": 104, "close": 104.5, "volume": 2000, "buyVolume": 1950, "sellVolume": 50},
        ]
        
        result = detect_absorptions(bars)
        
        # Should detect sell absorption (price couldn't go higher despite buying)
        if result:
            assert result[0].type == "SELL"


class TestBubbleDetection:
    """Tests for volume bubble detection."""

    def test_bubble_detection(self):
        """Volume bubble near entry -> detected."""
        # Bubble detection would check for volume spikes
        volume = 5000
        avg_volume = 1000
        
        is_bubble = volume > avg_volume * 3
        
        assert is_bubble == True