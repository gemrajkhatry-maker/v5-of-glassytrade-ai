"""Tests for VWAP (Volume-Weighted Average Price) Analytics."""
import pytest
from datetime import datetime, timezone, timedelta

from brokersv2.analytics.vwap import (
    VWAPResult,
    AnchoredVWAP,
    RollingVWAP,
    VWAPBands,
    ExecutionQuality,
    calculate_session_vwap,
    calculate_anchored_vwap,
    calculate_rolling_vwap,
    calculate_vwap_bands,
    calculate_execution_quality,
)


class TestSessionVWAP:
    """Tests for session VWAP calculation."""

    @pytest.fixture
    def sample_trades(self) -> list[dict]:
        return [
            {"timestamp": datetime(2025, 1, 15, 9, 15, 0, tzinfo=timezone.utc), "price": 100.0, "volume": 100},
            {"timestamp": datetime(2025, 1, 15, 9, 30, 0, tzinfo=timezone.utc), "price": 101.0, "volume": 150},
            {"timestamp": datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc), "price": 102.0, "volume": 200},
            {"timestamp": datetime(2025, 1, 15, 10, 30, 0, tzinfo=timezone.utc), "price": 101.5, "volume": 120},
            {"timestamp": datetime(2025, 1, 15, 11, 0, 0, tzinfo=timezone.utc), "price": 103.0, "volume": 180},
        ]

    def test_session_vwap_calculation(self, sample_trades: list[dict]) -> None:
        """Calculate session VWAP correctly."""
        vwap = calculate_session_vwap("NIFTY", sample_trades)
        
        # VWAP = sum(price * volume) / sum(volume)
        expected_vwap = (
            (100.0 * 100) + (101.0 * 150) + (102.0 * 200) + (101.5 * 120) + (103.0 * 180)
        ) / (100 + 150 + 200 + 120 + 180)
        
        assert abs(vwap.vwap - expected_vwap) < 0.01
        assert vwap.total_volume == 750
        assert vwap.total_trades == 5

    def test_session_vwap_is_immutable(self, sample_trades: list[dict]) -> None:
        """SessionVWAP is frozen."""
        vwap = calculate_session_vwap("NIFTY", sample_trades)
        with pytest.raises(Exception):
            vwap.vwap = 105.0

    def test_session_vwap_has_required_fields(self, sample_trades: list[dict]) -> None:
        """SessionVWAP has all required fields."""
        vwap = calculate_session_vwap("NIFTY", sample_trades)
        assert hasattr(vwap, 'symbol')
        assert hasattr(vwap, 'vwap')
        assert hasattr(vwap, 'total_volume')
        assert hasattr(vwap, 'total_trades')
        assert hasattr(vwap, 'start_time')
        assert hasattr(vwap, 'end_time')

    def test_session_vwap_price_range(self, sample_trades: list[dict]) -> None:
        """VWAP should be within price range."""
        vwap = calculate_session_vwap("NIFTY", sample_trades)
        prices = [t["price"] for t in sample_trades]
        assert min(prices) <= vwap.vwap <= max(prices)

    def test_session_vwap_empty_trades(self) -> None:
        """Empty trades list returns zero VWAP."""
        vwap = calculate_session_vwap("NIFTY", [])
        assert vwap.vwap == 0.0
        assert vwap.total_volume == 0
        assert vwap.total_trades == 0


