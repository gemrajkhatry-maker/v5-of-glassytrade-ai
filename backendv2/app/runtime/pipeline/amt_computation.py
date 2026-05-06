"""AMT Computation Stage - computes AMT analysis on accumulated candles.

This pipeline stage accumulates candles per symbol, runs AMTAnalyzer
when new candles arrive, and returns AMTResult for WebSocket streaming.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from app.runtime.pipeline.events import Candle, AMTResult
from app.domain.amt.service.amt_analyzer import AMTAnalyzer

logger = logging.getLogger(__name__)


class AMTComputationStage:
    """Pipeline stage that computes AMT analysis from candles.
    
    Accumulates candles per symbol and runs AMTAnalyzer to produce
    AMTResult objects with market state, profile levels, etc.
    """
    
    def __init__(self, amt_analyzer: AMTAnalyzer, max_history: int = 200):
        """Initialize AMT computation stage.
        
        Args:
            amt_analyzer: AMTAnalyzer instance for analysis
            max_history: Maximum candles to keep per symbol (default 200)
        """
        self._analyzer = amt_analyzer
        self._max_history = max_history
        self._history: dict[str, list[dict]] = defaultdict(list)
    
    def process(self, candle: Candle) -> AMTResult:
        """Process a candle and return AMTResult.
        
        Accumulates candle in per-symbol history, runs AMTAnalyzer,
        and returns analysis result.
        
        Args:
            candle: Candle to process
            
        Returns:
            AMTResult with market state, POC, VAH, VAL, etc.
        """
        symbol = candle.symbol
        
        # Convert Candle to Bar format expected by AMTAnalyzer
        bar = {
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
            "buyVolume": getattr(candle, 'buy_volume', 0.0),
            "sellVolume": getattr(candle, 'sell_volume', 0.0),
            "timestamp": candle.timestamp,
        }
        
        # Accumulate in history
        self._history[symbol].append(bar)
        
        # Limit history to max_history
        if len(self._history[symbol]) > self._max_history:
            self._history[symbol] = self._history[symbol][-self._max_history:]
        
        # Run AMT analysis
        bars = self._history[symbol]
        result = self._analyzer.analyze(bars=bars, symbol=symbol)
        
        return result
    
    def snapshot(self) -> dict[str, int]:
        """Return candle count per symbol for observability.
        
        Returns:
            Dict mapping symbol -> candle count
        """
        return {symbol: len(bars) for symbol, bars in self._history.items()}
    
    def restore(self, payload: dict[str, Any]) -> None:
        """Restore history from payload (for session resume).
        
        Args:
            payload: Dict mapping symbol -> list of bars
        """
        for symbol, bars in payload.items():
            self._history[symbol] = bars[-self._max_history:]
