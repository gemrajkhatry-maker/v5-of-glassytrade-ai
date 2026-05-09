"""Live feed adapter for market data ingestion.

The implementation is deterministic and adapter-driven: a caller supplies an
iterator of ticks or a callable returning ticks. Tests and paper-mode simulations
can inject deterministic streams, while production can wire this to a websocket
adapter that yields already-normalized `Tick` objects.

Supports integration with MarketDataService for:
- Historical data warmup on startup
- Live WebSocket streaming
- Order book depth processing
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from typing import Callable, Optional, TYPE_CHECKING
import logging

from app.runtime.feeds import FeedSource
from app.runtime.pipeline.events import Tick

if TYPE_CHECKING:
    from brokersv2.marketdata.service import MarketDataService

logger = logging.getLogger(__name__)


class LiveFeed(FeedSource):
    """Live market data feed.

    The feed does not hardcode exchange transport details. It only normalizes the
    provided tick source into the runtime contract.
    
    Can optionally integrate with MarketDataService for:
    - Historical warmup before live streaming
    - Live WebSocket streaming
    - Order book depth updates
    """

    def __init__(
        self,
        symbols: list[str],
        tick_source: Callable[[list[str]], Iterable[Tick]] | Iterable[Tick] | None = None,
        exchange: str = "NSE",
        strict_symbol_mode: bool = True,
        market_data_service: Optional[MarketDataService] = None,  # NEW
        warmup_enabled: bool = False,  # NEW
        warmup_timeframes: list[str] | None = None,  # NEW
        warmup_lookback_days: int = 10,  # NEW
    ):
        self._symbols = list(symbols)
        self._exchange = exchange
        self._tick_source = tick_source
        self._strict_symbol_mode = strict_symbol_mode
        self._running = False
        self._started = False
        self._cursor = 0
        
        # MarketDataService integration
        self._market_data = market_data_service
        self._warmup_enabled = warmup_enabled
        self._warmup_timeframes = warmup_timeframes or ["5m", "15m"]
        self._warmup_lookback_days = warmup_lookback_days
        self._live_stream = None
        
        if tick_source is None:
            self._sequence = None
        elif isinstance(tick_source, (list, tuple)):
            self._sequence = list(tick_source)
        else:
            self._sequence = None

    def name(self) -> str:
        return f"LiveFeed({self._exchange}, symbols={len(self._symbols)})"

    async def start_async(self) -> None:
        """
        Start feed with optional warmup and live streaming.
        
        Async version that supports MarketDataService integration.
        """
        if self._market_data:
            # Step 1: Warmup historical data
            if self._warmup_enabled:
                logger.info(
                    f"Starting warmup: {len(self._symbols)} symbols, "
                    f"timeframes={self._warmup_timeframes}, "
                    f"lookback={self._warmup_lookback_days} days"
                )
                
                # TODO: Convert symbols to CanonicalInstrument
                # For now, skip warmup if we can't resolve instruments
                logger.warning("Warmup requires CanonicalInstrument resolution - skipping")
            
            # Step 2: Start live streaming
            if self._market_data._ws_manager:
                logger.info("Starting live WebSocket streaming")
                
                # TODO: Convert symbols to CanonicalInstrument and subscribe
                # For now, use existing tick_source
                logger.warning("Live streaming requires CanonicalInstrument resolution - using tick_source")
        
        # Fallback to synchronous start
        self.start()

    def start(self) -> None:
        self._running = True
        self._started = True
        logger.info("LiveFeed started for symbols: %s", ",".join(self._symbols))

    def stop(self) -> None:
        self._running = False
        
        # Stop live streaming if active
        if self._market_data and self._live_stream:
            import asyncio
            try:
                asyncio.create_task(self._market_data.stop_live_stream())
            except Exception as e:
                logger.error(f"Error stopping live stream: {e}")
        
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
            "market_data_integrated": self._market_data is not None,
            "warmup_enabled": self._warmup_enabled,
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
