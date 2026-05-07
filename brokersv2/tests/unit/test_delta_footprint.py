"""Tests for Delta & Footprint Analytics - TDD."""

import pytest
from datetime import datetime, timezone
from brokersv2.analytics.delta.events import (
    TradeEvent,
    TradeSide,
    DeltaCandle,
    FootprintLevel,
    FootprintCandle,
    ImbalanceEvent,
    AuctionEvent,
)
from brokersv2.analytics.delta.trade_delta import TradeDeltaCalculator
from brokersv2.analytics.delta.cumulative import CumulativeDeltaEngine
from brokersv2.analytics.delta.footprint import FootprintAggregator
from brokersv2.analytics.delta.imbalance import ImbalanceDetector
from brokersv2.analytics.delta.auction import AuctionAnalyzer


class TestTradeDeltaCalculator:
    """Test trade delta calculations."""

    def test_buy_trade_delta(self):
        """Test buy trade has positive delta."""
        trade = TradeEvent(
            timestamp=datetime.now(timezone.utc),
            price=2500.0,
            quantity=100,
            side=TradeSide.BUY,
            security_id="NSE:RELIANCE",
        )
        assert trade.delta == 100.0

    def test_sell_trade_delta(self):
        """Test sell trade has negative delta."""
        trade = TradeEvent(
            timestamp=datetime.now(timezone.utc),
            price=2500.0,
            quantity=100,
            side=TradeSide.SELL,
            security_id="NSE:RELIANCE",
        )
        assert trade.delta == -100.0

    def test_calculator_starts_at_zero(self):
        """Test delta calculator starts with zero delta."""
        calc = TradeDeltaCalculator("NSE:RELIANCE")
        assert calc.total_delta == 0.0
        assert calc.buy_volume == 0.0
        assert calc.sell_volume == 0.0

    def test_process_buy_trade(self):
        """Test processing buy trade."""
        calc = TradeDeltaCalculator("NSE:RELIANCE")
        trade = TradeEvent(
            timestamp=datetime.now(timezone.utc),
            price=2500.0,
            quantity=100,
            side=TradeSide.BUY,
            security_id="NSE:RELIANCE",
        )
        
        calc.process_trade(trade)
        
        assert calc.total_delta == 100.0
        assert calc.buy_volume == 100.0
        assert calc.sell_volume == 0.0

    def test_process_sell_trade(self):
        """Test processing sell trade."""
        calc = TradeDeltaCalculator("NSE:RELIANCE")
        trade = TradeEvent(
            timestamp=datetime.now(timezone.utc),
            price=2500.0,
            quantity=150,
            side=TradeSide.SELL,
            security_id="NSE:RELIANCE",
        )
        
        calc.process_trade(trade)
        
        assert calc.total_delta == -150.0
        assert calc.buy_volume == 0.0
        assert calc.sell_volume == 150.0

    def test_mixed_trades(self):
        """Test processing mixed buy/sell trades."""
        calc = TradeDeltaCalculator("NSE:RELIANCE")
        
        calc.process_trade(TradeEvent(
            timestamp=datetime.now(timezone.utc),
            price=2500.0, quantity=100, side=TradeSide.BUY,
            security_id="NSE:RELIANCE",
        ))
        calc.process_trade(TradeEvent(
            timestamp=datetime.now(timezone.utc),
            price=2501.0, quantity=50, side=TradeSide.SELL,
            security_id="NSE:RELIANCE",
        ))
        
        assert calc.total_delta == 50.0  # 100 - 50
        assert calc.buy_volume == 100.0
        assert calc.sell_volume == 50.0

    def test_trade_count(self):
        """Test trade counting."""
        calc = TradeDeltaCalculator("NSE:RELIANCE")
        
        for _ in range(10):
            calc.process_trade(TradeEvent(
                timestamp=datetime.now(timezone.utc),
                price=2500.0, quantity=100, side=TradeSide.BUY,
                security_id="NSE:RELIANCE",
            ))
        
        assert calc.trade_count == 10

    def test_delta_per_trade(self):
        """Test average delta per trade."""
        calc = TradeDeltaCalculator("NSE:RELIANCE")
        
        calc.process_trade(TradeEvent(
            timestamp=datetime.now(timezone.utc),
            price=2500.0, quantity=100, side=TradeSide.BUY,
            security_id="NSE:RELIANCE",
        ))
        calc.process_trade(TradeEvent(
            timestamp=datetime.now(timezone.utc),
            price=2501.0, quantity=200, side=TradeSide.BUY,
            security_id="NSE:RELIANCE",
        ))
        
        assert calc.delta_per_trade == 150.0  # (100 + 200) / 2

    def test_buy_sell_ratio(self):
        """Test buy/sell volume ratio."""
        calc = TradeDeltaCalculator("NSE:RELIANCE")
        
        calc.process_trade(TradeEvent(
            timestamp=datetime.now(timezone.utc),
            price=2500.0, quantity=300, side=TradeSide.BUY,
            security_id="NSE:RELIANCE",
        ))
        calc.process_trade(TradeEvent(
            timestamp=datetime.now(timezone.utc),
            price=2501.0, quantity=100, side=TradeSide.SELL,
            security_id="NSE:RELIANCE",
        ))
        
        assert calc.buy_sell_ratio == 3.0  # 300 / 100

    def test_delta_percentage(self):
        """Test delta as percentage of total volume."""
        calc = TradeDeltaCalculator("NSE:RELIANCE")
        
        calc.process_trade(TradeEvent(
            timestamp=datetime.now(timezone.utc),
            price=2500.0, quantity=300, side=TradeSide.BUY,
            security_id="NSE:RELIANCE",
        ))
        calc.process_trade(TradeEvent(
            timestamp=datetime.now(timezone.utc),
            price=2501.0, quantity=100, side=TradeSide.SELL,
            security_id="NSE:RELIANCE",
        ))
        
        # Delta = 200, Total = 400, % = 50
        assert calc.delta_percentage == 50.0

    def test_reset_calculator(self):
        """Test resetting calculator."""
        calc = TradeDeltaCalculator("NSE:RELIANCE")
        calc.process_trade(TradeEvent(
            timestamp=datetime.now(timezone.utc),
            price=2500.0, quantity=100, side=TradeSide.BUY,
            security_id="NSE:RELIANCE",
        ))
        
        calc.reset()
        
        assert calc.total_delta == 0.0
        assert calc.trade_count == 0

    def test_aggressive_buyer_classification(self):
        """Test aggressive buyer detection."""
        trade = TradeEvent(
            timestamp=datetime.now(timezone.utc),
            price=2505.0,
            quantity=100,
            side=TradeSide.BUY,
            security_id="NSE:RELIANCE",
            is_aggressive_buyer=True,
        )
        assert trade.is_aggressive_buyer is True
        assert trade.is_aggressive_seller is False

    def test_aggressive_seller_classification(self):
        """Test aggressive seller detection."""
        trade = TradeEvent(
            timestamp=datetime.now(timezone.utc),
            price=2500.0,
            quantity=100,
            side=TradeSide.SELL,
            security_id="NSE:RELIANCE",
            is_aggressive_seller=True,
        )
        assert trade.is_aggressive_seller is True

    def test_trade_history(self):
        """Test trade history tracking."""
        calc = TradeDeltaCalculator("NSE:RELIANCE")
        
        trade1 = TradeEvent(
            timestamp=datetime.now(timezone.utc),
            price=2500.0, quantity=100, side=TradeSide.BUY,
            security_id="NSE:RELIANCE",
        )
        calc.process_trade(trade1)
        
        assert len(calc.trade_history) == 1
        assert calc.trade_history[0] == trade1


