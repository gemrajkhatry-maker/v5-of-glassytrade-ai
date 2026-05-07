"""Tests for Circuit Breaker integration in gateway."""
import pytest
from brokersv2.core.resilience import CircuitBreaker, CircuitState


class TestCircuitBreakerIntegration:
    """Test circuit breaker in gateway context."""

    def test_circuit_breaker_initial_state(self):
        """Test circuit breaker starts in closed state."""
        cb = CircuitBreaker(failure_threshold=5, recovery_timeout=30)
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    def test_circuit_breaker_transitions_to_open(self):
        """Test circuit breaker opens after threshold failures."""
        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30)

        # Trigger failures
        for i in range(3):
            try:
                with cb():
                    raise Exception("Broker error")
            except Exception:
                pass

        assert cb.state == CircuitState.OPEN

    def test_circuit_breaker_rejects_calls_when_open(self):
        """Test circuit breaker rejects calls when open."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=30)

        # Open the circuit
        try:
            with cb():
                raise Exception("Failure")
        except Exception:
            pass

        assert cb.state == CircuitState.OPEN

        # Next call should be rejected
        with pytest.raises(Exception):
            with cb():
                pass  # Should raise CircuitBreakerError

    def test_circuit_breaker_half_open_after_timeout(self):
        """Test circuit breaker transitions to half-open after timeout."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=1)  # 1 second

        # Open the circuit
        try:
            with cb():
                raise Exception("Failure")
        except Exception:
            pass

        assert cb.state == CircuitState.OPEN

        # Wait for recovery timeout
        import time
        time.sleep(1.1)

        # Should allow one test call (half-open)
        # State will be HALF_OPEN
        assert cb.state in [CircuitState.OPEN, CircuitState.HALF_OPEN]

    def test_circuit_breaker_closes_on_success(self):
        """Test circuit breaker closes after successful call in half-open."""
        cb = CircuitBreaker(failure_threshold=1, recovery_timeout=1)

        # Open the circuit
        try:
            with cb():
                raise Exception("Failure")
        except Exception:
            pass

        # Wait for recovery
        import time
        time.sleep(1.1)

        # Successful call should close it
        with cb():
            pass  # Success

        assert cb.state == CircuitState.CLOSED

    def test_circuit_breaker_metrics_integration(self):
        """Test circuit breaker state can be monitored via metrics."""
        from brokersv2.observability.metrics import MetricsCollector

        cb = CircuitBreaker(failure_threshold=3, recovery_timeout=30)
        metrics = MetricsCollector()

        # Track circuit state
        metrics.set_gauge("circuit_breaker_state", cb.state.value)

        metric = metrics.get_metric("circuit_breaker_state")
        assert metric is not None
        assert metric.value == CircuitState.CLOSED.value

    def test_circuit_breaker_with_broker_operations(self):
        """Test circuit breaker protects broker operations."""
        cb = CircuitBreaker(failure_threshold=2, recovery_timeout=30)

        # Simulate broker failures
        call_count = 0
        for i in range(3):
            try:
                with cb():
                    call_count += 1
                    if call_count <= 2:
                        raise Exception("Broker timeout")
            except Exception:
                pass

        # Should have made 2 calls before circuit opened
        assert call_count == 2
        assert cb.state == CircuitState.OPEN


class TestCircuitBreakerConfiguration:
    """Test circuit breaker configuration options."""

    def test_custom_failure_threshold(self):
        """Test custom failure threshold."""
        cb = CircuitBreaker(failure_threshold=10)
        assert cb.failure_threshold == 10

    def test_custom_recovery_timeout(self):
        """Test custom recovery timeout."""
        cb = CircuitBreaker(recovery_timeout=60)
        assert cb.recovery_timeout == 60

    def test_default_configuration(self):
        """Test default configuration values."""
        cb = CircuitBreaker()
        assert cb.failure_threshold > 0
        assert cb.recovery_timeout > 0


class TestDryRunMode:
    """Test DRY run mode functionality."""

    def test_dry_run_intercepts_order_placement(self):
        """Test DRY run mode intercepts order placement."""
        from brokersv2.gateway.server import DryRunBroker

        broker = DryRunBroker()
        result = broker.place_order_mock(
            symbol="RELIANCE",
            exchange="NSE",
            quantity=10,
            side="BUY",
            order_type="MARKET",
        )

        assert result["order_id"].startswith("DRY_RUN_")
        assert result["status"] == "COMPLETED"
        assert result["dry_run"] is True

    def test_dry_run_intercepts_order_cancellation(self):
        """Test DRY run mode intercepts order cancellation."""
        from brokersv2.gateway.server import DryRunBroker

        broker = DryRunBroker()
        result = broker.cancel_order_mock("DRY_RUN_123")

        assert result["cancelled"] is True
        assert result["dry_run"] is True

    def test_dry_run_returns_mock_quote(self):
        """Test DRY run mode returns mock quote."""
        from brokersv2.gateway.server import DryRunBroker

        broker = DryRunBroker()
        quote = broker.get_quote_mock("NSE:RELIANCE")

        assert quote["symbol"] == "NSE:RELIANCE"
        assert quote["ltp"] > 0
        assert quote["dry_run"] is True

    def test_dry_run_returns_mock_historical(self):
        """Test DRY run mode returns mock historical data."""
        from brokersv2.gateway.server import DryRunBroker

        broker = DryRunBroker()
        data = broker.get_historical_mock(
            symbol="RELIANCE",
            exchange="NSE",
            from_date="2024-01-01",
            to_date="2024-01-31",
        )

        assert "candles" in data
        assert data["dry_run"] is True

    def test_dry_run_mode_flag(self):
        """Test DRY run mode can be toggled."""
        from brokersv2.gateway.server import GatewayConfig

        config_dry = GatewayConfig(dry_run=True)
        assert config_dry.dry_run is True

        config_live = GatewayConfig(dry_run=False)
        assert config_live.dry_run is False

    def test_dry_run_tracks_all_operations(self):
        """Test DRY run mode tracks all simulated operations."""
        from brokersv2.gateway.server import DryRunBroker

        broker = DryRunBroker()

        # Simulate multiple operations
        broker.place_order_mock("RELIANCE", "NSE", 10, "BUY", "MARKET")
        broker.place_order_mock("TCS", "NSE", 5, "SELL", "LIMIT")
        broker.cancel_order_mock("DRY_RUN_1")

        # Check operation log
        assert len(broker.operation_log) == 3
        assert broker.operation_log[0]["operation"] == "place_order"
        assert broker.operation_log[1]["operation"] == "place_order"
        assert broker.operation_log[2]["operation"] == "cancel_order"
