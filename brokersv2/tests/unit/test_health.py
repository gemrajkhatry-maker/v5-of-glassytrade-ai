"""Tests for Health Check System - liveness, readiness, and component health."""
import pytest
from datetime import datetime, timezone
from brokersv2.observability.health import (
    HealthChecker,
    HealthStatus,
    HealthCheck,
    HealthResult,
    CheckType,
    HealthError,
)


class TestHealthStatus:
    """Test HealthStatus enum."""

    def test_status_values(self):
        """Test enum values."""
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"


class TestCheckType:
    """Test CheckType enum."""

    def test_type_values(self):
        """Test enum values."""
        assert CheckType.LIVENESS.value == "liveness"
        assert CheckType.READINESS.value == "readiness"


class TestHealthCheck:
    """Test HealthCheck configuration."""

    def test_create_check(self):
        """Test creating health check."""
        check = HealthCheck(
            name="database",
            check_type=CheckType.READINESS,
            critical=True,
        )

        assert check.name == "database"
        assert check.check_type == CheckType.READINESS
        assert check.critical is True

    def test_non_critical_check(self):
        """Test non-critical check."""
        check = HealthCheck(
            name="cache",
            check_type=CheckType.READINESS,
            critical=False,
        )

        assert check.critical is False


class TestHealthResult:
    """Test HealthResult value object."""

    def test_healthy_result(self):
        """Test healthy result."""
        result = HealthResult(
            check_name="database",
            status=HealthStatus.HEALTHY,
            message="Connection successful",
            response_time_ms=12.5,
        )

        assert result.is_healthy is True
        assert result.status == HealthStatus.HEALTHY

    def test_unhealthy_result(self):
        """Test unhealthy result."""
        result = HealthResult(
            check_name="database",
            status=HealthStatus.UNHEALTHY,
            message="Connection failed",
            response_time_ms=0,
            error="Connection refused",
        )

        assert result.is_healthy is False
        assert result.error == "Connection refused"


