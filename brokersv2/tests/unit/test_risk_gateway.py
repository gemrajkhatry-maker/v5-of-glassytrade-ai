"""Tests for Risk Gateway - position limits, exposure checks, and kill switch."""
import pytest
from datetime import datetime, timezone
from decimal import Decimal
from brokersv2.risk.gateway import (
    RiskGateway,
    RiskCheckResult,
    PositionLimit,
    ExposureLimit,
    RiskGatewayError,
    PositionLimitBreached,
    ExposureLimitBreached,
    KillSwitchActive,
)


@pytest.fixture
def now():
    return datetime(2024, 1, 15, 10, 30, 0, tzinfo=timezone.utc)


class TestPositionLimit:
    """Test PositionLimit configuration."""

    def test_create_limit(self):
        """Test creating position limit."""
        limit = PositionLimit(
            symbol="RELIANCE",
            exchange="NSE",
            max_quantity=1000,
            max_notional=Decimal("100000"),
        )

        assert limit.symbol == "RELIANCE"
        assert limit.max_quantity == 1000
        assert limit.max_notional == Decimal("100000")

    def test_global_limit(self):
        """Test global position limit (all symbols)."""
        limit = PositionLimit(
            symbol="*",
            exchange="*",
            max_quantity=5000,
            max_notional=Decimal("500000"),
        )

        assert limit.symbol == "*"
        assert limit.is_global is True


class TestExposureLimit:
    """Test ExposureLimit configuration."""

    def test_create_exposure_limit(self):
        """Test creating exposure limit."""
        limit = ExposureLimit(
            max_total_exposure=Decimal("1000000"),
            max_single_order=Decimal("100000"),
            max_daily_loss=Decimal("50000"),
            max_open_orders=100,
        )

        assert limit.max_total_exposure == Decimal("1000000")
        assert limit.max_single_order == Decimal("100000")
        assert limit.max_daily_loss == Decimal("50000")
        assert limit.max_open_orders == 100


class TestRiskCheckResult:
    """Test risk check result."""

    def test_passed_result(self):
        """Test passed risk check."""
        result = RiskCheckResult(
            check_name="position_limit",
            passed=True,
            message="Within limits",
        )

        assert result.passed is True
        assert result.is_blocking is False

    def test_failed_result(self):
        """Test failed risk check."""
        result = RiskCheckResult(
            check_name="position_limit",
            passed=False,
            message="Limit breached",
            is_blocking=True,
        )

        assert result.passed is False
        assert result.is_blocking is True


