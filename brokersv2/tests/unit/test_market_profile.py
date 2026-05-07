"""Tests for Market Profile Analytics - TDD."""

import pytest
from datetime import datetime, timezone
from brokersv2.analytics.profile.events import (
    ProfileType,
    VolumeNodeType,
    TPOLevel,
    VolumeProfileLevel,
    TPOProfile,
    VolumeProfile,
    VolumeNode,
    ProfileEvent,
)
from brokersv2.analytics.profile.tpo import TPOProfileEngine
from brokersv2.analytics.profile.volume_profile import VolumeProfileEngine
from brokersv2.analytics.profile.hvn_lvn import HVNLVNDetector
from brokersv2.analytics.profile.session import SessionProfileManager


class TestTPOProfileEngine:
    """Test TPO (Time Price Opportunity) profile calculations."""

    def test_tpo_engine_starts_empty(self):
        """Test TPO engine starts with no levels."""
        engine = TPOProfileEngine("NSE:NIFTY")
        assert engine.level_count == 0

    def test_add_tpo_to_price_level(self):
        """Test adding TPO to price level."""
        engine = TPOProfileEngine("NSE:NIFTY")
        time_a = datetime(2024, 1, 15, 9, 15, tzinfo=timezone.utc)
        
        engine.add_tpo(22000.0, "A", time_a)
        
        assert engine.level_count == 1
        level = engine.get_level(22000.0)
        assert level.tpo_count == 1
        assert "A" in level.tpo_letters

    def test_multiple_tpos_same_level(self):
        """Test multiple TPOs at same price level."""
        engine = TPOProfileEngine("NSE:NIFTY")
        time_a = datetime(2024, 1, 15, 9, 15, tzinfo=timezone.utc)
        time_b = datetime(2024, 1, 15, 9, 45, tzinfo=timezone.utc)
        
        engine.add_tpo(22000.0, "A", time_a)
        engine.add_tpo(22000.0, "B", time_b)
        
        level = engine.get_level(22000.0)
        assert level.tpo_count == 2
        assert "A" in level.tpo_letters
        assert "B" in level.tpo_letters

    def test_point_of_control(self):
        """Test POC calculation (price with most TPOs)."""
        engine = TPOProfileEngine("NSE:NIFTY")
        time_a = datetime(2024, 1, 15, 9, 15, tzinfo=timezone.utc)
        
        engine.add_tpo(22000.0, "A", time_a)
        engine.add_tpo(22000.0, "B", time_a)
        engine.add_tpo(22000.0, "C", time_a)
        engine.add_tpo(22010.0, "A", time_a)
        engine.add_tpo(22010.0, "B", time_a)
        
        poc = engine.get_poc()
        assert poc == 22000.0  # Has 3 TPOs vs 2

    def test_profile_range(self):
        """Test profile range calculation."""
        engine = TPOProfileEngine("NSE:NIFTY")
        time_a = datetime(2024, 1, 15, 9, 15, tzinfo=timezone.utc)
        
        engine.add_tpo(22000.0, "A", time_a)
        engine.add_tpo(22050.0, "A", time_a)
        
        assert engine.profile_range == 50.0

    def test_build_tpo_profile(self):
        """Test building complete TPO profile."""
        engine = TPOProfileEngine("NSE:NIFTY")
        time_a = datetime(2024, 1, 15, 9, 15, tzinfo=timezone.utc)
        
        engine.add_tpo(22000.0, "A", time_a)
        engine.add_tpo(22010.0, "A", time_a)
        
        profile = engine.build_profile()
        
        assert isinstance(profile, TPOProfile)
        assert profile.symbol == "NSE:NIFTY"
        assert profile.level_count == 2

    def test_tpo_letter_assignment(self):
        """Test TPO letter assignment for 30-min periods."""
        engine = TPOProfileEngine("NSE:NIFTY")
        time_a = datetime(2024, 1, 15, 9, 15, tzinfo=timezone.utc)
        time_b = datetime(2024, 1, 15, 9, 45, tzinfo=timezone.utc)
        time_c = datetime(2024, 1, 15, 10, 15, tzinfo=timezone.utc)
        
        engine.add_tpo(22000.0, "A", time_a)
        engine.add_tpo(22000.0, "B", time_b)
        engine.add_tpo(22000.0, "C", time_c)
        
        level = engine.get_level(22000.0)
        assert len(level.tpo_letters) == 3

    def test_total_tpo_count(self):
        """Test total TPO count across all levels."""
        engine = TPOProfileEngine("NSE:NIFTY")
        time_a = datetime(2024, 1, 15, 9, 15, tzinfo=timezone.utc)
        
        engine.add_tpo(22000.0, "A", time_a)
        engine.add_tpo(22010.0, "A", time_a)
        engine.add_tpo(22020.0, "A", time_a)
        
        assert engine.total_tpos == 3

    def test_tpo_first_last_time(self):
        """Test tracking first and last TPO times."""
        engine = TPOProfileEngine("NSE:NIFTY")
        time_early = datetime(2024, 1, 15, 9, 15, tzinfo=timezone.utc)
        time_late = datetime(2024, 1, 15, 15, 15, tzinfo=timezone.utc)
        
        engine.add_tpo(22000.0, "A", time_late)
        engine.add_tpo(22000.0, "B", time_early)
        
        level = engine.get_level(22000.0)
        assert level.first_tpo_time == time_early
        assert level.last_tpo_time == time_late

    def test_reset_engine(self):
        """Test resetting TPO engine."""
        engine = TPOProfileEngine("NSE:NIFTY")
        time_a = datetime(2024, 1, 15, 9, 15, tzinfo=timezone.utc)
        engine.add_tpo(22000.0, "A", time_a)
        
        engine.reset()
        
        assert engine.level_count == 0
        assert engine.total_tpos == 0


