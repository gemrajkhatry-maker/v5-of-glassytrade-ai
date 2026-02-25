# Brokers Module Architecture Documentation

## Overview

The brokers module implements a **multi-broker abstraction layer** with clean architecture (port/adapter pattern). It provides unified access to different broker implementations with reactive streaming capabilities using RxPY.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           Usage Layer                                      │
│    ┌─────────────────────┐           ┌─────────────────────┐               │
│    │  ReactiveBroker    │           │   BrokerGateway     │               │
│    │   (reactive.py)    │           │    (gateway.py)    │               │
│    └─────────┬───────────┘           └─────────┬───────────┘               │
│              │                                 │                          │
│              │         ┌───────────────────────┘                          │
│              │         │                                                  │
│              ▼         ▼                                                  │
│    ┌─────────────────────────────────────────────────────────────────┐     │
│    │                    IBrokerPort Interface                        │     │
│    │              (Abstract Broker Contract)                        │     │
│    └─────────────────────────────────────────────────────────────────┘     │
│                              │                                             │
│         ┌────────────────────┼────────────────────┐                       │
│         ▼                    ▼                    ▼                        │
│    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐                │
│    │ PaperBroker │    │ DhanBroker  │    │   (Future)  │                │
│    │ (Testing)   │    │ (Production)│    │             │                │
│    └─────────────┘    └─────────────┘    └─────────────┘                │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Table of Contents

