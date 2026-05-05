"""Live feed adapter for market data ingestion.

The implementation is deterministic and adapter-driven: a caller supplies an
iterator of ticks or a callable returning ticks. Tests and paper-mode simulations
can inject deterministic streams, while production can wire this to a websocket
adapter that yields already-normalized `Tick` objects.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Callable
import logging

from app.runtime.feeds import FeedSource
from app.runtime.pipeline.events import Tick

logger = logging.getLogger(__name__)


class LiveFeed(FeedSource):
    """Live market data feed.

    The feed does not hardcode exchange transport details. It only normalizes the
    provided tick source into the runtime contract.
    """

    def __init__(
        self,
        symbols: list[str],
        tick_source: Callable[[list[str]], Iterable[Tick]] | Iterable[Tick] | None = None,
        exchange: str = "NSE",
        strict_symbol_mode: bool = True,
    ):
        self._symbols = list(symbols)
        self._exchange = exchange
        self._tick_source = tick_source
        self._strict_symbol_mode = strict_symbol_mode
        self._running = False
        self._started = False
        self._cursor = 0
        if tick_source is None:
            self._sequence = None
        elif isinstance(tick_source, (list, tuple)):
            self._sequence = list(tick_source)
        else:
            self._sequence = None

    def name(self) -> str:
        return f"LiveFeed({self._exchange}, symbols={len(self._symbols)})"

    def start(self) -> None:
        self._running = True
        self._started = True
        logger.info("LiveFeed started for symbols: %s", ",".join(self._symbols))

    def stop(self) -> None:
        self._running = False
        logger.info("LiveFeed stopped")

    @property
    def symbols(self) -> list[str]:
        return list(self._symbols)

    def stream(self) -> Iterator[Tick]:
        if not self._started:
            self.start()
        if self._tick_source is None:
            logger.warning(
                "LiveFeed for symbols %s has no tick_source and will not emit ticks",
                ",".join(self._symbols) or "[]",
            )
            return iter(())
        if callable(self._tick_source):
            source_iter = iter(self._tick_source(self._symbols))
            for tick in source_iter:
                if not self._running:
                    break
                if self._symbols and tick.symbol not in self._symbols:
                    if self._strict_symbol_mode:
                        logging.debug("Ignoring unknown symbol tick: %s", tick.symbol)
                        continue
                yield tick
            return

        if self._sequence is None or self._cursor >= len(self._sequence):
            return iter(())

        source_iter = iter(self._sequence[self._cursor :])
        for tick in source_iter:
            self._cursor += 1
            if not self._running:
                break
            if self._symbols and tick.symbol not in self._symbols:
                if self._strict_symbol_mode:
                    logger.debug("Ignoring unknown symbol tick: %s", tick.symbol)
                    continue
            yield tick

    def snapshot(self) -> dict:
        return {
            "exchange": self._exchange,
            "strict_symbol_mode": self._strict_symbol_mode,
            "running": self._running,
            "started": self._started,
            "cursor": int(self._cursor),
            "symbols": list(self._symbols),
        }

    def restore(self, payload: dict) -> None:
        strict_symbol_mode = payload.get("strict_symbol_mode")
        if isinstance(strict_symbol_mode, bool):
            self._strict_symbol_mode = strict_symbol_mode
        symbols = payload.get("symbols")
        if isinstance(symbols, list):
            self._symbols = [str(symbol) for symbol in symbols if str(symbol)]
        cursor = payload.get("cursor")
        if isinstance(cursor, int):
            self._cursor = max(0, cursor)
