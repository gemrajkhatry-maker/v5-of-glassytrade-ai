"""
Unit tests for volume profile engine.
"""

import pytest
from src.profile.volume_profile import VolumeProfileEngine
from src.profile.node_detector import NodeDetector


class TestVolumeProfile:
    """Test volume profile calculations."""

    def test_poc_calculation(self):
        """Test POC is bucket with max volume."""
        engine = VolumeProfileEngine(bucket_size=0.10)
        profile = {
            9.0: 100,
            9.1: 500,  # POC
            9.2: 200,
            9.3: 100,
        }
        poc = engine.get_poc(profile)
        assert poc == 9.1

    def test_value_area_calculation(self):
        """Test VAH/VAL via 70% expansion."""
        engine = VolumeProfileEngine(bucket_size=0.10)
        profile = {
            9.0: 100,
            9.1: 500,
            9.2: 300,
            9.3: 100,
        }
        vah, val = engine.get_value_area(profile, 9.1)
        assert vah is not None
        assert val is not None
        assert vah > 9.1  # VAH above POC
        assert val < 9.1  # VAL below POC

    def test_lvn_detection(self):
        """Test LVN detection at 15% threshold."""
        profile = {
            9.0: 1000,
            9.1: 1000,
            9.2: 100,  # LVN (10% of mean)
            9.3: 1000,
        }
        lvns = NodeDetector.detect_lvns(profile, threshold=0.15)
        assert len(lvns) == 1
        assert lvns[0].price == 9.2

    def test_hvn_detection(self):
        """Test HVN detection at 200% threshold."""
        profile = {
            9.0: 100,
            9.1: 100,
            9.2: 500,  # HVN (500% of mean)
            9.3: 100,
        }
        hvns = NodeDetector.detect_hvns(profile, threshold=2.0)
        assert len(hvns) == 1
        assert hvns[0].price == 9.2

    def test_delta_profile(self):
        """Test delta profile tracking."""
        engine = VolumeProfileEngine(bucket_size=0.10)
        delta_profile = {}
        engine.update_delta_bucket(delta_profile, 9.1, bid_vol=50, ask_vol=100)
        assert delta_profile[9.1]["buy_delta"] == 100
        assert delta_profile[9.1]["sell_delta"] == 50
        assert delta_profile[9.1]["net_delta"] == 50

    def test_empty_profile(self):
        """Test empty profile returns None."""
        engine = VolumeProfileEngine(bucket_size=0.10)
        poc = engine.get_poc({})
        assert poc is None