1. [Directory Structure](#directory-structure)
2. [Clean Architecture Layers](#clean-architecture-layers)
3. [Port/Adapter Pattern Implementation](#portadapter-pattern-implementation)
4. [Class Diagrams](#class-diagrams)
5. [Flow Diagrams](#flow-diagrams)
6. [Key Patterns](#key-patterns)
7. [Data Flow](#data-flow)
8. [Implementation Details](#implementation-details)
9. [Code Examples](#code-examples)

---

## Directory Structure

```
brokers/
├── __init__.py              # Package exports and auto .env loading
├── gateway.py               # BrokerGateway, Factory, CircuitBreaker (719 lines)
├── reactive.py              # ReactiveBroker with RxPY Observables (896 lines)
├── requirements.txt         # Dependencies
├── ARCHITECTURE_REVIEW.md   # Existing review with issues
├── REACTIVE_QUICKSTART.md   # Quick start guide
│
├── broker/                  # Core broker abstraction (port/adapter pattern)
│   ├── __init__.py
│   ├── ports.py             # IBrokerPort, IReactiveBroker interfaces
│   ├── entities.py          # Domain entities (Instrument, Quote, Tick, etc.)
│   ├── types.py             # Enums (Exchange, OptionType, OrderSide, etc.)
│   ├── paper/               # Paper trading implementation
│   │   └── broker.py        # In-memory broker for testing
│   ├── dhan/                # Dhan broker - Clean Architecture
│   │   ├── __init__.py
│   │   ├── application/     # Application layer
│   │   │   ├── broker.py    # Main DhanBroker implementation
│   │   │   ├── config.py   # Configuration
│   │   │   ├── facade.py   # Convenience facade
│   │   │   ├── converters.py
│   │   │   ├── exchange_resolver.py
│   │   │   └── services/   # Application services
│   │   ├── domain/          # Domain layer
│   │   │   ├── entities.py # Dhan-specific entities
│   │   │   ├── value_objects.py
│   │   │   ├── errors.py   # Domain errors
│   │   │   └── constants.py
│   │   ├── infrastructure/  # Infrastructure layer
│   │   │   ├── http_client.py
│   │   │   ├── websocket_client.py
│   │   │   ├── symbol_mapper.py
│   │   │   ├── resilience.py # Circuit breaker, rate limiter
│   │   │   └── auth_provider.py
│   │   └── ports/           # Port interfaces (specific to Dhan)
│   │       ├── http_port.py
│   │       ├── websocket_port.py
│   │       └── resilience_port.py
│   └── logging/             # Logging utilities
│
├── tests/                   # Integration tests
└── scripts/                 # Demo scripts
```

---

## Clean Architecture Layers

### Layer 1: Domain Layer (`broker/entities.py`, `broker/types.py`)

Contains pure domain entities with no dependencies on external frameworks.

```python
@dataclass(frozen=True)
class Instrument:
    """Immutable instrument representation."""
    symbol: str
    exchange: Exchange
    security_id: str = ""
    option_type: Optional[OptionType] = None
    strike: Optional[float] = None
    expiry: Optional[datetime] = None
```

**Domain Entities:**
- `Instrument` - Tradeable instrument (stock, option, futures)
- `Quote` - Market quote with OHLC, volume, depth
- `Tick` - Single price update
- `Order` - Order with side, quantity, price, status
- `Position` - Portfolio position
- `OptionChain` - Full option chain with calls/puts
- `MarketDepth` - 20-level orderbook

---

### Layer 2: Port Layer (`broker/ports.py`)

Defines abstract interfaces (contracts) that all broker implementations must satisfy.

```python
class IBrokerPort(ABC):
    """Primary broker abstraction - defines the contract for all broker implementations."""
    
    @abstractmethod
    def get_quote(self, instrument: Instrument) -> Quote: ...
    
    @abstractmethod
    async def stream_ticker(self, instruments: List[Instrument]) -> AsyncIterator[Tick]: ...
    
    @abstractmethod
    def place_order(self, order: Order) -> Order: ...
```

**Interface Segregation Protocols:**
- `IMarketDataProvider` - Quote and historical data
- `IStreamingProvider` - Real-time streaming
- `IOrderExecutor` - Order placement and cancellation
- `IPortfolioProvider` - Positions and orderbook
- `IOptionsProvider` - Option chain operations

---

### Layer 3: Infrastructure/Adapter Layer

Implements the ports with concrete broker-specific logic.

```
┌─────────────────────────────────────────────────────────────────┐
│                    Infrastructure Layer                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   PaperBroker                 DhanBroker                        │
│   (broker/paper/)            (broker/dhan/)                     │
│                                                                 │
│   ┌─────────────┐            ┌─────────────────────────────┐    │
│   │ In-memory  │            │  Application Layer         │    │
│   │ simulated  │            │  - Broker logic            │    │
│   │ data       │            │  - Converters              │    │
│   └─────────────┘            │  - Services                │    │
│                             └─────────────────────────────┘    │
│                             ┌─────────────────────────────┐    │
│                             │  Infrastructure Layer       │    │
│                             │  - HTTP Client             │    │
│                             │  - WebSocket Client        │    │
│                             │  - Symbol Mapper           │    │
│                             │  - Auth Provider           │    │
│                             │  - Resilience (CB, RL)      │    │
│                             └─────────────────────────────┘    │
│                             ┌─────────────────────────────┐    │
│                             │  Domain Layer               │    │
│                             │  - Entities                 │    │
│                             │  - Value Objects           │    │
│                             │  - Errors                   │    │
│                             └─────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

---

## Port/Adapter Pattern Implementation

### Core Interface: IBrokerPort

The `IBrokerPort` is the main abstraction that all broker implementations must follow:

```python
# brokers/broker/ports.py
class IBrokerPort(ABC):
    """Primary broker abstraction."""
    
    # Lifecycle
    def initialize(self) -> None: ...
    def close(self) -> None: ...
    
    # Market Data - Synchronous
    def get_quote(self, instrument: Instrument) -> Quote: ...
    def get_quotes_batch(self, instruments: List[Instrument]) -> Dict[Instrument, Quote]: ...
    def get_historical(self, instrument, from_date, to_date, interval, include_oi): ...
    
    # Streaming - Asynchronous
    async def stream_ticker(self, instruments: List[Instrument]) -> AsyncIterator[Tick]: ...
    async def stream_quotes(self, instruments: List[Instrument]) -> AsyncIterator[Quote]: ...
    async def stream_depth(self, instruments, depth_level) -> AsyncIterator[MarketDepth]: ...
    
    # Options
    def get_option_chain(self, underlying, exchange, expiry_index) -> OptionChain: ...
    def get_expiry_list(self, underlying, exchange) -> List[datetime]: ...
    
    # Orders
    def place_order(self, order: Order) -> Order: ...
    def cancel_order(self, order_id: str) -> bool: ...
    def get_order_status(self, order_id: str) -> Order: ...
    
    # Portfolio
    def get_positions(self) -> List[Position]: ...
    def get_orderbook(self) -> List[Order]: ...
```

### Reactive Interface: IReactiveBroker

For reactive programming with RxPY:

```python
# brokers/broker/ports.py
class IReactiveBroker(ABC):
    """Reactive broker interface for event-driven architectures."""
    
    @abstractmethod
    def ticker_stream(self, instruments: List[Instrument]) -> "Observable[Tick]": ...
    
    @abstractmethod
    def quote_stream(self, instruments: List[Instrument]) -> "Observable[Quote]": ...
    
    @abstractmethod
    def depth_stream(self, symbols, exchange, depth_level) -> "Observable[MarketDepth]": ...
    
    @abstractmethod
    def option_chain_stream(self, underlying, exchange, expiry_index, refresh_interval) -> "Observable[OptionChain]": ...
    
    # ... more stream methods
```

---

## Class Diagrams

### Main Class Relationships

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              Class Diagram                                  │
└─────────────────────────────────────────────────────────────────────────────┘

                                    ┌──────────────────────┐
                                    │    <<abstract>>      │
                                    │    IBrokerPort       │
                                    ├──────────────────────┤
                                    │ + get_quote()        │
                                    │ + get_quotes_batch() │
                                    │ + stream_ticker()    │
                                    │ + place_order()      │
                                    │ + get_positions()    │
                                    │ + get_option_chain() │
                                    └──────────┬───────────┘
                                               │
           ┌───────────────────────────────────┼───────────────────────────────────┐
           │                                   │                                   │
           ▼                                   ▼                                   ▼
┌─────────────────────┐            ┌─────────────────────┐            ┌─────────────────────┐
│     PaperBroker     │            │      DhanBroker      │            │   FutureBroker      │
├─────────────────────┤            ├──────────────────────┤            ├─────────────────────┤
│ - _prices: Dict     │            │ - config             │            │                     │
│ - _orders: List    │            │ - http_client        │            │                     │
│ - _positions: List │            │ - ws_client         │            │                     │
├─────────────────────┤            │ - symbol_mapper     │            │                     │
│ + get_quote()       │            ├──────────────────────┤            │                     │
│ + stream_ticker()   │            │ + get_quote()        │            │                     │
│ + place_order()    │            │ + stream_ticker()    │            │                     │
│ + get_option_chain │            │ + place_order()      │            │                     │
└─────────────────────┘            │ + get_option_chain() │            └─────────────────────┘
                                   └──────────────────────┘
                                            │
                                            ▼
                                 ┌─────────────────────┐
                                 │    DhanFacade       │
                                 │   (convenience)     │
                                 ├─────────────────────┤
                                 │ + quote()          │
                                 │ + historical()     │
                                 │ + place_order()    │
                                 └─────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────┐
│                         Gateway & Factory Diagram                           │
└─────────────────────────────────────────────────────────────────────────────┘

┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│    BrokerType       │     │   BrokerFactory     │     │  CircuitBreaker     │
│    <<enum>>         │     ├──────────────────────┤     ├──────────────────────┤
├──────────────────────┤     │ + create()          │     │ - CLOSED            │
│ PAPER = "paper"      │────▶│ + register()        │     │ - OPEN              │
│ DHAN = "dhan"       │     │ + available_brokers │     │ - HALF_OPEN         │
└─────────────────────┘     └──────────┬───────────┘     └──────────┬──────────┘
                                       │                               │
                                       ▼                               │
                         ┌─────────────────────────────┐                │
                         │      BrokerGateway          │◀───────────────┘
                         ├──────────────────────────────┤
                         │ - _broker: IBrokerPort       │
                         │ - _circuit_breaker          │
                         ├──────────────────────────────┤
                         │ + paper()                    │
                         │ + dhan()                     │
                         │ + get_quote()                │
                         │ + stream_ticker()           │
                         │ + place_order()             │
                         └─────────────────────────────┘


┌─────────────────────────────────────────────────────────────────────────────┐
│                         ReactiveBroker Wrapper                              │
└─────────────────────────────────────────────────────────────────────────────┘

                         ┌─────────────────────┐
                         │   ReactiveBroker     │
                         ├──────────────────────┤
                         │ - _broker: IBrokerPort│
                         ├──────────────────────┤
                         │ + ticker_stream()    │──────────▶  Observable[Tick]
                         │ + quote_stream()    │──────────▶  Observable[Quote]
                         │ + depth_stream()    │──────────▶  Observable[MarketDepth]
                         │ + option_chain_stream()──▶ Observable[OptionChain]
                         │ + wrap()            │
                         │ + paper()           │
                         │ + dhan()            │
                         └─────────┬───────────┘
                                   │
                                   ▼
                         ┌─────────────────────┐
                         │   IBrokerPort       │
                         │  (wrapped)          │
                         └─────────────────────┘
```

---

## Flow Diagrams

### Order Placement Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Order Placement Flow                                │
└─────────────────────────────────────────────────────────────────────────────┘

   User                    BrokerGateway              CircuitBreaker          Broker
    │                          │                          │                    │
    │  place_order(...)        │                          │                    │
    │─────────────────────────▶│                          │                    │
    │                          │                          │                    │
    │                          │  can_execute()?          │                    │
    │                          │─────────────────────────▶│                    │
    │                          │                          │                    │
    │                          │     True/False           │                    │
    │                          │◀─────────────────────────│                    │
    │                          │                          │                    │
    │                          │  record_success/failure  │                    │
    │                          │─────────────────────────▶│                    │
    │                          │                          │                    │
    │                          │                          │  place_order(order) │
    │                          │                          │───────────────────▶│
    │                          │                          │                    │
    │                          │                          │     Order (filled) │
    │                          │                          │◀───────────────────│
    │                          │                          │                    │
    │    Order (filled)        │                          │                    │
    │◀─────────────────────────│                          │                    │
    │                          │                          │                    │
```

### Quote Retrieval Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Quote Retrieval Flow                                │
└─────────────────────────────────────────────────────────────────────────────┘

   Client              BrokerGateway              CircuitBreaker            Broker
    │                       │                          │                      │
    │ get_quote(symbol)    │                          │                      │
    │─────────────────────▶│                          │                      │
    │                       │                          │                      │
    │                       │  Create Instrument        │                      │
    │                       │───────────────────────▶│                      │
    │                       │                          │                      │
    │                       │  can_execute()?         │                      │
    │                       │────────────────────────▶│                      │
    │                       │                          │                      │
    │                       │      True               │                      │
    │                       │◀───────────────────────│                      │
    │                       │                          │                      │
    │                       │                          │   get_quote()       │
    │                       │                          │─────────────────────▶│
    │                       │                          │                      │
    │                       │                          │     Quote            │
    │                       │                          │◀─────────────────────│
    │                       │                          │                      │
    │                       │    record_success        │                      │
    │                       │────────────────────────▶│                      │
    │                       │                          │                      │
    │     Quote             │                          │                      │
    │◀──────────────────────│                          │                      │
    │                       │                          │                      │
```

### Reactive Stream Creation Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Reactive Stream Creation Flow                           │
└─────────────────────────────────────────────────────────────────────────────┘

   Client              ReactiveBroker              IBrokerPort            Dhan API
    │                       │                          │                      │
    │ ticker_stream([...])  │                          │                      │
    │─────────────────────▶│                          │                      │
    │                       │                          │                      │
    │                       │  _to_instruments()       │                      │
    │                       │───────────────────────▶│                      │
    │                       │                          │                      │
    │                       │  _create_async_observable()                   │
    │                       │◀───────────────────────│                      │
    │                       │                          │                      │
    │                       │   Observable (with subscribe function)         │
    │◀──────────────────────│                          │                      │
    │                       │                          │                      │
    │ subscribe(on_next)    │                          │                      │
    │─────────────────────▶│                          │                      │
    │                       │                          │                      │
    │                       │   New thread + event loop                     │
    │                       │─────────────────────────────────────────────▶   │
    │                       │                          │                      │
    │                       │                          │    async for tick    │
    │                       │                          │◀────────────────────│
    │                       │                          │                      │
    │                       │  on_next(tick)          │                      │
    │  tick callback       │◀─────────────────────────│                      │
    │◀──────────────────────│                          │                      │
    │                       │                          │                      │
```

### Circuit Breaker State Transitions

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Circuit Breaker State Machine                           │
└─────────────────────────────────────────────────────────────────────────────┘

                         ┌─────────────────┐
                         │                 │
                         │    CLOSED       │
                         │  (Normal Op)   │
                         │                 │
                         │  Calls pass     │
                         │  through        │
                         └────────┬────────┘
                                  │
            ┌─────────────────────┼─────────────────────┐
            │                     │                     │
            │ failure_count       │ success             │
            │ >= threshold        │                     │
            ▼                     ▼                     │
┌─────────────────────┐    ┌─────────────────────┐     │
│                     │    │                     │     │
│        OPEN         │    │    CLOSED          │◀────┘
│  (Fail Fast Mode)   │    │  (reset count)     │
│                     │    │                     │
│  All calls raise    │    └─────────────────────┘
│  CircuitBreakerError│
│                     │
└────────┬────────────┘
         │
         │ recovery_timeout
         │ elapsed
         ▼
┌─────────────────────┐
│                     │
│     HALF_OPEN       │
│  (Testing Recovery) │
│                     │
│  Allow limited      │
│  calls through      │
│                     │
└────────┬────────────┘
         │
         │ success_count
         │ >= threshold
         ▼
    ┌────────────┐
    │   CLOSED   │
    └────────────┘
```

### Option Chain Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         Option Chain Flow                                   │
└─────────────────────────────────────────────────────────────────────────────┘

   Client              BrokerGateway                 Broker
    │                       │                          │
    │ get_option_chain()    │                          │
    │ ("NIFTY", NFO, 0)     │                          │
    │─────────────────────▶│                          │
    │                       │                          │
    │                       │  get_option_chain()      │
    │                       │─────────────────────────▶│
    │                       │                          │
    │                       │   ┌─────────────────┐    │
    │                       │   │ 1. Get spot    │    │
    │                       │   │ 2. Get expiry  │    │
    │                       │   │ 3. Fetch chain│    │
    │                       │   │ 4. Build Option│    │
    │                       │   │    objects     │    │
    │                       │   └─────────────────┘    │
    │                       │                          │
    │                       │    OptionChain           │
    │                       │◀─────────────────────────│
    │                       │                          │
    │    OptionChain        │                          │
    │◀──────────────────────│                          │
    │                       │                          │
    │                                                                       │
    │  OptionChain contains:                                                │
    │  ┌─────────────────────────────────────────────────────────────────┐ │
    │  │ - underlying: Instrument                                      │ │
    │  │ - expiry: datetime                                            │ │
    │  │ - spot_price: float                                            │ │
    │  │ - atm_strike: float                                           │ │
    │  │ - step_size: float                                            │ │
    │  │ - calls: Dict[float, Option]   # Strike → Option              │ │
    │  │ - puts: Dict[float, Option]    # Strike → Option              │ │
    │  └─────────────────────────────────────────────────────────────────┘ │
```

---

## Key Patterns

### 1. Factory Pattern (BrokerFactory)

```python
# Usage
from brokers.gateway import BrokerFactory, BrokerType

# Create paper broker
paper = BrokerFactory.create(BrokerType.PAPER)

# Create Dhan broker
dhan = BrokerFactory.create(
    BrokerType.DHAN,
    client_id='xxx',
    access_token='yyy'
)

# Register custom broker
BrokerFactory.register(BrokerType.ZERODHA, ZerodhaBroker)
```

### 2. Circuit Breaker Pattern

```python
# Usage
from brokers.gateway import CircuitBreaker

breaker = CircuitBreaker(
    failure_threshold=5,    # Open after 5 failures
    recovery_timeout=60.0, # Wait 60s before half-open
    success_threshold=3    # Close after 3 successes
)

with breaker:
    result = broker.get_quote(instrument)
```

### 3. Dependency Injection

```python
# Gateway accepts any IBrokerPort implementation
gateway = BrokerGateway(
    broker=my_custom_broker,  # Any IBrokerPort
    circuit_breaker=CircuitBreaker()
)
```

### 4. Composition over Inheritance

```python
# ReactiveBroker wraps IBrokerPort without modifying it
class ReactiveBroker(IReactiveBroker):
    def __init__(self, broker: IBrokerPort):
        self._broker = broker  # Composition
    
    def ticker_stream(self, symbols, exchange):
        # Wraps async iterator as Observable
        return self._create_async_observable(
            lambda: self._broker.stream_ticker(instruments)
        )
```

---

## Data Flow

### Synchronous Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                      Synchronous API Data Flow                              │
└─────────────────────────────────────────────────────────────────────────────┘

   Request                     Transformation                 Broker
    │                              │                           │
    │ get_quote("RELIANCE")       │                           │
    │─────────────────────────────▶│                           │
    │                              │                           │
    │                              │ Instrument(symbol="RELIANCE")│
    │                              │───────────────────────────▶│
    │                              │                           │
    │                              │                    API Call│
    │                              │                   (HTTP)  │
    │                              │                  ────────▶│
    │                              │                           │
    │                              │                    Raw Response
    │                              │                   ◀────────│
    │                              │                           │
    │                              │       Quote entity        │
    │                              │◀──────────────────────────│
    │                              │                           │
    │         Quote                │                           │
    │◀─────────────────────────────│                           │
```

### Asynchronous Streaming Data Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Asynchronous Streaming Data Flow                         │
└─────────────────────────────────────────────────────────────────────────────┘

   Request                     WebSocket                   Broker
    │                              │                           │
    │ stream_ticker(["NIFTY"])    │                           │
    │─────────────────────────────▶│                           │
    │                              │                           │
    │                              │  Subscribe + Instruments │
    │                              │───────────────────────────▶│
    │                              │                           │
    │                              │                    WebSocket│
    │                              │                    Connect │
    │                              │                    ────────▶│
    │                              │                           │
    │◀─────────────────────────────│    AsyncIterator           │
    │   async generator            │                           │
    │                              │                           │
    │                              │    Tick data frames       │
    │                              │   ◀───────────────────────│
    │                              │                           │
    │   Tick objects (via yield)   │                           │
    │◀─────────────────────────────│                           │
    │                              │                           │
    │   (for await tick in ...)    │                           │
```

---

## Implementation Details

### BrokerGateway

The `BrokerGateway` provides a unified API with:

1. **Factory Methods** - `paper()`, `dhan()`, `create()`
2. **Circuit Breaker** - Wraps all operations
3. **Correlation IDs** - Tracks requests across logs
4. **Sync + Async API** - Both synchronous and streaming methods

```python
# brokers/gateway.py
class BrokerGateway:
    def __init__(self, broker: IBrokerPort, circuit_breaker: CircuitBreaker = None):
        self._broker = broker
        self._circuit_breaker = circuit_breaker or CircuitBreaker()
    
    @classmethod
    def paper(cls) -> "BrokerGateway":
        broker = BrokerFactory.create(BrokerType.PAPER)
        return cls(broker)
    
    def get_quote(self, symbol, exchange=Exchange.NSE, security_id="") -> Quote:
        instrument = Instrument(symbol=symbol, exchange=exchange, security_id=security_id)
        with self._circuit_breaker:
            return self._broker.get_quote(instrument)
```

### ReactiveBroker

The `ReactiveBroker` converts async iterators to RxPY Observables:

```python
# brokers/reactive.py
class ReactiveBroker(IReactiveBroker):
    def _create_async_observable(self, async_gen_factory):
        def _subscribe(observer, scheduler=None):
            def _thread_target():
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                task = loop.create_task(_run())
                loop.run_until_complete(task)
            
            thread = threading.Thread(target=_thread_target, daemon=True)
            thread.start()
            
            def _dispose():
                task.cancel()
            
            return Disposable(_dispose)
        
        return create(_subscribe)
```

### PaperBroker

Simulates broker operations without real API calls:

```python
# brokers/broker/paper/broker.py
class PaperBroker(IBrokerPort):
    def __init__(self, prices: Dict[str, float] = None):
        self._prices = DEFAULT_PRICES.copy()
        if prices:
            self._prices.update(prices)
    
    def get_quote(self, instrument: Instrument) -> Quote:
        price = self._get_price(instrument.symbol)
        return Quote(
            instrument=instrument,
            ltp=price,
            bid=price - 1,
            ask=price + 1,
            volume=random.randint(100000, 10000000),
            # ...
        )
    
    async def stream_ticker(self, instruments):
        while True:
            for inst in instruments:
                yield Tick(instrument=inst, price=self._get_price(inst.symbol), ...)
            await asyncio.sleep(0.05)
```

---

## Code Examples

### Basic Usage - Getting a Quote

```python
from brokers import BrokerGateway, Exchange

# Paper trading (testing)
gateway = BrokerGateway.paper()
quote = gateway.get_quote("RELIANCE", Exchange.NSE)
print(f"Price: {quote.ltp}, Volume: {quote.volume}")

# Production with Dhan
gateway = BrokerGateway.dhan(
    client_id="your_client_id",
    access_token="your_access_token"
)
quote = gateway.get_quote("RELIANCE", Exchange.NSE)
```

### Placing an Order

```python
from brokers import BrokerGateway
from brokers.broker.types import Exchange, OrderSide

gateway = BrokerGateway.paper()

order = gateway.place_order(
    symbol="RELIANCE",
    exchange=Exchange.NSE,
    side="BUY",
    quantity=10,
    price=2500.00,
    product_type="INTRADAY"
)

print(f"Order ID: {order.order_id}, Status: {order.status}")
```

### Reactive Streaming

```python
from brokers.reactive import ReactiveBroker
from brokers.broker.types import Exchange
from rx import operators as ops

# Create reactive broker
broker = ReactiveBroker.paper()

# Simple stream
broker.ticker_stream(['RELIANCE', 'TCS'], Exchange.NSE).subscribe(
    on_next=lambda tick: print(f"{tick.symbol}: {tick.price}"),
    on_error=lambda e: print(f"Error: {e}")
)

# With operators - throttled and filtered
(broker.ticker_stream(['NIFTY'], Exchange.NFO)
    .pipe(
        ops.filter(lambda t: t.volume > 10000),
        ops.throttle_first(1.0),  # Max 1 per second
    )
    .subscribe(lambda t: print(f"Filtered: {t.price}"))
)
```

### Option Chain Usage

```python
from brokers import BrokerGateway
from brokers.broker.types import Exchange

gateway = BrokerGateway.paper()

# Get option chain
chain = gateway.get_option_chain("BANKNIFTY", Exchange.NFO, expiry_index=0)

print(f"Spot: {chain.spot_price}, ATM: {chain.atm_strike}")

# Get ATM options
atm_ce, atm_pe = chain.get_atm_options()
print(f"ATM CE: {atm_ce.symbol} @ {atm_ce.ltp}")
print(f"ATM PE: {atm_pe.symbol} @ {atm_pe.ltp}")

# Get OTM options
otm_ce, otm_pe = chain.get_otm_options(distance=1)
```

### Async Streaming

```python
import asyncio
from brokers import BrokerGateway

async def main():
    gateway = BrokerGateway.paper()
    
    async for tick in gateway.stream_ticker(['RELIANCE', 'TCS']):
        print(f"{tick.instrument.symbol}: {tick.price}")

asyncio.run(main())
```

---

## Known Issues (from Architecture Review)

| Priority | Issue | Recommendation |
|----------|-------|----------------|
| P0 | Duplicate CircuitBreaker in gateway.py and dhan/infrastructure/resilience.py | Unify into single implementation |
| P1 | DhanFacade duplicates Broker methods | Refactor to extend or delegate |
| P1 | BrokerGateway duplicates Broker API | Use delegation or AOP |
| P2 | Hardcoded path in DhanBroker | Use environment config |
| P2 | Order entity missing fields | Add missing fields |

---

## Further Reading

- [Architecture Review](./ARCHITECTURE_REVIEW.md) - Detailed issues and recommendations
- [Reactive Quick Start](./REACTIVE_QUICKSTART.md) - RxPY usage guide
- [Broker Ports](./broker/ports.py) - Interface definitions
- [Dhan Broker](./broker/dhan/) - Full Dhan implementation
