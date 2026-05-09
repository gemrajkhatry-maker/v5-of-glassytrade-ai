"""
Candle normalizer and validator.

Ensures all candles from any provider conform to standard format
and pass validation checks before reaching strategies.
"""

from __future__ import annotations

from typing import List
from datetime import datetime, timezone
from decimal import Decimal
import logging

from brokersv2.domain.market.models import Candle
from brokersv2.domain.instrument.models import CanonicalInstrument
from brokersv2.providers.exceptions import InvalidCandleError, DataQualityError

logger = logging.getLogger(__name__)


class CandleNormalizer:
    """
    Normalize and validate candles from different providers.
    
    All strategies receive identical candle structures regardless of source.
    
    Responsibilities:
    - Validate OHLC relationships
    - Normalize timezones to UTC
    - Validate volume (non-negative)
    - Remove duplicate timestamps
    - Sort by timestamp
    - Detect data quality issues
    """
    
    def normalize(
        self,
        candles: List[Candle],
        instrument: CanonicalInstrument,
        timeframe: str,
    ) -> List[Candle]:
        """
        Normalize and validate candle list.
        
        Args:
            candles: Raw candles from provider
            instrument: Instrument these candles belong to
            timeframe: Timeframe string
        
        Returns:
            Normalized, validated, sorted candles
        
        Raises:
            InvalidCandleError: If candles fail validation
        """
        if not candles:
            return []
        
        # Step 1: Validate each candle
        valid_candles = []
        for candle in candles:
            if self._validate_candle(candle):
                valid_candles.append(candle)
            else:
                logger.warning(f"Invalid candle rejected: {candle}")
        
        if not valid_candles:
            logger.warning("All candles failed validation")
            return []
        
        # Step 2: Normalize timezones to UTC
        normalized = [self._normalize_timezone(c, instrument, timeframe) for c in valid_candles]
        
        # Step 3: Sort by timestamp
        normalized.sort(key=lambda c: c.timestamp)
        
        # Step 4: Remove duplicates
        normalized = self._remove_duplicates(normalized)
        
        # Step 5: Check for data quality issues
        self._check_data_quality(normalized, instrument, timeframe)
        
        logger.debug(f"Normalized {len(candles)} → {len(normalized)} candles")
        return normalized
    
    def _validate_candle(self, candle: Candle) -> bool:
        """
        Validate individual candle.
        
        Checks:
        - OHLC relationships (H >= L, H >= O, H >= C, L <= O, L <= C)
        - Positive prices
        - Non-negative volume
        
        Args:
            candle: Candle to validate
        
        Returns:
            True if valid, False otherwise
        """
        try:
            # Check positive prices
            if candle.open <= 0 or candle.high <= 0 or candle.low <= 0 or candle.close <= 0:
                logger.debug(f"Invalid prices: O={candle.open} H={candle.high} L={candle.low} C={candle.close}")
                return False
            
            # Check OHLC relationships
            if candle.high < candle.low:
                logger.debug(f"High < Low: H={candle.high} L={candle.low}")
                return False
            
            if candle.high < candle.open:
                logger.debug(f"High < Open: H={candle.high} O={candle.open}")
                return False
            
            if candle.high < candle.close:
                logger.debug(f"High < Close: H={candle.high} C={candle.close}")
                return False
            
            if candle.low > candle.open:
                logger.debug(f"Low > Open: L={candle.low} O={candle.open}")
                return False
            
            if candle.low > candle.close:
                logger.debug(f"Low > Close: L={candle.low} C={candle.close}")
                return False
            
            # Check non-negative volume
            if candle.volume < 0:
                logger.debug(f"Negative volume: {candle.volume}")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Candle validation error: {e}")
            return False
    
    def _normalize_timezone(
        self,
        candle: Candle,
        instrument: CanonicalInstrument,
        timeframe: str,
    ) -> Candle:
        """
        Normalize timestamp to UTC.
        
        Args:
            candle: Original candle
            instrument: Instrument
            timeframe: Timeframe
        
        Returns:
            New Candle with UTC timestamp
        """
        timestamp = candle.timestamp
        
        # If naive datetime, assume UTC
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        else:
            # Convert to UTC
            timestamp = timestamp.astimezone(timezone.utc)
        
        # Create new candle with UTC timestamp (frozen dataclass)
        return Candle(
            instrument=candle.instrument,
            timeframe=candle.timeframe,
            timestamp=timestamp,
            open=candle.open,
            high=candle.high,
            low=candle.low,
            close=candle.close,
            volume=candle.volume,
        )
    
    def _remove_duplicates(self, candles: List[Candle]) -> List[Candle]:
        """
        Remove candles with duplicate timestamps.
        
        Keeps the first occurrence, discards subsequent duplicates.
        
        Args:
            candles: Sorted candles
        
        Returns:
            Candles with unique timestamps
        """
        seen = set()
        unique = []
        duplicates = 0
        
        for candle in candles:
            if candle.timestamp not in seen:
                seen.add(candle.timestamp)
                unique.append(candle)
            else:
                duplicates += 1
                logger.debug(f"Duplicate candle at {candle.timestamp} removed")
        
        if duplicates > 0:
            logger.info(f"Removed {duplicates} duplicate candles")
        
        return unique
    
    def _check_data_quality(
        self,
        candles: List[Candle],
        instrument: CanonicalInstrument,
        timeframe: str,
    ):
        """
        Check for data quality issues.
        
        Checks:
        - Out-of-order timestamps (should be sorted)
        - Large gaps in data
        - Suspicious price jumps (>10% between consecutive candles)
        
        Args:
            candles: Normalized candles
            instrument: Instrument
            timeframe: Timeframe
        """
        if len(candles) < 2:
            return
        
        # Check for out-of-order (shouldn't happen after sorting, but verify)
        for i in range(1, len(candles)):
            if candles[i].timestamp <= candles[i-1].timestamp:
                logger.error(
                    f"Out-of-order candles detected at index {i}: "
                    f"{candles[i-1].timestamp} >= {candles[i].timestamp}"
                )
        
        # Check for suspicious price jumps
        for i in range(1, len(candles)):
            prev_close = candles[i-1].close
            curr_open = candles[i].open
            
            if prev_close > 0:
                jump_pct = abs(curr_open - prev_close) / prev_close * 100
                
                if jump_pct > 10:  # More than 10% gap
                    logger.warning(
                        f"Large price gap detected: {jump_pct:.2f}% "
                        f"at {candles[i].timestamp} "
                        f"(prev_close={prev_close}, curr_open={curr_open})"
                    )
    
    def validate_continuity(
        self,
        candles: List[Candle],
        expected_interval_minutes: int,
        tolerance_minutes: int = 5,
    ) -> List[str]:
        """
        Validate candle continuity (detect missing candles).
        
        Args:
            candles: Normalized candles
            expected_interval_minutes: Expected interval between candles
            tolerance_minutes: Tolerance for gap detection
        
        Returns:
            List of warning messages for missing candles
        """
        warnings = []
        
        if len(candles) < 2:
            return warnings
        
        for i in range(1, len(candles)):
            time_diff = (candles[i].timestamp - candles[i-1].timestamp).total_seconds() / 60.0
            
            # Allow for market hours gaps (overnight, weekends)
            if time_diff > expected_interval_minutes + tolerance_minutes:
                # Check if it's a reasonable gap (not overnight/weekend)
                if time_diff < 60 * 24:  # Less than 24 hours
                    warnings.append(
                        f"Possible missing candle: gap of {time_diff:.1f} minutes "
                        f"between {candles[i-1].timestamp} and {candles[i].timestamp}"
                    )
        
        return warnings