class TestRiskGateway:
    """Test risk gateway checks."""

    def test_position_limit_check_pass(self, now):
        """Test position limit check passes."""
        gateway = RiskGateway()
        gateway.add_position_limit(
            PositionLimit(
                symbol="RELIANCE",
                exchange="NSE",
                max_quantity=1000,
                max_notional=Decimal("100000"),
            )
        )

        # Current position: 500 shares @ 100 = 50,000
        gateway.update_position("RELIANCE", "NSE", quantity=500, avg_price=Decimal("100"))

        # Check new order: 100 shares @ 100 = 10,000
        result = gateway.check_position_limit(
            symbol="RELIANCE",
            exchange="NSE",
            quantity=100,
            price=Decimal("100"),
        )

        assert result.passed is True

    def test_position_limit_check_fail_quantity(self, now):
        """Test position limit check fails on quantity."""
        gateway = RiskGateway()
        gateway.add_position_limit(
            PositionLimit(
                symbol="RELIANCE",
                exchange="NSE",
                max_quantity=1000,
                max_notional=Decimal("100000"),
            )
        )

        # Current position: 950 shares
        gateway.update_position("RELIANCE", "NSE", quantity=950, avg_price=Decimal("100"))

        # Check new order: 100 shares (would exceed 1000)
        result = gateway.check_position_limit(
            symbol="RELIANCE",
            exchange="NSE",
            quantity=100,
            price=Decimal("100"),
        )

        assert result.passed is False
        assert result.is_blocking is True
        assert "quantity" in result.message.lower()

    def test_position_limit_check_fail_notional(self, now):
        """Test position limit check fails on notional value."""
        gateway = RiskGateway()
        gateway.add_position_limit(
            PositionLimit(
                symbol="RELIANCE",
                exchange="NSE",
                max_quantity=10000,  # High quantity limit
                max_notional=Decimal("100000"),
            )
        )

        # Current position: 800 shares @ 100 = 80,000
        gateway.update_position("RELIANCE", "NSE", quantity=800, avg_price=Decimal("100"))

        # Check new order: 100 shares @ 100 = 10,000 (would be 90,000)
        result = gateway.check_position_limit(
            symbol="RELIANCE",
            exchange="NSE",
            quantity=100,
            price=Decimal("100"),
        )

        assert result.passed is True  # 90,000 < 100,000

        # This would exceed notional: 80,000 + 30,000 = 110,000
        result = gateway.check_position_limit(
            symbol="RELIANCE",
            exchange="NSE",
            quantity=300,
            price=Decimal("100"),
        )

        assert result.passed is False
        assert result.is_blocking is True
        assert "notional" in result.message.lower()

    def test_global_position_limit(self, now):
        """Test global position limit across all symbols."""
        gateway = RiskGateway()
        gateway.add_position_limit(
            PositionLimit(
                symbol="*",
                exchange="*",
                max_quantity=5000,
                max_notional=Decimal("500000"),
            )
        )

        # Add positions in multiple symbols
        gateway.update_position("RELIANCE", "NSE", quantity=2000, avg_price=Decimal("100"))
        gateway.update_position("TCS", "NSE", quantity=2000, avg_price=Decimal("100"))

        # Total: 4000, limit: 5000
        result = gateway.check_position_limit(
            symbol="INFY",
            exchange="NSE",
            quantity=500,
            price=Decimal("100"),
        )

        assert result.passed is True  # 4500 < 5000

        # This would exceed
        result = gateway.check_position_limit(
            symbol="INFY",
            exchange="NSE",
            quantity=1500,
            price=Decimal("100"),
        )

        assert result.passed is False  # 5500 > 5000

    def test_exposure_check_pass(self, now):
        """Test exposure check passes."""
        gateway = RiskGateway()
        gateway.set_exposure_limit(
            ExposureLimit(
                max_total_exposure=Decimal("1000000"),
                max_single_order=Decimal("100000"),
                max_open_orders=100,
            )
        )

        gateway.set_current_exposure(
            total_exposure=Decimal("500000"),
            open_orders=50,
        )

        result = gateway.check_exposure(
            order_value=Decimal("50000"),
        )

        assert result.passed is True

    def test_exposure_check_fail_total(self, now):
        """Test exposure check fails on total exposure."""
        gateway = RiskGateway()
        gateway.set_exposure_limit(
            ExposureLimit(
                max_total_exposure=Decimal("1000000"),
                max_single_order=Decimal("100000"),
                max_open_orders=100,
            )
        )

        gateway.set_current_exposure(
            total_exposure=Decimal("950000"),
            open_orders=50,
        )

        result = gateway.check_exposure(
            order_value=Decimal("100000"),  # Would be 1,050,000
        )

        assert result.passed is False
        assert "total exposure" in result.message.lower()

    def test_exposure_check_fail_single_order(self, now):
        """Test exposure check fails on single order size."""
        gateway = RiskGateway()
        gateway.set_exposure_limit(
            ExposureLimit(
                max_total_exposure=Decimal("1000000"),
                max_single_order=Decimal("100000"),
                max_open_orders=100,
            )
        )

        gateway.set_current_exposure(
            total_exposure=Decimal("500000"),
            open_orders=50,
        )

        result = gateway.check_exposure(
            order_value=Decimal("150000"),  # Exceeds max_single_order
        )

        assert result.passed is False
        assert "single order" in result.message.lower()

    def test_exposure_check_fail_open_orders(self, now):
        """Test exposure check fails on open orders count."""
        gateway = RiskGateway()
        gateway.set_exposure_limit(
            ExposureLimit(
                max_total_exposure=Decimal("1000000"),
                max_single_order=Decimal("100000"),
                max_open_orders=100,
            )
        )

        gateway.set_current_exposure(
            total_exposure=Decimal("500000"),
            open_orders=100,  # At limit
        )

        result = gateway.check_exposure(
            order_value=Decimal("50000"),
        )

        assert result.passed is False
        assert "open orders" in result.message.lower()

    def test_kill_switch(self, now):
        """Test kill switch blocks all orders."""
        gateway = RiskGateway()

        # Activate kill switch
        gateway.activate_kill_switch(reason="Manual activation")

        result = gateway.check_kill_switch()

        assert result.passed is False
        assert result.is_blocking is True
        assert "kill switch" in result.message.lower()

    def test_kill_switch_deactivate(self, now):
        """Test kill switch deactivation."""
        gateway = RiskGateway()

        gateway.activate_kill_switch(reason="Testing")
        gateway.deactivate_kill_switch()

        result = gateway.check_kill_switch()

        assert result.passed is True

    def test_comprehensive_risk_check(self, now):
        """Test comprehensive risk check (all checks)."""
        gateway = RiskGateway()

        # Setup limits
        gateway.add_position_limit(
            PositionLimit(
                symbol="RELIANCE",
                exchange="NSE",
                max_quantity=1000,
                max_notional=Decimal("100000"),
            )
        )

        gateway.set_exposure_limit(
            ExposureLimit(
                max_total_exposure=Decimal("1000000"),
                max_single_order=Decimal("100000"),
                max_open_orders=100,
            )
        )

        # Setup current state
        gateway.update_position("RELIANCE", "NSE", quantity=500, avg_price=Decimal("100"))
        gateway.set_current_exposure(
            total_exposure=Decimal("500000"),
            open_orders=50,
        )

        # Run comprehensive check
        results = gateway.run_all_checks(
            symbol="RELIANCE",
            exchange="NSE",
            quantity=100,
            price=Decimal("100"),
            order_value=Decimal("10000"),
        )

        # All checks should pass
        assert all(r.passed for r in results)

    def test_comprehensive_check_with_failure(self, now):
        """Test comprehensive check with one failure."""
        gateway = RiskGateway()

        gateway.set_exposure_limit(
            ExposureLimit(
                max_total_exposure=Decimal("1000000"),
                max_single_order=Decimal("100000"),
                max_open_orders=100,
            )
        )

        gateway.set_current_exposure(
            total_exposure=Decimal("950000"),
            open_orders=50,
        )

        results = gateway.run_all_checks(
            symbol="RELIANCE",
            exchange="NSE",
            quantity=100,
            price=Decimal("100"),
            order_value=Decimal("100000"),  # Exceeds single order limit
        )

        # Should have at least one failure
        assert any(not r.passed for r in results)

    def test_is_order_allowed(self, now):
        """Test is_order_allowed convenience method."""
        gateway = RiskGateway()

        gateway.set_exposure_limit(
            ExposureLimit(
                max_total_exposure=Decimal("1000000"),
                max_single_order=Decimal("100000"),
                max_open_orders=100,
            )
        )

        gateway.set_current_exposure(
            total_exposure=Decimal("500000"),
            open_orders=50,
        )

        # Order within limits
        allowed, results = gateway.is_order_allowed(
            symbol="RELIANCE",
            exchange="NSE",
            quantity=100,
            price=Decimal("100"),
            order_value=Decimal("10000"),
        )

        assert allowed is True

        # Kill switch activated
        gateway.activate_kill_switch(reason="Emergency")

        allowed, results = gateway.is_order_allowed(
            symbol="RELIANCE",
            exchange="NSE",
            quantity=100,
            price=Decimal("100"),
            order_value=Decimal("10000"),
        )

        assert allowed is False

    def test_reset_gateway(self, now):
        """Test resetting risk gateway."""
        gateway = RiskGateway()

        gateway.update_position("RELIANCE", "NSE", quantity=500, avg_price=Decimal("100"))
        gateway.activate_kill_switch(reason="Testing")

        gateway.reset()

        # Positions should be cleared
        assert gateway.get_position("RELIANCE", "NSE") is None

        # Kill switch should be off
        result = gateway.check_kill_switch()
        assert result.passed is True

    def test_pnl_tracking(self, now):
        """Test daily P&L tracking."""
        gateway = RiskGateway()

        gateway.set_exposure_limit(
            ExposureLimit(
                max_total_exposure=Decimal("1000000"),
                max_single_order=Decimal("100000"),
                max_daily_loss=Decimal("50000"),
                max_open_orders=100,
            )
        )

        # Simulate losses
        gateway.update_daily_pnl(Decimal("-30000"))
        gateway.update_daily_pnl(Decimal("-15000"))

        # Total loss: 45,000 (within 50,000 limit)
        result = gateway.check_exposure(order_value=Decimal("10000"))
        assert result.passed is True

        # Additional loss would exceed
        gateway.update_daily_pnl(Decimal("-10000"))  # Total: 55,000

        result = gateway.check_exposure(order_value=Decimal("10000"))
        assert result.passed is False
        assert "daily loss" in result.message.lower()

    def test_get_risk_summary(self, now):
        """Test risk summary generation."""
        gateway = RiskGateway()

        gateway.add_position_limit(
            PositionLimit(
                symbol="RELIANCE",
                exchange="NSE",
                max_quantity=1000,
                max_notional=Decimal("100000"),
            )
        )

        gateway.update_position("RELIANCE", "NSE", quantity=500, avg_price=Decimal("100"))
        gateway.set_current_exposure(
            total_exposure=Decimal("500000"),
            open_orders=50,
        )

        summary = gateway.get_risk_summary()

        assert "positions" in summary
        assert "exposure" in summary
        assert "limits" in summary
        assert summary["kill_switch_active"] is False