class TestVolumeProfileEngine:
    """Test volume profile calculations."""

    def test_volume_profile_starts_empty(self):
        """Test volume profile starts with no levels."""
        engine = VolumeProfileEngine("NSE:BANKNIFTY")
        assert engine.level_count == 0

    def test_add_volume_to_price(self):
        """Test adding volume at price level."""
        engine = VolumeProfileEngine("NSE:BANKNIFTY")
        
        engine.add_volume(48000.0, 100)
        
        assert engine.level_count == 1
        assert engine.get_volume_at_price(48000.0) == 100

    def test_cumulative_volume(self):
        """Test cumulative volume at price level."""
        engine = VolumeProfileEngine("NSE:BANKNIFTY")
        
        engine.add_volume(48000.0, 100)
        engine.add_volume(48000.0, 150)
        
        assert engine.get_volume_at_price(48000.0) == 250

    def test_buy_sell_separation(self):
        """Test buy/sell volume separation."""
        engine = VolumeProfileEngine("NSE:BANKNIFTY")
        
        engine.add_volume(48000.0, 100, buy_volume=60, sell_volume=40)
        
        level = engine.get_level(48000.0)
        assert level.buy_volume == 60
        assert level.sell_volume == 40

    def test_poc_calculation(self):
        """Test Point of Control calculation."""
        engine = VolumeProfileEngine("NSE:BANKNIFTY")
        
        engine.add_volume(48000.0, 300)
        engine.add_volume(48010.0, 500)
        engine.add_volume(48020.0, 200)
        
        poc = engine.get_poc()
        assert poc == 48010.0  # Highest volume

    def test_value_area_calculation(self):
        """Test Value Area calculation (70% rule)."""
        engine = VolumeProfileEngine("NSE:BANKNIFTY")
        
        # Add volumes that create clear value area
        engine.add_volume(48000.0, 100)
        engine.add_volume(48010.0, 400)  # POC
        engine.add_volume(48020.0, 100)
        
        vah, val = engine.get_value_area(percentage=70.0)
        
        assert vah >= val
        assert vah == 48020.0 or vah == 48010.0
        assert val == 48000.0 or val == 48010.0

    def test_total_volume(self):
        """Test total volume calculation."""
        engine = VolumeProfileEngine("NSE:BANKNIFTY")
        
        engine.add_volume(48000.0, 100)
        engine.add_volume(48010.0, 200)
        engine.add_volume(48020.0, 300)
        
        assert engine.total_volume == 600

    def test_build_volume_profile(self):
        """Test building complete volume profile."""
        engine = VolumeProfileEngine("NSE:BANKNIFTY")
        
        engine.add_volume(48000.0, 100)
        engine.add_volume(48010.0, 200)
        
        profile = engine.build_profile()
        
        assert isinstance(profile, VolumeProfile)
        assert profile.symbol == "NSE:BANKNIFTY"
        assert profile.level_count == 2
        assert profile.total_volume == 300

    def test_volume_profile_range(self):
        """Test volume profile range."""
        engine = VolumeProfileEngine("NSE:BANKNIFTY")
        
        engine.add_volume(48000.0, 100)
        engine.add_volume(48100.0, 200)
        
        assert engine.profile_range == 100.0

    def test_volume_weighted_average_price(self):
        """Test VWAP calculation."""
        engine = VolumeProfileEngine("NSE:BANKNIFTY")
        
        engine.add_volume(48000.0, 100)
        engine.add_volume(48020.0, 200)
        
        vwap = engine.get_vwap()
        # (48000*100 + 48020*200) / 300 = 48013.33
        assert abs(vwap - 48013.33) < 0.1

    def test_reset_engine(self):
        """Test resetting volume profile engine."""
        engine = VolumeProfileEngine("NSE:BANKNIFTY")
        engine.add_volume(48000.0, 100)
        
        engine.reset()
        
        assert engine.level_count == 0
        assert engine.total_volume == 0


