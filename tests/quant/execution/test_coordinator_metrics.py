"""Tests for coordinator-backed metrics (Phase 0.4).

The previous MetricsCollector was a disconnected singleton that never received
events from the coordinator — /api/v1/metrics reported 0 ticks while WebSocket
showed live market flow.

Phase 0.4 introduces:
- CoordinatorMetricsProvider reads activity from the coordinator's engines
- Per-engine activity: last_tick_received_at, last_bar_closed_at,
  last_amt_update_at, last_decision_at, decision_count, approved_count,
  blocked_count, open_position, seed_status, data_age_seconds
- Snapshot replaces the disconnected MetricsCollector
"""
import time

from quant.execution.coordinator_metrics import (
    CoordinatorMetricsProvider,
    EngineActivity,
    coordinator_metrics_provider,
)


class FakeEngine:
    """Minimal double for engine activity attributes."""

    def __init__(self, symbol):
        self.symbol = symbol
        self._last_tick = time.time()
        self._last_bar = time.time()
        self._last_amt = time.time()
        self._last_decision = time.time()
        self._decision_count = 0
        self._approved_count = 0
        self._blocked_count = 0
        self._open_position = None
        self._seed_status = "READY"
        self._data_age = 0.0

    def state(self):
        class _State:
            pass
        s = _State()
        s.symbol = self.symbol
        s.position = self._open_position
        return s


class FakeCoordinator:
    """Coordinator double exposing engines and storage."""

    def __init__(self, engines=None):
        self._engines = engines or {}
        self._storage = None

    @property
    def engines(self):
        return self._engines

    @property
    def storage(self):
        return self._storage


def test_engine_activity_dataclass():
    """EngineActivity holds per-engine runtime metrics."""
    ea = EngineActivity(
        symbol="NIFTY 1 SEP 24200 CALL",
        last_tick_received_at=time.time(),
        last_bar_closed_at=time.time(),
        last_amt_update_at=time.time(),
        last_decision_at=time.time(),
        decision_count=5,
        approved_count=2,
        blocked_count=3,
        open_position=None,
        seed_status="READY",
        data_age_seconds=0.5,
    )
    assert ea.symbol == "NIFTY 1 SEP 24200 CALL"
    assert ea.decision_count == 5
    assert ea.open_position is None


def test_coordinator_metrics_provider_exists():
    """CoordinatorMetricsProvider can be constructed with a coordinator."""
    coord = FakeCoordinator()
    provider = CoordinatorMetricsProvider(coord)
    assert provider is not None


def test_coordinator_metrics_provider_returns_snapshot():
    """Snapshot includes per-engine activity."""
    eng = FakeEngine("NIFTY 1 SEP 24200 CALL")
    coord = FakeCoordinator(engines={"NIFTY 1 SEP 24200 CALL": eng})
    provider = CoordinatorMetricsProvider(coord)
    snapshot = provider.snapshot()
    assert "engines" in snapshot
    assert "NIFTY 1 SEP 24200 CALL" in snapshot["engines"]
    ea = snapshot["engines"]["NIFTY 1 SEP 24200 CALL"]
    assert "last_tick_received_at" in ea
    assert "decision_count" in ea
    assert "seed_status" in ea


def test_coordinator_metrics_zero_engines():
    """No engines — snapshot is empty but well-formed."""
    coord = FakeCoordinator(engines={})
    provider = CoordinatorMetricsProvider(coord)
    snapshot = provider.snapshot()
    assert snapshot["engines"] == {}


def test_coordinator_metrics_aggregates_totals():
    """Snapshot includes aggregate totals across all engines."""
    eng1 = FakeEngine("NIFTY 1 SEP 24200 CALL")
    eng1._decision_count = 5
    eng2 = FakeEngine("BANKNIFTY 30 SEP 51000 PUT")
    eng2._decision_count = 3
    coord = FakeCoordinator(engines={
        "NIFTY 1 SEP 24200 CALL": eng1,
        "BANKNIFTY 30 SEP 51000 PUT": eng2,
    })
    provider = CoordinatorMetricsProvider(coord)
    snapshot = provider.snapshot()
    assert snapshot["totals"]["decision_count"] == 8


