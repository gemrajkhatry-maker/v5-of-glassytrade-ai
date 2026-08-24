from __future__ import annotations

from unittest.mock import Mock

from app.domain.ops.self_healing import DBFallbackBuffer


def test_fallback_flush_supports_open_positions_and_preserves_fifo_on_failure():
    buffer = DBFallbackBuffer()
    buffer.buffer_write("save_open_position", {"id": "open-1"})
    buffer.buffer_write("save_trade", {"id": "trade-1"})

    storage = Mock()
    storage.save_open_position.side_effect = RuntimeError("database offline")
    storage.save_trade.return_value = None

    assert buffer.try_flush(storage) == 0
    assert buffer.buffer_size == 2
    assert buffer.get_stats()["flush_successes"] == 0
    storage.save_trade.assert_not_called()


def test_fallback_flush_replays_fifo_after_storage_recovers():
    buffer = DBFallbackBuffer()
    buffer.buffer_write("save_open_position", {"id": "open-1"})
    buffer.buffer_write("save_trade", {"id": "trade-1"})

    calls: list[str] = []
    storage = Mock()

    def save_open_position(payload):
        calls.append(f"open:{payload['id']}")

    def save_trade(payload):
        calls.append(f"trade:{payload['id']}")

    storage.save_open_position.side_effect = save_open_position
    storage.save_trade.side_effect = save_trade

    assert buffer.try_flush(storage) == 2
    assert buffer.buffer_size == 0
    assert calls == ["open:open-1", "trade:trade-1"]
    assert buffer.get_stats()["flush_successes"] == 2
