"""Absorption detection tests - TDD cycle 1.3 (testing existing implementation)."""
import pytest
from app.domain.amt.service.orderflow_detectors import detect_absorptions
from app.domain.amt.model.amt_models import Absorption


class TestAbsorptionDetection:
    """Test absorption detection logic from orderflow_detectors.py."""

    def test_detects_buy_absorption(self):
        """Should detect BUY absorption: high volume + tight range + positive delta."""
        # Create 20 base bars with average volume
        bars = []
        for i in range(20):
            bars.append({
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 100,
                "buyVolume": 60,
                "sellVolume": 40,
            })
        
        # Add absorption bar: 3x avg volume, tight range, positive delta
        bars.append({
            "high": 100.3,
            "low": 99.7,
            "close": 100.1,
            "volume": 400,  # 4x average (100)
            "buyVolume": 300,
            "sellVolume": 100,
        })

        absorptions = detect_absorptions(bars, avg_volume_multiplier=1.5, range_threshold=0.5, min_bars=20)

        assert len(absorptions) >= 1
        assert absorptions[0].side == "BUY"
        assert absorptions[0].volume == 400
        assert absorptions[0].bar_index == 20

    def test_detects_sell_absorption(self):
        """Should detect SELL absorption: high volume + tight range + negative delta."""
        bars = []
        for i in range(20):
            bars.append({
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 100,
                "buyVolume": 60,
                "sellVolume": 40,
            })
        
        # Absorption bar: high volume, tight range, negative delta
        bars.append({
            "high": 100.3,
            "low": 99.7,
            "close": 99.9,
            "volume": 400,
            "buyVolume": 100,
            "sellVolume": 300,
        })

        absorptions = detect_absorptions(bars, avg_volume_multiplier=1.5, range_threshold=0.5, min_bars=20)

        assert len(absorptions) >= 1
        assert absorptions[0].side == "SELL"

    def test_no_absorption_normal_volume(self):
        """Should NOT detect absorption with normal volume."""
        bars = []
        for i in range(20):
            bars.append({
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 100,
                "buyVolume": 60,
                "sellVolume": 40,
            })

        absorptions = detect_absorptions(bars, avg_volume_multiplier=1.5, range_threshold=0.5, min_bars=20)

        assert len(absorptions) == 0

    def test_no_absorption_wide_range(self):
        """Should NOT detect absorption with wide range (not compressed)."""
        bars = []
        for i in range(20):
            bars.append({
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 100,
                "buyVolume": 60,
                "sellVolume": 40,
            })
        
        # High volume but WIDE range (not compressed)
        bars.append({
            "high": 105.0,
            "low": 95.0,
            "close": 100.0,
            "volume": 400,
            "buyVolume": 300,
            "sellVolume": 100,
        })

        absorptions = detect_absorptions(bars, avg_volume_multiplier=1.5, range_threshold=0.5, min_bars=20)

        assert len(absorptions) == 0

    def test_respects_volume_multiplier_threshold(self):
        """Should only detect absorption when volume >= avg * multiplier."""
        bars = []
        for i in range(20):
            bars.append({
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 100,
                "buyVolume": 60,
                "sellVolume": 40,
            })
        
        # Volume = 140, avg = ~103, multiplier = 1.5, need >= 154.5
        bars.append({
            "high": 100.3,
            "low": 99.7,
            "close": 100.1,
            "volume": 140,  # Below threshold
            "buyVolume": 100,
            "sellVolume": 40,
        })

        absorptions = detect_absorptions(bars, avg_volume_multiplier=1.5, range_threshold=0.5, min_bars=20)

        assert len(absorptions) == 0

    def test_calculates_strength_correctly(self):
        """Should calculate absorption strength (normalized volume excess)."""
        bars = []
        for i in range(20):
            bars.append({
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 100,
                "buyVolume": 60,
                "sellVolume": 40,
            })
        
        # Very high volume = high strength
        bars.append({
            "high": 100.3,
            "low": 99.7,
            "close": 100.1,
            "volume": 600,  # 6x average
            "buyVolume": 450,
            "sellVolume": 150,
        })

        absorptions = detect_absorptions(bars, avg_volume_multiplier=1.5, range_threshold=0.5, min_bars=20)

        assert len(absorptions) >= 1
        # strength = min(1.0, 600 / (100 * 3)) = min(1.0, 2.0) = 1.0
        assert absorptions[0].strength == pytest.approx(1.0, abs=0.01)

    def test_requires_minimum_bars(self):
        """Should require minimum bars for average calculation."""
        bars = [
            {"high": 101.0, "low": 99.0, "close": 100.0, "volume": 400, "buyVolume": 300, "sellVolume": 100},
        ] * 10  # Only 10 bars, need 20

        absorptions = detect_absorptions(bars, avg_volume_multiplier=1.5, range_threshold=0.5, min_bars=20)

        assert len(absorptions) == 0

    def test_handles_zero_volume_gracefully(self):
        """Should not crash on zero volume bars."""
        bars = []
        for i in range(20):
            bars.append({
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 0,
                "buyVolume": 0,
                "sellVolume": 0,
            })

        absorptions = detect_absorptions(bars, avg_volume_multiplier=1.5, range_threshold=0.5, min_bars=20)

        assert isinstance(absorptions, list)
        assert len(absorptions) == 0

    def test_detects_multiple_absorptions(self):
        """Should detect multiple absorption events in same dataset."""
        bars = []
        for i in range(20):
            bars.append({
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 100,
                "buyVolume": 60,
                "sellVolume": 40,
            })
        
        # First absorption (BUY)
        bars.append({
            "high": 100.3,
            "low": 99.7,
            "close": 100.1,
            "volume": 400,
            "buyVolume": 300,
            "sellVolume": 100,
        })
        
        # More normal bars
        for i in range(5):
            bars.append({
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 100,
                "buyVolume": 60,
                "sellVolume": 40,
            })
        
        # Second absorption (SELL)
        bars.append({
            "high": 100.3,
            "low": 99.7,
            "close": 99.9,
            "volume": 400,
            "buyVolume": 100,
            "sellVolume": 300,
        })

        absorptions = detect_absorptions(bars, avg_volume_multiplier=1.5, range_threshold=0.5, min_bars=20)

        assert len(absorptions) >= 2
        assert absorptions[0].side == "BUY"
        assert absorptions[1].side == "SELL"

    def test_neutral_delta_no_absorption(self):
        """Should NOT detect absorption when delta is neutral (buyVol == sellVol)."""
        bars = []
        for i in range(20):
            bars.append({
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 100,
                "buyVolume": 60,
                "sellVolume": 40,
            })
        
        # High volume, tight range, but NEUTRAL delta
        bars.append({
            "high": 100.3,
            "low": 99.7,
            "close": 100.0,
            "volume": 400,
            "buyVolume": 200,
            "sellVolume": 200,  # Equal
        })

        absorptions = detect_absorptions(bars, avg_volume_multiplier=1.5, range_threshold=0.5, min_bars=20)

        assert len(absorptions) == 0

    def test_custom_volume_multiplier(self):
        """Should respect custom volume multiplier threshold."""
        bars = []
        for i in range(20):
            bars.append({
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 100,
                "buyVolume": 60,
                "sellVolume": 40,
            })
        
        # Volume = 200 (2x average)
        bars.append({
            "high": 100.3,
            "low": 99.7,
            "close": 100.1,
            "volume": 200,
            "buyVolume": 150,
            "sellVolume": 50,
        })

        # With multiplier=1.5, should detect (200 > 100*1.5)
        absorptions_low = detect_absorptions(bars, avg_volume_multiplier=1.5, range_threshold=0.5, min_bars=20)
        assert len(absorptions_low) >= 1

        # With multiplier=2.5, should NOT detect (200 < 100*2.5)
        absorptions_high = detect_absorptions(bars, avg_volume_multiplier=2.5, range_threshold=0.5, min_bars=20)
        assert len(absorptions_high) == 0

    def test_uses_close_price_for_absorption_price(self):
        """Should use bar close price for absorption price."""
        bars = []
        for i in range(20):
            bars.append({
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 100,
                "buyVolume": 60,
                "sellVolume": 40,
            })
        
        # Absorption bar: high volume, TIGHT range (0.6 vs avg 2.0 * 0.5 = 1.0 threshold)
        bars.append({
            "high": 100.3,
            "low": 99.7,
            "close": 100.2,  # Close price
            "volume": 400,
            "buyVolume": 300,
            "sellVolume": 100,
        })

        absorptions = detect_absorptions(bars, avg_volume_multiplier=1.5, range_threshold=0.5, min_bars=20)

        assert len(absorptions) >= 1
        assert absorptions[0].price == 100.2

    def test_returns_absorption_dataclass(self):
        """Should return Absorption dataclass instances."""
        bars = []
        for i in range(20):
            bars.append({
                "high": 101.0,
                "low": 99.0,
                "close": 100.0,
                "volume": 100,
                "buyVolume": 60,
                "sellVolume": 40,
            })
        
        bars.append({
            "high": 100.3,
            "low": 99.7,
            "close": 100.1,
            "volume": 400,
            "buyVolume": 300,
            "sellVolume": 100,
        })

        absorptions = detect_absorptions(bars, avg_volume_multiplier=1.5, range_threshold=0.5, min_bars=20)

        assert len(absorptions) >= 1
        assert isinstance(absorptions[0], Absorption)
        # Verify frozen dataclass attributes
        assert hasattr(absorptions[0], 'bar_index')
        assert hasattr(absorptions[0], 'price')
        assert hasattr(absorptions[0], 'volume')
        assert hasattr(absorptions[0], 'side')
        assert hasattr(absorptions[0], 'strength')
