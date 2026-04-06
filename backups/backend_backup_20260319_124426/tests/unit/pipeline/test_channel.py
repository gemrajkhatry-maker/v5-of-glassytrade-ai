"""Tests for the typed bounded channel."""
import asyncio
import pytest
from app.pipeline.channel import Channel


@pytest.mark.asyncio
async def test_send_and_receive():
    ch: Channel[str] = Channel("test", capacity=10)
    await ch.send("hello")
    msg = await ch.receive()
    assert msg == "hello"


@pytest.mark.asyncio
async def test_async_iteration():
    ch: Channel[int] = Channel("nums", capacity=10)
    for i in range(5):
        await ch.send(i)
    await ch.close()  # sends None sentinel

    received = []
    async for item in ch:
        received.append(item)
    assert received == [0, 1, 2, 3, 4]


@pytest.mark.asyncio
async def test_backpressure_send_nowait_full():
    ch: Channel[int] = Channel("small", capacity=2)
    assert await ch.send_nowait(1) is True
    assert await ch.send_nowait(2) is True
    assert await ch.send_nowait(3) is False  # full → dropped


@pytest.mark.asyncio
async def test_stats():
    ch: Channel[str] = Channel("stats_test", capacity=100)
    await ch.send("a")
    await ch.send("b")
    await ch.receive()
    stats = ch.stats
    assert stats["sent"] == 2
    assert stats["received"] == 1
    assert stats["qsize"] == 1


@pytest.mark.asyncio
async def test_backpressure_blocks():
    """Channel at capacity should block sender until consumer reads."""
    ch: Channel[int] = Channel("bp", capacity=1)
    await ch.send(1)  # fills channel

    sent = False

    async def slow_sender():
        nonlocal sent
        await ch.send(2)  # should block until consumer reads
        sent = True

    async def consumer():
        await asyncio.sleep(0.05)
        await ch.receive()  # unblocks sender

    await asyncio.gather(slow_sender(), consumer())
    assert sent is True
