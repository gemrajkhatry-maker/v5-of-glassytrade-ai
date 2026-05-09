"""
Historical data warmup helper.

Preloads historical data for instruments/timeframes to ensure
fast strategy startup and avoid blocking during live trading.

Usage:
    warmup = HistoricalWarmup(router)
    await warmup.preload(
        instruments=[NIFTY_50, BANKNIFTY],
        timeframes=["5m", "15m"],
        lookback_days=10,
    )
"""

from __future__ import annotations

from typing import List
from datetime import datetime, timedelta
import logging

from brokersv2.providers.router import HistoricalDataRouter
from brokersv2.domain.market.models import Candle
from brokersv2.domain.instrument.models import CanonicalInstrument

logger = logging.getLogger(__name__)


class HistoricalWarmup:
    """
    Preload historical data for fast strategy startup.
    
    Features:
    - Multi-instrument, multi-timeframe preloading
    - Configurable lookback period
    - Progress tracking
    - Failure tolerance (continues on individual failures)
    - Performance metrics
    """
    
    def __init__(self, router: HistoricalDataRouter):
        """
        Initialize warmup helper.
        
        Args:
            router: HistoricalDataRouter instance
        """
        self._router = router
        self._cache: dict = {}  # instrument.timeframe -> candles
    
    async def preload(
        self,
        instruments: List[CanonicalInstrument],
        timeframes: List[str],
        lookback_days: int = 10,
    ) -> dict:
        """
        Preload historical data for all instrument/timeframe combinations.
        
        Args:
            instruments: List of instruments to preload
            timeframes: List of timeframes to preload
            lookback_days: Days of historical data to fetch
        
        Returns:
            Dict with preload results and metrics
        """
        results = {
            "total_combinations": len(instruments) * len(timeframes),
            "successful": 0,
            "failed": 0,
            "total_candles": 0,
            "duration_seconds": 0,
            "failures": [],
        }
        
        start_time = datetime.now()
        
        logger.info(
            f"Warmup: preloading {results['total_combinations']} "
            f"combinations ({len(instruments)} instruments × {len(timeframes)} timeframes), "
            f"lookback={lookback_days} days"
        )
        
        for instrument in instruments:
            for timeframe in timeframes:
                try:
                    candles = await self._preload_single(
                        instrument, timeframe, lookback_days
                    )
                    
                    if candles:
                        results["successful"] += 1
                        results["total_candles"] += len(candles)
                        
                        # Cache for strategy use
                        cache_key = f"{instrument.symbol}.{timeframe}"
                        self._cache[cache_key] = candles
                        
                        logger.info(
                            f"Warmup: {instrument.symbol} {timeframe} - "
                            f"{len(candles)} candles loaded"
                        )
                    else:
                        results["failed"] += 1
                        results["failures"].append(
                            f"{instrument.symbol}.{timeframe}: empty response"
                        )
                        
                except Exception as e:
                    results["failed"] += 1
                    results["failures"].append(
                        f"{instrument.symbol}.{timeframe}: {str(e)}"
                    )
                    
                    logger.error(
                        f"Warmup: {instrument.symbol} {timeframe} failed: {e}"
                    )
        
        # Calculate duration
        duration = (datetime.now() - start_time).total_seconds()
        results["duration_seconds"] = duration
        
        # Summary
        logger.info(
            f"Warmup complete: {results['successful']}/{results['total_combinations']} "
            f"successful, {results['total_candles']} total candles, "
            f"{duration:.1f}s"
        )
        
        if results["failures"]:
            logger.warning(f"Warmup failures: {len(results['failures'])}")
            for failure in results["failures"][:5]:  # Show first 5
                logger.warning(f"  - {failure}")
        
        return results
    
    async def _preload_single(
        self,
        instrument: CanonicalInstrument,
        timeframe: str,
        lookback_days: int,
    ) -> List[Candle]:
        """
        Preload data for single instrument/timeframe.
        
        Args:
            instrument: Instrument
            timeframe: Timeframe
            lookback_days: Days to lookback
        
        Returns:
            List of Candle objects
        """
        to_date = datetime.now()
        from_date = to_date - timedelta(days=lookback_days)
        
        candles = await self._router.get_candles(
            instrument=instrument,
            timeframe=timeframe,
            from_date=from_date.strftime("%Y-%m-%d"),
            to_date=to_date.strftime("%Y-%m-%d"),
        )
        
        return candles
    
    def get_cached_candles(
        self,
        instrument_symbol: str,
        timeframe: str,
    ) -> List[Candle]:
        """
        Get cached candles from warmup.
        
        Args:
            instrument_symbol: Instrument symbol
            timeframe: Timeframe
        
        Returns:
            Cached candles or empty list
        """
        cache_key = f"{instrument_symbol}.{timeframe}"
        return self._cache.get(cache_key, [])
    
    def is_warmed_up(
        self,
        instrument_symbol: str,
        timeframe: str,
    ) -> bool:
        """
        Check if instrument/timeframe is warmed up.
        
        Args:
            instrument_symbol: Instrument symbol
            timeframe: Timeframe
        
        Returns:
            True if data is cached
        """
        cache_key = f"{instrument_symbol}.{timeframe}"
        return cache_key in self._cache
    
    def clear_cache(self):
        """Clear all cached data."""
        self._cache.clear()
        logger.info("Warmup cache cleared")
    
    def get_cache_status(self) -> dict:
        """
        Get cache status.
        
        Returns:
            Dict with cache information
        """
        return {
            "entries": len(self._cache),
            "instruments": list(set(
                key.split(".")[0] for key in self._cache.keys()
            )),
            "timeframes": list(set(
                key.split(".")[1] for key in self._cache.keys()
            )),
        }
    
    def __repr__(self) -> str:
        return f"<HistoricalWarmup cached={len(self._cache)}>"
