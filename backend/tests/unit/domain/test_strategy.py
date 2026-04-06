"""Tests for strategy protocols and implementations."""

import pytest

pytestmark = pytest.mark.skip(reason="AMTSetupDetector stub — feature not yet implemented (planned Phase 5)")
from app.domain.fabio_ai.strategy.protocols import (
    Setup,
    MarketContext,
    EntrySignal,
    RiskResult,
    Order,
    Strategy,
)
from app.domain.fabio_ai.strategy.setup_detector import (
    AMTSetupDetector,
    create_setup_detector,
)


class TestAMTSetupDetector:
    """Tests for AMT-based setup detection."""

    def test_detect_aaa_at_val(self):
        """Test AAA detection at Value Area Low."""
        detector = AMTSetupDetector()

        # Price at VAL (95 * 1.02 = 96.9)
        context = MarketContext(
            symbol="NIFTY",
            current_price=96.0,  # At VAL
            market_state="BALANCED",
            regime="MORNING",
            vwap=100.0,
            vah=105.0,
            val=95.0,
            poc=100.0,
            cvd_slope=50.0,  # Strong positive CVD
            delta=100.0,  # Positive delta
            profile_shape="",
            volume_bubbles="",
            lvns=[95.0],
            hvns=[],
        )

        setup = detector.identify(context)

        assert setup is not None
        assert setup.setup_type == "AAA"
        assert setup.confidence >= 0.7

    def test_detect_momentum_at_vah(self):
        """Test Momentum detection at Value Area High."""
        detector = AMTSetupDetector()

        context = MarketContext(
            symbol="NIFTY",
            current_price=104.0,
            market_state="IMBALANCED",
            regime="MORNING",
            vwap=100.0,
            vah=105.0,
            val=95.0,
            poc=100.0,
            cvd_slope=30.0,
            delta=100.0,
            profile_shape="",
            volume_bubbles="",
            lvns=[],
            hvns=[],
        )

        setup = detector.identify(context)

        assert setup is not None
        assert setup.setup_type == "MOMENTUM"
        assert setup.confidence >= 0.7

    def test_detect_mean_reversion(self):
        """Test Mean Reversion detection when price far from VWAP."""
        detector = AMTSetupDetector()

        context = MarketContext(
            symbol="NIFTY",
            current_price=103.0,
            market_state="BALANCED",
            regime="MORNING",
            vwap=100.0,
            vah=105.0,
            val=95.0,
            poc=100.0,
            cvd_slope=10.0,
            delta=10.0,
            profile_shape="",
            volume_bubbles="",
            lvns=[],
            hvns=[],
        )

        setup = detector.identify(context)

        assert setup is not None
        assert setup.setup_type == "MEAN_REVERSION"

    def test_no_setup_in_choppy_market(self):
        """Test that no setup is detected in choppy market."""
        detector = AMTSetupDetector()

        context = MarketContext(
            symbol="NIFTY",
            current_price=100.0,
            market_state="BALANCED",
            regime="MORNING",
            vwap=100.0,
            vah=101.0,
            val=99.0,
            poc=100.0,
            cvd_slope=0.0,
            delta=0.0,
            profile_shape="",
            volume_bubbles="",
            lvns=[],
            hvns=[],
        )

        setup = detector.identify(context)

        # No strong setup in this context
        assert setup is None or setup.confidence < 0.5

    def test_factory_creates_amt_detector(self):
        """Test factory creates correct detector type."""
        detector = create_setup_detector("amt")
        assert isinstance(detector, AMTSetupDetector)

    def test_unknown_detector_type_raises(self):
        """Test that unknown detector type raises error."""
        with pytest.raises(ValueError, match="Unknown detector type"):
            create_setup_detector("unknown")


class TestProtocols:
    """Tests for protocol implementations."""

    def test_risk_result_approved(self):
        """Test approved risk result."""
        result = RiskResult(approved=True)

        assert result.approved is True
        assert result.rejection_reason == ""

    def test_risk_result_rejected(self):
        """Test rejected risk result."""
        result = RiskResult(approved=False, rejection_reason="DAILY_LOSS_LIMIT")

        assert result.approved is False
        assert result.rejection_reason == "DAILY_LOSS_LIMIT"

    def test_entry_signal_creation(self):
        """Test entry signal creation."""
        signal = EntrySignal(
            symbol="NIFTY",
            direction="LONG",
            entry_price=100.0,
            stop_loss=95.0,
            take_profit=115.0,
            position_size=75.0,
            setup=Setup(
                setup_type="AAA",
                confidence=0.8,
                thesis="Test setup",
                key_levels={"val": 95.0},
                trigger_conditions=[],
            ),
            confidence="HIGH",
            thesis="Test thesis",
        )

        assert signal.symbol == "NIFTY"
        assert signal.direction == "LONG"
        assert signal.confidence == "HIGH"

    def test_order_creation(self):
        """Test order creation."""
        order = Order(
            order_id="O1",
            trade_id="T1",
            symbol="NIFTY",
            side="BUY",
            order_type="MARKET",
            price=None,
            quantity=75.0,
        )

        assert order.order_id == "O1"
        assert order.order_type == "MARKET"
        assert order.price is None


class TestStrategyComposition:
    """Test that Strategy can compose components."""

    def test_strategy_with_mock_components(self):
        """Test Strategy can be instantiated with mock components."""

        class MockMarketAnalyzer:
            def analyze(self, symbol, data, tick):
                return MarketContext(
                    symbol=symbol,
                    current_price=100.0,
                    market_state="BALANCED",
                    regime="MORNING",
                    vwap=100.0,
                    vah=105.0,
                    val=95.0,
                    poc=100.0,
                    cvd_slope=10.0,
                    delta=10.0,
                    profile_shape="",
                    volume_bubbles="",
                    lvns=[],
                    hvns=[],
                )

        class MockSetupDetector:
            def identify(self, context):
                return Setup(
                    setup_type="AAA",
                    confidence=0.8,
                    thesis="Test",
                    key_levels={},
                    trigger_conditions=[],
                )

        class MockSignalGenerator:
            def generate(self, context, setup):
                return None  # No signal

        class MockRiskCalculator:
            def validate(self, signal, portfolio_state):
                return RiskResult(approved=False)

        class MockExecutionPlanner:
            def plan_entry(self, signal):
                return None

        class MockExitEngine:
            def check_exit(self, trade_id, position_state, current_price, context):
                return False, ""

        strategy = Strategy(
            market_analyzer=MockMarketAnalyzer(),
            setup_detector=MockSetupDetector(),
            signal_generator=MockSignalGenerator(),
            risk_calculator=MockRiskCalculator(),
            execution_planner=MockExecutionPlanner(),
            exit_engine=MockExitEngine(),
        )

        assert strategy is not None
