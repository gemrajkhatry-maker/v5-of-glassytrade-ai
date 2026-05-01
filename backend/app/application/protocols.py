"""Application layer protocols for dependency injection.

These protocols define interfaces that can be used for type hints
without creating circular import dependencies.
"""

from typing import Protocol, runtime_checkable


@runtime_checkable
class IServiceGraph(Protocol):
    """Protocol for ServiceGraph to enable type hints without circular imports."""
    
    @property
    def config(self):
        """Return the configuration object."""
        ...
    
    @property
    def active_symbols(self) -> list:
        """Return list of active symbols."""
        ...
    
    @property
    def trading_session(self):
        """Return the trading session service."""
        ...
    
    @property
    def market_data(self):
        """Return the market data port."""
        ...
    
    @property
    def engine(self):
        """Return the trading engine."""
        ...


@runtime_checkable
class IStreamManager(Protocol):
    """Protocol for StreamManager."""
    
    async def start(self):
        """Start streaming."""
        ...
    
    async def stop(self):
        """Stop streaming."""
        ...


@runtime_checkable
class IWatchdogManager(Protocol):
    """Protocol for WatchdogManager."""
    
    async def start(self):
        """Start watchdog."""
        ...
    
    async def stop(self):
        """Stop watchdog."""
        ...


@runtime_checkable
class IStateBroadcaster(Protocol):
    """Protocol for StateBroadcaster."""
    
    def get_state(self, symbol: str) -> dict:
        """Return state for symbol."""
        ...


@runtime_checkable
class ITickProcessor(Protocol):
    """Protocol for TickProcessor."""
    
    async def process_tick(self, *args, **kwargs):
        """Process a tick."""
        ...