class TestAnchoredVWAP:
    """Tests for anchored VWAP calculation."""

    @pytest.fixture
    def sample_trades(self) -> list[dict]:
        base_time = datetime(2025, 1, 15, 9, 15, 0, tzinfo=timezone.utc)
        return [
            {"timestamp": base_time + timedelta(minutes=i*15), "price": 100.0 + i, "volume": 100 + i*10}
            for i in range(20)
        ]

    def test_anchored_vwap_from_start(self, sample_trades: list[dict]) -> None:
        """Calculate anchored VWAP from start point."""
        anchor_time = sample_trades[0]["timestamp"]
        vwap = calculate_anchored_vwap("NIFTY", sample_trades, anchor_time)
        
        assert vwap.vwap > 0
        assert vwap.anchor_time == anchor_time
        assert vwap.periods_since_anchor == 20

    def test_anchored_vwap_from_middle(self, sample_trades: list[dict]) -> None:
        """Calculate anchored VWAP from middle point."""
        anchor_time = sample_trades[10]["timestamp"]
        vwap = calculate_anchored_vwap("NIFTY", sample_trades, anchor_time)
        
        assert vwap.vwap > 0
        assert vwap.periods_since_anchor == 10  # Only last 10 trades

    def test_anchored_vwap_is_immutable(self, sample_trades: list[dict]) -> None:
        """AnchoredVWAP is frozen."""
        anchor_time = sample_trades[0]["timestamp"]
        vwap = calculate_anchored_vwap("NIFTY", sample_trades, anchor_time)
        with pytest.raises(Exception):
            vwap.vwap = 105.0

    def test_anchored_vwap_current_price(self, sample_trades: list[dict]) -> None:
        """Anchored VWAP includes current price."""
        anchor_time = sample_trades[0]["timestamp"]
        vwap = calculate_anchored_vwap("NIFTY", sample_trades, anchor_time)
        
        current_price = sample_trades[-1]["price"]
        assert vwap.current_price == current_price

    def test_anchored_vwap_distance_from_vwap(self, sample_trades: list[dict]) -> None:
        """Calculate distance from VWAP as percentage."""
        anchor_time = sample_trades[0]["timestamp"]
        vwap = calculate_anchored_vwap("NIFTY", sample_trades, anchor_time)
        
        assert vwap.distance_from_vwap_pct is not None
        # Distance should be calculable
        assert isinstance(vwap.distance_from_vwap_pct, float)


class TestRollingVWAP:
    """Tests for rolling VWAP calculation."""

    @pytest.fixture
    def sample_trades(self) -> list[dict]:
        base_time = datetime(2025, 1, 15, 9, 15, 0, tzinfo=timezone.utc)
        return [
            {"timestamp": base_time + timedelta(minutes=i*5), "price": 100.0 + (i % 5), "volume": 100}
            for i in range(50)
        ]

    def test_rolling_vwap_calculation(self, sample_trades: list[dict]) -> None:
        """Calculate rolling VWAP with window."""
        rolling = calculate_rolling_vwap("NIFTY", sample_trades, window_periods=10)
        
        assert len(rolling.values) > 0
        assert rolling.window_periods == 10

    def test_rolling_vwap_is_immutable(self, sample_trades: list[dict]) -> None:
        """RollingVWAP is frozen."""
        rolling = calculate_rolling_vwap("NIFTY", sample_trades, window_periods=10)
        with pytest.raises(Exception):
            rolling.window_periods = 20

    def test_rolling_vwap_latest_value(self, sample_trades: list[dict]) -> None:
        """Get latest rolling VWAP value."""
        rolling = calculate_rolling_vwap("NIFTY", sample_trades, window_periods=10)
        
        assert rolling.latest_vwap is not None
        assert rolling.latest_vwap > 0

    def test_rolling_vwap_respects_window(self, sample_trades: list[dict]) -> None:
        """Rolling VWAP only uses window_periods."""
        rolling = calculate_rolling_vwap("NIFTY", sample_trades, window_periods=5)
        
        # Should have fewer values than total trades
        assert len(rolling.values) <= len(sample_trades)


