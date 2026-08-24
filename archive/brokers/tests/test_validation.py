"""
Tests for OHLC Data Validator.
"""

import numpy as np
import pandas as pd
import pytest

from brokers.broker.validation import OHLCValidator, DataIntegrityError


class TestOHLCValidator:
    """Test OHLC validation functionality."""

    @pytest.fixture
    def valid_ohlc_df(self):
        """Create a valid OHLC DataFrame."""
        return pd.DataFrame(
            {
                "open": [100.0, 101.0, 102.0],
                "high": [105.0, 106.0, 107.0],
                "low": [99.0, 100.0, 101.0],
                "close": [104.0, 105.0, 106.0],
                "volume": [1000, 2000, 3000],
                "timestamp": pd.date_range("2025-01-01", periods=3, freq="1min"),
            }
        )

    def test_valid_data_passes(self, valid_ohlc_df):
        """Test that valid data passes validation."""
        errors = OHLCValidator.validate(valid_ohlc_df, "RELIANCE")
        assert len(errors) == 0

    def test_missing_columns(self):
        """Test validation fails when required columns are missing."""
        df = pd.DataFrame({"open": [100.0], "close": [104.0]})
        errors = OHLCValidator.validate(df, "RELIANCE")
        assert len(errors) == 1
        assert "Missing required columns" in errors[0]

    def test_empty_dataframe(self):
        """Test validation fails for empty DataFrame."""
        df = pd.DataFrame(
            {"open": [], "high": [], "low": [], "close": [], "volume": []}
        )
        errors = OHLCValidator.validate(df, "RELIANCE")
        assert len(errors) == 1
        assert "empty" in errors[0]

    def test_high_less_than_low(self):
        """Test validation catches High < Low."""
        df = pd.DataFrame(
            {
                "open": [100.0],
                "high": [95.0],  # Less than low
                "low": [99.0],
                "close": [104.0],
                "volume": [1000],
            }
        )
        errors = OHLCValidator.validate(df, "RELIANCE")
        assert len(errors) == 1
        assert "High" in errors[0] and "Low" in errors[0]

    def test_high_less_than_open(self):
        """Test validation catches High < Open."""
        df = pd.DataFrame(
            {
                "open": [110.0],
                "high": [105.0],  # Less than open
                "low": [99.0],
                "close": [104.0],
                "volume": [1000],
            }
        )
        errors = OHLCValidator.validate(df, "RELIANCE")
        assert len(errors) == 1
        assert "High" in errors[0] and "Open" in errors[0]

    def test_high_less_than_close(self):
        """Test validation catches High < Close."""
        df = pd.DataFrame(
            {
                "open": [100.0],
                "high": [103.0],  # Less than close
                "low": [99.0],
                "close": [104.0],
                "volume": [1000],
            }
        )
        errors = OHLCValidator.validate(df, "RELIANCE")
        assert len(errors) == 1
        assert "High" in errors[0] and "Close" in errors[0]

    def test_low_greater_than_open(self):
        """Test validation catches Low > Open."""
        df = pd.DataFrame(
            {
                "open": [100.0],
                "high": [105.0],
                "low": [101.0],  # Greater than open
                "close": [104.0],
                "volume": [1000],
            }
        )
        errors = OHLCValidator.validate(df, "RELIANCE")
        assert len(errors) == 1
        assert "Low" in errors[0] and "Open" in errors[0]

    def test_low_greater_than_close(self):
        """Test validation catches Low > Close."""
        df = pd.DataFrame(
            {
                "open": [100.0],
                "high": [105.0],
                "low": [103.0],  # Greater than close
                "close": [102.0],
                "volume": [1000],
            }
        )
        errors = OHLCValidator.validate(df, "RELIANCE")
        assert len(errors) == 1
        assert "Low" in errors[0] and "Close" in errors[0]

    def test_negative_volume(self):
        """Test validation catches negative volume."""
        df = pd.DataFrame(
            {
                "open": [100.0],
                "high": [105.0],
                "low": [99.0],
                "close": [104.0],
                "volume": [-100],  # Negative
            }
        )
        errors = OHLCValidator.validate(df, "RELIANCE")
        assert len(errors) == 1
        assert "Negative volume" in errors[0]

    def test_nan_values(self):
        """Test validation catches NaN values."""
        df = pd.DataFrame(
            {
                "open": [100.0],
                "high": [np.nan],  # NaN
                "low": [99.0],
                "close": [104.0],
                "volume": [1000],
            }
        )
        errors = OHLCValidator.validate(df, "RELIANCE")
        assert len(errors) == 1
        assert "NaN" in errors[0]

    def test_inf_values(self):
        """Test validation catches inf values."""
        df = pd.DataFrame(
            {
                "open": [100.0],
                "high": [np.inf],  # inf
                "low": [99.0],
                "close": [104.0],
                "volume": [1000],
            }
        )
        errors = OHLCValidator.validate(df, "RELIANCE")
        assert len(errors) == 1
        assert "inf" in errors[0]

    def test_duplicate_timestamps(self):
        """Test validation catches duplicate timestamps."""
        df = pd.DataFrame(
            {
                "open": [100.0, 101.0],
                "high": [105.0, 106.0],
                "low": [99.0, 100.0],
                "close": [104.0, 105.0],
                "volume": [1000, 2000],
                "timestamp": ["2025-01-01 10:00", "2025-01-01 10:00"],  # Duplicate
            }
        )
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        errors = OHLCValidator.validate(df, "RELIANCE")
        assert len(errors) == 1
        assert "duplicate" in errors[0].lower()

    def test_validate_or_raise_passes(self, valid_ohlc_df):
        """Test validate_or_raise doesn't raise for valid data."""
        try:
            OHLCValidator.validate_or_raise(valid_ohlc_df, "RELIANCE")
        except DataIntegrityError:
            pytest.fail("Should not raise for valid data")

    def test_validate_or_raise_fails(self):
        """Test validate_or_raise raises for invalid data."""
        df = pd.DataFrame(
            {
                "open": [100.0],
                "high": [95.0],  # Invalid
                "low": [99.0],
                "close": [104.0],
                "volume": [1000],
            }
        )

        with pytest.raises(DataIntegrityError) as exc_info:
            OHLCValidator.validate_or_raise(df, "RELIANCE")

        assert "RELIANCE" in str(exc_info.value)
        assert "integrity issues" in str(exc_info.value)

    def test_is_valid_returns_true(self, valid_ohlc_df):
        """Test is_valid returns True for valid data."""
        assert OHLCValidator.is_valid(valid_ohlc_df, "RELIANCE") is True

    def test_is_valid_returns_false(self):
        """Test is_valid returns False for invalid data."""
        df = pd.DataFrame(
            {
                "open": [100.0],
                "high": [95.0],  # Invalid
                "low": [99.0],
                "close": [104.0],
                "volume": [1000],
            }
        )
        assert OHLCValidator.is_valid(df, "RELIANCE") is False

    def test_multiple_errors_reported(self):
        """Test that multiple errors are all reported."""
        df = pd.DataFrame(
            {
                "open": [100.0],
                "high": [95.0],  # Invalid: high < low
                "low": [99.0],
                "close": [96.0],  # Invalid: high < close
                "volume": [-100],  # Invalid: negative
            }
        )
        errors = OHLCValidator.validate(df, "RELIANCE")
        assert len(errors) == 1  # All errors in one row
        # Check that all issues are mentioned
        error_str = errors[0]
        assert "High" in error_str
        assert "volume" in error_str


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
