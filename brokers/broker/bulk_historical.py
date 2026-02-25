"""
Bulk Historical Data Download

Provides efficient downloading of historical data for multiple symbols
with error collection and progress tracking.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Callable, Any, Iterator

import pandas as pd

from brokers.broker.logging import get_logger
from brokers.broker.validation import OHLCValidator, DataIntegrityError

logger = get_logger("bulk_historical")


@dataclass
class BulkHistoricalResult:
    """
    Result of bulk historical data download.

    Contains successful downloads, errors, and aggregate statistics.

    Attributes:
        data: Dict mapping symbol -> DataFrame of historical data
        errors: Dict mapping symbol -> error message
        start_time: Download start timestamp
        end_time: Download end timestamp

    Example:
        >>> result = downloader.download(["RELIANCE", "TCS"], "2024-01-01", "2024-01-31")
        >>> print(f"Downloaded: {result.successful}/{result.total}")
        >>> for symbol, df in result:
        ...     print(f"{symbol}: {len(df)} bars")
    """

    data: Dict[str, pd.DataFrame] = field(default_factory=dict)
    errors: Dict[str, str] = field(default_factory=dict)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None

    @property
    def successful(self) -> int:
        """Number of successful downloads."""
        return len(self.data)

    @property
    def failed(self) -> int:
        """Number of failed downloads."""
        return len(self.errors)

    @property
    def total(self) -> int:
        """Total number of symbols attempted."""
        return self.successful + self.failed

    @property
    def success_rate(self) -> float:
        """Success rate as a percentage."""
        if self.total == 0:
            return 0.0
        return (self.successful / self.total) * 100

    @property
    def duration_seconds(self) -> Optional[float]:
        """Download duration in seconds."""
        if self.start_time and self.end_time:
            return (self.end_time - self.start_time).total_seconds()
        return None

    def __iter__(self) -> Iterator[tuple[str, pd.DataFrame]]:
        """Iterate over successful downloads."""
        return iter(self.data.items())

    def __getitem__(self, symbol: str) -> pd.DataFrame:
        """Get data for a specific symbol."""
        return self.data[symbol]

    def __contains__(self, symbol: str) -> bool:
        """Check if symbol was successfully downloaded."""
        return symbol in self.data

    def get(self, symbol: str, default=None) -> Optional[pd.DataFrame]:
        """Get data for symbol with default if not found."""
        return self.data.get(symbol, default)

    def get_error(self, symbol: str) -> Optional[str]:
        """Get error message for a failed symbol."""
        return self.errors.get(symbol)

    def has_error(self, symbol: str) -> bool:
        """Check if symbol had an error."""
        return symbol in self.errors


class BulkHistoricalDownloader:
    """
    Download historical data for multiple symbols efficiently.

    Features:
    - Batch downloading with error collection
    - Progress tracking via callbacks
    - Optional OHLC validation
    - Configurable error handling (continue vs fail-fast)
    - Result aggregation

    Example:
        >>> downloader = BulkHistoricalDownloader(fetch_func=broker.get_historical_data)
        >>> result = downloader.download(
        ...     symbols=["RELIANCE", "TCS", "INFY"],
        ...     from_date="2024-01-01",
        ...     to_date="2024-01-31",
        ...     interval="1d"
        ... )
        >>> print(f"Success: {result.successful}/{result.total}")
    """

    def __init__(
        self,
        fetch_func: Callable[[str, str, str, str], pd.DataFrame],
        validate_ohlc: bool = True,
        continue_on_error: bool = True,
    ):
        """
        Initialize downloader.

        Args:
            fetch_func: Function to fetch historical data for a single symbol.
                       Signature: (symbol, from_date, to_date, interval) -> DataFrame
            validate_ohlc: Whether to validate OHLC data integrity
            continue_on_error: If True, continue on errors; if False, raise on first error
        """
        self._fetch_func = fetch_func
        self._validate_ohlc = validate_ohlc
        self._continue_on_error = continue_on_error

    def download(
        self,
        symbols: List[str],
        from_date: str,
        to_date: str,
        interval: str = "1d",
        exchange: Optional[str] = None,
        progress_callback: Optional[Callable[[str, bool, Optional[str]], None]] = None,
    ) -> BulkHistoricalResult:
        """
        Download historical data for multiple symbols.

        Args:
            symbols: List of symbols to download
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
            interval: Time interval ("1d", "1h", "15m", etc.)
            exchange: Optional exchange override
            progress_callback: Optional callback(symbol, success, error_msg) for progress updates

        Returns:
            BulkHistoricalResult with data and errors

        Raises:
            DataIntegrityError: If OHLC validation fails and validate_ohlc is True
            Exception: If continue_on_error is False and a download fails
        """
        result = BulkHistoricalResult()
        result.start_time = datetime.now()

        logger.info(f"Bulk download starting: {len(symbols)} symbols")

        for i, symbol in enumerate(symbols, 1):
            try:
                logger.debug(f"[{i}/{len(symbols)}] Downloading {symbol}...")

                # Fetch data
                df = self._fetch_func(symbol, from_date, to_date, interval)

                if df is None or df.empty:
                    raise ValueError("No data returned")

                # Validate OHLC if enabled
                if self._validate_ohlc:
                    errors = OHLCValidator.validate(df, symbol)
                    if errors:
                        raise DataIntegrityError(
                            f"OHLC validation failed for {symbol}: {'; '.join(errors[:3])}"
                        )

                # Store successful download
                result.data[symbol] = df
                logger.debug(f"Downloaded {symbol}: {len(df)} bars")

                # Call progress callback
                if progress_callback:
                    progress_callback(symbol, True, None)

            except Exception as e:
                error_msg = str(e)
                result.errors[symbol] = error_msg
                logger.warning(f"Failed to download {symbol}: {error_msg}")

                # Call progress callback
                if progress_callback:
                    progress_callback(symbol, False, error_msg)

                # Raise immediately if not continuing on error
                if not self._continue_on_error:
                    result.end_time = datetime.now()
                    raise

        result.end_time = datetime.now()

        duration = result.duration_seconds
        logger.info(
            f"Bulk download complete: {result.successful}/{result.total} successful "
            f"({duration:.1f}s)"
        )

        return result

    def download_parallel(
        self,
        symbols: List[str],
        from_date: str,
        to_date: str,
        interval: str = "1d",
        max_workers: int = 4,
        exchange: Optional[str] = None,
    ) -> BulkHistoricalResult:
        """
        Download historical data for multiple symbols in parallel.

        Args:
            symbols: List of symbols to download
            from_date: Start date (YYYY-MM-DD)
            to_date: End date (YYYY-MM-DD)
            interval: Time interval
            max_workers: Maximum number of parallel workers
            exchange: Optional exchange override

        Returns:
            BulkHistoricalResult with data and errors
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        result = BulkHistoricalResult()
        result.start_time = datetime.now()

        logger.info(
            f"Parallel bulk download starting: {len(symbols)} symbols "
            f"(max_workers={max_workers})"
        )

        def fetch_single(
            symbol: str,
        ) -> tuple[str, Optional[pd.DataFrame], Optional[str]]:
            """Fetch data for a single symbol."""
            try:
                df = self._fetch_func(symbol, from_date, to_date, interval)

                if df is None or df.empty:
                    return symbol, None, "No data returned"

                # Validate OHLC if enabled
                if self._validate_ohlc:
                    errors = OHLCValidator.validate(df, symbol)
                    if errors:
                        return (
                            symbol,
                            None,
                            f"OHLC validation failed: {'; '.join(errors[:3])}",
                        )

                return symbol, df, None

            except Exception as e:
                return symbol, None, str(e)

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all tasks
            future_to_symbol = {
                executor.submit(fetch_single, symbol): symbol for symbol in symbols
            }

            # Collect results as they complete
            for future in as_completed(future_to_symbol):
                symbol, df, error = future.result()

                if error:
                    result.errors[symbol] = error
                    logger.warning(f"Failed to download {symbol}: {error}")
                else:
                    result.data[symbol] = df
                    logger.debug(f"Downloaded {symbol}: {len(df)} bars")

        result.end_time = datetime.now()

        duration = result.duration_seconds
        logger.info(
            f"Parallel bulk download complete: {result.successful}/{result.total} successful "
            f"({duration:.1f}s)"
        )

        return result


