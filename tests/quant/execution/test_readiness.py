"""Tests for truthful readiness with degraded states (Phase 0.3).

The previous readiness check reported 'ok' or 'degraded' without distinguishing
degraded-no-new-entries from not-ready. It also did not reflect paper position
quarantine status, runtime activity, or history seed status.

Phase 0.3 introduces:
- ReadinessStatus enum: READY, DEGRADED_NO_NEW_ENTRIES, NOT_READY
- QuantCoordinator.readiness_status() aggregates sub-checks
- Backend health router integrates coordinator readiness
"""

from quant.execution.readiness import (
    ReadinessStatus,
    readiness_status,
)


def test_readiness_status_enum_exists():
    """ReadinessStatus must define the canonical readiness outcomes."""
    assert ReadinessStatus.READY.value == "READY"
    assert ReadinessStatus.DEGRADED_NO_NEW_ENTRIES.value == "DEGRADED_NO_NEW_ENTRIES"
    assert ReadinessStatus.NOT_READY.value == "NOT_READY"


def test_readiness_requires_started_coordinator():
    """A coordinator that has not started is NOT_READY."""
    class FakeCoord:
        started = False
    status, details = readiness_status(FakeCoord())
    assert status == ReadinessStatus.NOT_READY
    assert "not_started" in details.get("coordinator", "").lower()


def test_readiness_crashed_engines_is_not_ready():
    """Crashed engines — no trading can happen, NOT_READY."""
    class FakeCoord:
        started = True
        def crashed_engines(self):
            return ["NIFTY 1 SEP 24200 CALL"]
    status, details = readiness_status(FakeCoord())
    assert status == ReadinessStatus.NOT_READY


def test_readiness_quarantined_positions_is_degraded():
    """Quarantined paper positions — system is up but no new entries until resolved."""
    class FakeCoord:
        started = True
        def crashed_engines(self):
            return []
        def quarantined_positions(self):
            return {"NIFTY 1 SEP 24050 CALL", "MIDCPNIFTY 29 SEP 14700 PUT"}
    status, details = readiness_status(FakeCoord())
    assert status == ReadinessStatus.DEGRADED_NO_NEW_ENTRIES
    assert "quarantined" in details


def test_readiness_no_quarantine_is_ready():
    """Clean state with no quarantine and no crashes — READY."""
    class FakeCoord:
        started = True
        def crashed_engines(self):
            return []
        def quarantined_positions(self):
            return set()
    status, details = readiness_status(FakeCoord())
    assert status == ReadinessStatus.READY


def test_readiness_combines_multiple_issues():
    """Crashed engines + quarantine — NOT_READY wins over DEGRADED."""
    class FakeCoord:
        started = True
        def crashed_engines(self):
            return ["NIFTY 1 SEP 24200 CALL"]
        def quarantined_positions(self):
            return {"NIFTY 1 SEP 24050 CALL"}
    status, details = readiness_status(FakeCoord())
    assert status == ReadinessStatus.NOT_READY


def test_readiness_with_no_coordinator():
    """No coordinator at all — NOT_READY."""
    status, details = readiness_status(None)
    assert status == ReadinessStatus.NOT_READY


def test_readiness_includes_sub_check_details():
    """Readiness details must include each sub-check for diagnostics."""
    class FakeCoord:
        started = True
        def crashed_engines(self):
            return []
        def quarantined_positions(self):
            return set()
    status, details = readiness_status(FakeCoord())
    assert "coordinator" in details
    assert "crashed_engines" in details
    assert "quarantined" in details
