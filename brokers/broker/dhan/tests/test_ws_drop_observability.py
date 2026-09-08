"""Regression tests for WebSocket feed drop observability.

Covers the backpressure path in DhanWebSocketClient._receive_loop:

- drops are counted and observable via dropped_message_count
- the oldest message is dropped (newest retained) so the queue cannot stall
- drop events surface in the client repr for ops visibility
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from dataclasses import FrozenInstanceError

from brokers.broker.dhan.infrastructure.websocket_client import DhanWebSocketClient
from brokers.broker.dhan.ports import WSMessage


def _msg(security_id: str = "1333") -> WSMessage:
    return WSMessage(
        type="tick",
        data={"security_id": security_id, "ltp": 100.0},
        timestamp=datetime.now(),
    )


def test_drop_counter_starts_at_zero():
    client = DhanWebSocketClient()
    assert client.dropped_message_count == 0


def test_queue_overflow_counts_drops_and_keeps_newest():
    client = DhanWebSocketClient()

    async def _run() -> None:
        client._message_queue = asyncio.Queue(maxsize=1)
        # Fill the queue; a second message must overflow and drop the oldest.
        client._message_queue.put_nowait(_msg("first"))
        client._enqueue_message(_msg("second"))
        client._enqueue_message(_msg("third"))

        assert client.dropped_message_count == 2
        assert client._message_queue.qsize() == 1
        health = client.health_snapshot
        assert health.received == 2
        assert health.dropped == 2
        assert health.queue_depth == 1
        # The oldest message is dropped; the newest survives.
        surviving = client._message_queue.get_nowait()
        assert surviving.data["security_id"] == "third"

    asyncio.run(_run())


def test_no_drops_when_queue_has_room():
    client = DhanWebSocketClient()

    async def _run() -> None:
        client._message_queue = asyncio.Queue(maxsize=10)
        client._enqueue_message(_msg("a"))
        client._enqueue_message(_msg("b"))
        assert client.dropped_message_count == 0
        assert client._message_queue.qsize() == 2

    asyncio.run(_run())


def test_repr_exposes_drop_count():
    client = DhanWebSocketClient()
    client._dropped_message_count = 7
    assert "dropped=7" in repr(client)


def test_health_snapshot_exposes_raw_feed_counters_and_queue_state():
    client = DhanWebSocketClient()

    async def _run() -> None:
        client._message_queue = asyncio.Queue(maxsize=3)
        client._enqueue_message(_msg("first"))
        client._enqueue_message(_msg("second"))

        health = client.health_snapshot

        assert health.received == 2
        assert health.processed == 0
        assert health.dropped == 0
        assert health.queue_depth == 2
        assert health.queue_capacity == 3
        assert health.reconnect_count == 0

    asyncio.run(_run())


def test_health_snapshot_counts_messages_when_consumed():
    client = DhanWebSocketClient()

    async def _run() -> None:
        client._message_queue = asyncio.Queue(maxsize=3)
        client._enqueue_message(_msg("only"))

        message = await anext(client.messages())

        assert message.data["security_id"] == "only"
        assert client.health_snapshot.processed == 1
        assert client.health_snapshot.queue_depth == 0

    asyncio.run(_run())


def test_health_snapshot_is_immutable():
    client = DhanWebSocketClient()

    try:
        client.health_snapshot.received = 1
    except FrozenInstanceError:
        pass
    else:
        raise AssertionError("health snapshots must be immutable")


def test_health_snapshot_counts_reconnect_attempts():
    class _ReconnectableClient(DhanWebSocketClient):
        async def connect(self) -> None:
            self._connected = True

    client = _ReconnectableClient(reconnect_delay=0, max_reconnect_attempts=1)

    asyncio.run(client._attempt_reconnect())

    assert client.health_snapshot.reconnect_count == 1