# Convenience function for simple use cases
def download_bulk_historical(
    symbols: List[str],
    from_date: str,
    to_date: str,
    fetch_func: Callable[[str, str, str, str], pd.DataFrame],
    interval: str = "1d",
    validate: bool = True,
    continue_on_error: bool = True,
) -> BulkHistoricalResult:
    """
    Convenience function for bulk historical data download.

    Args:
        symbols: List of symbols to download
        from_date: Start date (YYYY-MM-DD)
        to_date: End date (YYYY-MM-DD)
        fetch_func: Function to fetch data for a single symbol
        interval: Time interval
        validate: Whether to validate OHLC data
        continue_on_error: Continue on download errors

    Returns:
        BulkHistoricalResult with data and errors

    Example:
        >>> def fetch(symbol, from_date, to_date, interval):
        ...     # Your fetch logic here
        ...     return pd.DataFrame(...)
        >>>
        >>> result = download_bulk_historical(
        ...     ["RELIANCE", "TCS", "INFY"],
        ...     "2024-01-01",
        ...     "2024-01-31",
        ...     fetch_func=fetch
        ... )
    """
    downloader = BulkHistoricalDownloader(
        fetch_func=fetch_func,
        validate_ohlc=validate,
        continue_on_error=continue_on_error,
    )

    return downloader.download(symbols, from_date, to_date, interval)
