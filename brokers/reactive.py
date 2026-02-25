"""
Reactive Broker - RxPY Observable Implementation.

Provides reactive streaming endpoints using RxPY Observables.
This allows for powerful reactive programming patterns like:
- Operators (map, filter, throttle, buffer, etc.)
- Composing multiple streams
- Error handling and retry logic
- Backpressure management

Usage:
    from brokers.reactive import ReactiveBroker
    
    broker = ReactiveBroker.dhan()
    
    # Subscribe to ticker stream
    broker.ticker_stream(['RELIANCE', 'TCS']).subscribe(
        on_next=lambda tick: print(f"{tick.symbol}: {tick.price}"),
        on_error=lambda e: print(f"Error: {e}"),
        on_completed=lambda: print("Done")
    )
    
    # With operators
    (broker.ticker_stream(['RELIANCE'])
        .pipe(
            ops.filter(lambda t: t.volume > 1000),
            ops.throttle_first(1.0),  # Max 1 update per second
            ops.map(lambda t: f"{t.symbol}: {t.price}")
        )
        .subscribe(print)
    )
"""
from typing import List, Optional, TypeVar, Callable, Any, Union, Tuple, Dict
from datetime import datetime
import asyncio
import threading

# Type variables
T = TypeVar('T')

# Try to import RxPY
try:
    from rx import Observable, create, from_iterable
    from rx import operators as ops
    from rx.subject import Subject, BehaviorSubject
    from rx.disposable import Disposable
    RXPY_AVAILABLE = True
except ImportError:
    RXPY_AVAILABLE = False
    Observable = Any
    ops = None
    Subject = Any
    BehaviorSubject = Any
    Disposable = Any

from brokers.broker.ports import IBrokerPort, IReactiveBroker, IAsyncOptionChainProvider
from brokers.broker.entities import Instrument, Quote, Tick, Order, Position, OptionChain
from brokers.broker.types import Exchange


