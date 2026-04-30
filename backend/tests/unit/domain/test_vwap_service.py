"""Tests for VWAPService."""

import pytest
from app.domain.fabio_ai.services.vwap_service import VWAPService, VWAPConfig, VWAPResult


class TestVWAPService:
    """Test VWAP calculation and bands."""

    def test_vwap_initial_state(self):
        """Test VWAP starts at zero."""
        service = VWAPService()
        assert service.get_vwap() == 0.0

    def test_vwap_single_update(self):
        """Test VWAP with single price."""
        service = VWAPService()
        result = service.update(typical_price=100.0, volume=10.0, time="2024-01-01 09:15:00")
        assert result == 100.0

    def test_vwap_multiple_updates(self):
        """Test VWAP with multiple prices weighted by volume."""
        service = VWAPService()
        # VWAP = (100*10 + 110*20) / 30 = 106.67
        service.update(100.0, 10.0, "2024-01-01 09:15:00")
        service.update(110.0, 20.0, "2024-01-01 09:16:00")
        assert abs(service.get_vwap() - 106.67) < 0.1

    def test_vwap_session_reset(self):
        """Test VWAP resets on new session (new date)."""
        service = VWAPService()
        service.update(100.0, 10.0, "2024-01-01 09:15:00")
        service.update(110.0, 20.0, "2024-01-01 09:16:00")
        vwap_before = service.get_vwap()
        
        # New day resets
        service.update(150.0, 5.0, "2024-01-02 09:15:00")
        assert service.get_vwap() == 150.0

    def test_build_bands_basic(self):
        """Test VWAP bands calculation."""
        service = VWAPService()
        service.update(100.0, 100.0, "2024-01-01 09:15:00")
        service.update(102.0, 100.0, "2024-01-01 09:16:00")
        service.update(98.0, 100.0, "2024-01-01 09:17:00")
        service.update(101.0, 100.0, "2024-01-01 09:18:00")
        
        result = service.build_bands(live_price=100.0)
        
        assert result.session_vwap > 0
        assert result.vwap_upper_1 > result.vwap_lower_1
        assert result.vwap_upper_2 > result.vwap_upper_1

    def test_sigma_calculation(self):
        """Test sigma deviation calculation."""
        service = VWAPService()
        for i in range(100):
            service.update(100.0 + i * 0.1, 10.0, f"2024-01-01 09:{i:02d}:00")
        
        result = service.build_bands(live_price=110.0)
        assert result.vwap_deviation_sigmas is not None
        assert result.vwap_deviation_sigmas > 0

    def test_sigma_clamp_extreme(self):
        """Test sigma clamping for extreme values."""
        config = VWAPConfig()
        service = VWAPService(config)
        
        # Build up variance
        for i in range(10):
            service.update(100.0, 10.0, f"2024-01-01 09:{i:02d}:00")
        
        result = service.build_bands(live_price=1000.0)  # Extreme price
        assert result.vwap_deviation_sigmas is not None
        assert abs(result.vwap_deviation_sigmas) <= config.MAX_SIGMA_CLAMP

    def test_minimum_std_enforced(self):
        """Test minimum std prevents division issues."""
        service = VWAPService()
        # Single tick - no variance
        service.update(100.0, 10.0, "2024-01-01 09:15:00")
        
        result = service.build_bands(live_price=100.0)
        assert result.vwap_std >= VWAPConfig.MIN_VWAP_STD

    def test_reset_clears_state(self):
        """Test reset clears all state."""
        service = VWAPService()
        service.update(100.0, 10.0, "2024-01-01 09:15:00")
        service.reset()
        assert service.get_vwap() == 0.0