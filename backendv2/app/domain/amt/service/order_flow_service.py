"""Order Flow Service - extracted order flow metrics.

Extracted from AMTAnalyzer to follow Single Responsibility Principle.
Handles footprint analysis, CVD, big trades, absorption, OFI, bubbles.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.trading.model.value_objects import AggressivePrint, OrderBook

logger = logging.getLogger(__name__)

from app.domain.amt.service.cvd_tracker import CVDTracker
from app.domain.amt.service.orderflow_detectors import (
    BigTradeDetector,
    BubbleDetector,
    OFICalculator,
    AbsorptionDetector,
)
from app.domain.amt.service.aggression_scorer import PersistentAggressionScorer
from app.domain.services.aggressive_prints import AggressivePrintRegistry


from dataclasses import dataclass


@dataclass
class OrderFlowConfig:
    """Configuration for order flow calculations."""
    
    FOOTPRINT_MIN_PRINTS: int = 2
    DELTA_THRESHOLD: float = 0.30
    OFI_THRESHOLD: float = 0.10


class OrderFlowMetrics:
    """Result of order flow analysis."""
    
    def __init__(self) -> None:
        # Volume metrics
        self.avg_candle_vol: float = 0.0
        
        # Order book metrics
        self.obi: float = 0.0
        self.toxicity: float = 0.0
        
        # Footprint metrics
        self.norm_delta: float = 0.0
        self.footprint_confirmed: bool = False
        
        # CVD metrics
        self.cvd_state = None
        self.cvd_confirmed: bool = False
        
        # Trade metrics
        self.big_trade_confirmed: bool = False
        
        # Absorption metrics
        self.absorption_detected: bool = False
        self.absorption_side: str = ""
        self.absorption_range_ratio: float = 0.0
        self.absorption_vol_ratio: float = 0.0
        
        # OFI metrics
        self.ofi_aligned: bool = False
        
        # Confluences
        self.confluence_bonus: bool = False
        
        # Bubble metrics
        self.volume_bubble_near: bool = False
        
        # Aggression result
        self.aggression_score: float = 0.0
        self.has_aggression: bool = False
        self.agg_result = None


class OrderFlowService:
    """Order flow analysis service.
    
    Extracted from AMTAnalyzer to follow Single Responsibility Principle.
    """
    
    def __init__(self, config: OrderFlowConfig | None = None) -> None:
        self.config = config or OrderFlowConfig()
        
        # Initialize detectors
        self._cvd_tracker = CVDTracker()
        self._big_trade_detector = BigTradeDetector()
        self._bubble_detector = BubbleDetector()
        self._ofi_calculator = OFICalculator()
        self._absorption_detector = AbsorptionDetector()
        self._bubble_registry = AggressivePrintRegistry()
        self._agg_scorer = PersistentAggressionScorer()
        
        # State for incremental prints
        self._prev_agg_prints: list["AggressivePrint"] = []
        self._prev_agg_data_len: int = 0
    
    def compute_metrics(
        self,
        recent_data,
        order_book: "OrderBook | None",
        current,
        agg_prints: list["AggressivePrint"],
        market_state,
        lvns: list[float],
        vah: float,
        val: float,
        poc: float,
        tick_size: float,
    ) -> OrderFlowMetrics:
        """Compute all order flow metrics.
        
        Args:
            recent_data: Recent candle data
            order_book: Current order book snapshot
            current: Current candle
            agg_prints: Aggressive prints detected
            market_state: Current market state
            lvns: Low volume nodes
            vah, val, poc: Value area and POC levels
            tick_size: Tick size for confluence detection
            
        Returns:
            OrderFlowMetrics with all computed values
        """
        metrics = OrderFlowMetrics()
        
        # Average volume
        metrics.avg_candle_vol = self._compute_avg_volume(recent_data)
        
        # Order book metrics
        metrics.obi, metrics.toxicity = self._compute_obi(order_book)
        
        # Footprint metrics
        metrics.norm_delta = (
            current.delta / current.volume if current.volume > 0 else 0
        )
        metrics.footprint_confirmed = (
            len(agg_prints) >= self.config.FOOTPRINT_MIN_PRINTS
            and abs(metrics.norm_delta) > self.config.DELTA_THRESHOLD
        )
        
        # CVD
        cvd_state = self._cvd_tracker.state()
        metrics.cvd_state = cvd_state
        metrics.cvd_confirmed = self._check_cvd_confirmation(
            market_state, cvd_state
        )
        
        # Big trade
        metrics.big_trade_confirmed = (
            self._big_trade_detector.detect(current, metrics.avg_candle_vol)
            is not None
        )
        
        # Absorption
        absorption = self._compute_absorption(recent_data, current, metrics.avg_candle_vol)
        metrics.absorption_detected = absorption.detected
        metrics.absorption_side = absorption.side if absorption.detected else ""
        metrics.absorption_range_ratio = absorption.range_ratio
        metrics.absorption_vol_ratio = absorption.vol_ratio
        
        # OFI
        ofi_result = self._ofi_calculator.update(current)
        metrics.ofi_aligned = abs(ofi_result.ofi) >= self.config.OFI_THRESHOLD
        
        # Confluence
        metrics.confluence_bonus = self._check_confluence(lvns, [vah, val, poc], tick_size)
        
        # Volume bubble
        bubble = self._bubble_detector.detect(current)
        metrics.volume_bubble_near = bubble.detected
        
        # Aggression score
        self._agg_scorer.set_persistence_for_state(market_state)
        metrics.agg_result = self._agg_scorer.score(
            footprint_confirmed=metrics.footprint_confirmed,
            cvd_confirmed=metrics.cvd_confirmed,
            big_trade_confirmed=metrics.big_trade_confirmed,
            absorption_detected=metrics.absorption_detected,
            ofi_aligned=metrics.ofi_aligned,
            confluence_bonus=metrics.confluence_bonus,
            volume_bubble_near=metrics.volume_bubble_near,
        )
        metrics.aggression_score = metrics.agg_result.score
        metrics.has_aggression = metrics.agg_result.confirmed
        
        return metrics
    
    def update_cvd(self, current) -> None:
        """Update CVD tracker with new candle."""
        self._cvd_tracker.update(current)
    
    def get_cvd_state(self):
        """Get current CVD state."""
        return self._cvd_tracker.state()
    
    def _compute_avg_volume(self, recent_data) -> float:
        """Compute average candle volume."""
        if recent_data:
            return sum(float(d.volume) for d in recent_data) / len(recent_data)
        return 0.0
    
    def _compute_obi(self, order_book) -> tuple[float, float]:
        """Compute Order Book Imbalance and toxicity."""
        if not order_book:
            return 0.0, 0.0
        
        bids_q = sum(b.quantity for b in order_book.bids)
        asks_q = sum(a.quantity for a in order_book.asks)
        total = bids_q + asks_q
        
        if total <= 0:
            return 0.0, 0.0
        
        obi = (bids_q - asks_q) / total
        toxicity = 0.0
        
        if len(order_book.bids) >= 3 and len(order_book.asks) >= 3:
            top_bids = sum(b.quantity for b in order_book.bids[:3])
            top_asks = sum(a.quantity for a in order_book.asks[:3])
            top_total = top_bids + top_asks
            if top_total > 0 and abs((top_bids - top_asks) / top_total) > 0.7:
                toxicity = obi
        
        return obi, toxicity
    
    def _check_cvd_confirmation(self, market_state, cvd_state) -> bool:
        """Check if CVD confirms market state."""
        # Simplified check - expand based on original logic
        if market_state.name in ("IMBALANCED") and cvd_state.slope != 0:
            return True
        if cvd_state.has_divergence:
            return True
        return False
    
    def _compute_absorption(self, recent_data, current, avg_vol) -> object:
        """Compute absorption detection."""
        if not recent_data or len(recent_data) < 2:
            # Return a mock absorption result for empty data
            class MockAbsorption:
                detected = False
                side = ""
                range_ratio = 0.0
                vol_ratio = 0.0
            return MockAbsorption()
        atr = (
            max(d.high for d in recent_data[-14:])
            - min(d.low for d in recent_data[-14:])
        ) / max(len(recent_data[-14:]), 1)
        return self._absorption_detector.detect(current, atr, avg_vol)
    
    def _check_confluence(self, lvns: list[float], levels: list[float], tick_size: float) -> bool:
        """Check if any LVN aligns with key levels."""
        for lvn in lvns:
            for level in levels:
                if level > 0 and abs(lvn - level) < tick_size * 3:
                    return True
        return False