class TestCumulativeDeltaEngine:
    """Test cumulative delta calculations."""

    def test_cumulative_delta_starts_zero(self):
        """Test cumulative delta starts at zero."""
        engine = CumulativeDeltaEngine("NSE:RELIANCE")
        assert engine.cumulative_delta == 0.0

    def test_cumulative_delta_increments(self):
        """Test cumulative delta increments."""
        engine = CumulativeDeltaEngine("NSE:RELIANCE")
        
        engine.add_delta(100.0)
        assert engine.cumulative_delta == 100.0
        
        engine.add_delta(-50.0)
        assert engine.cumulative_delta == 50.0

    def test_delta_high_water_mark(self):
        """Test tracking high water mark."""
        engine = CumulativeDeltaEngine("NSE:RELIANCE")
        
        engine.add_delta(100.0)
        engine.add_delta(200.0)
        engine.add_delta(-150.0)
        
        assert engine.high_water_mark == 300.0  # 100 + 200

    def test_delta_low_water_mark(self):
        """Test tracking low water mark."""
        engine = CumulativeDeltaEngine("NSE:RELIANCE")
        
        engine.add_delta(-100.0)
        engine.add_delta(-200.0)
        engine.add_delta(150.0)
        
        assert engine.low_water_mark == -300.0  # -100 + -200

    def test_delta_divergence(self):
        """Test delta divergence from price."""
        engine = CumulativeDeltaEngine("NSE:RELIANCE")
        
        # Price going up, delta going down
        engine.add_price_point(2500.0, 100.0)
        engine.add_price_point(2510.0, -50.0)
        
        assert len(engine.price_history) == 2

    def test_session_delta(self):
        """Test session delta tracking."""
        engine = CumulativeDeltaEngine("NSE:RELIANCE")
        
        engine.add_delta(100.0)
        engine.add_delta(200.0)
        
        assert engine.session_delta == 300.0


