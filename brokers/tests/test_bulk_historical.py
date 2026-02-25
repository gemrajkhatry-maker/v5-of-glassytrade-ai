"""
Tests for Bulk Historical Data Download.
"""

import pandas as pd
import pytest
from datetime import datetime

from brokers.broker.bulk_historical import (
    BulkHistoricalResult,
    BulkHistoricalDownloader,
    download_bulk_historical,
)
from brokers.broker.validation import DataIntegrityError


class TestBulkHistoricalResult:
    """Test BulkHistoricalResult dataclass."""

    def test_empty_result(self):
        """Test empty result creation."""
        result = BulkHistoricalResult()
        assert result.successful == 0
        assert result.failed == 0
        assert result.total == 0
        assert result.success_rate == 0.0

    def test_result_with_data(self):
        """Test result with successful downloads."""
        result = BulkHistoricalResult(
            data={
                "RELIANCE": pd.DataFrame({"close": [100, 101]}),
                "TCS": pd.DataFrame({"close": [200, 201]}),
            }
        )
        assert result.successful == 2
        assert result.failed == 0
        assert result.total == 2
        assert result.success_rate == 100.0

    def test_result_with_errors(self):
        """Test result with errors."""
        result = BulkHistoricalResult(
            data={"RELIANCE": pd.DataFrame({"close": [100]})},
            errors={"INVALID": "Symbol not found"},
        )
        assert result.successful == 1
        assert result.failed == 1
        assert result.total == 2
        assert result.success_rate == 50.0

    def test_result_iteration(self):
        """Test iterating over results."""
        result = BulkHistoricalResult(
            data={
                "RELIANCE": pd.DataFrame({"close": [100]}),
                "TCS": pd.DataFrame({"close": [200]}),
            }
        )

        items = list(result)
        assert len(items) == 2
        assert all(isinstance(symbol, str) for symbol, _ in items)
        assert all(isinstance(df, pd.DataFrame) for _, df in items)

    def test_result_getitem(self):
        """Test dictionary-style access."""
        result = BulkHistoricalResult(data={"RELIANCE": pd.DataFrame({"close": [100]})})

        df = result["RELIANCE"]
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 1

    def test_result_contains(self):
        """Test 'in' operator."""
        result = BulkHistoricalResult(
            data={"RELIANCE": pd.DataFrame()}, errors={"INVALID": "Error"}
        )

        assert "RELIANCE" in result
        assert "INVALID" not in result
        assert "TCS" not in result

    def test_result_get(self):
        """Test get method with default."""
        result = BulkHistoricalResult(data={"RELIANCE": pd.DataFrame({"close": [100]})})

        df = result.get("RELIANCE")
        assert df is not None

        df = result.get("INVALID")
        assert df is None

        df = result.get("INVALID", pd.DataFrame())
        assert isinstance(df, pd.DataFrame)

    def test_result_get_error(self):
        """Test get_error method."""
        result = BulkHistoricalResult(errors={"INVALID": "Not found"})

        assert result.get_error("INVALID") == "Not found"
        assert result.get_error("RELIANCE") is None

    def test_result_has_error(self):
        """Test has_error method."""
        result = BulkHistoricalResult(errors={"INVALID": "Not found"})

        assert result.has_error("INVALID")
        assert not result.has_error("RELIANCE")


