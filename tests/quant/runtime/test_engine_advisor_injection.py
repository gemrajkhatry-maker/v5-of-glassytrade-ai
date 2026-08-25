"""F4 (block0): QuantEngine must NOT sniff MLX_MODEL_PATH/MLX_ADAPTER_PATH
inside __init__. Environment reads in the deterministic replay engine break
backtest determinism and spawn an LLMAdvisor daemon thread on EVERY
construction (replay loops leaked one thread per run).

Contract after the fix:
- QuantEngine(advisor=None) [default] starts NO advisor thread.
- An injected advisor is used as-is.
- Only the live wiring path (quant.wiring_advisor.build_live_advisor) reads
  MLX_* env vars.
"""

import threading

from quant.runtime import QuantEngine
from tests.helpers.synthetic import SyntheticGateway
from tests.quant.runtime.test_runtime import _ticks


def _baseline_threads() -> int:
    return threading.active_count()


def test_default_construction_starts_no_advisor_thread():
    before = _baseline_threads()
    eng = QuantEngine(SyntheticGateway(_ticks()), "SYM", interval_seconds=1)
    after = _baseline_threads()
    assert getattr(eng, "_advisor", None) is None, (
        "default QuantEngine must have no advisor"
    )
    assert after == before, (
        f"thread count changed across construction: {before} -> {after}"
    )


def test_env_vars_alone_do_not_spawn_an_advisor_thread(monkeypatch):
    monkeypatch.setenv("MLX_MODEL_PATH", "/tmp/fake-mlx-model")
    monkeypatch.setenv("MLX_ADAPTER_PATH", "/tmp/fake-mlx-adapter")
    before = _baseline_threads()
    eng = QuantEngine(SyntheticGateway(_ticks()), "SYM", interval_seconds=1)
    after = _baseline_threads()
    assert eng._advisor is None
    assert after == before, (
        "engine must not consult MLX_* env vars at construction time"
    )


def test_injected_advisor_is_used_and_no_extra_thread_leaks():
    class _StubAdvisor:
        def __init__(self):
            self.calls = []

        def on_context(self, ctx):
            self.calls.append(ctx)

        def shutdown(self):
            pass

    stub = _StubAdvisor()
    before = _baseline_threads()
    eng = QuantEngine(SyntheticGateway(_ticks()), "SYM", interval_seconds=1,
                      advisor=stub)
    assert after_thread_count_unchanged(before), "stub advisor started a thread?"
    assert eng._advisor is stub


def after_thread_count_unchanged(before: int) -> bool:
    return threading.active_count() == before