def test_coordinator_metrics_open_position_flag():
    """Engine with open position is flagged in metrics."""
    eng = FakeEngine("NIFTY 1 SEP 24200 CALL")
    eng._open_position = {"id": "pos-123", "size": 100}
    coord = FakeCoordinator(engines={"NIFTY 1 SEP 24200 CALL": eng})
    provider = CoordinatorMetricsProvider(coord)
    snapshot = provider.snapshot()
    ea = snapshot["engines"]["NIFTY 1 SEP 24200 CALL"]
    assert ea["open_position"] is True


def test_coordinator_metrics_seed_status_exposed():
    """Per-engine seed status is exposed for degraded-mode visibility."""
    eng = FakeEngine("NIFTY 1 SEP 24200 CALL")
    eng._seed_status = "DEGRADED_RATE_LIMIT"
    coord = FakeCoordinator(engines={"NIFTY 1 SEP 24200 CALL": eng})
    provider = CoordinatorMetricsProvider(coord)
    snapshot = provider.snapshot()
    ea = snapshot["engines"]["NIFTY 1 SEP 24200 CALL"]
    assert ea["seed_status"] == "DEGRADED_RATE_LIMIT"


def test_coordinator_metrics_data_age_seconds():
    """Data age (seconds since last tick) is exposed per engine."""
    eng = FakeEngine("NIFTY 1 SEP 24200 CALL")
    eng._last_tick = time.time() - 30.0  # 30 seconds ago
    coord = FakeCoordinator(engines={"NIFTY 1 SEP 24200 CALL": eng})
    provider = CoordinatorMetricsProvider(coord)
    snapshot = provider.snapshot()
    ea = snapshot["engines"]["NIFTY 1 SEP 24200 CALL"]
    assert ea["data_age_seconds"] >= 29.0


def test_coordinator_metrics_provider_function():
    """coordinator_metrics_provider() convenience function works."""
    coord = FakeCoordinator(engines={})
    provider = coordinator_metrics_provider(coord)
    assert isinstance(provider, CoordinatorMetricsProvider)


def test_totals_expose_model_risk_failures():
    """D-2 follow-up: a degraded ExitEngine session must be visible in /v1/metrics.

    The model-risk counter lives on quant.execution.exits; the metrics snapshot
    must surface the live process-level value, not an import-time snapshot.
    """
    import quant.execution.exits as exits_mod

    # No real coordinator needed: an empty engine map exercises the totals path.
    provider = CoordinatorMetricsProvider(FakeCoordinator(engines={}))
    totals = provider.snapshot()["totals"]

    assert "model_risk_failures" in totals
    assert totals["model_risk_failures"] == exits_mod.MODEL_RISK_FAILURES

    # A real failure must move the exposed value, not just the module global.
    exits_mod.MODEL_RISK_FAILURES += 1
    try:
        totals = provider.snapshot()["totals"]
        assert totals["model_risk_failures"] == exits_mod.MODEL_RISK_FAILURES
    finally:
        exits_mod.MODEL_RISK_FAILURES -= 1


def test_totals_expose_model_sizing_failures():
    """Finding 1 (review of D-12): a TimesFM *entry sizing* failure must be
    observable in /v1/metrics, distinct from the pre-existing exit-side
    model_risk_failures counter."""
    import quant.execution.exits as exits_mod

    provider = CoordinatorMetricsProvider(FakeCoordinator(engines={}))
    totals = provider.snapshot()["totals"]

    assert "model_sizing_failures" in totals
    assert totals["model_sizing_failures"] == exits_mod.MODEL_SIZING_FAILURES

    exits_mod.MODEL_SIZING_FAILURES += 1
    try:
        totals = provider.snapshot()["totals"]
        assert totals["model_sizing_failures"] == exits_mod.MODEL_SIZING_FAILURES
    finally:
        exits_mod.MODEL_SIZING_FAILURES -= 1
