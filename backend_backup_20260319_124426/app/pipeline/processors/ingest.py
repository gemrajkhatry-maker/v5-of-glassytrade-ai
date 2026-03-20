"""Data ingestion processors — the pluggable data source layer.

Any processor here produces RawTickMessage. The rest of the pipeline
is identical regardless of which ingestor is used.

Available ingestors:
  DhanWsIngestor   — live Dhan WebSocket stream (production)
  RestPollIngestor — REST LTP polling (MCX OPTFUT fallback)
  FileReplayIngestor — replays a recorded tick file (backtesting/dev)
  SimIngestor      — synthetic random ticks (unit testing)
"""
from __future__ import annotations

import asyncio
import csv
import json
import logging
import random
from datetime import datetime, timezone, timedelta
from pathlib import Path

from app.pipeline.channel import Channel
from app.pipeline.message import Message, RawTickPayload
from app.pipeline.processor import BaseProcessor, ProcessorConfig

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))


class DhanWsIngestor(BaseProcessor):
    """Streams live ticks from Dhan WebSocket. Produces RawTickMessage."""

    name = "dhan_ws_ingestor"

    async def setup(self, config: ProcessorConfig) -> None:
        await super().setup(config)
        self._symbols: list[str] = config.settings.get("symbols", [])
        self._market_data = None  # injected via settings at runtime

    async def process(self, inbox: dict[str, Channel], outbox: dict[str, Channel]) -> None:
        from app.infrastructure.adapters.dhan_adapter import DhanMarketDataAdapter
        adapter = DhanMarketDataAdapter()
        out = outbox["raw_ticks"]

        while True:
            try:
                async for pkt in adapter.stream_full(self._symbols):
                    msg = Message(
                        payload=RawTickPayload(
                            ltp=float(pkt.get("ltp", 0)),
                            volume=int(pkt.get("volume", 0)),
                            ltq=int(pkt.get("ltq", 0)),
                            oi=int(pkt.get("oi", 0)),
                            total_buy_qty=int(pkt.get("total_buy_qty", 0)),
                            total_sell_qty=int(pkt.get("total_sell_qty", 0)),
                            depth_bids=tuple(
                                (b["price"], b["qty"]) for b in pkt.get("depth_bids", [])
                            ),
                            depth_asks=tuple(
                                (a["price"], a["qty"]) for a in pkt.get("depth_asks", [])
                            ),
                            source="ws",
                        ),
                        symbol=pkt.get("symbol", self._symbols[0] if self._symbols else ""),
                        timestamp=datetime.now(IST),
                        source_processor=self.name,
                    )
                    await out.send(msg)
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning("[%s] WS error, reconnecting in 5s: %s", self.name, e)
                await asyncio.sleep(5)


class RestPollIngestor(BaseProcessor):
    """REST LTP polling fallback. Produces RawTickMessage every poll_interval seconds.

    Use when WS feed is unavailable (e.g. MCX OPTFUT on Dhan WS).
    Identical output schema to DhanWsIngestor — rest of pipeline unchanged.
    """

    name = "rest_poll_ingestor"

    async def setup(self, config: ProcessorConfig) -> None:
        await super().setup(config)
        self._symbols: list[str] = config.settings.get("symbols", [])
        self._poll_interval: float = float(config.settings.get("poll_interval", 3.0))

    async def process(self, inbox: dict[str, Channel], outbox: dict[str, Channel]) -> None:
        from app.infrastructure.adapters.dhan_adapter import DhanMarketDataAdapter
        adapter = DhanMarketDataAdapter()
        out = outbox["raw_ticks"]

        logger.info("[%s] REST polling %d symbol(s) every %.1fs", self.name, len(self._symbols), self._poll_interval)
        async for pkt in adapter.stream_poll(self._symbols, poll_interval=self._poll_interval):
            msg = Message(
                payload=RawTickPayload(
                    ltp=float(pkt.get("ltp", 0)),
                    volume=0,
                    source="poll",
                ),
                symbol=pkt.get("symbol", self._symbols[0] if self._symbols else ""),
                timestamp=datetime.now(IST),
                source_processor=self.name,
            )
            await out.send(msg)


