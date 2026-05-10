"""Tests for Order Book Sweep Detection."""
from datetime import datetime, timezone
from typing import List

import pytest

from brokersv2.analytics.order_book.events import PriceLevel
from brokersv2.analytics.order_book.sweep_detection import (
    SweepEvent,
    SweepDetector,
    SweepDirection,
)


class TestSweepEvent:
    """Tests for SweepEvent immutability and fields."""

    @pytest.fixture
    def sweep_event(self) -> SweepEvent:
        return SweepEvent(
            timestamp=datetime.now(timezone.utc),
            symbol="NIFTY",
            direction=SweepDirection.BID,
            levels_consumed=3,
            total_volume_swept=450,
            price_impact=2.5,
            start_price=18100.0,
            end_price=18097.5,
        )

    def test_immutability(self, sweep_event: SweepEvent) -> None:
        """SweepEvent is frozen and cannot be modified."""
        with pytest.raises(Exception):
            sweep_event.levels_consumed = 5

    def test_has_required_fields(self, sweep_event: SweepEvent) -> None:
        """SweepEvent has all required fields."""
        assert sweep_event.timestamp is not None
        assert sweep_event.symbol == "NIFTY"
        assert sweep_event.direction == SweepDirection.BID
        assert sweep_event.levels_consumed == 3
        assert sweep_event.total_volume_swept == 450
        assert sweep_event.price_impact == 2.5

    def test_price_impact_calculation(self, sweep_event: SweepEvent) -> None:
        """Price impact is calculated correctly."""
        assert sweep_event.price_impact == 2.5

    def test_is_bid_sweep(self, sweep_event: SweepEvent) -> None:
        """Detect bid sweep."""
        assert sweep_event.is_bid_sweep is True
        assert sweep_event.is_ask_sweep is False

    def test_is_ask_sweep(self) -> None:
        """Detect ask sweep."""
        event = SweepEvent(
            timestamp=datetime.now(timezone.utc),
            symbol="NIFTY",
            direction=SweepDirection.ASK,
            levels_consumed=2,
            total_volume_swept=300,
            price_impact=1.5,
            start_price=18100.0,
            end_price=18101.5,
        )
        assert event.is_ask_sweep is True
        assert event.is_bid_sweep is False


