from __future__ import annotations


from quant.multi_engine import QuantCoordinator


def test_coordinator_snapshot_includes_effective_risk_policy():
    import threading

    from quant.runtime import QuantEngine
    from tests.helpers.synthetic import SyntheticGateway

    coordinator = object.__new__(QuantCoordinator)
    coordinator._lock = threading.RLock()
    engine = QuantEngine(
        SyntheticGateway([]),
        "NIFTY",
        interval_seconds=1,
        risk_per_trade_pct=0.0037,
        max_daily_loss_pct=0.013,
        max_consecutive_losses=7,
    )
    assert engine.event_store.get_all() == []
    coordinator._engines = {"NIFTY": engine}

    risk = coordinator.snapshot("NIFTY")["riskState"]

    assert risk["baseRiskPct"] == 0.0037
    assert risk["effectiveBaseRiskPct"] == 0.0025
    assert risk["riskPerTradePct"] == 0.0025
    assert risk["maxDailyLossPct"] == 0.013
    assert risk["maxConsecutiveLosses"] == 7
    assert risk["effectiveHmpTier"] == "CONSERVATIVE"


def test_snapshot_does_not_fallback_to_mutable_engine_state(monkeypatch):
    coordinator = object.__new__(QuantCoordinator)
    coordinator._lock = __import__("threading").RLock()
    engine = type("Engine", (), {})()
    engine.event_store = type("Store", (), {"fold": lambda self: (_ for _ in ()).throw(ValueError("corrupt fold"))})()
    engine.state = type("State", (), {"symbol": "NIFTY"})()
    engine.live_cache = type("Cache", (), {"snapshot": lambda self, symbol: type("Live", (), {
        "ltp": None, "oi": None, "depth": None, "tick": None,
    })()})()
    engine.latest_agent_decision = None
    coordinator._engines = {"NIFTY": engine}

    snapshot = coordinator.snapshot("NIFTY")
    assert snapshot["portfolio"]["positions"] == []
    assert snapshot["riskState"]["canonicalState"] == "DEGRADED_CANONICAL_FOLD_UNAVAILABLE"


def test_snapshot_marks_append_degraded_state(monkeypatch):
    coordinator = object.__new__(QuantCoordinator)
    coordinator._lock = __import__("threading").RLock()
    engine = type("Engine", (), {})()
    from quant.event_store import EventStore
    engine.event_store = EventStore()
    engine.persistence_degraded = True
    engine.persistence_failure = OSError("disk full")
    engine.live_cache = type("Cache", (), {"snapshot": lambda self, symbol: type("Live", (), {
        "ltp": None, "oi": None, "depth": None, "tick": None,
    })()})()
    engine.latest_agent_decision = None
    engine.latest_depth = None
    coordinator._engines = {"NIFTY": engine}

    snapshot = coordinator.snapshot("NIFTY")
    assert snapshot["riskState"]["canonicalState"] == "DEGRADED_EVENT_APPEND_FAILED"


def test_degraded_snapshot_tolerates_optional_engine_projection_fields():
    coordinator = object.__new__(QuantCoordinator)
    coordinator._lock = __import__("threading").RLock()
    engine = type("Engine", (), {})()
    from quant.event_store import EventStore
    engine.event_store = EventStore()
    engine.persistence_degraded = True
    engine.persistence_failure = OSError("disk full")
    engine.live_cache = type("Cache", (), {"snapshot": lambda self, symbol: type("Live", (), {
        "ltp": None, "oi": None, "depth": None, "tick": None,
    })()})()
    coordinator._engines = {"NIFTY": engine}

    snapshot = coordinator.snapshot("NIFTY")
    assert snapshot["riskState"]["canonicalState"] == "DEGRADED_EVENT_APPEND_FAILED"
