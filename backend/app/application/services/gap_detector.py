"""Gap Detection Service — Detects and fills data gaps in streaming market data.

This service runs periodically (every 5 minutes) to:
1. Detect gaps in real-time candle data caused by WebSocket disconnections
2. Fetch historical data from broker API to fill those gaps
3. Merge historical data safely without race conditions

Designed specifically for MCX markets where low liquidity causes streaming gaps.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from app.config import settings
from app.shared.timezones import IST

if TYPE_CHECKING:
    from app.application.services.trading_session import TradingSessionService
    from app.domain.ports.broker import IBroker
    from app.domain.trading.models.value_objects import OHLC

logger = logging.getLogger(__name__)


class GapDetector:
    """Detects and fills gaps in streaming market data."""

    def __init__(
        self,
        session_service: TradingSessionService,
        fetch_historical_callback = None,  # Callable(symbol, from_time, to_time) -> list[OHLC]
    ):
        """Initialize gap detector.

        Args:
            session_service: Trading session service with candle data
            fetch_historical_callback: Optional callback to fetch historical data
        """
        self._session_service = session_service
        self._fetch_historical_callback = fetch_historical_callback
        self._merge_locks: dict[str, asyncio.Lock] = {}
        self._running = False

    async def detect_and_fill_gaps(self, symbols: list[str]) -> dict[str, int]:
        """Detect gaps in streaming data and fill them with historical data.

        Args:
            symbols: List of symbols to check for gaps

        Returns:
            Dict mapping symbol -> number of candles filled
        """
        if not settings.GAP_FILL_ENABLED:
            logger.debug("Gap fill disabled, skipping")
            return {}

        logger.info(
            "Gap detection: checking %d symbols for gaps (lookback=%ds, min_gap=%ds)",
            len(symbols),
            settings.GAP_FILL_MAX_LOOKBACK,
            settings.GAP_FILL_MIN_GAP_SECONDS,
        )

        results = {}
        now = datetime.now(IST)

        for symbol in symbols:
            try:
                filled = await self._check_and_fill_symbol(symbol, now)
                results[symbol] = filled
            except Exception as e:
                logger.error(
                    "Gap detection failed for %s: %s",
                    symbol,
                    e,
                    exc_info=True,
                )
                results[symbol] = 0

        total_filled = sum(results.values())
        logger.info("Gap detection complete: filled %d candles total", total_filled)
        return results

    async def _check_and_fill_symbol(
        self,
        symbol: str,
        now: datetime,
    ) -> int:
        """Check a single symbol for gaps and fill them.

        Args:
            symbol: Symbol to check
            now: Current timestamp

        Returns:
            Number of candles filled
        """
        # Get existing candles from session
        session = self._session_service.get_or_create_session(symbol)
        existing_candles = session.data[-200:]  # Last 200 candles max

        if len(existing_candles) < 2:
            logger.debug("%s: insufficient data (%d candles), skipping gap check", symbol, len(existing_candles))
            return 0

        # Find gaps
        gaps = self._find_gaps(existing_candles, now)

        if not gaps:
            logger.debug("%s: no gaps detected", symbol)
            return 0

        # Fill each gap
        total_filled = 0
        for gap_start, gap_end in gaps:
            try:
                filled = await self._fill_gap(symbol, gap_start, gap_end)
                total_filled += filled
            except Exception as e:
                logger.error(
                    "Failed to fill gap for %s (%s to %s): %s",
                    symbol,
                    gap_start,
                    gap_end,
                    e,
                    exc_info=True,
                )

        return total_filled

    def _find_gaps(
        self,
        candles: list[OHLC],
        now: datetime,
    ) -> list[tuple[datetime, datetime]]:
        """Find time gaps in candle data.

        Args:
            candles: List of OHLC candles (sorted by time)
            now: Current timestamp

        Returns:
            List of (gap_start, gap_end) tuples
        """
        gaps = []
        min_gap = timedelta(seconds=settings.GAP_FILL_MIN_GAP_SECONDS)
        max_lookback = timedelta(seconds=settings.GAP_FILL_MAX_LOOKBACK)
        max_fill_age = timedelta(seconds=settings.GAP_FILL_MAX_FILL_AGE)

        # Only look at recent candles
        lookback_cutoff = now - max_lookback

        # Sort candles by time (safety check)
        sorted_candles = sorted(candles, key=lambda c: self._parse_time(c.time))

        # Find gaps
        for i in range(1, len(sorted_candles)):
            prev_time = self._parse_time(sorted_candles[i - 1].time)
            curr_time = self._parse_time(sorted_candles[i].time)

            # Skip if outside lookback window
            if curr_time < lookback_cutoff:
                continue

            # Skip if gap is too recent (might be currently-forming candle)
            if now - curr_time < max_fill_age:
                continue

            # Check if gap exceeds threshold
            time_diff = curr_time - prev_time
            if time_diff > min_gap:
                gaps.append((prev_time, curr_time))
                logger.warning(
                    "Gap detected: %s missing %.0f minutes (%s to %s)",
                    sorted_candles[i].symbol if hasattr(sorted_candles[i], 'symbol') else "unknown",
                    time_diff.total_seconds() / 60,
                    prev_time.strftime("%H:%M:%S"),
                    curr_time.strftime("%H:%M:%S"),
                )

        return gaps

    async def _fill_gap(
        self,
        symbol: str,
        gap_start: datetime,
        gap_end: datetime,
    ) -> int:
        """Fill a time gap with historical data.

        Args:
            symbol: Symbol to fill
            gap_start: Gap start time
            gap_end: Gap end time

        Returns:
            Number of candles added
        """
        logger.info(
            "Historical fill: fetching data for %s (%s to %s)",
            symbol,
            gap_start.strftime("%H:%M:%S"),
            gap_end.strftime("%H:%M:%S"),
        )

        try:
            # Fetch historical data from broker
            historical_candles = await self._fetch_historical(
                symbol, gap_start, gap_end
            )

            if not historical_candles:
                logger.warning("No historical data returned for %s gap", symbol)
                return 0

            logger.info(
                "Historical fill: fetched %d candles for %s",
                len(historical_candles),
                symbol,
            )

            # Merge into session data (thread-safe)
            merged = await self._merge_historical(symbol, historical_candles)

            logger.info(
                "Merge complete: %d candles added, %d duplicates skipped for %s",
                merged["added"],
                merged["skipped"],
                symbol,
            )

            return merged["added"]

        except Exception as e:
            logger.error("Historical fill failed for %s: %s", symbol, e, exc_info=True)
            return 0

    async def _fetch_historical(
        self,
        symbol: str,
        from_time: datetime,
        to_time: datetime,
    ) -> list[OHLC]:
        """Fetch historical candles from broker API.

        Args:
            symbol: Symbol to fetch
            from_time: Start time
            to_time: End time

        Returns:
            List of OHLC candles
        """
        if not self._fetch_historical_callback:
            logger.debug("No historical fetch callback configured, skipping gap fill for %s", symbol)
            return []

        try:
            # Call the callback to fetch historical data
            candles = await self._fetch_historical_callback(symbol, from_time, to_time)
            return candles or []
        except Exception as e:
            logger.error("Failed to fetch historical data for %s: %s", symbol, e)
            return []

    async def _merge_historical(
        self,
        symbol: str,
        historical_candles: list[OHLC],
    ) -> dict[str, int]:
        """Merge historical candles into session data (thread-safe).

        Args:
            symbol: Symbol to merge
            historical_candles: Historical candles to add

        Returns:
            Dict with 'added' and 'skipped' counts
        """
        # Acquire per-symbol lock to prevent race conditions
        if symbol not in self._merge_locks:
            self._merge_locks[symbol] = asyncio.Lock()

        async with self._merge_locks[symbol]:
            session = self._session_service.get_or_create_session(symbol)
            existing_candles = session.data

            # Create set of existing timestamps for fast lookup
            existing_times = {
                self._parse_time(c.time).timestamp() for c in existing_candles
            }

            added = 0
            skipped = 0

            # Add historical candles that don't exist
            for hist_candle in historical_candles:
                hist_time = self._parse_time(hist_candle.time).timestamp()

                if hist_time in existing_times:
                    skipped += 1
                    continue

                # Insert in chronological position
                existing_candles.append(hist_candle)
                existing_times.add(hist_time)
                added += 1

            # Re-sort by timestamp
            existing_candles.sort(key=lambda c: self._parse_time(c.time).timestamp())

            # Cap at MAX_CANDLES_PER_SYMBOL
            from app.application.services.trading_session import MAX_CANDLES_PER_SYMBOL
            if len(existing_candles) > MAX_CANDLES_PER_SYMBOL:
                existing_candles[:] = existing_candles[-MAX_CANDLES_PER_SYMBOL:]

            # Update session data
            session.data = existing_candles

            return {"added": added, "skipped": skipped}

    @staticmethod
    def _parse_time(time_str: str) -> datetime:
        """Parse time string to datetime.

        Args:
            time_str: ISO format time string

        Returns:
            Parsed datetime object
        """
        try:
            return datetime.fromisoformat(time_str.replace("Z", "+00:00"))
        except Exception:
            # Fallback for various formats
            return datetime.fromisoformat(time_str)