class TestHealthChecker:
    """Test health checker functionality."""

    def test_register_check(self):
        """Test registering health check."""
        checker = HealthChecker()
        checker.register_check(
            HealthCheck(name="database", check_type=CheckType.READINESS)
        )

        assert "database" in checker.get_registered_checks()

    def test_register_multiple_checks(self):
        """Test registering multiple checks."""
        checker = HealthChecker()
        checker.register_check(
            HealthCheck(name="database", check_type=CheckType.READINESS)
        )
        checker.register_check(
            HealthCheck(name="cache", check_type=CheckType.READINESS)
        )
        checker.register_check(
            HealthCheck(name="process", check_type=CheckType.LIVENESS)
        )

        checks = checker.get_registered_checks()
        assert len(checks) == 3
        assert "database" in checks
        assert "cache" in checks
        assert "process" in checks

    def test_update_check_result(self):
        """Test updating check result."""
        checker = HealthChecker()
        checker.register_check(
            HealthCheck(name="database", check_type=CheckType.READINESS)
        )

        checker.update_result("database", HealthStatus.HEALTHY, "OK", 5.2)

        result = checker.get_result("database")
        assert result is not None
        assert result.status == HealthStatus.HEALTHY
        assert result.response_time_ms == 5.2

    def test_check_liveness_healthy(self):
        """Test liveness check when healthy."""
        checker = HealthChecker()
        checker.register_check(
            HealthCheck(name="process", check_type=CheckType.LIVENESS, critical=True)
        )
        checker.update_result("process", HealthStatus.HEALTHY, "Running")

        result = checker.check_liveness()
        assert result.status == HealthStatus.HEALTHY
        assert result.is_overall_healthy is True

    def test_check_liveness_unhealthy(self):
        """Test liveness check when unhealthy."""
        checker = HealthChecker()
        checker.register_check(
            HealthCheck(name="process", check_type=CheckType.LIVENESS, critical=True)
        )
        checker.update_result("process", HealthStatus.UNHEALTHY, "Deadlock detected")

        result = checker.check_liveness()
        assert result.status == HealthStatus.UNHEALTHY
        assert result.is_overall_healthy is False

    def test_check_readiness_all_healthy(self):
        """Test readiness check when all dependencies healthy."""
        checker = HealthChecker()
        checker.register_check(
            HealthCheck(name="database", check_type=CheckType.READINESS, critical=True)
        )
        checker.register_check(
            HealthCheck(name="cache", check_type=CheckType.READINESS, critical=False)
        )

        checker.update_result("database", HealthStatus.HEALTHY, "Connected")
        checker.update_result("cache", HealthStatus.HEALTHY, "Connected")

        result = checker.check_readiness()
        assert result.status == HealthStatus.HEALTHY
        assert result.is_overall_healthy is True

    def test_check_readiness_critical_failure(self):
        """Test readiness check when critical dependency fails."""
        checker = HealthChecker()
        checker.register_check(
            HealthCheck(name="database", check_type=CheckType.READINESS, critical=True)
        )
        checker.register_check(
            HealthCheck(name="cache", check_type=CheckType.READINESS, critical=False)
        )

        checker.update_result("database", HealthStatus.UNHEALTHY, "Connection failed")
        checker.update_result("cache", HealthStatus.HEALTHY, "Connected")

        result = checker.check_readiness()
        assert result.status == HealthStatus.UNHEALTHY
        assert result.is_overall_healthy is False

    def test_check_readiness_non_critical_failure(self):
        """Test readiness check when only non-critical dependency fails."""
        checker = HealthChecker()
        checker.register_check(
            HealthCheck(name="database", check_type=CheckType.READINESS, critical=True)
        )
        checker.register_check(
            HealthCheck(name="cache", check_type=CheckType.READINESS, critical=False)
        )

        checker.update_result("database", HealthStatus.HEALTHY, "Connected")
        checker.update_result("cache", HealthStatus.UNHEALTHY, "Cache miss")

        result = checker.check_readiness()
        # Should be degraded but not unhealthy
        assert result.status == HealthStatus.DEGRADED
        assert result.is_overall_healthy is True  # Can still serve traffic

    def test_check_readiness_no_checks(self):
        """Test readiness check with no registered checks."""
        checker = HealthChecker()

        result = checker.check_readiness()
        assert result.status == HealthStatus.UNHEALTHY
        assert "No readiness checks" in result.message

    def test_get_overall_status(self):
        """Test overall status aggregation."""
        checker = HealthChecker()
        checker.register_check(
            HealthCheck(name="db", check_type=CheckType.READINESS, critical=True)
        )
        checker.register_check(
            HealthCheck(name="cache", check_type=CheckType.READINESS, critical=False)
        )
        checker.register_check(
            HealthCheck(name="queue", check_type=CheckType.READINESS, critical=True)
        )

        checker.update_result("db", HealthStatus.HEALTHY)
        checker.update_result("cache", HealthStatus.UNHEALTHY)
        checker.update_result("queue", HealthStatus.HEALTHY)

        status = checker.get_overall_status()
        assert status["overall"] == HealthStatus.DEGRADED.value
        assert status["total_checks"] == 3
        assert status["healthy"] == 2
        assert status["unhealthy"] == 1

    def test_all_healthy_status(self):
        """Test overall status when all healthy."""
        checker = HealthChecker()
        checker.register_check(
            HealthCheck(name="db", check_type=CheckType.READINESS, critical=True)
        )
        checker.update_result("db", HealthStatus.HEALTHY)

        status = checker.get_overall_status()
        assert status["overall"] == HealthStatus.HEALTHY.value

    def test_all_unhealthy_status(self):
        """Test overall status when all unhealthy."""
        checker = HealthChecker()
        checker.register_check(
            HealthCheck(name="db", check_type=CheckType.READINESS, critical=True)
        )
        checker.update_result("db", HealthStatus.UNHEALTHY)

        status = checker.get_overall_status()
        assert status["overall"] == HealthStatus.UNHEALTHY.value

    def test_health_summary(self):
        """Test health summary generation."""
        checker = HealthChecker()
        checker.register_check(
            HealthCheck(name="database", check_type=CheckType.READINESS, critical=True)
        )
        checker.register_check(
            HealthCheck(name="cache", check_type=CheckType.READINESS, critical=False)
        )

        checker.update_result("database", HealthStatus.HEALTHY, "Connected", 10.5)
        checker.update_result("cache", HealthStatus.DEGRADED, "Slow", 250.0)

        summary = checker.get_health_summary()

        assert "checks" in summary
        assert len(summary["checks"]) == 2
        assert summary["overall_status"] in ["healthy", "degraded", "unhealthy"]

    def test_check_result_timestamp(self):
        """Test result has timestamp."""
        checker = HealthChecker()
        checker.register_check(
            HealthCheck(name="database", check_type=CheckType.READINESS)
        )
        checker.update_result("database", HealthStatus.HEALTHY)

        result = checker.get_result("database")
        assert result.timestamp is not None

    def test_unregister_check(self):
        """Test unregistering health check."""
        checker = HealthChecker()
        checker.register_check(
            HealthCheck(name="database", check_type=CheckType.READINESS)
        )
        checker.unregister_check("database")

        assert "database" not in checker.get_registered_checks()

    def test_check_result_history(self):
        """Test that results are updated (not accumulated)."""
        checker = HealthChecker()
        checker.register_check(
            HealthCheck(name="database", check_type=CheckType.READINESS)
        )

        checker.update_result("database", HealthStatus.HEALTHY)
        checker.update_result("database", HealthStatus.UNHEALTHY)
        checker.update_result("database", HealthStatus.HEALTHY)

        # Should only have latest result
        result = checker.get_result("database")
        assert result.status == HealthStatus.HEALTHY

    def test_critical_vs_non_critical(self):
        """Test critical vs non-critical check handling."""
        checker = HealthChecker()
        checker.register_check(
            HealthCheck(name="critical_db", check_type=CheckType.READINESS, critical=True)
        )
        checker.register_check(
            HealthCheck(name="non_critical_cache", check_type=CheckType.READINESS, critical=False)
        )

        # Only non-critical fails
        checker.update_result("critical_db", HealthStatus.HEALTHY)
        checker.update_result("non_critical_cache", HealthStatus.UNHEALTHY)

        result = checker.check_readiness()
        # Should be degraded but still overall healthy
        assert result.is_overall_healthy is True

        # Only critical fails
        checker.update_result("critical_db", HealthStatus.UNHEALTHY)
        checker.update_result("non_critical_cache", HealthStatus.HEALTHY)

        result = checker.check_readiness()
        assert result.is_overall_healthy is False

    def test_response_time_tracking(self):
        """Test response time is tracked."""
        checker = HealthChecker()
        checker.register_check(
            HealthCheck(name="database", check_type=CheckType.READINESS)
        )

        checker.update_result("database", HealthStatus.HEALTHY, response_time_ms=15.3)

        result = checker.get_result("database")
        assert result.response_time_ms == 15.3

    def test_error_message_tracking(self):
        """Test error message is tracked."""
        checker = HealthChecker()
        checker.register_check(
            HealthCheck(name="database", check_type=CheckType.READINESS)
        )

        checker.update_result(
            "database",
            HealthStatus.UNHEALTHY,
            error="Connection timeout after 30s",
        )

        result = checker.get_result("database")
        assert result.error == "Connection timeout after 30s"

    def test_get_all_results(self):
        """Test getting all check results."""
        checker = HealthChecker()
        checker.register_check(
            HealthCheck(name="db", check_type=CheckType.READINESS)
        )
        checker.register_check(
            HealthCheck(name="cache", check_type=CheckType.READINESS)
        )

        checker.update_result("db", HealthStatus.HEALTHY)
        checker.update_result("cache", HealthStatus.HEALTHY)

        results = checker.get_all_results()
        assert len(results) == 2
        assert "db" in results
        assert "cache" in results

    def test_liveness_vs_readiness_separation(self):
        """Test liveness and readiness are separate."""
        checker = HealthChecker()
        checker.register_check(
            HealthCheck(name="process", check_type=CheckType.LIVENESS)
        )
        checker.register_check(
            HealthCheck(name="database", check_type=CheckType.READINESS)
        )

        checker.update_result("process", HealthStatus.HEALTHY)
        checker.update_result("database", HealthStatus.UNHEALTHY)

        # Liveness should be healthy (process is running)
        liveness = checker.check_liveness()
        assert liveness.status == HealthStatus.HEALTHY

        # Readiness should be unhealthy (database is down)
        readiness = checker.check_readiness()
        assert readiness.status == HealthStatus.UNHEALTHY
