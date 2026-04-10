"""Data Pipeline Orchestrator — wires all data services into a coherent pipeline.

Flow:
  Tick → CandleAggregator → [VolumeProfile, VWAP, CVD] → AMT Observation

Multi-symbol, multi-timeframe support.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from appv2.domain.models.tick import Tick
from appv2.domain.models.ohlc import OHLC
from appv2.domain.services.candle_aggregator import CandleAggregator
from appv2.domain.services.incremental_volume_profile import IncrementalVolumeProfile
from appv2.domain.services.vwap_calculator import VWAPCalculator
from appv2.domain.services.cvd_tracker import CVDTracker

logger = logging.getLogger(__name__)


@dataclass
class DataPipelineOutput:
    """Output of one pipeline step."""
    symbol: str
    interval: int  # seconds
    candle: OHLC | None  # Completed candle (None if still building)
    vwap: float = 0.0
    vwap_sigma: float = 0.0
    poc: float = 0.0
    vah: float = 0.0
    val: float = 0.0
    cvd: float = 0.0
    cvd_slope: float = 0.0
    vp_total_volume: float = 0.0
    vp_candle_count: int = 0


class DataPipelineOrchestrator:
    """Per-symbol data pipeline — processes ticks into AMT-ready observations.

    Usage:
        pipeline = DataPipelineOrchestrator("NIFTY", tick_size=0.05)
        output = pipeline.process_tick(tick)
    """

    def __init__(
        self,
        symbol: str,
        tick_size: float = 0.05,
        intervals: list[int] | None = None,
    ):
        self.symbol = symbol
        self._tick_size = tick_size
        self._intervals = intervals or [60]

        # Core services
        self._candle_agg = CandleAggregator(intervals=self._intervals)
        self._vp = IncrementalVolumeProfile(tick_size=tick_size)
        self._vwap = VWAPCalculator()
        self._cvd = CVDTracker()

        # Cached state
        self._last_output: DataPipelineOutput | None = None

    def process_tick(self, tick: Tick) -> list[DataPipelineOutput]:
        """Process a tick through the full pipeline.

        Returns:
            List of DataPipelineOutput (one per interval where a candle completed).
        """
        outputs: list[DataPipelineOutput] = []

        # Step 1: Aggregate tick into candles
        candle_results = self._candle_agg.add_tick(tick)

        for interval_sec, candle in candle_results.items():
            if candle is None:
                continue

            # Step 2: Update Volume Profile
            self._vp.update_candle(candle)

            # Step 3: Update VWAP
            vwap_result = self._vwap.update_candle(candle)

            # Step 4: Update CVD
            cvd_state = self._cvd.update_candle(candle)

            # Step 5: Compute POC + VA
            poc = self._vp.get_poc_with_vwap_tiebreak(vwap_result.vwap)
            poc_raw, vah, val = self._vp.compute_value_area()
            if poc == 0:
                poc = poc_raw

            output = DataPipelineOutput(
                symbol=self.symbol,
                interval=interval_sec,
                candle=candle,
                vwap=vwap_result.vwap,
                vwap_sigma=vwap_result.sigma,
                poc=poc,
                vah=vah,
                val=val,
                cvd=cvd_state.cvd,
                cvd_slope=cvd_state.slope,
                vp_total_volume=self._vp.get_total_volume(),
                vp_candle_count=self._vp._candle_count,
            )
            outputs.append(output)
            self._last_output = output

        return outputs

    def get_latest_state(self) -> DataPipelineOutput | None:
        """Get the most recent pipeline output."""
        return self._last_output

    def get_current_candle(self, interval: int) -> OHLC | None:
        """Get the in-progress candle for an interval."""
        return self._candle_agg.get_current_candle(self.symbol, interval)

    def reset(self) -> None:
        """Reset all services (session boundary)."""
        self._vp.reset()
        self._vwap.reset()
        self._cvd.reset()
        self._candle_agg.reset(self.symbol)
        self._last_output = None

    def get_state_dict(self) -> dict:
        """Serialize current state for broadcast."""
        if self._last_output is None:
            return {"symbol": self.symbol, "ready": False}

        return {
            "symbol": self.symbol,
            "ready": True,
            "poc": self._last_output.poc,
            "vah": self._last_output.vah,
            "val": self._last_output.val,
            "vwap": self._last_output.vwap,
            "vwap_sigma": self._last_output.vwap_sigma,
            "cvd": self._last_output.cvd,
            "cvd_slope": self._last_output.cvd_slope,
            "vp_total_volume": self._last_output.vp_total_volume,
            "vp_candle_count": self._last_output.vp_candle_count,
            "current_candle": self._last_output.candle.to_dict() if self._last_output.candle else None,
        }
