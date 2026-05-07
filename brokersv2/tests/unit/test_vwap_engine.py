"""Tests for real-time VWAP calculation engine."""
import pytest
from datetime import datetime, timezone, timedelta
from decimal import Decimal
from brokersv2.domain.market.events import TickEvent
from brokersv2.marketdata.vwap_engine import (
    VWAPCalculator,
    VWAPSession,
    VWAPResult,
    VWAPError,
    VWAPTimeframe,
    AnchoredVWAP,
)


@pytest.fixture
def now():
    return datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


@pytest.fixture
def sample_ticks(now):
    """Create sample tick events for VWAP calculation."""
    return [
        TickEvent(
            timestamp=now,
            security_id="NSE_EQ_SYMBOL1",
            symbol="RELIANCE",
            exchange="NSE",
            ltp=Decimal("100.00"),
            open=Decimal("99.50"),
            high=Decimal("101.00"),
            low=Decimal("99.00"),
            close=Decimal("99.50"),
            volume=1000,
            oi=5000,
        ),
        TickEvent(
            timestamp=now + timedelta(minutes=1),
            security_id="NSE_EQ_SYMBOL1",
            symbol="RELIANCE",
            exchange="NSE",
            ltp=Decimal("101.00"),
            open=Decimal("100.00"),
            high=Decimal("101.50"),
            low=Decimal("99.50"),
            close=Decimal("100.00"),
            volume=1500,
            oi=5200,
        ),
        TickEvent(
            timestamp=now + timedelta(minutes=2),
            security_id="NSE_EQ_SYMBOL1",
            symbol="RELIANCE",
            exchange="NSE",
            ltp=Decimal("100.50"),
            open=Decimal("101.00"),
            high=Decimal("101.00"),
            low=Decimal("100.00"),
            close=Decimal("101.00"),
            volume=800,
            oi=5100,
        ),
    ]


class TestVWAPResult:
    """Test VWAP result value object."""

    def test_basic_vwap(self, now):
        """Test basic VWAP result creation."""
        result = VWAPResult(
            security_id="TEST",
            symbol="TEST",
            timestamp=now,
            vwap=Decimal("100.50"),
            cumulative_volume=10000,
            cumulative_turnover=Decimal("1005000.00"),
        )

        assert result.security_id == "TEST"
        assert result.vwap == Decimal("100.50")
        assert result.cumulative_volume == 10000
        assert result.cumulative_turnover == Decimal("1005000.00")

    def test_vwap_deviation(self, now):
        """Test VWAP deviation calculation."""
        result = VWAPResult(
            security_id="TEST",
            symbol="TEST",
            timestamp=now,
            vwap=Decimal("100.00"),
            cumulative_volume=10000,
            cumulative_turnover=Decimal("1000000.00"),
            current_price=Decimal("101.00"),
        )

        # Deviation: (101.00 - 100.00) / 100.00 = 1.0%
        assert result.vwap_deviation_pct == pytest.approx(1.0, abs=0.01)

    def test_vwap_deviation_below(self, now):
        """Test VWAP deviation when price is below VWAP."""
        result = VWAPResult(
            security_id="TEST",
            symbol="TEST",
            timestamp=now,
            vwap=Decimal("100.00"),
            cumulative_volume=10000,
            cumulative_turnover=Decimal("1000000.00"),
            current_price=Decimal("98.00"),
        )

        # Deviation: (98.00 - 100.00) / 100.00 = -2.0%
        assert result.vwap_deviation_pct == pytest.approx(-2.0, abs=0.01)


