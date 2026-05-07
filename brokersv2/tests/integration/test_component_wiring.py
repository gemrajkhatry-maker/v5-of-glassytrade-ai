"""Integration tests for full component wiring - end-to-end workflows."""
import pytest
from datetime import datetime, timezone
from decimal import Decimal
from fastapi.testclient import TestClient

from brokersv2.gateway.server import create_app, GatewayConfig
from brokersv2.oms.order_machine import OrderStateMachine, OrderEvent, OrderState
from brokersv2.oms.fill_processor import FillProcessor
from brokersv2.oms.reconciliation import (
    ReconciliationEngine,
    OrderSnapshot,
)
from brokersv2.risk.gateway import RiskGateway, PositionLimit, ExposureLimit
from brokersv2.observability.metrics import MetricsCollector
from brokersv2.observability.health import (
    HealthChecker,
    HealthStatus,
    HealthCheck,
    CheckType,
)


@pytest.fixture
def app():
    """Create production-like app."""
    config = GatewayConfig(debug=False)
    return create_app(config)


@pytest.fixture
def client(app):
    """Create test client."""
    return TestClient(app)


@pytest.fixture
def metrics():
    """Create metrics collector."""
    return MetricsCollector()


@pytest.fixture
def health_checker():
    """Create health checker."""
    return HealthChecker()


@pytest.fixture
def risk_gateway():
    """Create risk gateway with limits."""
    gateway = RiskGateway()
    
    # Add position limits
    gateway.add_position_limit(PositionLimit(
        symbol="RELIANCE",
        exchange="NSE",
        max_quantity=1000,
        max_notional=Decimal("100000"),
    ))
    
    # Add exposure limits
    gateway.set_exposure_limit(ExposureLimit(
        max_total_exposure=Decimal("1000000"),
        max_single_order=Decimal("100000"),
        max_open_orders=100,
    ))
    
    return gateway


class TestFullOrderLifecycle:
    """Test complete order lifecycle with all components."""

    def test_order_submission_to_fill(self):
        """Test order from submission through fill with risk checks."""
        # Setup components
        risk = RiskGateway()
        risk.set_exposure_limit(ExposureLimit(
            max_total_exposure=Decimal("1000000"),
            max_single_order=Decimal("100000"),
        ))
        risk.set_current_exposure(total_exposure=Decimal("500000"), open_orders=0)

        machine = OrderStateMachine(order_id="ORD001")
        fills = FillProcessor(order_id="ORD001", ordered_quantity=100)

        # Step 1: Risk check before submission
        allowed, risk_results = risk.is_order_allowed(
            symbol="RELIANCE",
            exchange="NSE",
            quantity=100,
            price=Decimal("100"),
            order_value=Decimal("10000"),
        )
        assert allowed is True

        # Step 2: Submit order
        state = machine.transition(OrderEvent.SUBMIT)
        assert state == OrderState.SUBMITTED

        # Step 3: Process partial fill
        fill1 = fills.process_fill("FILL001", quantity=50, price=Decimal("100.00"))
        machine.transition(OrderEvent.PARTIAL_FILL)

        # Step 4: Process remaining fill
        fill2 = fills.process_fill("FILL002", quantity=50, price=Decimal("100.50"))
        machine.transition(OrderEvent.FILL)

        # Step 5: Verify final state
        assert machine.current_state == OrderState.FILLED
        stats = fills.get_stats()
        assert stats.total_filled == 100
        assert stats.is_complete is True

    def test_order_with_risk_rejection(self):
        """Test order rejected by risk gateway."""
        risk = RiskGateway()
        risk.set_exposure_limit(ExposureLimit(
            max_total_exposure=Decimal("100000"),
            max_single_order=Decimal("50000"),
        ))
        risk.set_current_exposure(total_exposure=Decimal("90000"), open_orders=0)

        # This order would exceed total exposure
        allowed, results = risk.is_order_allowed(
            symbol="RELIANCE",
            exchange="NSE",
            quantity=100,
            price=Decimal("100"),
            order_value=Decimal("20000"),  # Would be 110,000
        )

        assert allowed is False
        assert any(not r.passed for r in results)

    def test_kill_switch_blocks_orders(self):
        """Test kill switch prevents order submission."""
        risk = RiskGateway()
        risk.activate_kill_switch(reason="Emergency")

        allowed, results = risk.is_order_allowed(
            symbol="RELIANCE",
            exchange="NSE",
            quantity=100,
            price=Decimal("100"),
            order_value=Decimal("10000"),
        )

        assert allowed is False
        # Should have kill switch failure
        kill_switch_result = [r for r in results if r.check_name == "kill_switch"]
        assert len(kill_switch_result) == 1
        assert kill_switch_result[0].passed is False