class TestVWAPBands:
    """Tests for VWAP bands calculation."""

    @pytest.fixture
    def sample_trades(self) -> list[dict]:
        base_time = datetime(2025, 1, 15, 9, 15, 0, tzinfo=timezone.utc)
        return [
            {"timestamp": base_time + timedelta(minutes=i*5), "price": 100.0 + (i % 10) - 5, "volume": 100}
            for i in range(30)
        ]

    def test_vwap_bands_calculation(self, sample_trades: list[dict]) -> None:
        """Calculate VWAP bands with standard deviations."""
        bands = calculate_vwap_bands("NIFTY", sample_trades, num_std=2.0)
        
        assert bands.upper_band > bands.vwap
        assert bands.lower_band < bands.vwap
        assert bands.std_dev > 0

    def test_vwap_bands_is_immutable(self, sample_trades: list[dict]) -> None:
        """VWAPBands is frozen."""
        bands = calculate_vwap_bands("NIFTY", sample_trades, num_std=2.0)
        with pytest.raises(Exception):
            bands.upper_band = 105.0

    def test_vwap_bands_width(self, sample_trades: list[dict]) -> None:
        """Calculate bands width."""
        bands = calculate_vwap_bands("NIFTY", sample_trades, num_std=2.0)
        
        assert bands.band_width > 0
        assert bands.band_width == bands.upper_band - bands.lower_band

    def test_vwap_bands_percentage(self, sample_trades: list[dict]) -> None:
        """Calculate bands width as percentage."""
        bands = calculate_vwap_bands("NIFTY", sample_trades, num_std=2.0)
        
        assert bands.band_width_pct > 0

    def test_vwap_bands_price_position(self, sample_trades: list[dict]) -> None:
        """Determine price position relative to bands."""
        bands = calculate_vwap_bands("NIFTY", sample_trades, num_std=2.0)
        
        # Price position should be calculable
        assert bands.current_price > 0
        assert bands.position is not None


class TestExecutionQuality:
    """Tests for execution quality metrics."""

    @pytest.fixture
    def sample_trades(self) -> list[dict]:
        return [
            {"timestamp": datetime(2025, 1, 15, 9, 15, 0, tzinfo=timezone.utc), "price": 100.0, "volume": 100},
            {"timestamp": datetime(2025, 1, 15, 9, 30, 0, tzinfo=timezone.utc), "price": 100.5, "volume": 150},
            {"timestamp": datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone.utc), "price": 101.0, "volume": 200},
        ]

    def test_execution_quality_buy(self, sample_trades: list[dict]) -> None:
        """Calculate execution quality for buy orders."""
        avg_fill_price = 100.5
        quality = calculate_execution_quality(
            trades=sample_trades,
            side="BUY",
            avg_fill_price=avg_fill_price,
        )
        
        assert quality.side == "BUY"
        assert quality.avg_fill_price == avg_fill_price
        assert quality.slippage is not None
        assert quality.slippage_bps is not None

    def test_execution_quality_sell(self, sample_trades: list[dict]) -> None:
        """Calculate execution quality for sell orders."""
        avg_fill_price = 100.5
        quality = calculate_execution_quality(
            trades=sample_trades,
            side="SELL",
            avg_fill_price=avg_fill_price,
        )
        
        assert quality.side == "SELL"

    def test_execution_quality_is_immutable(self, sample_trades: list[dict]) -> None:
        """ExecutionQuality is frozen."""
        quality = calculate_execution_quality(
            trades=sample_trades,
            side="BUY",
            avg_fill_price=100.5,
        )
        with pytest.raises(Exception):
            quality.slippage = 0.5

    def test_execution_quality_positive_slippage_buy(self, sample_trades: list[dict]) -> None:
        """Positive slippage for buys means worse execution."""
        # Fill price higher than VWAP = bad for buy
        vwap = calculate_session_vwap("NIFTY", sample_trades)
        quality = calculate_execution_quality(
            trades=sample_trades,
            side="BUY",
            avg_fill_price=vwap.vwap + 0.5,
        )
        
        assert quality.slippage > 0  # Paid more than VWAP

    def test_execution_quality_negative_slippage_buy(self, sample_trades: list[dict]) -> None:
        """Negative slippage for buys means better execution."""
        # Fill price lower than VWAP = good for buy
        vwap = calculate_session_vwap("NIFTY", sample_trades)
        quality = calculate_execution_quality(
            trades=sample_trades,
            side="BUY",
            avg_fill_price=vwap.vwap - 0.5,
        )
        
        assert quality.slippage < 0  # Paid less than VWAP

    def test_execution_quality_has_required_fields(self, sample_trades: list[dict]) -> None:
        """ExecutionQuality has all required fields."""
        quality = calculate_execution_quality(
            trades=sample_trades,
            side="BUY",
            avg_fill_price=100.5,
        )
        
        assert hasattr(quality, 'side')
        assert hasattr(quality, 'avg_fill_price')
        assert hasattr(quality, 'benchmark_vwap')
        assert hasattr(quality, 'slippage')
        assert hasattr(quality, 'slippage_bps')
        assert hasattr(quality, 'implementation_shortfall')