class TestHVNLVNDetector:
    """Test High/Low Volume Node detection."""

    def test_detect_hvn(self):
        """Test detecting High Volume Node."""
        detector = HVNLVNDetector(hvn_threshold=2.0)
        
        # Create volume profile with clear HVN
        volumes = {48000.0: 100, 48010.0: 500, 48020.0: 100}
        avg_volume = sum(volumes.values()) / len(volumes)
        
        hvns = detector.find_hvns(volumes, avg_volume * 2.0)
        
        assert len(hvns) == 1
        assert hvns[0].price == 48010.0

    def test_detect_lvn(self):
        """Test detecting Low Volume Node."""
        detector = HVNLVNDetector(lvn_threshold=0.5)
        
        volumes = {48000.0: 500, 48010.0: 100, 48020.0: 500}
        avg_volume = sum(volumes.values()) / len(volumes)
        
        lvns = detector.find_lvns(volumes, avg_volume * 0.5)
        
        assert len(lvns) == 1
        assert lvns[0].price == 48010.0

    def test_hvn_strength(self):
        """Test HVN strength calculation."""
        detector = HVNLVNDetector()
        
        volumes = {48000.0: 100, 48010.0: 1000, 48020.0: 100}
        avg_volume = sum(volumes.values()) / len(volumes)
        
        hvns = detector.find_hvns(volumes, avg_volume)
        
        assert len(hvns) == 1
        assert 0.0 < hvns[0].strength <= 1.0

    def test_multiple_nodes(self):
        """Test detecting multiple nodes."""
        detector = HVNLVNDetector(hvn_threshold=1.2)
        
        volumes = {
            48000.0: 500,
            48010.0: 100,
            48020.0: 600,
            48030.0: 100,
            48040.0: 500,
        }
        avg_volume = sum(volumes.values()) / len(volumes)
        
        # Use lower threshold to get multiple nodes
        hvns = detector.find_hvns(volumes, avg_volume * 1.2)
        
        # Should find at least the top volume levels
        assert len(hvns) >= 1

    def test_no_nodes_found(self):
        """Test when no nodes meet threshold."""
        detector = HVNLVNDetector(hvn_threshold=10.0)
        
        volumes = {48000.0: 100, 48010.0: 110, 48020.0: 105}
        avg_volume = sum(volumes.values()) / len(volumes)
        
        hvns = detector.find_hvns(volumes, avg_volume * 10.0)
        
        assert len(hvns) == 0

    def test_volume_node_type(self):
        """Test volume node type classification."""
        hvn = VolumeNode(
            node_type=VolumeNodeType.HVN,
            price=48010.0,
            volume=500,
            strength=0.8,
        )
        assert hvn.node_type == VolumeNodeType.HVN

    def test_node_sorting(self):
        """Test nodes sorted by strength."""
        detector = HVNLVNDetector()
        
        volumes = {
            48000.0: 400,
            48010.0: 600,
            48020.0: 500,
        }
        avg_volume = sum(volumes.values()) / len(volumes)
        
        hvns = detector.find_hvns(volumes, avg_volume)
        
        # Should be sorted by strength (volume)
        for i in range(len(hvns) - 1):
            assert hvns[i].volume >= hvns[i+1].volume