class TestSweepDetector:
    """Tests for sweep detection logic."""

    @pytest.fixture
    def detector(self) -> SweepDetector:
        return SweepDetector(min_levels=2, min_volume=100)

    def _create_bids(self, levels: List[tuple]) -> List[PriceLevel]:
        """Helper to create bid levels."""
        return [PriceLevel(price=p, quantity=q, order_count=1) for p, q in levels]

    def _create_asks(self, levels: List[tuple]) -> List[PriceLevel]:
        """Helper to create ask levels."""
        return [PriceLevel(price=p, quantity=q, order_count=1) for p, q in levels]

    def test_no_sweep_when_single_level_consumed(self, detector: SweepDetector) -> None:
        """No sweep detected when only 1 level consumed (below threshold)."""
        before_bids = self._create_bids([
            (18100, 100),
            (18099, 150),
            (18098, 200),
        ])
        after_bids = self._create_bids([
            (18100, 0),  # Only this level consumed
            (18099, 150),
            (18098, 200),
        ])
        asks = self._create_asks([(18101, 100)])

        result = detector.detect_bid_sweep(before_bids, after_bids, asks)
        assert result is None

    def test_sweep_when_multiple_levels_consumed(self, detector: SweepDetector) -> None:
        """Sweep detected when multiple levels consumed."""
        before_bids = self._create_bids([
            (18100, 100),
            (18099, 150),
            (18098, 200),
        ])
        after_bids = self._create_bids([
            (18100, 0),  # Consumed
            (18099, 0),  # Consumed
            (18098, 200),
        ])
        asks = self._create_asks([(18101, 100)])

        result = detector.detect_bid_sweep(before_bids, after_bids, asks)
        assert result is not None
        assert result.levels_consumed == 2
        assert result.total_volume_swept == 250  # 100 + 150
        assert result.is_bid_sweep is True

    def test_sweep_volume_threshold(self) -> None:
        """No sweep when volume below threshold."""
        detector = SweepDetector(min_levels=2, min_volume=500)

        before_bids = self._create_bids([
            (18100, 50),
            (18099, 60),
            (18098, 200),
        ])
        after_bids = self._create_bids([
            (18100, 0),
            (18099, 0),
            (18098, 200),
        ])
        asks = self._create_asks([(18101, 100)])

        result = detector.detect_bid_sweep(before_bids, after_bids, asks)
        assert result is None  # Only 110 volume, below 500 threshold

    def test_ask_sweep_detection(self, detector: SweepDetector) -> None:
        """Detect ask side sweep."""
        before_asks = self._create_asks([
            (18101, 100),
            (18102, 150),
            (18103, 200),
        ])
        after_asks = self._create_asks([
            (18101, 0),  # Consumed
            (18102, 0),  # Consumed
            (18103, 200),
        ])
        bids = self._create_bids([(18100, 100)])

        result = detector.detect_ask_sweep(bids, before_asks, after_asks)
        assert result is not None
        assert result.is_ask_sweep is True
        assert result.levels_consumed == 2
        assert result.total_volume_swept == 250

    def test_sweep_price_impact_bid(self, detector: SweepDetector) -> None:
        """Calculate price impact for bid sweep."""
        before_bids = self._create_bids([
            (18100, 100),
            (18099, 150),
            (18098, 200),
        ])
        after_bids = self._create_bids([
            (18100, 0),
            (18099, 0),
            (18098, 0),
        ])
        asks = self._create_asks([(18101, 100)])

        result = detector.detect_bid_sweep(before_bids, after_bids, asks)
        assert result is not None
        assert result.start_price == 18100.0
        assert result.end_price == 18098.0
        assert result.price_impact == 2.0  # 18100 - 18098

    def test_sweep_price_impact_ask(self, detector: SweepDetector) -> None:
        """Calculate price impact for ask sweep."""
        before_asks = self._create_asks([
            (18101, 100),
            (18102, 150),
            (18103, 200),
        ])
        after_asks = self._create_asks([
            (18101, 0),
            (18102, 0),
            (18103, 0),
        ])
        bids = self._create_bids([(18100, 100)])

        result = detector.detect_ask_sweep(bids, before_asks, after_asks)
        assert result is not None
        assert result.start_price == 18101.0
        assert result.end_price == 18103.0
        assert result.price_impact == 2.0  # 18103 - 18101

    def test_partial_consumption_no_sweep(self, detector: SweepDetector) -> None:
        """No sweep when levels partially consumed."""
        before_bids = self._create_bids([
            (18100, 100),
            (18099, 150),
            (18098, 200),
        ])
        after_bids = self._create_bids([
            (18100, 50),  # Partial, not fully consumed
            (18099, 75),  # Partial
            (18098, 200),
        ])
        asks = self._create_asks([(18101, 100)])

        result = detector.detect_bid_sweep(before_bids, after_bids, asks)
        assert result is None

    def test_empty_book_no_sweep(self, detector: SweepDetector) -> None:
        """No sweep with empty order book."""
        result = detector.detect_bid_sweep([], [], [])
        assert result is None

    def test_sweep_event_fields_complete(self, detector: SweepDetector) -> None:
        """Sweep event has all calculated fields."""
        before_bids = self._create_bids([
            (18100, 100),
            (18099, 150),
            (18098, 200),
            (18097, 250),
        ])
        after_bids = self._create_bids([
            (18100, 0),
            (18099, 0),
            (18098, 0),
            (18097, 250),
        ])
        asks = self._create_asks([(18101, 100)])

        result = detector.detect_bid_sweep(before_bids, after_bids, asks)
        assert result is not None
        assert result.symbol == ""  # Default, can be set via detector
        assert result.levels_consumed == 3
        assert result.total_volume_swept == 450  # 100 + 150 + 200
        assert result.price_impact == 2.0  # 18100 - 18098