class TestMetricsIntegration:
    """Test metrics collection across components."""

    def test_metrics_track_order_flow(self, metrics):
        """Test metrics track complete order flow."""
        # Simulate order flow
        metrics.increment("orders_submitted", labels={"exchange": "NSE"})
        metrics.increment("orders_submitted", labels={"exchange": "NSE"})
        
        metrics.observe("order_fill_time_ms", 45.2)
        metrics.observe("order_fill_time_ms", 52.1)
        
        metrics.set_gauge("active_orders", 2)

        # Verify metrics
        submitted = metrics.get_metric("orders_submitted", labels={"exchange": "NSE"})
        assert submitted.value == 2

        fill_time = metrics.get_metric("order_fill_time_ms")
        assert fill_time.count == 2

        active = metrics.get_metric("active_orders")
        assert active.value == 2

    def test_metrics_with_health_checks(self, metrics, health_checker):
        """Test metrics and health checks work together."""
        # Register and update health check
        health_checker.register_check(
            HealthCheck(name="database", check_type=CheckType.READINESS)
        )
        health_checker.update_result("database", HealthStatus.HEALTHY, response_time_ms=12.5)

        # Track in metrics
        metrics.set_gauge("health_check_response_ms", 12.5, labels={"check": "database"})

        # Verify both systems working
        result = health_checker.get_result("database")
        assert result.response_time_ms == 12.5

        metric = metrics.get_metric("health_check_response_ms", labels={"check": "database"})
        assert metric.value == 12.5


class TestHealthCheckIntegration:
    """Test health check system with real components."""

    def test_full_system_health(self, health_checker):
        """Test comprehensive system health."""
        # Register all critical components
        health_checker.register_check(
            HealthCheck(name="order_engine", check_type=CheckType.LIVENESS, critical=True)
        )
        health_checker.register_check(
            HealthCheck(name="risk_gateway", check_type=CheckType.READINESS, critical=True)
        )
        health_checker.register_check(
            HealthCheck(name="market_data", check_type=CheckType.READINESS, critical=True)
        )

        # Set all healthy
        health_checker.update_result("order_engine", HealthStatus.HEALTHY, "Running")
        health_checker.update_result("risk_gateway", HealthStatus.HEALTHY, "Active")
        health_checker.update_result("market_data", HealthStatus.HEALTHY, "Streaming")

        # Check overall health
        readiness = health_checker.check_readiness()
        assert readiness.is_overall_healthy is True
        assert readiness.status == HealthStatus.HEALTHY

    def test_degraded_system_health(self, health_checker):
        """Test system with degraded dependency."""
        health_checker.register_check(
            HealthCheck(name="database", check_type=CheckType.READINESS, critical=True)
        )
        health_checker.register_check(
            HealthCheck(name="cache", check_type=CheckType.READINESS, critical=False)
        )

        # Critical healthy, non-critical degraded
        health_checker.update_result("database", HealthStatus.HEALTHY)
        health_checker.update_result("cache", HealthStatus.UNHEALTHY, "Slow")

        readiness = health_checker.check_readiness()
        # Should be degraded but still serving
        assert readiness.is_overall_healthy is True
        assert readiness.status == HealthStatus.DEGRADED


