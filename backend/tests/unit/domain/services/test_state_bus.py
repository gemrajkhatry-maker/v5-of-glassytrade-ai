"""Tests for State Bus — central state validation and anomaly detection."""

import pytest
from datetime import datetime, timezone, timedelta
from app.domain.services.state_bus import StateBus, DataAnomaly, _MAX_STALENESS_MS


class TestDataAnomaly:
    """Tests for DataAnomaly record."""

    def test_create(self):
        """Test creating a DataAnomaly."""
        anomaly = DataAnomaly(
            symbol="NIFTY",
            anomaly_type="SESSION_CHANGE",
            detail="Session changed: old -> new",
        )
        assert anomaly.symbol == "NIFTY"
        assert anomaly.anomaly_type == "SESSION_CHANGE"
        assert "old -> new" in anomaly.detail
        assert anomaly.timestamp != ""  # Should have timestamp

    def test_repr(self):
        """Test string representation."""
        anomaly = DataAnomaly(
            symbol="BANKNIFTY",
            anomaly_type="STALE_DATA",
            detail="Data is 10000ms old",
        )
        result = repr(anomaly)
        assert "BANKNIFTY" in result
        assert "STALE_DATA" in result
        assert "Data is 10000ms old" in result


class TestStateBus:
    """Tests for StateBus."""

    def setup_method(self):
        """Set up test state bus."""
        self.bus = StateBus()

    def test_init(self):
        """Test StateBus initialization."""
        assert len(self.bus._latest) == 0
        assert len(self.bus._current_sessions) == 0
        assert len(self.bus._anomalies) == 0
        assert self.bus._max_anomalies == 100

    def test_set_current_session(self):
        """Test setting current session."""
        self.bus.set_current_session("NIFTY", "session_123")
        assert self.bus._current_sessions["NIFTY"] == "session_123"

    def test_session_change_detection(self):
        """Test that session changes are detected."""
        self.bus.set_current_session("NIFTY", "session_123")
        self.bus.set_current_session("NIFTY", "session_456")

        anomalies = self.bus.get_anomalies()
        assert len(anomalies) == 1
        assert anomalies[0].anomaly_type == "SESSION_CHANGE"
        assert "session_123 -> session_456" in anomalies[0].detail

    def test_publish_new_symbol(self):
        """Test publishing state for a new symbol."""
        state = {"poc": 25000, "val": 24800, "vah": 25200}
        result = self.bus.publish("NIFTY", state)

        assert result == state
        assert self.bus.get("NIFTY") == state
        assert len(self.bus.get_anomalies()) == 0

    def test_publish_valid_state(self):
        """Test publishing valid state passes validation."""
        state = {
            "poc": 25000,
            "val": 24800,
            "vah": 25200,
            "sessionVwap": 25050,
            "computedAt": datetime.now(timezone.utc).isoformat(),
        }
        result = self.bus.publish("NIFTY", state)
        assert result == state

    def test_publish_invalid_poc(self):
        """Test that invalid POC is rejected."""
        state = {"poc": 0, "val": 24800, "vah": 25200}
        result = self.bus.publish("NIFTY", state)
        assert result is None  # Rejected

        anomalies = self.bus.get_anomalies()
        assert len(anomalies) == 1
        assert anomalies[0].anomaly_type == "INVARIANT_VIOLATION"
        assert "POC" in anomalies[0].detail

    def test_publish_val_greater_than_poc(self):
        """Test that VAL >= POC is rejected."""
        state = {"poc": 25000, "val": 25100, "vah": 25200}
        result = self.bus.publish("NIFTY", state)
        assert result is None  # Rejected

    def test_publish_poc_greater_than_vah(self):
        """Test that POC >= VAH is rejected."""
        state = {"poc": 25300, "val": 24800, "vah": 25200}
        result = self.bus.publish("NIFTY", state)
        assert result is None  # Rejected

    def test_publish_negative_vwap(self):
        """Test that negative VWAP is rejected."""
        state = {"poc": 25000, "val": 24800, "vah": 25200, "sessionVwap": -100}
        result = self.bus.publish("NIFTY", state)
        assert result is None  # Rejected

    def test_stale_data_detection(self):
        """Test stale data detection."""
        # First publish fresh data
        state = {
            "poc": 25000,
            "val": 24800,
            "vah": 25200,
            "sessionVwap": 25050,
            "computedAt": datetime.now(timezone.utc).isoformat(),
        }
        result = self.bus.publish("NIFTY", state)
        assert result is not None  # Accepted

        # Now publish stale data (simulate old timestamp)
        old_time = datetime.now(timezone.utc) - timedelta(milliseconds=_MAX_STALENESS_MS + 100)
        state["computedAt"] = old_time.isoformat()
        result = self.bus.publish("NIFTY", state)
        assert result is None  # Rejected - stale

        anomalies = self.bus.get_anomalies(symbol="NIFTY")
        stale_anomalies = [a for a in anomalies if a.anomaly_type == "STALE_DATA"]
        assert len(stale_anomalies) == 1

    def test_get_anomalies_filtered(self):
        """Test getting anomalies filtered by symbol."""
        self.bus.set_current_session("NIFTY", "session_123")
        self.bus.set_current_session("BANKNIFTY", "session_456")

        anomalies = self.bus.get_anomalies(symbol="NIFTY")
        assert all(a.symbol == "NIFTY" for a in anomalies)

    def test_get_anomalies_limit(self):
        """Test that anomalies are limited."""
        for i in range(150):
            self.bus._record_anomaly(
                DataAnomaly(symbol=f"SYM{i}", anomaly_type="TEST", detail="test")
            )

        assert len(self.bus._anomalies) == 100  # Trimmed to max_anomalies

    def test_clear_anomalies(self):
        """Test clearing anomalies."""
        self.bus._record_anomaly(
            DataAnomaly(symbol="NIFTY", anomaly_type="TEST", detail="test")
        )
        assert len(self.bus.get_anomalies()) == 1

        self.bus.clear_anomalies()
        assert len(self.bus.get_anomalies()) == 0

    def test_session_mismatch_with_incoming(self):
        """Test session mismatch detection with incoming data."""
        self.bus.set_current_session("NIFTY", "session_123")

        state = {"sessionId": "session_456", "poc": 25000, "val": 24800, "vah": 25200}  # Different session, valid values
        result = self.bus.publish("NIFTY", state)

        # Should still publish (legitimate session change not yet registered)
        assert result == state

        anomalies = self.bus.get_anomalies()
        mismatch = [a for a in anomalies if a.anomaly_type == "SESSION_MISMATCH"]
        assert len(mismatch) == 1
