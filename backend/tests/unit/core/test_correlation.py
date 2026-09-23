"""Tests for correlation ID module."""

from app.core.correlation import get_correlation_id, set_correlation_id, clear_correlation_id


class TestCorrelationID:
    def test_default_id_generated(self):
        """Test that a default correlation ID is generated."""
        clear_correlation_id()
        cid = get_correlation_id()
        assert cid is not None
        assert len(cid) > 0

    def test_set_and_get(self):
        """Test setting and getting correlation ID."""
        set_correlation_id("test-correlation-123")
        assert get_correlation_id() == "test-correlation-123"
        clear_correlation_id()

    def test_reset(self):
        """Test resetting correlation ID."""
        set_correlation_id("test-123")
        clear_correlation_id()
        # Should generate new ID after reset
        assert get_correlation_id() != "test-123"