class TestVWAPCalculator:
    """Test real-time VWAP calculation."""

    def test_single_tick_vwap(self, now):
        """Test VWAP with single tick."""
        calc = VWAPCalculator(security_id="TEST")
        tick = TickEvent(
            timestamp=now,
            security_id="TEST",
            symbol="TEST",
            exchange="NSE",
            ltp=Decimal("100.00"),
            open=Decimal("99.50"),
            high=Decimal("100.50"),
            low=Decimal("99.00"),
            close=Decimal("99.50"),
            volume=1000,
            oi=0,
        )

        result = calc.process_tick(tick)

        assert result is not None
        # VWAP = typical price = (100.50 + 99.00 + 99.50) / 3 = 99.667
        assert result.vwap == pytest.approx(Decimal("99.667"), abs=Decimal("0.1"))
        assert result.cumulative_volume == 1000

    def test_multiple_ticks_vwap(self, sample_ticks):
        """Test VWAP with multiple ticks."""
        calc = VWAPCalculator(security_id="NSE_EQ_SYMBOL1")

        results = []
        for tick in sample_ticks:
            result = calc.process_tick(tick)
            results.append(result)

        # Check cumulative volume
        final_result = results[-1]
        assert final_result.cumulative_volume == 3300  # 1000+1500+800

        # VWAP = sum(typical_price * volume) / sum(volume)
        # Typical price ≈ (high + low + close) / 3
        # Tick 1: (101.00 + 99.00 + 99.50) / 3 = 99.833, vol=1000
        # Tick 2: (101.50 + 99.50 + 100.00) / 3 = 100.333, vol=1500
        # Tick 3: (101.00 + 100.00 + 101.00) / 3 = 100.667, vol=800
        # VWAP = (99.833*1000 + 100.333*1500 + 100.667*800) / 3300
        #      = (99833 + 150500 + 80534) / 3300
        #      = 330867 / 3300 ≈ 100.263
        assert final_result.vwap == pytest.approx(Decimal("100.263"), abs=Decimal("0.1"))

    def test_wrong_security_rejected(self, now):
        """Test that ticks with wrong security_id are rejected."""
        calc = VWAPCalculator(security_id="TEST1")
        tick = TickEvent(
            timestamp=now,
            security_id="TEST2",  # Wrong!
            symbol="OTHER",
            exchange="NSE",
            ltp=Decimal("100.00"),
            open=Decimal("99.50"),
            high=Decimal("100.50"),
            low=Decimal("99.00"),
            close=Decimal("99.50"),
            volume=1000,
            oi=0,
        )

        with pytest.raises(VWAPError, match="security_id mismatch"):
            calc.process_tick(tick)

    def test_vwap_reset(self, sample_ticks):
        """Test VWAP session reset."""
        calc = VWAPCalculator(security_id="NSE_EQ_SYMBOL1")

        for tick in sample_ticks:
            calc.process_tick(tick)

        assert calc.current_volume > 0

        calc.reset()

        assert calc.current_volume == 0
        assert calc.current_turnover == Decimal("0")

    def test_get_current_vwap(self, sample_ticks):
        """Test retrieving current VWAP without new tick."""
        calc = VWAPCalculator(security_id="NSE_EQ_SYMBOL1")

        for tick in sample_ticks:
            calc.process_tick(tick)

        result = calc.get_current_vwap()

        assert result is not None
        assert result.vwap is not None
        assert result.cumulative_volume == 3300

    def test_get_vwap_no_data(self):
        """Test VWAP when no data processed yet."""
        calc = VWAPCalculator(security_id="TEST")

        result = calc.get_current_vwap()

        assert result is None

    def test_vwap_with_zero_volume(self, now):
        """Test VWAP handling of zero volume tick."""
        calc = VWAPCalculator(security_id="TEST")
        tick = TickEvent(
            timestamp=now,
            security_id="TEST",
            symbol="TEST",
            exchange="NSE",
            ltp=Decimal("100.00"),
            open=Decimal("99.50"),
            high=Decimal("100.50"),
            low=Decimal("99.00"),
            close=Decimal("99.50"),
            volume=0,  # Zero volume
            oi=0,
        )

        result = calc.process_tick(tick)

        # Zero volume tick should be processed but not affect VWAP
        assert result is not None
        assert result.cumulative_volume == 0