class FileReplayIngestor(BaseProcessor):
    """Replays a recorded tick file (CSV or JSONL). Produces RawTickMessage.

    Guaranteed to produce identical output from identical input — enables
    deterministic backtesting. Supports speed_multiplier for fast/slow replay.
    """

    name = "file_replay_ingestor"

    async def setup(self, config: ProcessorConfig) -> None:
        await super().setup(config)
        self._file_path = Path(config.settings["file_path"])
        self._speed: float = float(config.settings.get("speed_multiplier", 1.0))
        self._loop: bool = bool(config.settings.get("loop", False))
        if not self._file_path.exists():
            raise FileNotFoundError(f"Tick file not found: {self._file_path}")

    async def process(self, inbox: dict[str, Channel], outbox: dict[str, Channel]) -> None:
        out = outbox["raw_ticks"]
        suffix = self._file_path.suffix.lower()

        while True:
            last_ts: datetime | None = None

            rows = []
            if suffix == ".csv":
                with self._file_path.open() as f:
                    rows = list(csv.DictReader(f))
            else:
                with self._file_path.open() as f:
                    rows = [json.loads(line) for line in f if line.strip()]

            for row in rows:
                ts_str = row.get("timestamp", "")
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00")).astimezone(IST)
                except Exception:
                    ts = datetime.now(IST)

                # Replay at correct speed
                if last_ts is not None and self._speed > 0:
                    gap = (ts - last_ts).total_seconds()
                    if gap > 0:
                        await asyncio.sleep(gap / self._speed)
                last_ts = ts

                msg = Message(
                    payload=RawTickPayload(
                        ltp=float(row.get("ltp", 0)),
                        volume=int(float(row.get("volume", 0))),
                        oi=int(float(row.get("oi", 0))),
                        total_buy_qty=int(float(row.get("total_buy_qty", 0))),
                        total_sell_qty=int(float(row.get("total_sell_qty", 0))),
                        source="file",
                    ),
                    symbol=row.get("symbol", ""),
                    timestamp=ts,
                    source_processor=self.name,
                )
                await out.send(msg)

            if not self._loop:
                logger.info("[%s] File replay complete: %d ticks", self.name, len(rows))
                break
            logger.info("[%s] Looping file replay", self.name)


class SimIngestor(BaseProcessor):
    """Synthetic tick generator for unit tests and development.

    Produces realistic-looking ticks without any external dependency.
    Seeded for reproducibility: SimIngestor(seed=42) always produces the same sequence.
    """

    name = "sim_ingestor"

    async def setup(self, config: ProcessorConfig) -> None:
        await super().setup(config)
        self._symbols: list[str] = config.settings.get("symbols", ["SIM_SYMBOL"])
        self._base_price: float = float(config.settings.get("base_price", 100.0))
        self._tick_interval: float = float(config.settings.get("tick_interval", 1.0))
        self._seed: int | None = config.settings.get("seed")
        self._max_ticks: int = int(config.settings.get("max_ticks", 0))  # 0 = infinite
        self._rng = random.Random(self._seed)

    async def process(self, inbox: dict[str, Channel], outbox: dict[str, Channel]) -> None:
        out = outbox["raw_ticks"]
        price = self._base_price
        tick_count = 0

        while self._max_ticks == 0 or tick_count < self._max_ticks:
            price *= (1 + self._rng.gauss(0, 0.001))
            price = max(price, 0.01)
            vol = self._rng.randint(10, 500)
            buy_vol = self._rng.randint(0, vol)

            for sym in self._symbols:
                msg = Message(
                    payload=RawTickPayload(
                        ltp=round(price, 2),
                        volume=vol,
                        ltq=self._rng.randint(1, 20),
                        oi=self._rng.randint(1000, 50000),
                        total_buy_qty=buy_vol,
                        total_sell_qty=vol - buy_vol,
                        source="sim",
                    ),
                    symbol=sym,
                    timestamp=datetime.now(IST),
                    source_processor=self.name,
                    pipeline_id=self._settings.get("pipeline_id", "sim"),
                )
                await out.send(msg)
            tick_count += 1
            await asyncio.sleep(self._tick_interval)
