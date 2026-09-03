"""F3 (block0): QuantCoordinator must shut down each engine's LLMAdvisor
worker when stopping an engine.

LLMAdvisor spawns a daemon worker thread in __init__ (gated by
``self._running``); ``shutdown()`` flips the flag but NOTHING called it on
the coordinator path — every rescan cycle leaked one spinning daemon thread
per stopped engine until process exit.

The fix is defensive: ``_stop_engine`` pops the engine and calls
``getattr(engine, "_advisor", None).shutdown()`` inside a guard so any
exception logs but never aborts the gateway close.
"""

import threading
import time

import pytest

from quant.multi_engine import QuantCoordinator


class _FakeWorkerAdvisor:
    """Mimics LLMAdvisor's contract: daemon worker thread + shutdown flag."""

    def __init__(self, registry=None):
        self._running = True
        self.registry = registry if registry is not None else []
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="FakeAdvisorWorker"
        )
        self._thread.start()

    def _loop(self):
        while self._running:
            time.sleep(0.005)

    def on_context(self, ctx):
        pass

    def set_emit_fn(self, fn):
        pass

    def shutdown(self):
        self.registry.append(id(self))
        self._running = False
        self._thread.join(timeout=2.0)


class _BrokenAdvisor:
    """shutdown() raises — the coordinator must log and continue."""

    def __init__(self):
        self.calls = 0

    def set_emit_fn(self, fn):
        pass

    def shutdown(self):
        self.calls += 1
        raise RuntimeError("boom")


class _MD:
    def get_nearest_futures(self, *a, **k):
        return None

    def get_lot_size(self, symbol):
        return 1.0

    async def fetch_history(self, *a, **k):
        return []


@pytest.fixture()
def coordinator(tmp_path):
    return QuantCoordinator(
        _MD(),
        config={
            "underlyings": [],
            "n": 1,
            "contracts_file": str(tmp_path / "c.json"),
            "session_levels_file": str(tmp_path / "session_levels.json"),
            "include_futures": False,
            "advisor_enabled": True,  # this test verifies advisor shutdown
        },
    )


def test_stop_engine_shuts_down_advisor_each_cycle(coordinator, monkeypatch):
    shutdowns: list[int] = []

    def _fake_advisor_factory(emit_fn=None):
        return _FakeWorkerAdvisor(shutdowns)

    import quant.wiring_advisor as wiring

    monkeypatch.setattr(wiring, "_ADVISOR_FACTORY", _fake_advisor_factory)    # Don't run engine loops (they'd block on next_tick forever and pollute
    # the thread-count baseline). Engines run on the coordinator's bounded
    # pool; suppressing the run task keeps pool workers from being occupied.
    # We are counting ADVISOR worker threads only — the leak F3 fixes.
    from quant.multi_engine import QuantCoordinator

    monkeypatch.setattr(
        QuantCoordinator, "_start_engine_loop", lambda self, engine: None
    )

    baseline = threading.active_count()
    for _ in range(3):
        eng = coordinator._spawn_engine("NIFTY AUG FUT")
        assert eng._advisor is not None
        coordinator._stop_engine("NIFTY AUG FUT")

    assert len(shutdowns) == 3, f"expected 3 advisor shutdowns, got {len(shutdowns)}"
    assert threading.active_count() == baseline, (
        "worker threads leaked across rescan cycles"
    )


def test_stop_engine_survives_broken_advisor_shutdown(coordinator, monkeypatch):
    broken = _BrokenAdvisor()

    def _broken_factory(emit_fn=None):
        return broken

    import quant.wiring_advisor as wiring

    monkeypatch.setattr(wiring, "_ADVISOR_FACTORY", _broken_factory)
    # Suppress the engine run task: this test exercises advisor shutdown on
    # stop, not the run loop (which would block a pool worker on next_tick).
    from quant.multi_engine import QuantCoordinator

    monkeypatch.setattr(
        QuantCoordinator, "_start_engine_loop", lambda self, engine: None
    )

    eng = coordinator._spawn_engine("NIFTY AUG FUT")
    assert eng._advisor is broken
    # Must NOT raise despite advisor.shutdown() blowing up.
    coordinator._stop_engine("NIFTY AUG FUT")
    assert broken.calls == 1
