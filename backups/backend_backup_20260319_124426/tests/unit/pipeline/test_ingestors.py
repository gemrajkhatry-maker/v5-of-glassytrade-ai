"""Tests for pluggable data source processors (no broker required)."""
import asyncio
import json
import pytest
import tempfile
from pathlib import Path
from datetime import datetime, timezone, timedelta

from app.pipeline.channel import Channel
from app.pipeline.processor import ProcessorConfig
from app.pipeline.processors.ingest import SimIngestor, FileReplayIngestor
from app.pipeline.message import RawTickPayload


IST = timezone(timedelta(hours=5, minutes=30))


@pytest.mark.asyncio
async def test_sim_ingestor_produces_ticks():
    """SimIngestor must produce RawTickMessages without any external dep."""
    ingestor = SimIngestor()
    config = ProcessorConfig(
        name="sim_test",
        processor_class="app.pipeline.processors.ingest.SimIngestor",
        outbox={"raw_ticks": "raw_ticks"},
        settings={
            "symbols": ["TEST"],
            "base_price": 100.0,
            "tick_interval": 0.0,
            "max_ticks": 5,
            "seed": 42,
        },
    )
    await ingestor.setup(config)

    out_ch: Channel = Channel("raw_ticks", capacity=100)
    task = asyncio.create_task(ingestor.process({}, {"raw_ticks": out_ch}))

    received = []
    for _ in range(5):
        msg = await asyncio.wait_for(out_ch.receive(), timeout=2.0)
        received.append(msg)
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)

    assert len(received) == 5
    for msg in received:
        assert isinstance(msg.payload, RawTickPayload)
        assert msg.payload.ltp > 0
        assert msg.symbol == "TEST"
        assert msg.payload.source == "sim"


@pytest.mark.asyncio
async def test_sim_ingestor_seeded_reproducibility():
    """Same seed must produce identical tick sequence."""
    async def collect(seed: int, n: int):
        ingestor = SimIngestor()
        config = ProcessorConfig(
            name="sim",
            processor_class="app.pipeline.processors.ingest.SimIngestor",
            outbox={"raw_ticks": "raw_ticks"},
            settings={"symbols": ["X"], "tick_interval": 0.0, "max_ticks": n, "seed": seed},
        )
        await ingestor.setup(config)
        ch: Channel = Channel("raw_ticks", capacity=100)
        task = asyncio.create_task(ingestor.process({}, {"raw_ticks": ch}))
        msgs = [await asyncio.wait_for(ch.receive(), timeout=2.0) for _ in range(n)]
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        return [m.payload.ltp for m in msgs]

    run1 = await collect(42, 10)
    run2 = await collect(42, 10)
    assert run1 == run2


@pytest.mark.asyncio
async def test_file_replay_ingestor_jsonl():
    """FileReplayIngestor reads JSONL tick file and produces correct messages."""
    ticks = [
        {"symbol": "CRUDE", "ltp": 100.0, "volume": 10, "timestamp": "2026-03-14T09:15:00+05:30"},
        {"symbol": "CRUDE", "ltp": 101.5, "volume": 20, "timestamp": "2026-03-14T09:16:00+05:30"},
        {"symbol": "CRUDE", "ltp": 100.8, "volume": 15, "timestamp": "2026-03-14T09:17:00+05:30"},
    ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".jsonl", delete=False) as f:
        for t in ticks:
            f.write(json.dumps(t) + "\n")
        tmp_path = f.name

    try:
        ingestor = FileReplayIngestor()
        config = ProcessorConfig(
            name="replay_test",
            processor_class="app.pipeline.processors.ingest.FileReplayIngestor",
            outbox={"raw_ticks": "raw_ticks"},
            settings={"file_path": tmp_path, "speed_multiplier": 0.0, "loop": False},
        )
        await ingestor.setup(config)

        ch: Channel = Channel("raw_ticks", capacity=100)
        await ingestor.process({}, {"raw_ticks": ch})

        received = []
        for _ in range(3):
            try:
                msg = ch._queue.get_nowait()
                received.append(msg)
            except Exception:
                break

        assert len(received) == 3
        assert received[0].payload.ltp == 100.0
        assert received[1].payload.ltp == 101.5
        assert received[2].symbol == "CRUDE"
        assert all(m.payload.source == "file" for m in received)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_file_replay_ingestor_missing_file():
    """FileReplayIngestor raises FileNotFoundError on missing file."""
    ingestor = FileReplayIngestor()
    config = ProcessorConfig(
        name="bad_replay",
        processor_class="app.pipeline.processors.ingest.FileReplayIngestor",
        outbox={"raw_ticks": "raw_ticks"},
        settings={"file_path": "/nonexistent/file.jsonl", "speed_multiplier": 1.0},
    )
    with pytest.raises(FileNotFoundError):
        await ingestor.setup(config)