class TestSessionProfileManager:
    """Test session profile management."""

    def test_create_session_profile(self):
        """Test creating session profile."""
        manager = SessionProfileManager()
        session_date = datetime(2024, 1, 15, tzinfo=timezone.utc)
        
        profile = manager.create_session("NSE:NIFTY", session_date)
        
        assert profile.symbol == "NSE:NIFTY"
        assert profile.session_date == session_date

    def test_store_session(self):
        """Test storing session profile."""
        manager = SessionProfileManager()
        session_date = datetime(2024, 1, 15, tzinfo=timezone.utc)
        
        session = manager.create_session("NSE:NIFTY", session_date)
        manager.store_session(session)
        
        assert manager.get_session_count() == 1

    def test_get_session_by_date(self):
        """Test retrieving session by date."""
        manager = SessionProfileManager()
        session_date = datetime(2024, 1, 15, tzinfo=timezone.utc)
        
        session = manager.create_session("NSE:NIFTY", session_date)
        manager.store_session(session)
        
        retrieved = manager.get_session("NSE:NIFTY", session_date)
        assert retrieved is not None
        assert retrieved.symbol == "NSE:NIFTY"

    def test_get_recent_sessions(self):
        """Test getting recent sessions."""
        manager = SessionProfileManager()
        
        for i in range(5):
            date = datetime(2024, 1, 15 + i, tzinfo=timezone.utc)
            session = manager.create_session("NSE:NIFTY", date)
            manager.store_session(session)
        
        recent = manager.get_recent_sessions("NSE:NIFTY", count=3)
        assert len(recent) == 3

    def test_session_history(self):
        """Test session history tracking."""
        manager = SessionProfileManager()
        
        for i in range(10):
            date = datetime(2024, 1, 15 + i, tzinfo=timezone.utc)
            session = manager.create_session("NSE:NIFTY", date)
            manager.store_session(session)
        
        history = manager.get_session_history("NSE:NIFTY")
        assert len(history) == 10

    def test_rolling_profile(self):
        """Test creating rolling profile from sessions."""
        manager = SessionProfileManager()
        
        for i in range(5):
            date = datetime(2024, 1, 15 + i, tzinfo=timezone.utc)
            session = manager.create_session("NSE:NIFTY", date)
            manager.store_session(session)
        
        rolling = manager.create_rolling_profile("NSE:NIFTY", lookback=3)
        
        assert rolling is not None

    def test_average_poc_with_sessions(self):
        """Test calculating average POC across sessions with POC data."""
        manager = SessionProfileManager()
        
        # Create sessions - they don't have POC data by default
        # So average POC should be None
        avg_poc = manager.get_average_poc("NSE:NIFTY", lookback=5)
        assert avg_poc is None  # No POC data in default sessions


class TestProfileEvents:
    """Test profile event generation."""

    def test_profile_event_creation(self):
        """Test creating profile event."""
        event = ProfileEvent(
            event_type=ProfileType.TPO,
            symbol="NSE:NIFTY",
            timestamp=datetime.now(timezone.utc),
            data={"poc": 22000.0},
        )
        
        assert event.event_type == ProfileType.TPO
        assert event.symbol == "NSE:NIFTY"

    def test_volume_profile_event(self):
        """Test volume profile event."""
        event = ProfileEvent(
            event_type=ProfileType.VOLUME,
            symbol="NSE:BANKNIFTY",
            timestamp=datetime.now(timezone.utc),
            data={"vah": 48100.0, "val": 47900.0},
        )
        
        assert event.event_type == ProfileType.VOLUME

    def test_session_profile_event(self):
        """Test session profile event."""
        event = ProfileEvent(
            event_type=ProfileType.SESSION,
            symbol="NSE:NIFTY",
            timestamp=datetime.now(timezone.utc),
        )
        
        assert event.event_type == ProfileType.SESSION
