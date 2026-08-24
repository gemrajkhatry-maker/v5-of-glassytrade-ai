"""Tests for OrderFlowService."""

import pytest
from quant.amt.orderflow.service import (
    OrderFlowService,
    OrderFlowConfig,
    OrderFlowMetrics,
)
from quant.contracts.value_objects import OHLC, OrderBook


class TestOrderFlowService:
    """Test order flow service operations."""

    def test_service_initialization(self):
        """Test service initializes with detectors."""
        service = OrderFlowService()
        assert service._cvd_tracker is not None
        assert service._big_trade_detector is not None
        assert service._bubble_detector is not None

    def test_service_with_config(self):
        """Test service accepts custom config."""
        config = OrderFlowConfig(OFI_THRESHOLD=0.15)
        service = OrderFlowService(config)
        assert service.config.OFI_THRESHOLD == 0.15

    def test_compute_metrics_empty_data(self):
        """Test metrics with empty data."""
        service = OrderFlowService()
        
        metrics = service.compute_metrics(
            recent_data=[],
            order_book=None,
            current=OHLC("2024-01-01 09:15:00", 100, 102, 99, 101, 100, 10),
            agg_prints=[],
            market_state=type('MS', (), {'name': 'BALANCED'})(),
            lvns=[],
            vah=105.0,
            val=95.0,
            poc=100.0,
            tick_size=0.05,
        )
        
        assert isinstance(metrics, OrderFlowMetrics)
        assert metrics.avg_candle_vol == 0.0
        assert metrics.footprint_confirmed is False

    def test_compute_metrics_normal_data(self):
        """Test metrics with sample data."""
        service = OrderFlowService()
        
        data = [
            OHLC("2024-01-01 09:15:00", 100, 102, 99, 101, 100, 10),
            OHLC("2024-01-01 09:16:00", 101, 103, 100, 102, 150, 15),
        ]
        
        metrics = service.compute_metrics(
            recent_data=data,
            order_book=None,
            current=data[-1],
            agg_prints=[],
            market_state=type('MS', (), {'name': 'BALANCED'})(),
            lvns=[98.0, 103.0],
            vah=105.0,
            val=95.0,
            poc=100.0,
            tick_size=0.05,
        )
        
        assert metrics.avg_candle_vol > 0

    def test_obf_computation(self):
        """Test OBI computation."""
        service = OrderFlowService()
        
        # Create mock order book
        ob = OrderBook(
            bids=[type('Bid', (), {'quantity': 100})(), type('Bid', (), {'quantity': 80})()],
            asks=[type('Ask', (), {'quantity': 50})(), type('Ask', (), {'quantity': 60})()],
        )
        
        obi, toxicity = service._compute_obi(ob)
        assert obi > 0  # More bids than asks


class TestOrderFlowMetrics:
    """Test OrderFlowMetrics dataclass."""
    
    def test_metrics_defaults(self):
        """Test metrics initializes with defaults."""
        metrics = OrderFlowMetrics()
        assert metrics.avg_candle_vol == 0.0
        assert metrics.obi == 0.0
        assert metrics.footprint_confirmed is False