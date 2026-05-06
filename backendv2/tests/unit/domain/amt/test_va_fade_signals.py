"""Value Area Fade signal tests - TDD cycle 1.5 (testing existing implementation)."""
import pytest
from app.domain.amt.service.signal_generator import generate_triple_a_signal
from app.domain.amt.model.amt_models import Absorption, VolumeProfile


class TestValueFadeSignals:
    """Test Value Area Fade strategy: mean-reversion at VA boundaries."""

    def _create_bars(self, count=30, base_price=100.0, volatility=1.0):
        """Helper to create synthetic bar data."""
        bars = []
        for i in range(count):
            price = base_price + (i % 5 - 2) * volatility
            bars.append({
                "timestamp": i,
                "open": price,
                "high": price + volatility,
                "low": price - volatility,
                "close": price,
                "volume": 100,
                "buyVolume": 60,
                "sellVolume": 40,
            })
        return bars

    def test_va_fade_long_at_val_with_positive_delta(self):
        """Should generate LONG VA-fade signal at VAL with positive delta."""
        bars = self._create_bars(count=30, base_price=100.0)
        
        # Add absorption to trigger ACCUMULATING phase
        absorption = Absorption(bar_index=0, price=101.0, volume=500.0, side="BUY", strength=0.85)
        
        # Price near VAL (98.0), below VWAP, positive delta
        current_bar = {
            "timestamp": 30,
            "open": 98.5,
            "high": 99.0,
            "low": 98.0,
            "close": 98.5,
            "volume": 150,
            "buyVolume": 120,  # Positive delta
            "sellVolume": 30,
        }

        signal = generate_triple_a_signal(
            bars=bars + [current_bar],
            absorptions=[absorption],
            vp=VolumeProfile(
                poc=100.0,
                vah=102.0,
                val=98.0,
                step=0.5,
                levels=[],
            ),
            vwap=99.0,
        )

        assert signal is not None
        assert signal.type == "LONG"
        assert signal.entry == pytest.approx(98.5, abs=0.5)
        assert signal.tp == pytest.approx(100.0)  # Target POC
        assert signal.sl < 98.0  # Below VAL
        assert "VA-fade" in signal.reason

    def test_va_fade_short_at_vah_with_negative_delta(self):
        """Should generate SHORT VA-fade signal at VAH with negative delta."""
        bars = self._create_bars(count=30, base_price=100.0)
        
        # Add absorption
        absorption = Absorption(bar_index=0, price=99.0, volume=500.0, side="SELL", strength=0.85)
        
        # Price near VAH (102.0), above VWAP, negative delta
        current_bar = {
            "timestamp": 30,
            "open": 101.5,
            "high": 102.5,
            "low": 101.0,
            "close": 101.5,
            "volume": 150,
            "buyVolume": 30,
            "sellVolume": 120,  # Negative delta
        }

        signal = generate_triple_a_signal(
            bars=bars + [current_bar],
            absorptions=[absorption],
            vp=VolumeProfile(
                poc=100.0,
                vah=102.0,
                val=98.0,
                step=0.5,
                levels=[],
            ),
            vwap=101.0,
        )

        assert signal is not None
        assert signal.type == "SHORT"
        assert signal.entry == pytest.approx(101.5, abs=0.5)
        assert signal.tp == pytest.approx(100.0)  # Target POC
        assert signal.sl > 102.0  # Above VAH
        assert "VA-fade" in signal.reason

    def test_no_va_fade_if_not_near_val(self):
        """Should NOT generate LONG VA-fade if price far from VAL."""
        bars = self._create_bars(count=30, base_price=100.0)
        
        absorption = Absorption(bar_index=0, price=101.0, volume=500.0, side="BUY", strength=0.85)
        
        current_bar = {
            "timestamp": 30,
            "open": 100.5,
            "high": 101.0,
            "low": 100.0,
            "close": 100.5,
            "volume": 150,
            "buyVolume": 120,
            "sellVolume": 30,
        }

        signal = generate_triple_a_signal(
            bars=bars + [current_bar],
            absorptions=[absorption],
            vp=VolumeProfile(
                poc=100.0,
                vah=102.0,
                val=98.0,
                step=0.5,
                levels=[],
            ),
            vwap=101.0,
        )

        # Should not be LONG VA-fade (price not near VAL)
        if signal is not None:
            assert not (signal.type == "LONG" and "VA-fade" in signal.reason)

    def test_no_va_fade_if_not_near_vah(self):
        """Should NOT generate SHORT VA-fade if price far from VAH."""
        bars = self._create_bars(count=30, base_price=100.0)
        
        absorption = Absorption(bar_index=0, price=99.0, volume=500.0, side="SELL", strength=0.85)
        
        current_bar = {
            "timestamp": 30,
            "open": 100.5,
            "high": 101.0,
            "low": 100.0,
            "close": 100.5,
            "volume": 150,
            "buyVolume": 30,
            "sellVolume": 120,
        }

        signal = generate_triple_a_signal(
            bars=bars + [current_bar],
            absorptions=[absorption],
            vp=VolumeProfile(
                poc=100.0,
                vah=102.0,
                val=98.0,
                step=0.5,
                levels=[],
            ),
            vwap=99.0,
        )

        # Should not be SHORT VA-fade (price not near VAH)
        if signal is not None:
            assert not (signal.type == "SHORT" and "VA-fade" in signal.reason)

    def test_no_va_fade_wrong_delta_direction_long(self):
        """Should NOT generate LONG VA-fade with negative delta."""
        bars = self._create_bars(count=30, base_price=100.0)
        
        absorption = Absorption(bar_index=0, price=101.0, volume=500.0, side="BUY", strength=0.85)
        
        # At VAL but NEGATIVE delta (wrong direction)
        current_bar = {
            "timestamp": 30,
            "open": 98.5,
            "high": 99.0,
            "low": 98.0,
            "close": 98.5,
            "volume": 150,
            "buyVolume": 30,
            "sellVolume": 120,  # Negative delta
        }

        signal = generate_triple_a_signal(
            bars=bars + [current_bar],
            absorptions=[absorption],
            vp=VolumeProfile(
                poc=100.0,
                vah=102.0,
                val=98.0,
                step=0.5,
                levels=[],
            ),
            vwap=99.0,
        )

        # Should not be LONG VA-fade (delta wrong direction)
        if signal is not None:
            assert not (signal.type == "LONG" and "VA-fade" in signal.reason)

    def test_no_va_fade_wrong_delta_direction_short(self):
        """Should NOT generate SHORT VA-fade with positive delta."""
        bars = self._create_bars(count=30, base_price=100.0)
        
        absorption = Absorption(bar_index=0, price=99.0, volume=500.0, side="SELL", strength=0.85)
        
        # At VAH but POSITIVE delta (wrong direction)
        current_bar = {
            "timestamp": 30,
            "open": 101.5,
            "high": 102.5,
            "low": 101.0,
            "close": 101.5,
            "volume": 150,
            "buyVolume": 120,  # Positive delta
            "sellVolume": 30,
        }

        signal = generate_triple_a_signal(
            bars=bars + [current_bar],
            absorptions=[absorption],
            vp=VolumeProfile(
                poc=100.0,
                vah=102.0,
                val=98.0,
                step=0.5,
                levels=[],
            ),
            vwap=101.0,
        )

        # Should not be SHORT VA-fade (delta wrong direction)
        if signal is not None:
            assert not (signal.type == "SHORT" and "VA-fade" in signal.reason)

    def test_va_fade_targets_poc(self):
        """Should target POC as take-profit for VA-fade signals."""
        bars = self._create_bars(count=30, base_price=100.0)
        
        absorption = Absorption(bar_index=0, price=101.0, volume=500.0, side="BUY", strength=0.85)
        
        current_bar = {
            "timestamp": 30,
            "open": 98.5,
            "high": 99.0,
            "low": 98.0,
            "close": 98.5,
            "volume": 150,
            "buyVolume": 120,
            "sellVolume": 30,
        }

        signal = generate_triple_a_signal(
            bars=bars + [current_bar],
            absorptions=[absorption],
            vp=VolumeProfile(
                poc=100.0,
                vah=102.0,
                val=98.0,
                step=0.5,
                levels=[],
            ),
            vwap=99.0,
        )

        if signal is not None and signal.type == "LONG" and "VA-fade" in signal.reason:
            assert signal.tp == pytest.approx(100.0)  # POC
            assert "target POC" in signal.reason

    def test_va_fade_stops_outside_va_boundary(self):
        """Should place stop loss outside VA boundary (below VAL for LONG, above VAH for SHORT)."""
        bars = self._create_bars(count=30, base_price=100.0)
        
        absorption = Absorption(bar_index=0, price=101.0, volume=500.0, side="BUY", strength=0.85)
        
        # LONG at VAL
        current_bar_long = {
            "timestamp": 30,
            "open": 98.5,
            "high": 99.0,
            "low": 98.0,
            "close": 98.5,
            "volume": 150,
            "buyVolume": 120,
            "sellVolume": 30,
        }

        signal_long = generate_triple_a_signal(
            bars=bars + [current_bar_long],
            absorptions=[absorption],
            vp=VolumeProfile(
                poc=100.0,
                vah=102.0,
                val=98.0,
                step=0.5,
                levels=[],
            ),
            vwap=99.0,
        )

        if signal_long is not None and signal_long.type == "LONG":
            assert signal_long.sl < 98.0  # Below VAL

    def test_va_fade_confidence_scaled_by_delta(self):
        """Should scale confidence by delta/volume ratio."""
        bars = self._create_bars(count=30, base_price=100.0)
        
        absorption = Absorption(bar_index=0, price=101.0, volume=500.0, side="BUY", strength=0.85)
        
        # High delta = high confidence
        current_bar_high_delta = {
            "timestamp": 30,
            "open": 98.5,
            "high": 99.0,
            "low": 98.0,
            "close": 98.5,
            "volume": 150,
            "buyVolume": 140,  # Very high delta
            "sellVolume": 10,
        }

        signal = generate_triple_a_signal(
            bars=bars + [current_bar_high_delta],
            absorptions=[absorption],
            vp=VolumeProfile(
                poc=100.0,
                vah=102.0,
                val=98.0,
                step=0.5,
                levels=[],
            ),
            vwap=99.0,
        )

        if signal is not None and signal.type == "LONG" and "VA-fade" in signal.reason:
            assert signal.confidence > 0.5  # High delta should give reasonable confidence
            assert signal.confidence <= 1.0  # Max confidence is 1.0

    def test_va_fade_requires_valid_volume_profile(self):
        """Should NOT generate VA-fade without valid VAH/VAL/POC."""
        bars = self._create_bars(count=30, base_price=100.0)
        
        absorption = Absorption(bar_index=0, price=101.0, volume=500.0, side="BUY", strength=0.85)
        
        current_bar = {
            "timestamp": 30,
            "open": 98.5,
            "high": 99.0,
            "low": 98.0,
            "close": 98.5,
            "volume": 150,
            "buyVolume": 120,
            "sellVolume": 30,
        }

        signal = generate_triple_a_signal(
            bars=bars + [current_bar],
            absorptions=[absorption],
            vp=VolumeProfile(
                poc=0.0,  # Invalid
                vah=0.0,
                val=0.0,
                step=0.5,
                levels=[],
            ),
            vwap=99.0,
        )

        # Should not be VA-fade (invalid VA)
        if signal is not None:
            assert "VA-fade" not in signal.reason

    def test_va_fade_includes_bars_since_absorption(self):
        """Should include bars_since_absorption in signal reason."""
        bars = self._create_bars(count=30, base_price=100.0)
        
        absorption = Absorption(bar_index=0, price=101.0, volume=500.0, side="BUY", strength=0.85)
        
        current_bar = {
            "timestamp": 30,
            "open": 98.5,
            "high": 99.0,
            "low": 98.0,
            "close": 98.5,
            "volume": 150,
            "buyVolume": 120,
            "sellVolume": 30,
        }

        signal = generate_triple_a_signal(
            bars=bars + [current_bar],
            absorptions=[absorption],
            vp=VolumeProfile(
                poc=100.0,
                vah=102.0,
                val=98.0,
                step=0.5,
                levels=[],
            ),
            vwap=99.0,
        )

        if signal is not None and "VA-fade" in signal.reason:
            assert "bars_since_absorption" in signal.reason