class TestBulkHistoricalDownloader:
    """Test BulkHistoricalDownloader."""

    def test_successful_download(self):
        """Test successful bulk download."""

        def mock_fetch(symbol, from_date, to_date, interval):
            return pd.DataFrame(
                {
                    "open": [100, 101],
                    "high": [105, 106],
                    "low": [99, 100],
                    "close": [104, 105],
                    "volume": [1000, 2000],
                }
            )

        downloader = BulkHistoricalDownloader(
            fetch_func=mock_fetch, validate_ohlc=True, continue_on_error=True
        )

        result = downloader.download(
            symbols=["RELIANCE", "TCS"], from_date="2024-01-01", to_date="2024-01-31"
        )

        assert result.successful == 2
        assert result.failed == 0
        assert "RELIANCE" in result
        assert "TCS" in result

    def test_download_with_errors(self):
        """Test download with some failures."""

        def mock_fetch(symbol, from_date, to_date, interval):
            if symbol == "INVALID":
                raise ValueError("Symbol not found")
            return pd.DataFrame(
                {
                    "open": [100],
                    "high": [105],
                    "low": [99],
                    "close": [104],
                    "volume": [1000],
                }
            )

        downloader = BulkHistoricalDownloader(
            fetch_func=mock_fetch, continue_on_error=True
        )

        result = downloader.download(
            symbols=["RELIANCE", "INVALID", "TCS"],
            from_date="2024-01-01",
            to_date="2024-01-31",
        )

        assert result.successful == 2
        assert result.failed == 1
        assert "RELIANCE" in result
        assert "INVALID" not in result
        assert result.has_error("INVALID")

    def test_download_fail_fast(self):
        """Test download with fail-fast mode."""

        def mock_fetch(symbol, from_date, to_date, interval):
            if symbol == "INVALID":
                raise ValueError("Symbol not found")
            return pd.DataFrame(
                {
                    "open": [100],
                    "high": [105],
                    "low": [99],
                    "close": [104],
                    "volume": [1000],
                }
            )

        downloader = BulkHistoricalDownloader(
            fetch_func=mock_fetch, continue_on_error=False
        )

        with pytest.raises(ValueError):
            downloader.download(
                symbols=["RELIANCE", "INVALID", "TCS"],
                from_date="2024-01-01",
                to_date="2024-01-31",
            )

    def test_download_with_validation_error(self):
        """Test download with OHLC validation errors."""

        def mock_fetch(symbol, from_date, to_date, interval):
            # Return invalid OHLC data
            return pd.DataFrame(
                {
                    "open": [100],
                    "high": [95],  # Invalid: high < low
                    "low": [99],
                    "close": [104],
                    "volume": [1000],
                }
            )

        downloader = BulkHistoricalDownloader(
            fetch_func=mock_fetch, validate_ohlc=True, continue_on_error=True
        )

        result = downloader.download(
            symbols=["RELIANCE"], from_date="2024-01-01", to_date="2024-01-31"
        )

        assert result.failed == 1
        assert result.has_error("RELIANCE")

    def test_download_empty_data(self):
        """Test handling of empty data."""

        def mock_fetch(symbol, from_date, to_date, interval):
            return pd.DataFrame()

        downloader = BulkHistoricalDownloader(
            fetch_func=mock_fetch, continue_on_error=True
        )

        result = downloader.download(
            symbols=["RELIANCE"], from_date="2024-01-01", to_date="2024-01-31"
        )

        assert result.failed == 1
        assert "No data returned" in result.get_error("RELIANCE")

    def test_progress_callback(self):
        """Test progress callback."""
        progress_calls = []

        def progress_callback(symbol, success, error_msg):
            progress_calls.append((symbol, success, error_msg))

        def mock_fetch(symbol, from_date, to_date, interval):
            if symbol == "FAIL":
                raise ValueError("Failed")
            return pd.DataFrame(
                {
                    "open": [100],
                    "high": [105],
                    "low": [99],
                    "close": [104],
                    "volume": [1000],
                }
            )

        downloader = BulkHistoricalDownloader(
            fetch_func=mock_fetch,
            validate_ohlc=False,  # Disable validation for this test
            continue_on_error=True,
        )

        downloader.download(
            symbols=["RELIANCE", "FAIL", "TCS"],
            from_date="2024-01-01",
            to_date="2024-01-31",
            progress_callback=progress_callback,
        )

        assert len(progress_calls) == 3
        assert progress_calls[0] == ("RELIANCE", True, None)
        assert progress_calls[1] == ("FAIL", False, "Failed")
        assert progress_calls[2] == ("TCS", True, None)


class TestConvenienceFunction:
    """Test download_bulk_historical convenience function."""

    def test_convenience_function(self):
        """Test the convenience function."""

        def mock_fetch(symbol, from_date, to_date, interval):
            return pd.DataFrame({"close": [100, 101]})

        result = download_bulk_historical(
            symbols=["RELIANCE", "TCS"],
            from_date="2024-01-01",
            to_date="2024-01-31",
            fetch_func=mock_fetch,
            validate=False,
        )

        assert result.successful == 2
        assert "RELIANCE" in result
        assert "TCS" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
