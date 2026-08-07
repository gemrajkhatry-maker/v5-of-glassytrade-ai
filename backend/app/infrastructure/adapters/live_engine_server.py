"""Standalone live engine runner — QuantEngine over Dhan, broadcast over WS."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import pathlib
import sys
import threading

_here = pathlib.Path(__file__).resolve()
for _ancestor in _here.parents:
    if (_ancestor / "quant").is_dir() and (_ancestor / "brokers").is_dir():
        for _p in (str(_ancestor), str(_ancestor / "backend")):
            if _p not in sys.path:
                sys.path.insert(0, _p)
        break

import websockets
from websockets.exceptions import ConnectionClosed

from quant.runtime import QuantEngine
from quant.ws_adapter import view_state_to_ws

from app.infrastructure.adapters.dhan_adapter import DhanMarketDataAdapter
from app.infrastructure.adapters.live_gateway import LiveGateway

logger = logging.getLogger(__name__)


def _make_adapter() -> DhanMarketDataAdapter:
    return DhanMarketDataAdapter(
        client_id=os.getenv("DHAN_CLIENT_ID"),
        access_token=os.getenv("DHAN_ACCESS_TOKEN"),
        exchange="NFO",
    )


def run_live_engine(
    symbol: str,
    interval_seconds: int = 60,
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    """Run QuantEngine on a background thread and broadcast projected state over WS."""
    gateway = LiveGateway(_make_adapter(), symbol)
    engine = QuantEngine(gateway, symbol, interval_seconds=interval_seconds)

    stop = threading.Event()

    def drive() -> None:
        try:
            engine.run()
        finally:
            stop.set()

    threading.Thread(target=drive, name="quant-engine", daemon=True).start()

    async def broadcast(ws) -> None:
        while not stop.is_set():
            snapshot = json.dumps(view_state_to_ws(engine.projector.snapshot(symbol)))
            await ws.send(snapshot)
            await asyncio.sleep(1.0)

    async def handler(ws) -> None:
        try:
            await broadcast(ws)
        except ConnectionClosed:
            pass

    async def serve() -> None:
        async with websockets.serve(handler, host, port):
            while not stop.is_set():
                await asyncio.sleep(0.5)

    try:
        asyncio.run(serve())
    except KeyboardInterrupt:
        logger.info("Received SIGINT, shutting down")
    finally:
        stop.set()
        gateway.close()
        logger.info("Engine stopped")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the standalone live quant engine.")
    parser.add_argument("--symbol", default="NIFTY")
    parser.add_argument("--interval", type=int, default=60)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    run_live_engine(args.symbol, interval_seconds=args.interval, host=args.host, port=args.port)