class TestReconciliationIntegration:
    """Test reconciliation with order management."""

    def test_reconcile_filled_order(self):
        """Test reconciliation of fully filled order."""
        # Create order with fills
        fills = FillProcessor(order_id="ORD001", ordered_quantity=100)
        fills.process_fill("FILL001", quantity=50, price=Decimal("100.00"))
        fills.process_fill("FILL002", quantity=50, price=Decimal("100.50"))

        # Create snapshots
        internal_snapshot = OrderSnapshot(
            order_id="ORD001",
            timestamp=datetime.now(timezone.utc),
            state="FILLED",
            filled_quantity=100,
            average_price=Decimal("100.25"),
        )

        broker_snapshot = OrderSnapshot(
            order_id="ORD001",
            timestamp=datetime.now(timezone.utc),
            state="FILLED",
            filled_quantity=100,
            average_price=Decimal("100.25"),
        )

        # Reconcile
        engine = ReconciliationEngine(tolerance=Decimal("0.01"))
        result = engine.reconcile_order("ORD001", internal_snapshot, broker_snapshot)

        assert result.is_reconciled is True
        assert len(result.discrepancies) == 0

    def test_reconcile_with_discrepancy(self):
        """Test reconciliation detects discrepancies."""
        internal_snapshot = OrderSnapshot(
            order_id="ORD001",
            timestamp=datetime.now(timezone.utc),
            state="FILLED",
            filled_quantity=100,
            average_price=Decimal("100.00"),
        )

        broker_snapshot = OrderSnapshot(
            order_id="ORD001",
            timestamp=datetime.now(timezone.utc),
            state="PARTIAL",
            filled_quantity=50,
            average_price=Decimal("99.50"),
        )

        engine = ReconciliationEngine()
        result = engine.reconcile_order("ORD001", internal_snapshot, broker_snapshot)

        assert result.is_reconciled is False
        assert len(result.discrepancies) > 0


class TestGatewayIntegration:
    """Test gateway server with all components."""

    def test_full_health_endpoint(self, client):
        """Test health endpoint returns complete status."""
        response = client.get("/health")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] in ["healthy", "degraded", "unhealthy"]
        assert "checks" in data
        assert "timestamp" in data

    def test_metrics_endpoint_with_data(self, client, app):
        """Test metrics endpoint returns Prometheus format."""
        # Add some metrics
        app.state.metrics.increment("test_counter")
        app.state.metrics.set_gauge("test_gauge", 42)

        response = client.get("/metrics")
        assert response.status_code == 200
        assert "text/plain" in response.headers["content-type"]
        assert "test_counter" in response.text
        assert "test_gauge" in response.text

    def test_info_endpoint(self, client):
        """Test info endpoint returns server details."""
        response = client.get("/info")
        assert response.status_code == 200

        data = response.json()
        assert data["service"] == "glassytrade-gateway"
        assert "version" in data
        assert "uptime_seconds" in data

    def test_risk_endpoint_integration(self, client):
        """Test risk endpoint returns status."""
        response = client.get("/risk/status")
        assert response.status_code == 200

        data = response.json()
        assert "kill_switch_active" in data
        assert "exposure" in data
        assert "positions_count" in data


