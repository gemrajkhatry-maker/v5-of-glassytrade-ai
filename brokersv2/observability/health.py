"""Health Check System - liveness, readiness, and component health tracking."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class HealthError(Exception):
    """Base exception for health check errors."""
    pass


class HealthStatus(Enum):
    """Health status values."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class CheckType(Enum):
    """Types of health checks."""
    LIVENESS = "liveness"
    READINESS = "readiness"


@dataclass
class HealthCheck:
    """Health check configuration."""
    name: str
    check_type: CheckType
    critical: bool = True


@dataclass
class HealthResult:
    """Result of a health check."""
    check_name: str
    status: HealthStatus
    message: str = ""
    response_time_ms: float = 0.0
    error: Optional[str] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)

    @property
    def is_healthy(self) -> bool:
        """Check if result indicates healthy status."""
        return self.status in [HealthStatus.HEALTHY, HealthStatus.DEGRADED]


@dataclass
class AggregatedResult:
    """Aggregated health check result."""
    status: HealthStatus
    message: str
    is_overall_healthy: bool
    checks: List[HealthResult] = None
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc)
        if self.checks is None:
            self.checks = []


class HealthChecker:
    """
    Production health checker with liveness and readiness support.
    
    Features:
    - Liveness checks (is process alive?)
    - Readiness checks (are dependencies ready?)
    - Critical vs non-critical checks
    - Health aggregation
    - Kubernetes-compatible
    - Response time tracking
    - Error message tracking
    """

    def __init__(self):
        self._checks: Dict[str, HealthCheck] = {}
        self._results: Dict[str, HealthResult] = {}

    def register_check(self, check: HealthCheck):
        """
        Register a health check.
        
        Args:
            check: HealthCheck configuration
        """
        self._checks[check.name] = check
        logger.debug(f"Health check registered: {check.name}")

    def unregister_check(self, name: str):
        """
        Unregister a health check.
        
        Args:
            name: Check name
        """
        self._checks.pop(name, None)
        self._results.pop(name, None)
        logger.debug(f"Health check unregistered: {name}")

    def update_result(
        self,
        check_name: str,
        status: HealthStatus,
        message: str = "",
        response_time_ms: float = 0.0,
        error: Optional[str] = None,
    ):
        """
        Update result for a health check.
        
        Args:
            check_name: Check name
            status: Health status
            message: Status message
            response_time_ms: Response time in milliseconds
            error: Error message if unhealthy
        """
        self._results[check_name] = HealthResult(
            check_name=check_name,
            status=status,
            message=message,
            response_time_ms=response_time_ms,
            error=error,
        )

        if status == HealthStatus.UNHEALTHY:
            logger.warning(f"Health check failed: {check_name} - {message}")

    def get_result(self, check_name: str) -> Optional[HealthResult]:
        """
        Get result for a specific check.
        
        Args:
            check_name: Check name
            
        Returns:
            HealthResult or None
        """
        return self._results.get(check_name)

    def get_all_results(self) -> Dict[str, HealthResult]:
        """
        Get all check results.
        
        Returns:
            Dictionary of check_name -> HealthResult
        """
        return dict(self._results)

    def get_registered_checks(self) -> List[str]:
        """
        Get list of registered check names.
        
        Returns:
            List of check names
        """
        return list(self._checks.keys())

    def check_liveness(self) -> AggregatedResult:
        """
        Check liveness (is process alive and responsive?).
        
        Returns:
            AggregatedResult
        """
        liveness_checks = {
            name: check for name, check in self._checks.items()
            if check.check_type == CheckType.LIVENESS
        }

        if not liveness_checks:
            return AggregatedResult(
                status=HealthStatus.UNHEALTHY,
                message="No liveness checks registered",
                is_overall_healthy=False,
            )

        results = []
        all_healthy = True

        for name in liveness_checks:
            result = self._results.get(name)
            if result and result.status == HealthStatus.HEALTHY:
                results.append(result)
            else:
                all_healthy = False
                if result:
                    results.append(result)
                else:
                    results.append(HealthResult(
                        check_name=name,
                        status=HealthStatus.UNHEALTHY,
                        message="No result available",
                    ))

        status = HealthStatus.HEALTHY if all_healthy else HealthStatus.UNHEALTHY
        message = "All liveness checks passed" if all_healthy else "Some liveness checks failed"

        return AggregatedResult(
            status=status,
            message=message,
            is_overall_healthy=all_healthy,
            checks=results,
        )

    def check_readiness(self) -> AggregatedResult:
        """
        Check readiness (are all dependencies ready?).
        
        Returns:
            AggregatedResult
        """
        readiness_checks = {
            name: check for name, check in self._checks.items()
            if check.check_type == CheckType.READINESS
        }

        if not readiness_checks:
            return AggregatedResult(
                status=HealthStatus.UNHEALTHY,
                message="No readiness checks registered",
                is_overall_healthy=False,
            )

        results = []
        critical_failures = 0
        any_failure = 0

        for name, check in readiness_checks.items():
            result = self._results.get(name)

            if not result:
                result = HealthResult(
                    check_name=name,
                    status=HealthStatus.UNHEALTHY,
                    message="No result available",
                )

            results.append(result)

            # Track failures
            if result.status == HealthStatus.UNHEALTHY:
                any_failure += 1
                if check.critical:
                    critical_failures += 1

        # Determine overall status
        if critical_failures > 0:
            status = HealthStatus.UNHEALTHY
            message = f"{critical_failures} critical check(s) failed"
            is_overall_healthy = False
        elif any_failure > 0:
            status = HealthStatus.DEGRADED
            message = f"{any_failure} non-critical check(s) degraded"
            is_overall_healthy = True  # Can still serve traffic
        else:
            status = HealthStatus.HEALTHY
            message = "All readiness checks passed"
            is_overall_healthy = True

        return AggregatedResult(
            status=status,
            message=message,
            is_overall_healthy=is_overall_healthy,
            checks=results,
        )

    def get_overall_status(self) -> dict:
        """
        Get overall system status.
        
        Returns:
            Dictionary with status summary
        """
        total = len(self._results)
        healthy = sum(1 for r in self._results.values() if r.status == HealthStatus.HEALTHY)
        degraded = sum(1 for r in self._results.values() if r.status == HealthStatus.DEGRADED)
        unhealthy = sum(1 for r in self._results.values() if r.status == HealthStatus.UNHEALTHY)

        # Determine overall
        if unhealthy > 0:
            # Check if any critical checks failed
            critical_unhealthy = sum(
                1 for name, r in self._results.items()
                if r.status == HealthStatus.UNHEALTHY
                and self._checks.get(name, HealthCheck("", CheckType.READINESS)).critical
            )

            if critical_unhealthy > 0:
                overall = HealthStatus.UNHEALTHY.value
            else:
                overall = HealthStatus.DEGRADED.value
        elif degraded > 0:
            overall = HealthStatus.DEGRADED.value
        else:
            overall = HealthStatus.HEALTHY.value

        return {
            "overall": overall,
            "total_checks": total,
            "healthy": healthy,
            "degraded": degraded,
            "unhealthy": unhealthy,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def get_health_summary(self) -> dict:
        """
        Get comprehensive health summary.
        
        Returns:
            Dictionary with detailed health information
        """
        checks_summary = []

        for name, check in self._checks.items():
            result = self._results.get(name)

            check_info = {
                "name": name,
                "type": check.check_type.value,
                "critical": check.critical,
                "status": result.status.value if result else "unknown",
                "message": result.message if result else "No result",
                "response_time_ms": result.response_time_ms if result else 0,
            }

            if result and result.error:
                check_info["error"] = result.error

            checks_summary.append(check_info)

        overall = self.get_overall_status()

        return {
            "overall_status": overall["overall"],
            "checks": checks_summary,
            "summary": overall,
        }

    def reset(self):
        """Reset all health check results."""
        self._results.clear()
        logger.info("Health checker results reset")