class TestVWAPSession:
    """Test VWAP session management."""

    def test_session_start_end(self, now, sample_ticks):
        """Test VWAP session with start/end times."""
        session_start = now - timedelta(hours=1)
        session_end = now + timedelta(hours=7)  # Typical trading day

        session = VWAPSession(
            security_id="NSE_EQ_SYMBOL1",
            start_time=session_start,
            end_time=session_end,
        )

        for tick in sample_ticks:
            session.process_tick(tick)

        result = session.get_result()

        assert result is not None
        assert result.cumulative_volume == 3300

    def test_session_expired(self, now):
        """Test VWAP session that has expired."""
        session_start = now - timedelta(hours=2)
        session_end = now - timedelta(hours=1)  # Already ended

        session = VWAPSession(
            security_id="TEST",
            start_time=session_start,
            end_time=session_end,
        )

        assert session.is_expired(now) is True

    def test_session_active(self, now):
        """Test VWAP session that is still active."""
        session_start = now - timedelta(hours=1)
        session_end = now + timedelta(hours=7)

        session = VWAPSession(
            security_id="TEST",
            start_time=session_start,
            end_time=session_end,
        )

        assert session.is_expired(now) is False

    def test_session_auto_reset(self, now):
        """Test session auto-reset at expiry."""
        session_start = now - timedelta(hours=2)
        session_end = now - timedelta(hours=1)

        session = VWAPSession(
            security_id="TEST",
            start_time=session_start,
            end_time=session_end,
            auto_reset=True,
        )

        tick = TickEvent(
            timestamp=now,
            security_id="TEST",
            symbol="TEST",
            exchange="NSE",
            ltp=Decimal("100.00"),
            open=Decimal("99.50"),
            high=Decimal("100.50"),
            low=Decimal("99.00"),
            close=Decimal("99.50"),
            volume=1000,
            oi=0,
        )

        # Should auto-reset and process tick
        result = session.process_tick(tick)
        assert result is not None


class TestAnchoredVWAP:
    """Test anchored VWAP from specific points."""

    def test_anchor_at_price(self, now, sample_ticks):
        """Test anchoring VWAP at specific price level."""
        calc = VWAPCalculator(security_id="NSE_EQ_SYMBOL1")

        for tick in sample_ticks:
            calc.process_tick(tick)

        # Anchor at high volume node
        anchor = AnchoredVWAP.from_calculator(
            calc,
            anchor_price=Decimal("100.00"),
            anchor_time=now,
        )

        assert anchor.anchor_price == Decimal("100.00")
        assert anchor.vwap_at_anchor is not None

    def test_anchor_deviation(self, now, sample_ticks):
        """Test deviation from anchored VWAP."""
        calc = VWAPCalculator(security_id="NSE_EQ_SYMBOL1")

        for tick in sample_ticks:
            calc.process_tick(tick)

        result = calc.get_current_vwap()
        anchor = AnchoredVWAP.from_calculator(
            calc,
            anchor_price=result.vwap,
            anchor_time=now,
        )

        # Current VWAP should equal anchor (no new data)
        deviation = anchor.deviation_from_anchor(result.vwap)
        assert deviation == pytest.approx(0.0, abs=0.01)


class TestVWAPTimeframe:
    """Test VWAP across different timeframes."""

    def test_daily_vwap(self, now, sample_ticks):
        """Test daily VWAP calculation."""
        calc = VWAPCalculator(
            security_id="NSE_EQ_SYMBOL1",
            timeframe=VWAPTimeframe.DAILY,
        )

        for tick in sample_ticks:
            calc.process_tick(tick)

        result = calc.get_current_vwap()
        assert result is not None
        assert result.cumulative_volume == 3300

    def test_session_vwap(self, now, sample_ticks):
        """Test session-based VWAP."""
        calc = VWAPCalculator(
            security_id="NSE_EQ_SYMBOL1",
            timeframe=VWAPTimeframe.SESSION,
            session_start=now - timedelta(hours=1),
        )

        for tick in sample_ticks:
            calc.process_tick(tick)

        result = calc.get_current_vwap()
        assert result is not None

    def test_custom_window_vwap(self, now, sample_ticks):
        """Test custom window VWAP (e.g., last hour)."""
        calc = VWAPCalculator(
            security_id="NSE_EQ_SYMBOL1",
            timeframe=VWAPTimeframe.CUSTOM,
            window_minutes=60,
        )

        for tick in sample_ticks:
            calc.process_tick(tick)

        result = calc.get_current_vwap()
        assert result is not None
        # Should only include ticks within 60-minute window
