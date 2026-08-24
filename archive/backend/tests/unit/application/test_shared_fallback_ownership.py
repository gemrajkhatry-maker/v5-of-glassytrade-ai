from __future__ import annotations

from types import SimpleNamespace

from app.domain.ops.self_healing import get_shared_fallback_buffer


def test_storage_boundary_returns_one_shared_fallback_owner():
    storage = SimpleNamespace()
    first = get_shared_fallback_buffer(storage)
    second = get_shared_fallback_buffer(storage)
    assert first is second


def test_dual_storage_failure_marks_buffer_degraded(tmp_path):
    class BrokenPersistence:
        def fallback_spool_path(self):
            return str(tmp_path / "fallback.jsonl")

        def enqueue_fallback_write(self, *_args, **_kwargs):
            raise OSError("sqlite unavailable")

        def load_fallback_writes(self):
            return []

        def delete_fallback_write(self, *_args, **_kwargs):
            return None

    buffer = get_shared_fallback_buffer(BrokenPersistence())
    # Force the filesystem path itself to fail after construction.
    buffer._spool.append = lambda _item: (_ for _ in ()).throw(OSError("disk unavailable"))
    buffer.buffer_write("save_trade", {"position_id": "memory-only"})
    assert buffer.durability_degraded is True
    assert buffer.durability_status["memory_only_writes"] == 1