class TestEndToEndTradingWorkflow:
    """Test complete trading workflow end-to-end."""

    def test_complete_trading_session(self):
        """Simulate complete trading session."""
        # Initialize all components
        metrics = MetricsCollector()
        health = HealthChecker()
        risk = RiskGateway()
        
        # Setup health checks
        health.register_check(HealthCheck(name="trading_engine", check_type=CheckType.LIVENESS))
        health.register_check(HealthCheck(name="risk_gateway", check_type=CheckType.READINESS))
        
        # Setup risk limits
        risk.add_position_limit(PositionLimit(
            symbol="NIFTY",
            exchange="NSE",
            max_quantity=5000,
            max_notional=Decimal("500000"),
        ))
        
        # Start trading session
        metrics.increment("trading_sessions", description="Trading session started")
        health.update_result("trading_engine", HealthStatus.HEALTHY)
        health.update_result("risk_gateway", HealthStatus.HEALTHY)
        
        # Submit order 1
        metrics.increment("orders_submitted", labels={"symbol": "NIFTY"})
        machine1 = OrderStateMachine(order_id="ORD001")
        machine1.transition(OrderEvent.SUBMIT)
        
        fills1 = FillProcessor(order_id="ORD001", ordered_quantity=100)
        fills1.process_fill("F001", quantity=100, price=Decimal("100.00"))
        machine1.transition(OrderEvent.FILL)
        
        # Submit order 2
        metrics.increment("orders_submitted", labels={"symbol": "NIFTY"})
        machine2 = OrderStateMachine(order_id="ORD002")
        machine2.transition(OrderEvent.SUBMIT)
        
        fills2 = FillProcessor(order_id="ORD002", ordered_quantity=50)
        fills2.process_fill("F002", quantity=50, price=Decimal("100.50"))
        machine2.transition(OrderEvent.FILL)
        
        # End of session metrics
        metrics.set_gauge("total_orders", 2)
        metrics.set_gauge("total_fills", 2)
        
        # Verify session
        assert machine1.current_state == OrderState.FILLED
        assert machine2.current_state == OrderState.FILLED
        
        order_count = metrics.get_metric("orders_submitted", labels={"symbol": "NIFTY"})
        assert order_count.value == 2
        
        readiness = health.check_readiness()
        assert readiness.is_overall_healthy is True

    def test_trading_session_with_risk_controls(self):
        """Test trading session with active risk management."""
        risk = RiskGateway()
        metrics = MetricsCollector()
        
        # Configure strict limits
        risk.set_exposure_limit(ExposureLimit(
            max_total_exposure=Decimal("200000"),
            max_single_order=Decimal("50000"),
            max_daily_loss=Decimal("10000"),
        ))
        
        # Simulate trading with exposure tracking
        risk.set_current_exposure(total_exposure=Decimal("100000"), open_orders=2)
        
        # Order 1: Within limits
        allowed1, _ = risk.is_order_allowed(
            symbol="RELIANCE",
            exchange="NSE",
            quantity=100,
            price=Decimal("100"),
            order_value=Decimal("10000"),
        )
        assert allowed1 is True
        
        # Update exposure
        risk.set_current_exposure(total_exposure=Decimal("180000"), open_orders=3)
        
        # Order 2: Would exceed limit
        allowed2, results = risk.is_order_allowed(
            symbol="RELIANCE",
            exchange="NSE",
            quantity=100,
            price=Decimal("100"),
            order_value=Decimal("30000"),  # Would be 210,000
        )
        assert allowed2 is False
        
        # Track rejections
        metrics.increment("orders_rejected", labels={"reason": "risk_limit"})
        
        rejected = metrics.get_metric("orders_rejected", labels={"reason": "risk_limit"})
        assert rejected.value == 1


class TestComponentIsolation:
    """Test that components can work independently."""

    def test_metrics_without_other_components(self):
        """Test metrics work in isolation."""
        metrics = MetricsCollector()
        metrics.increment("standalone_counter")
        metrics.set_gauge("standalone_gauge", 100)
        
        assert metrics.get_metric("standalone_counter").value == 1
        assert metrics.get_metric("standalone_gauge").value == 100

    def test_order_machine_without_other_components(self):
        """Test order state machine in isolation."""
        machine = OrderStateMachine(order_id="TEST")
        machine.transition(OrderEvent.SUBMIT)
        machine.transition(OrderEvent.FILL)
        
        assert machine.current_state == OrderState.FILLED

    def test_risk_gateway_without_other_components(self):
        """Test risk gateway in isolation."""
        risk = RiskGateway()
        risk.set_exposure_limit(ExposureLimit(
            max_total_exposure=Decimal("100000"),
            max_single_order=Decimal("50000"),
        ))
        risk.set_current_exposure(total_exposure=Decimal("50000"), open_orders=0)
        
        allowed, _ = risk.is_order_allowed(
            symbol="TEST",
            exchange="NSE",
            quantity=10,
            price=Decimal("100"),
            order_value=Decimal("1000"),
        )
        assert allowed is True