class TestFootprintAggregator:
    """Test footprint aggregation."""

    def test_create_footprint_level(self):
        """Test creating footprint level."""
        level = FootprintLevel(
            price=2500.0,
            bid_volume=100,
            ask_volume=150,
            delta=50.0,
        )
        assert level.price == 2500.0
        assert level.delta == 50.0

    def test_aggregate_trades_to_footprint(self):
        """Test aggregating trades to footprint."""
        agg = FootprintAggregator("NSE:RELIANCE")
        
        agg.add_trade(2500.0, 100, TradeSide.BUY)
        agg.add_trade(2500.0, 50, TradeSide.SELL)
        
        assert agg.get_volume_at_price(2500.0) == 150

    def test_footprint_delta_at_level(self):
        """Test delta calculation at price level."""
        agg = FootprintAggregator("NSE:RELIANCE")
        
        agg.add_trade(2500.0, 100, TradeSide.BUY)
        agg.add_trade(2500.0, 50, TradeSide.SELL)
        
        assert agg.get_delta_at_price(2500.0) == 50.0  # 100 - 50

    def test_point_of_control(self):
        """Test POC calculation."""
        agg = FootprintAggregator("NSE:RELIANCE")
        
        agg.add_trade(2500.0, 100, TradeSide.BUY)
        agg.add_trade(2501.0, 300, TradeSide.BUY)
        agg.add_trade(2502.0, 150, TradeSide.BUY)
        
        poc = agg.get_point_of_control()
        assert poc == 2501.0  # Highest volume

    def test_build_footprint_candle(self):
        """Test building footprint candle."""
        agg = FootprintAggregator("NSE:RELIANCE")
        
        agg.add_trade(2500.0, 100, TradeSide.BUY)
        agg.add_trade(2501.0, 150, TradeSide.SELL)
        
        candle = agg.build_candle()
        
        assert isinstance(candle, FootprintCandle)
        assert candle.level_count == 2

    def test_imbalance_ratio_at_level(self):
        """Test imbalance ratio calculation."""
        agg = FootprintAggregator("NSE:RELIANCE")
        
        agg.add_trade(2500.0, 300, TradeSide.BUY)
        agg.add_trade(2500.0, 100, TradeSide.SELL)
        
        ratio = agg.get_imbalance_ratio(2500.0)
        # (300 - 100) / (300 + 100) = 0.5
        assert abs(ratio - 0.5) < 0.01


class TestImbalanceDetector:
    """Test imbalance detection."""

    def test_detect_imbalance(self):
        """Test detecting volume imbalance."""
        detector = ImbalanceDetector(threshold=3.0)
        
        imbalance = detector.check_imbalance(bid_volume=300, ask_volume=100)
        
        assert imbalance is True  # 300/100 = 3.0 >= threshold

    def test_no_imbalance(self):
        """Test no imbalance when ratio below threshold."""
        detector = ImbalanceDetector(threshold=3.0)
        
        imbalance = detector.check_imbalance(bid_volume=200, ask_volume=100)
        
        assert imbalance is False  # 200/100 = 2.0 < threshold

    def test_stacked_imbalance(self):
        """Test detecting stacked imbalances."""
        detector = ImbalanceDetector(threshold=3.0, stacked_consecutive=3)
        
        # Add 3 consecutive imbalances
        detector.record_imbalance(True)
        detector.record_imbalance(True)
        is_stacked = detector.record_imbalance(True)
        
        assert is_stacked is True

    def test_consecutive_count(self):
        """Test consecutive imbalance counting."""
        detector = ImbalanceDetector()
        
        detector.record_imbalance(True)
        detector.record_imbalance(True)
        detector.record_imbalance(False)
        detector.record_imbalance(True)
        
        assert detector.consecutive_count == 1  # Reset after False

    def test_imbalance_ratio_calculation(self):
        """Test imbalance ratio calculation."""
        detector = ImbalanceDetector()
        
        ratio = detector.calculate_ratio(bid_volume=300, ask_volume=100)
        assert abs(ratio - 3.0) < 0.01


class TestAuctionAnalyzer:
    """Test auction analysis."""

    def test_detect_unfinished_auction(self):
        """Test detecting unfinished auction."""
        analyzer = AuctionAnalyzer()
        
        # High volume at extreme with no rejection
        event = analyzer.check_auction(
            price=2510.0,
            volume=500,
            is_high=True,
            rejection_wick=0.0,
        )
        
        assert event.is_unfinished_auction is True

    def test_detect_rejection(self):
        """Test detecting auction rejection."""
        analyzer = AuctionAnalyzer()
        
        event = analyzer.check_auction(
            price=2510.0,
            volume=500,
            is_high=True,
            rejection_wick=50.0,
        )
        
        assert event.rejection_wick == 50.0

    def test_absorption_detection(self):
        """Test detecting absorption."""
        analyzer = AuctionAnalyzer()
        
        # Large volume with minimal price movement
        event = analyzer.check_auction(
            price=2500.0,
            volume=1000,
            is_high=False,
            rejection_wick=5.0,
            price_movement=1.0,
        )
        
        assert event.absorption_volume == 1000

    def test_auction_completion_ratio(self):
        """Test auction completion ratio."""
        analyzer = AuctionAnalyzer()
        
        event = analyzer.check_auction(
            price=2500.0,
            volume=500,
            is_high=False,
            rejection_wick=0.0,
            price_movement=10.0,
        )
        
        assert 0.0 <= event.completion_ratio <= 1.0