class ReactiveBroker(IReactiveBroker):
    """
    Reactive wrapper around any IBrokerPort implementation.
    
    Converts async iterators to RxPY Observables, enabling:
    - Functional reactive programming
    - Stream composition and transformation
    - Built-in operators (filter, map, throttle, buffer, etc.)
    - Error handling and retry logic
    
    Example:
        broker = ReactiveBroker.dhan()
        
        # Simple subscription
        broker.ticker_stream(['TCS']).subscribe(
            on_next=lambda t: print(f"{t.symbol}: {t.price}")
        )
        
        # With operators
        (broker.ticker_stream(['TCS'])
            .pipe(
                ops.filter(lambda t: t.price > 100),
                ops.buffer_with_time(1.0),  # Batch 1 second
            )
            .subscribe(print)
        )
    """
    
    def __init__(self, broker: IBrokerPort):
        """
        Initialize reactive broker wrapper.
        
        Args:
            broker: The underlying broker implementation
        """
        if not RXPY_AVAILABLE:
            raise ImportError(
                "RxPY is required for reactive streams. "
                "Install with: pip install rx"
            )
        self._broker = broker
        self._order_subject: Optional[Subject] = None
        self._position_subject: Optional[Subject] = None
    
    # -------------------------------------------------------------------------
    # Factory Methods
    # -------------------------------------------------------------------------
    
    @classmethod
    def wrap(cls, broker: IBrokerPort) -> 'ReactiveBroker':
        """Wrap an existing broker instance."""
        return cls(broker)
    
    @classmethod
    def paper(cls, **kwargs) -> 'ReactiveBroker':
        """Create reactive broker with paper trading."""
        from brokers.broker.paper import PaperBroker
        return cls(PaperBroker(**kwargs))
    
    @classmethod
    def dhan(
        cls,
        client_id: Optional[str] = None,
        access_token: Optional[str] = None,
        **kwargs
    ) -> 'ReactiveBroker':
        """Create reactive broker with Dhan."""
        from brokers.broker.dhan import DhanBroker
        return cls(DhanBroker.create(
            client_id=client_id,
            access_token=access_token,
            **kwargs
        ))
    
    # -------------------------------------------------------------------------
    # Shared Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _to_instruments(
        symbols: Union[List[str], List[Instrument]],
        exchange: Exchange,
    ) -> List[Instrument]:
        """Convert symbol strings or Instrument objects to a uniform list."""
        if symbols and isinstance(symbols[0], Instrument):
            return list(symbols)
        return [
            Instrument(symbol=s, exchange=exchange, security_id="")
            for s in symbols
        ]

    @staticmethod
    def _create_async_observable(async_gen_factory: Callable) -> Observable:
        """
        Create an Observable from an async generator factory.

        Single implementation for the subscribe-in-thread pattern used by
        all async streaming endpoints. Handles cancellation correctly:
        the dispose callback cancels the running task, allowing the event
        loop to shut down cleanly without corrupting aiohttp sessions.

        Args:
            async_gen_factory: Callable that returns an async generator
                               (e.g., lambda: self._broker.stream_ticker(instruments))
        """
        def _subscribe(observer, scheduler=None):
            task_ref: List = []
            loop_ref: List = []

            async def _run():
                try:
                    async for item in async_gen_factory():
                        observer.on_next(item)
                except asyncio.CancelledError:
                    pass
                except Exception as e:
                    observer.on_error(e)
                    return
                observer.on_completed()

            def _thread_target():
                loop = asyncio.new_event_loop()
                loop_ref.append(loop)
                asyncio.set_event_loop(loop)
                task = loop.create_task(_run())
                task_ref.append(task)
                try:
                    loop.run_until_complete(task)
                except asyncio.CancelledError:
                    pass
                finally:
                    pending = asyncio.all_tasks(loop)
                    for t in pending:
                        t.cancel()
                    if pending:
                        loop.run_until_complete(
                            asyncio.gather(*pending, return_exceptions=True)
                        )
                    loop.close()

            thread = threading.Thread(target=_thread_target, daemon=True)
            thread.start()

            def _dispose():
                if task_ref and loop_ref:
                    task = task_ref[0]
                    loop = loop_ref[0]
                    if not loop.is_closed():
                        loop.call_soon_threadsafe(task.cancel)

            return Disposable(_dispose)

        return create(_subscribe)

    # -------------------------------------------------------------------------
    # Observable Streams
    # -------------------------------------------------------------------------
    
    def ticker_stream(
        self,
        symbols: Union[List[str], List[Instrument]],
        exchange: Exchange = Exchange.NSE
    ) -> Observable:
        """
        Create Observable of ticker updates.
        
        Accepts either symbol strings (resolved via symbol mapper) or
        pre-built Instrument objects (e.g. from option chain with security_id).
        
        Args:
            symbols: List of trading symbols (str) or Instrument objects.
                     When passing Instrument objects with security_id set,
                     symbol resolution is skipped (required for option contracts).
            exchange: Exchange (default: NSE). Ignored when passing Instruments.
            
        Returns:
            Observable[Tick] - emits Tick objects
            
        Usage:
            # Equity by symbol name
            broker.ticker_stream(['TCS', 'RELIANCE']).subscribe(...)
            
            # Option contracts by human-readable symbol (after getting chain)
            chain = broker.broker.get_option_chain('NIFTY', Exchange.NFO)
            atm_ce = chain.calls[chain.atm_strike]
            broker.ticker_stream([atm_ce.symbol], Exchange.NFO).subscribe(...)
        """
        instruments = self._to_instruments(symbols, exchange)
        return self._create_async_observable(
            lambda: self._broker.stream_ticker(instruments)
        )
    
    def quote_stream(
        self,
        symbols: Union[List[str], List[Instrument]],
        exchange: Exchange = Exchange.NSE
    ) -> Observable:
        """
        Create Observable of quote updates.

        Accepts either symbol strings or pre-built Instrument objects.

        Args:
            symbols: List of trading symbols (str) or Instrument objects.
                     When passing Instrument objects with security_id set,
                     symbol resolution is skipped (required for option contracts).
            exchange: Exchange (default: NSE). Ignored when passing Instruments.

        Returns:
            Observable[Quote] - emits Quote objects
        """
        instruments = self._to_instruments(symbols, exchange)
        return self._create_async_observable(
            lambda: self._broker.stream_quotes(instruments)
        )

    def depth_stream(
        self,
        symbols: Union[List[str], List[Instrument]],
        exchange: Exchange = Exchange.NSE,
        depth_level: int = 20,
    ) -> Observable:
        """
        Observable of market depth updates.

        depth_level=20  → dedicated 20-level depth feed (up to 50 instruments)
        depth_level=200 → dedicated 200-level depth feed (1 instrument only)
        depth_level=5   → 5-level depth via the regular market feed

        Each emission is a MarketDepth for one side (bid or ask) with the
        symbol name backfilled from the instrument map.

        Args:
            symbols: Trading symbol strings or Instrument objects.
            exchange: Exchange (default: NSE).
            depth_level: 5, 20, or 200.

        Returns:
            Observable[MarketDepth]
        """
        instruments = self._to_instruments(symbols, exchange)
        return self._create_async_observable(
            lambda: self._broker.stream_depth(instruments, depth_level)
        )

    def depth_20_stream(
        self,
        symbols: Union[List[str], List[Instrument]],
        exchange: Exchange = Exchange.NSE,
    ) -> Observable:
        """
        Observable of 20-level market depth via the dedicated depth feed.

        Supports up to 50 NSE instruments per subscription. Each emission
        is a MarketDepth for one side (bid or ask) with symbol backfilled.

        Args:
            symbols: Trading symbol strings or Instrument objects.
            exchange: Exchange (default: NSE).

        Returns:
            Observable[MarketDepth]
        """
        instruments = self._to_instruments(symbols, exchange)
        return self._create_async_observable(
            lambda: self._broker.stream_depth_20(instruments)
        )

    def depth_200_stream(
        self,
        symbol: Union[str, Instrument],
        exchange: Exchange = Exchange.NSE,
    ) -> Observable:
        """
        Observable of 200-level market depth via the full-depth feed.

        Only 1 instrument per connection (Dhan server limit). Each emission
        is a MarketDepth for one side (bid or ask) with symbol backfilled.

        Args:
            symbol: A single trading symbol (str) or Instrument object.
            exchange: Exchange (default: NSE).

        Returns:
            Observable[MarketDepth]
        """
        instruments = self._to_instruments(
            [symbol] if isinstance(symbol, str) else [symbol], exchange
        )
        return self._create_async_observable(
            lambda: self._broker.stream_depth_200(instruments)
        )

    def full_stream(
        self,
        symbols: Union[List[str], List[Instrument]],
        exchange: Exchange = Exchange.MCX,
    ) -> Observable:
        """
        Observable of raw FULL packets for any exchange segment (including MCX).

        Use for MCX instruments where stream_ticker/stream_quotes are not supported.
        Each emission is a plain dict with keys:
          ltp, open, high, low, close, volume, oi, atp,
          depth_bids, depth_asks, security_id, symbol, timestamp.
        """
        instruments = self._to_instruments(symbols, exchange)
        return self._create_async_observable(
            lambda: self._broker.stream_full(instruments)
        )

    def full_stream_as_ticks(
        self,
        symbols: Union[List[str], List[Instrument]],
        exchange: Exchange = Exchange.MCX,
        interval_seconds: float = 0.0,
    ) -> Observable:
        """
        FULL packet stream converted to Tick objects — drop-in replacement for
        ticker_throttled() for MCX instruments.

        Converts each FULL dict to a brokers.Tick so downstream Rx pipelines
        (ops.map(broker_tick_to_internal)) work unchanged.

        interval_seconds > 0 applies throttle_first, same as ticker_throttled.
        """
        instruments = self._to_instruments(symbols, exchange)

        def _full_to_tick(pkt: dict) -> "Tick":
            bids = pkt.get("depth_bids") or []
            asks = pkt.get("depth_asks") or []
            inst = next(
                (i for i in instruments if i.symbol == pkt.get("symbol")),
                instruments[0] if instruments else None,
            )
            return Tick(
                instrument=inst,
                price=float(pkt.get("ltp", 0.0)),
                volume=int(pkt.get("volume", 0)),
                timestamp=pkt.get("timestamp"),
                bid=float(bids[0]["price"]) if bids else None,
                ask=float(asks[0]["price"]) if asks else None,
            )

        stream = self._create_async_observable(
            lambda: self._broker.stream_full(instruments)
        ).pipe(ops.map(_full_to_tick))

        if interval_seconds > 0:
            stream = stream.pipe(ops.throttle_first(interval_seconds))
        return stream

    def order_update_stream(self) -> Observable:
        """
        Observable of order status updates.
        
        Returns:
            Observable[Order] - emits Order objects on status change
            
        Note:
            Orders are pushed via on_order_update callback.
            Use push_order_update() to emit updates.
        """
        if self._order_subject is None:
            self._order_subject = Subject()
        return self._order_subject
    
    def position_update_stream(self) -> Observable:
        """
        Observable of position changes.
        
        Returns:
            Observable[Position] - emits Position objects on change
            
        Note:
            Positions are pushed via on_position_update callback.
            Use push_position_update() to emit updates.
        """
        if self._position_subject is None:
            self._position_subject = Subject()
        return self._position_subject
    
    # -------------------------------------------------------------------------
    # Push Methods (for internal use)
    # -------------------------------------------------------------------------
    
    def push_order_update(self, order: Order) -> None:
        """Push an order update to subscribers."""
        if self._order_subject:
            self._order_subject.on_next(order)
    
    def push_position_update(self, position: Position) -> None:
        """Push a position update to subscribers."""
        if self._position_subject:
            self._position_subject.on_next(position)
    
    # -------------------------------------------------------------------------
    # Convenience Methods with Common Operators
    # -------------------------------------------------------------------------
    
    def ticker_throttled(
        self,
        symbols: Union[List[str], List[Instrument]],
        interval_seconds: float = 1.0,
        exchange: Exchange = Exchange.NSE
    ) -> Observable:
        """
        Throttled ticker stream - max one update per interval.
        
        Args:
            symbols: List of trading symbols
            interval_seconds: Minimum time between updates
            exchange: Exchange
            
        Returns:
            Observable[Tick] - throttled stream
        """
        return self.ticker_stream(symbols, exchange).pipe(
            ops.throttle_first(interval_seconds)
        )
    
    def ticker_buffered(
        self,
        symbols: Union[List[str], List[Instrument]],
        buffer_seconds: float = 5.0,
        exchange: Exchange = Exchange.NSE
    ) -> Observable:
        """
        Buffered ticker stream - emits lists of ticks.
        
        Args:
            symbols: List of trading symbols
            buffer_seconds: Buffer window in seconds
            exchange: Exchange
            
        Returns:
            Observable[List[Tick]] - buffered stream
        """
        return self.ticker_stream(symbols, exchange).pipe(
            ops.buffer_with_time(buffer_seconds)
        )
    
    def ticker_filtered(
        self,
        symbols: Union[List[str], List[Instrument]],
        min_volume: int = 0,
        min_price: float = 0.0,
        exchange: Exchange = Exchange.NSE
    ) -> Observable:
        """
        Filtered ticker stream.
        
        Args:
            symbols: List of trading symbols
            min_volume: Minimum volume filter
            min_price: Minimum price filter
            exchange: Exchange
            
        Returns:
            Observable[Tick] - filtered stream
        """
        def _filter(tick: Tick) -> bool:
            if min_volume > 0 and tick.volume < min_volume:
                return False
            if min_price > 0 and tick.price < min_price:
                return False
            return True
        
        return self.ticker_stream(symbols, exchange).pipe(
            ops.filter(_filter)
        )
    
    # -------------------------------------------------------------------------
    # Option Chain Streams
    # -------------------------------------------------------------------------
    
    def option_chain_stream(
        self,
        underlying: str,
        exchange: Exchange = Exchange.NFO,
        expiry_index: int = 0,
        refresh_interval: float = 5.0
    ) -> Observable:
        """
        Periodic option chain updates.
        
        Emits the full option chain at regular intervals.
        Useful for monitoring ATM changes, OI changes, etc.
        
        Args:
            underlying: Underlying symbol (e.g., "NIFTY", "BANKNIFTY")
            exchange: Exchange (default: NFO)
            expiry_index: Which expiry (0=nearest)
            refresh_interval: Seconds between refreshes
            
        Returns:
            Observable[OptionChain] - periodic chain updates
            
        Usage:
            broker.option_chain_stream('BANKNIFTY', refresh_interval=10.0)
                .pipe(
                    ops.map(lambda c: {'atm': c.atm_strike, 'spot': c.spot_price})
                )
                .subscribe(print)
        """
        broker = self._broker

        async def _option_chain_gen():
            # Always use the sync bridge via executor to avoid asyncio.Lock
            # event-loop mismatch (the broker's locks are bound to its own
            # background loop, not the RxPY thread's loop).
            loop = asyncio.get_running_loop()
            while True:
                chain = await loop.run_in_executor(
                    None,
                    lambda: broker.get_option_chain(underlying, exchange, expiry_index),
                )
                yield chain
                await asyncio.sleep(refresh_interval)

        return self._create_async_observable(_option_chain_gen)
    
    def atm_strike_stream(
        self,
        underlying: str,
        exchange: Exchange = Exchange.NFO,
        expiry_index: int = 0,
        refresh_interval: float = 5.0
    ) -> Observable:
        """
        Stream of ATM strike changes.
        
        Emits only when ATM strike changes.
        
        Args:
            underlying: Underlying symbol
            exchange: Exchange
            expiry_index: Which expiry
            refresh_interval: Seconds between checks
            
        Returns:
            Observable[float] - ATM strike when it changes
            
        Usage:
            broker.atm_strike_stream('BANKNIFTY')
                .subscribe(lambda strike: print(f"New ATM: {strike}"))
        """
        return self.option_chain_stream(
            underlying, exchange, expiry_index, refresh_interval
        ).pipe(
            ops.map(lambda c: c.atm_strike),
            ops.distinct_until_changed()
        )
    
    def spot_price_stream(
        self,
        underlying: str,
        exchange: Exchange = Exchange.NFO,
        expiry_index: int = 0,
        refresh_interval: float = 2.0
    ) -> Observable:
        """
        Stream of spot price updates from option chain.
        
        Args:
            underlying: Underlying symbol
            exchange: Exchange
            expiry_index: Which expiry
            refresh_interval: Seconds between refreshes
            
        Returns:
            Observable[float] - spot price updates
        """
        return self.option_chain_stream(
            underlying, exchange, expiry_index, refresh_interval
        ).pipe(
            ops.map(lambda c: c.spot_price)
        )
    
    def option_oi_stream(
        self,
        underlying: str,
        strike: float,
        option_type: str = 'CE',
        exchange: Exchange = Exchange.NFO,
        expiry_index: int = 0,
        refresh_interval: float = 5.0
    ) -> Observable:
        """
        Stream of Open Interest for a specific option.
        
        Args:
            underlying: Underlying symbol
            strike: Strike price
            option_type: 'CE' or 'PE'
            exchange: Exchange
            expiry_index: Which expiry
            refresh_interval: Seconds between refreshes
            
        Returns:
            Observable[int] - OI updates
            
        Usage:
            broker.option_oi_stream('BANKNIFTY', 60200, 'CE')
                .subscribe(lambda oi: print(f"OI: {oi:,}"))
        """
        def _get_oi(chain: OptionChain) -> int:
            if option_type.upper() == 'CE':
                opt = chain.calls.get(strike)
            else:
                opt = chain.puts.get(strike)
            return getattr(opt, 'oi', 0) if opt else 0
        
        return self.option_chain_stream(
            underlying, exchange, expiry_index, refresh_interval
        ).pipe(
            ops.map(_get_oi)
        )
    
    def option_chain_diff_stream(
        self,
        underlying: str,
        exchange: Exchange = Exchange.NFO,
        expiry_index: int = 0,
        refresh_interval: float = 5.0
    ) -> Observable:
        """
        Stream of option chain changes (OI, volume, price changes).
        
        Emits dict with changes between updates.
        
        Args:
            underlying: Underlying symbol
            exchange: Exchange
            expiry_index: Which expiry
            refresh_interval: Seconds between refreshes
            
        Returns:
            Observable[Dict] - chain diffs
            
        Usage:
            broker.option_chain_diff_stream('BANKNIFTY')
                .subscribe(lambda diff: print(f"Changes: {diff}"))
        """
        # Use a list as a mutable cell so each subscribe() call gets its own
        # fresh state — avoids stale prev_chain from a previous subscription.
        _state = [None]  # _state[0] = prev_chain

        def _compute_diff(chain: OptionChain) -> dict:
            prev_chain = _state[0]
            if prev_chain is None:
                _state[0] = chain
                return {'initial': True, 'spot': chain.spot_price}
            
            diff = {
                'spot': chain.spot_price,
                'spot_change': chain.spot_price - prev_chain.spot_price,
                'atm': chain.atm_strike,
                'oi_changes': {},
                'volume_changes': {},
            }

            # Compute OI and volume changes for ATM ± 1 strike
            atm = chain.atm_strike
            step = chain.step_size

            for strike in [atm - step, atm, atm + step]:
                for opt_type, source in [('CE', chain.calls), ('PE', chain.puts)]:
                    curr = source.get(strike)
                    prev_src = prev_chain.calls if opt_type == 'CE' else prev_chain.puts
                    prev_opt = prev_src.get(strike) if prev_src else None

                    if curr and prev_opt:
                        key = f"{strike}{opt_type}"
                        oi_change = getattr(curr, 'oi', 0) - getattr(prev_opt, 'oi', 0)
                        vol_change = getattr(curr, 'volume', 0) - getattr(prev_opt, 'volume', 0)
                        if oi_change != 0:
                            diff['oi_changes'][key] = oi_change
                        if vol_change != 0:
                            diff['volume_changes'][key] = vol_change
            
            _state[0] = chain
            return diff
        
        return self.option_chain_stream(
            underlying, exchange, expiry_index, refresh_interval
        ).pipe(
            ops.map(_compute_diff)
        )
    
    # -------------------------------------------------------------------------
    # Historical Data Observables
    # -------------------------------------------------------------------------

    def historical_stream(
        self,
        symbol: Union[str, Instrument],
        from_date: datetime,
        to_date: datetime,
        interval: str = "1d",
        exchange: Exchange = Exchange.NSE,
        include_oi: bool = False,
    ) -> Observable:
        """
        Create Observable of historical OHLCV candles for a single symbol.

        Fetches data via the underlying broker (synchronously, in the subscribe
        call) and emits each row as a plain dict, then completes.

        Args:
            symbol:      Trading symbol string or Instrument object.
            from_date:   Start of the requested range.
            to_date:     End of the requested range.
            interval:    Candle interval — "1d", "1m", "5m", "15m", "1h", etc.
            exchange:    Exchange (default NSE). Ignored when an Instrument is passed.
            include_oi:  Emit an ``oi`` key in each dict when the broker supports it.

        Returns:
            Observable[Dict] — each item has keys:
                open, high, low, close, volume, timestamp (+ oi if include_oi)

        Example::

            from datetime import datetime, timedelta
            reactive.historical_stream(
                "TCS",
                from_date=datetime.now() - timedelta(days=30),
                to_date=datetime.now(),
                interval="1d",
            ).pipe(
                ops.filter(lambda c: c["volume"] > 1_000_000),
            ).subscribe(print)
        """
        instrument = (
            symbol
            if isinstance(symbol, Instrument)
            else Instrument(symbol=symbol, exchange=exchange, security_id="")
        )

        def _subscribe(observer, scheduler=None):
            try:
                df = self._broker.get_historical(
                    instrument, from_date, to_date, interval, include_oi
                )
                for _, row in df.iterrows():
                    observer.on_next(row.to_dict())
                observer.on_completed()
            except Exception as exc:
                observer.on_error(exc)
            return Disposable(lambda: None)

        return create(_subscribe)

    def bulk_historical_stream(
        self,
        symbols: Union[List[str], List[Instrument]],
        from_date: datetime,
        to_date: datetime,
        interval: str = "1d",
        exchange: Exchange = Exchange.NSE,
    ) -> Observable:
        """
        Create Observable of historical candles for multiple symbols.

        Fetches each symbol sequentially and emits ``(symbol_name, candle_dict)``
        tuples, then completes. Errors for individual symbols are forwarded via
        ``on_error`` and terminate the stream.

        Args:
            symbols:   List of symbol strings or Instrument objects.
            from_date: Start of the requested range.
            to_date:   End of the requested range.
            interval:  Candle interval — "1d", "1m", "5m", "15m", "1h", etc.
            exchange:  Exchange (default NSE). Ignored when Instruments are passed.

        Returns:
            Observable[Tuple[str, Dict]] — each item is ``(symbol, candle_dict)``

        Example::

            reactive.bulk_historical_stream(
                ["NIFTY", "BANKNIFTY"],
                from_date=datetime(2026, 1, 1),
                to_date=datetime(2026, 2, 1),
                interval="1d",
            ).pipe(
                ops.group_by(lambda item: item[0]),   # group by symbol
            ).subscribe(...)
        """
        instruments = self._to_instruments(symbols, exchange)

        def _subscribe(observer, scheduler=None):
            try:
                for inst in instruments:
                    df = self._broker.get_historical(
                        inst, from_date, to_date, interval
                    )
                    for _, row in df.iterrows():
                        observer.on_next((inst.symbol, row.to_dict()))
                observer.on_completed()
            except Exception as exc:
                observer.on_error(exc)
            return Disposable(lambda: None)

        return create(_subscribe)

    # -------------------------------------------------------------------------
    # Access to underlying broker
    # -------------------------------------------------------------------------

    @property
    def broker(self) -> IBrokerPort:
        """Access underlying broker for sync operations."""
        return self._broker


# =============================================================================
# Convenience Functions
# =============================================================================

def create_reactive_dhan(
    client_id: Optional[str] = None,
    access_token: Optional[str] = None,
    **kwargs
) -> ReactiveBroker:
    """Create a reactive Dhan broker."""
    return ReactiveBroker.dhan(
        client_id=client_id,
        access_token=access_token,
        **kwargs
    )


def create_reactive_paper(**kwargs) -> ReactiveBroker:
    """Create a reactive paper broker."""
    return ReactiveBroker.paper(**kwargs)
