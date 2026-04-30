"""AMT Analyzer V2 — Backward-compatible adapter wrapping AMTPipeline.

This adapter allows gradual migration from AMTAnalyzer to the new pipeline
architecture while maintaining full API compatibility.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.domain.trading.models.enums import MarketState
from app.domain.trading.models.value_objects import OHLC, OrderBook, AMTResult
from app.domain.fabio_ai.services.amt_pipeline import AMTPipeline

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class AMTAnalyzerV2:
    """Backward-compatible adapter wrapping AMTPipeline.
    
    Provides the same interface as AMTAnalyzer while using the new
    pipeline architecture internally. Useful for validation and
    gradual migration.
    """

    def __init__(self, config=None, symbol_config=None):
        """Initialize with optional config (ignored in v2, kept for compat)."""
        self._pipeline = AMTPipeline(config=config)
        self._symbol_config = symbol_config

    def analyze(
        self,
        data: list[OHLC],
        order_book: OrderBook | None = None,
        incremental_profile=None,
        prior_poc: float = 0.0,
        prior_vah: float = 0.0,
        prior_val: float = 0.0,
        developing_profile=None,
        cushion_tier: str = "Conservative",
        session_pnl: float = 0.0,
        npoc_tracker=None,
        underlying: str = "NIFTY",
        daily_data: list[OHLC] | None = None,
        hourly_data: list[OHLC] | None = None,
        option_tick: OHLC | None = None,
        cvd_source: str = "",
        symbol: str = "",
        prior_avg_volume: float = 0.0,
        **kwargs,
    ) -> AMTResult:
        """Run AMT analysis via pipeline, with backward-compatible parameters.
        
        Note: Many parameters are accepted but not yet wired into pipeline.
        Will be integrated incrementally.
        """
        # Run pipeline directly
        result = self._pipeline.analyze(
            data,
            order_book=order_book,
            prior_poc=prior_poc,
            prior_vah=prior_vah,
            prior_val=prior_val,
            cushion_tier=cushion_tier,
            session_pnl=session_pnl,
            underlying=underlying,
            daily_data=daily_data,
            hourly_data=hourly_data,
            option_tick=option_tick,
            cvd_source=cvd_source,
            symbol=symbol,
            prior_avg_volume=prior_avg_volume,
            **kwargs,
        )
        
        # Ensure we have all legacy fields populated
        # Pipeline result should already have MTF and OF metrics
        if not hasattr(result, 'hourly_vah'):
            result.hourly_vah = 0.0
        if not hasattr(result, 'hourly_val'):
            result.hourly_val = 0.0
        if not hasattr(result, 'hourly_poc'):
            result.hourly_poc = 0.0
        if not hasattr(result, 'daily_vah'):
            result.daily_vah = 0.0
        if not hasattr(result, 'daily_val'):
            result.daily_val = 0.0
        if not hasattr(result, 'daily_poc'):
            result.daily_poc = 0.0
        if not hasattr(result, 'ofi'):
            result.ofi = 0.0
        if not hasattr(result, 'session_favor_strategy'):
            result.session_favor_strategy = "NEUTRAL"
            
        return result

    # Expose pipeline components for external access (testing/validation)
    @property
    def pipeline(self) -> "AMTPipeline":
        """Access underlying pipeline for validation."""
        return self._pipeline

    def compute_observation(self, data, order_book=None, prior_vah=0.0, prior_val=0.0):
        """Build RL observation vector - delegates to pipeline result."""
        from app.domain.fabio_ai.models.observation import AMTObservation
        
        result = self.analyze(data, order_book, prior_vah=prior_vah, prior_val=prior_val)
        current = data[-1] if data else OHLC(time="", open=0, high=0, low=0, close=0, volume=0)
        
        return AMTObservation(
            dist_to_poc=0.0,  # Will be computed properly
            is_in_balance=(result.market_state == MarketState.BALANCED.value),
            delta_divergence=0.0,
            nearest_lvn=0.0,
            cvd_slope=0.0,
            profile_shape="D",
            poc_migration=0,
            session="OPEN",
            opening_relation="NEUTRAL",
            aggression_sigma=0.0,
            obi=0.0,
            norm_delta=0.0,
        )