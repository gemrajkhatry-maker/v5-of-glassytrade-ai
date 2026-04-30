"""Tests for VolumeProfileService."""

import pytest
from app.domain.fabio_ai.services.volume_profile_service import (
    VolumeProfileService,
    VolumeProfileConfig,
)
from app.domain.services.volume_profile import create_profile
from app.domain.trading.models.value_objects import OHLC


class TestVolumeProfileService:
    """Test volume profile service operations."""

    def test_service_initialization(self):
        """Test service initializes with default config."""
        service = VolumeProfileService()
        assert service.config is not None
        assert service.config.LVN_THRESHOLD == 0.15

    def test_service_with_custom_config(self):
        """Test service accepts custom config."""
        config = VolumeProfileConfig(LVN_THRESHOLD=0.20)
        service = VolumeProfileService(config)
        assert service.config.LVN_THRESHOLD == 0.20

    def test_lvns_empty_profile(self):
        """Test LVN detection with empty profile."""
        service = VolumeProfileService()
        lvns = service.find_lvns([])
        assert lvns == []

    def test_hvns_empty_profile(self):
        """Test HVN detection with empty profile."""
        service = VolumeProfileService()
        hvns = service.find_hvns([])
        assert hvns == []

    def test_lvns_with_sample_data(self):
        """Test LVN detection returns prices."""
        service = VolumeProfileService()
        
        # Create sample OHLC data
        data = [
            OHLC(time="2024-01-01 09:15:00", open=100, high=102, low=99, close=101, volume=100, delta=10),
            OHLC(time="2024-01-01 09:16:00", open=101, high=103, low=100, close=102, volume=200, delta=20),
            OHLC(time="2024-01-01 09:17:00", open=102, high=104, low=101, close=103, volume=150, delta=15),
        ]
        
        profile = create_profile(data, buckets=50)
        assert len(profile) > 0
        
        lvns = service.find_lvns(profile)
        assert isinstance(lvns, list)

    def test_reset_lvn_tracker(self):
        """Test LVN tracker reset."""
        service = VolumeProfileService()
        service.reset_lvn_tracker()  # Should not raise


# Import at end to avoid circular dependency
VolumeProfileLevel = object  # Placeholder, actual type from value_objects