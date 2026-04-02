# Brokers Module — Complete Architecture & How-It-Works Guide

> **Scope**: Every component, every flow, every protocol. From network bytes to high-level trading abstractions.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Clean Architecture Layers](#2-clean-architecture-layers)
3. [Component Interaction Map](#3-component-interaction-map)
4. [How Communication Works](#4-how-communication-works)
5. [How Symbol Mapping Works](#5-how-symbol-mapping-works)
6. [How Option Methods Work](#6-how-option-methods-work)
7. [How Streaming Works](#7-how-streaming-works)
8. [How Orders Work](#8-how-orders-work)
9. [How Portfolio Works](#9-how-portfolio-works)
10. [How Authentication Works](#10-how-authentication-works)
11. [How Resilience Works](#11-how-resilience-works)
12. [How Error Handling Works](#12-how-error-handling-works)
13. [Complete Flow Diagrams](#13-complete-flow-diagrams)
14. [Exchange Support Matrix](#14-exchange-support-matrix)
15. [Performance Characteristics](#15-performance-characteristics)

---

## 1. System Overview

The brokers module is a **multi-broker abstraction layer** built on clean architecture (port/adapter) principles. It provides:

- **Unified API** for market data, orders, portfolio across different brokers
- **Reactive streaming** via RxPY Observables
- **Fault tolerance** with circuit breakers and rate limiters
- **Symbol resolution** from human-readable names to broker-specific IDs
- **Option chain processing** with Greeks, OI analysis, ATM/OTM/ITM selection

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              USAGE LAYER                                            │
│                                                                                     │
│   ┌──────────────────────┐    ┌──────────────────────┐    ┌──────────────────────┐  │
│   │    BrokerGateway     │    │   ReactiveBroker     │    │   CircuitBreaker     │  │
│   │  (gateway.py:422L)   │    │  (reactive.py:896L)  │    │      Wrapper         │  │
│   │                      │    │                      │    │  (ports.py:804L)     │  │
│   │  Factory methods     │    │  Observable factory  │    │  Wraps any broker    │  │
│   │  .paper() .dhan()    │    │  ticker/quote/depth  │    │  with fault tolerance│  │
│   │  Sync + async API    │    │  option chain streams│    │                      │  │
│   └──────────┬───────────┘    └──────────┬───────────┘    └──────────┬───────────┘  │
│              │                           │                           │              │
│              └───────────────────────────┼───────────────────────────┘              │
│                                          │                                          │
│                                          ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────────────┐    │
│  │                        IBrokerPort Interface                                │    │
│  │                     (Abstract Broker Contract)                              │    │
│  │                                                                             │    │
│  │  Market Data:  get_quote(), get_quotes_batch(), get_historical()           │    │
│  │  Streaming:    stream_ticker(), stream_quotes(), stream_depth()            │    │
│  │  Options:      get_option_chain(), get_expiry_list()                       │    │
│  │  Orders:       place_order(), cancel_order(), get_order_status()           │    │
│  │  Portfolio:    get_positions(), get_orderbook()                            │    │
│  └──────────────────────────────────────────┬──────────────────────────────────┘    │
│                                             │                                       │
│                    ┌────────────────────────┼────────────────────────┐              │
│                    ▼                        ▼                        ▼              │
│  ┌───────────────────────┐  ┌───────────────────────┐  ┌───────────────────────┐   │
│  │     PaperBroker       │  │      DhanBroker       │  │   Future Brokers      │   │
│  │  (paper/broker.py)    │  │ (dhan/application/    │  │   (Zerodha, Upstox)   │   │
│  │                       │  │      broker.py)       │  │                       │   │
│  │  In-memory simulation │  │  Facade → Services    │  │   Pluggable via       │   │
│  │  No external deps     │  │  Async-first design   │  │   IBrokerPort         │   │
│  │  Testing & dev        │  │  Production-ready     │  │   interface           │   │
│  └───────────────────────┘  └───────────┬───────────┘  └───────────────────────┘   │
│                                         │                                           │
└─────────────────────────────────────────┼───────────────────────────────────────────┘
                                          │
                    ┌─────────────────────┼─────────────────────┐
                    ▼                     ▼                     ▼
  ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
  │   Application Layer │  │    Domain Layer     │  │ Infrastructure Layer│
  │                     │  │                     │  │                     │
  │  MarketDataService  │  │  DhanInstrument     │  │  DhanHttpClient     │
  │  HistoricalService  │  │  ExchangeSegment    │  │  DhanWebSocketClient│
  │  StreamingService   │  │  InstrumentType     │  │  DhanSymbolMapper   │
  │  OptionsService     │  │  OptionType         │  │  DhanAuthProvider   │
  │  OrderService       │  │  FeedType           │  │  DepthWebSocket     │
  │  PortfolioService   │  │  Error hierarchy    │  │  Resilience         │
  └─────────────────────┘  └─────────────────────┘  └─────────────────────┘
```

---

## 2. Clean Architecture Layers

### Layer 1: Domain Layer — Pure Business Logic

**Files**: `broker/dhan/domain/entities.py`, `broker/dhan/domain/constants.py`, `broker/dhan/domain/errors.py`, `broker/dhan/domain/segment_mapping.py`, `broker/dhan/domain/value_objects.py`

**Purpose**: Broker-agnostic business rules, entities, and error types. Zero external dependencies.

**Key Domain Entities**:

```
DhanInstrument
├── security_id: str          # Dhan's internal ID
├── trading_symbol: str       # Human-readable symbol (e.g., "NIFTY 27 MAR 24000 CALL")
├── symbol: str               # Short symbol (e.g., "NIFTY")
├── exchange_segment: ExchangeSegment  # NSE_EQ, NSE_FNO, MCX_COMM, etc.
├── instrument_type: InstrumentTypeEnum  # EQUITY, INDEX_OPTION, INDEX_FUTURE, etc.
├── lot_size: int
├── tick_size: float
└── expiry: Optional[datetime]

ExchangeSegment (enum)
├── NSE_EQ = 1    # NSE Equity
├── NSE_FNO = 2   # NSE Futures & Options
├── NSE_CURRENCY = 3
├── BSE_EQ = 4
├── BSE_FNO = 5
├── BSE_CURRENCY = 6
├── MCX_COMM = 7  # MCX Commodity
├── MCX_FNO = 13  # MCX Futures & Options
└── IDX_I = 16    # Index

InstrumentTypeEnum (enum)
├── EQUITY
├── INDEX
├── INDEX_OPTION
├── INDEX_FUTURE
├── STOCK_OPTION
├── STOCK_FUTURE
└── COMMODITY_FUTURE
```

**Error Hierarchy** (597 lines of comprehensive error handling):

```
DhanError (base)
├── DhanAuthError
│   ├── DhanLoginError
│   ├── DhanTOTPError
│   ├── DhanTokenExpiredError
│   └── DhanTokenInvalidError
├── DhanNetworkError
│   ├── DhanConnectionError
│   ├── DhanTimeoutError
│   └── DhanRateLimitError
├── DhanMarketDataError
│   ├── DhanSymbolNotFoundError
│   ├── DhanFeedNotSupportedError
│   └── DhanInvalidDataError
├── DhanOrderError
│   ├── DhanOrderPlacementError
│   ├── DhanOrderCancellationError
│   └── DhanOrderStatusError
├── DhanWebSocketError
│   ├── DhanWebSocketConnectionError
│   ├── DhanWebSocketDisconnectedError
│   └── DhanWebSocketMessageError
└── DhanConfigError
```

### Layer 2: Port Layer — Abstract Contracts

**Files**: `broker/ports.py`, `broker/dhan/ports/__init__.py`

**Purpose**: Define what the system needs, not how it's implemented.

**Core Interfaces**:

```python
# Primary broker contract
class IBrokerPort(ABC):
    # Lifecycle
    def initialize(self) -> None
    def close(self) -> None

    # Market Data (sync)
    def get_quote(self, instrument: Instrument) -> Quote
    def get_quotes_batch(self, instruments: List[Instrument]) -> Dict[Instrument, Quote]
    def get_historical(self, instrument, from_date, to_date, interval, include_oi) -> DataFrame

    # Streaming (async)
    async def stream_ticker(self, instruments) -> AsyncIterator[Tick]
    async def stream_quotes(self, instruments) -> AsyncIterator[Quote]
    async def stream_depth(self, instruments, depth_level=20) -> AsyncIterator[MarketDepth]
    async def stream_full(self, instruments) -> AsyncIterator[FullPacket]

    # Options
    def get_option_chain(self, underlying, exchange, expiry_index=0) -> OptionChain
    def get_expiry_list(self, underlying, exchange) -> List[datetime]

    # Orders
    def place_order(self, order: Order) -> Order
    def cancel_order(self, order_id: str) -> bool
    def get_order_status(self, order_id: str) -> Order

    # Portfolio
    def get_positions(self) -> List[Position]
    def get_orderbook(self) -> List[Order]

# Reactive streaming contract
class IReactiveBroker(ABC):
    def ticker_stream(self, instruments) -> Observable[Tick]
    def quote_stream(self, instruments) -> Observable[Quote]
    def depth_stream(self, symbols, exchange, depth_level=20) -> Observable[MarketDepth]
    def option_chain_stream(self, underlying, exchange, expiry_index, refresh_interval) -> Observable[OptionChain]
    # ... 12 more stream methods

# Dhan-specific protocols
@runtime_checkable
class IHttpClient(Protocol):
    async def get(self, endpoint, params) -> HttpResponse
    async def post(self, endpoint, json) -> HttpResponse
    async def close(self)

@runtime_checkable
class IWebSocketClient(Protocol):
    async def connect(self)
    async def subscribe(self, instruments, feed_type)
    async def disconnect(self)
    async def receive(self) -> WSMessage

@runtime_checkable
class ISymbolMapper(Protocol):
    async def get_security_id(self, symbol, exchange) -> Optional[str]
    async def refresh_cache(self)

@runtime_checkable
class IAuthProvider(Protocol):
    async def login(self, client_id) -> str
    async def validate_otp(self, client_id, otp) -> str
    async def generate_token(self, client_id) -> str

@runtime_checkable
class IRateLimiter(Protocol):
    async def acquire(self, category)

@runtime_checkable
class ICircuitBreaker(Protocol):
    async def execute(self, operation) -> Any
```

### Layer 3: Application Layer — Business Services

**Files**: `broker/dhan/application/broker.py`, `broker/dhan/application/services/`

**Purpose**: Orchestrate domain logic and infrastructure. Each service handles one concern.

**Service Architecture**:

```
DhanBroker (Facade)
├── MarketDataService    → Quotes, LTP, batch quotes by segment
├── HistoricalService    → OHLCV data, date range splitting, expired options
├── StreamingService     → WebSocket feeds (ticker, quotes, depth, full)
├── OptionsService       → Option chains, expiries, symbol formatting
├── OrderService         → Order placement, cancellation, status, orderbook
└── PortfolioService     → Positions, trade history, P&L, trade book
```

**Base Service** (`base.py:162L`):
- Shared dependency injection (HTTP client, symbol mapper, rate limiter, circuit breaker)
- Common helpers: `_apply_rate_limit()`, `_execute_with_cb()`, `_resolve_security_id()`
- Parallel instrument resolution: `_resolve_instruments_parallel()`

### Layer 4: Infrastructure Layer — External System Adapters

**Files**: `broker/dhan/infrastructure/`

**Purpose**: Implement ports with concrete external system integrations.

```
infrastructure/
├── http_client.py (707L)          → aiohttp REST client with retries, auth, pooling
├── websocket_client.py (689L)     → WebSocket binary protocol decoder
├── depth_websocket_client.py (315L) → 20/200-level depth WebSocket
├── symbol_mapper.py (867L)        → CSV instrument cache, symbol resolution
├── auth_provider.py (1045L)       → TOTP auth, JWT management, token refresh
└── resilience.py (365L)           → Token bucket rate limiter, circuit breaker
```

---

## 3. Component Interaction Map

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                    CLIENT CODE                                      │
│                                                                                     │
│   gateway = BrokerGateway.dhan()                                                    │
│   quote = gateway.get_quote("RELIANCE", Exchange.NSE)                               │
│   async for tick in gateway.stream_ticker(["NIFTY"], Exchange.NFO): ...             │
│   chain = gateway.get_option_chain("NIFTY", Exchange.NFO, expiry_index=0)           │
└──────────────────────────────────┬──────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              BROKER GATEWAY (gateway.py)                            │
│                                                                                     │
│   1. Converts string symbols → Instrument objects                                   │
│   2. Wraps broker with CircuitBreakerWrapper                                        │
│   3. Intercepts orders when DRY_RUN=True                                            │
│   4. Delegates to wrapped broker                                                    │
└──────────────────────────────────┬──────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           CIRCUIT BREAKER WRAPPER (ports.py)                        │
│                                                                                     │
│   Sync methods:   with self._breaker: return broker.method()                        │
│   Async methods:  passthrough (streams have own reconnect logic)                    │
│                                                                                     │
│   States: CLOSED (normal) → OPEN (fail-fast) → HALF_OPEN (testing) → CLOSED         │
└──────────────────────────────────┬──────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              DHAN BROKER (dhan/application/broker.py)               │
│                                                                                     │
│   Facade Pattern: Thin layer delegating to focused services                         │
│                                                                                     │
│   Sync → Async Bridge:                                                              │
│   def get_quote(self, instrument):                                                  │
│       return self._run_async(self._market_data.get_quote_async(instrument))         │
│                                                                                     │
│   Threading Model:                                                                  │
│   - Persistent sidecar event loop (threading.Thread + asyncio.new_event_loop)       │
│   - Thread-safe sync wrappers (asyncio.run_coroutine_threadsafe)                    │
│   - Instance-level lock (_loop_lock) prevents race conditions                       │
└──────┬──────────┬──────────┬──────────┬──────────┬──────────────────────────────────┘
       │          │          │          │          │
       ▼          ▼          ▼          ▼          ▼
┌──────────┐┌──────────┐┌──────────┐┌──────────┐┌──────────┐
│  Market  ││Historical││Streaming ││ Options  ││  Orders  │
│  Data    ││ Service  ││ Service  ││ Service  ││ Service  │
│ Service  ││          ││          ││          ││          │
└────┬─────┘└────┬─────┘└────┬─────┘└────┬─────┘└────┬─────┘
     │           │           │           │           │
     └───────────┴───────────┴───────────┴───────────┘
                                 │
                    Shared Dependencies (BaseDhanService)
                    ├── _http_client: IHttpClient
                    ├── _symbol_mapper: ISymbolMapper
                    ├── _rate_limiter: IRateLimiter
                    ├── _circuit_breaker: ICircuitBreaker
                    └── _ensure_initialized: callable
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                             INFRASTRUCTURE ADAPTERS                                 │
│                                                                                     │
│   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐                   │
│   │  DhanHttpClient │  │ DhanWebSocket   │  │ DhanSymbolMapper│                   │
│   │  (aiohttp)      │  │ Client          │  │ (CSV cache)     │                   │
│   │                 │  │ (websockets)    │  │                 │                   │
│   │ - GET/POST      │  │ - Connect       │  │ - 240K instruments│                 │
│   │ - Retry logic   │  │ - Subscribe     │  │ - 6-step resolution│                │
│   │ - Token refresh │  │ - Binary decode │  │ - Fuzzy matching│                   │
│   │ - Connection    │  │ - Reconnect     │  │ - O(1) lookups  │                   │
│   │   pooling       │  │ - Heartbeat     │  │                 │                   │
│   └────────┬────────┘  └────────┬────────┘  └────────┬────────┘                   │
│            │                    │                    │                             │
│   ┌────────┴────────┐  ┌────────┴────────┐  ┌────────┴────────┐                   │
│   │ DhanAuthProvider│  │ DepthWebSocket  │  │ TokenBucketRate │                   │
│   │ (TOTP/JWT)      │  │ Client          │  │ Limiter         │                   │
│   │                 │  │ (20/200 depth)  │  │                 │                   │
│   │ - Login flow    │  │ - Binary proto  │  │ - Token bucket  │                   │
│   │ - Token gen     │  │ - Depth decode  │  │ - Thread-safe   │                   │
│   │ - Token refresh │  │ - Reconnect     │  │ - Per-category  │                   │
│   └─────────────────┘  └─────────────────┘  └─────────────────┘                   │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. How Communication Works

### 4.1 HTTP Client Architecture

**File**: `broker/dhan/infrastructure/http_client.py` (707 lines)

**Technology**: `aiohttp` async HTTP client with connection pooling.

**Request Lifecycle**:

```
Client Request
    │
    ▼
┌─────────────────────────────────────────────┐
│ 1. Rate Limiter Check                       │
│    - Token bucket algorithm                 │
│    - Per-category limits (market_data, etc) │
│    - Blocks if no tokens available          │
└───────────────────┬─────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│ 2. Circuit Breaker Check                    │
│    - CLOSED: Allow request                  │
│    - OPEN: Raise CircuitBreakerError        │
│    - HALF_OPEN: Allow limited test request  │
└───────────────────┬─────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│ 3. Build HTTP Request                       │
│    - URL: base_url + endpoint               │
│    - Headers:                               │
│        Authorization: Bearer <token>        │
│        access-token: <token>                │
│        Content-Type: application/json       │
│        client-id: <client_id>               │
│        X-Correlation-ID: <uuid>             │
│    - Body: JSON payload (for POST)          │
└───────────────────┬─────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│ 4. Execute Request (with retry loop)        │
│    - Max retries: 3 (configurable)          │
│    - Backoff: 0.5s, 1s, 2s (exponential)   │
│    - Retry on: 408, 429, 500, 502, 503, 504│
│    - Timeout: 30s (configurable)            │
└───────────────────┬─────────────────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────┐
│ 5. Handle Response                          │
│    - 200/201: Parse JSON, return HttpResponse│
│    - 401: Auto token refresh + retry once   │
│    - 429: DhanRateLimitError                │
│    - 4xx/5xx: Map to domain error           │
│    - Network error: DhanConnectionError     │
└─────────────────────────────────────────────┘
```

**Token Refresh on 401**:

```python
async def _request_with_retry(self, method, url, **kwargs):
    for attempt in range(self.retry_config.max_retries + 1):
        try:
            response = await self._session.request(method, url, **kwargs)

            if response.status == 401 and self._auth_provider:
                # Token expired — refresh and retry once
                new_token = await self._auth_provider.refresh_token()
                self._access_token = new_token
                # Update headers with new token
                continue

            return self._map_response(response)

        except aiohttp.ClientError as e:
            if attempt == self.retry_config.max_retries:
                raise DhanConnectionError(message=str(e))
            await asyncio.sleep(self.retry_config.get_delay(attempt))
```

**Connection Pooling**:

```python
connector = aiohttp.TCPConnector(
    limit=100,              # Max total connections
    limit_per_host=10,      # Max connections per host
    ttl_dns_cache=300,      # DNS cache TTL
    use_dns_cache=True,
    keepalive_timeout=30,   # Keep-alive timeout
)
```

### 4.2 WebSocket Streaming Protocol

**File**: `broker/dhan/infrastructure/websocket_client.py` (689 lines)

**Technology**: `websockets` library with binary protocol decoding.

**Connection URL**:
```
wss://api-feed.dhan.co?version=2&token=<ACCESS_TOKEN>&clientId=<CLIENT_ID>&authType=2
```

**Binary Packet Format** (Little Endian):

```
┌─────────────────────────────────────────────────────────────────┐
│                        PACKET HEADER (8 bytes)                  │
├─────────┬───────────────┬───────────────────────┬───────────────┤
│ [0]     │ [1]           │ [2-3]                 │ [4-7]         │
│ Response│ Exchange      │ Sub-exchange/         │ SecurityId    │
│ Code    │ Segment       │ reserved              │ (uint32)      │
│ (uint8) │ (uint8)       │ (uint16)              │               │
├─────────┼───────────────┼───────────────────────┼───────────────┤
│ Values: │ 1=NSE_EQ      │                       │ Dhan's internal│
│ 2=Ticker│ 2=NSE_FNO     │                       │ instrument ID  │
│ 4=Quote │ 3=NSE_CURRENCY│                       │                │
│ 5=OI    │ 4=BSE_EQ      │                       │ Maps to REST   │
│ 6=Prev  │ 5=BSE_FNO     │                       │ security_id    │
│ 8=Full  │ 6=BSE_CURRENCY│                       │ via lookup     │
│ 50=Disc │ 7=MCX_COMM    │                       │                │
│         │ 13=MCX_FNO    │                       │                │
│         │ 16=IDX_I      │                       │                │
└─────────┴───────────────┴───────────────────────┴───────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     PACKET PAYLOADS                             │
├─────────┬───────────────┬───────────────────────────────────────┤
│ Type    │ Size          │ Fields                                │
├─────────┼───────────────┼───────────────────────────────────────┤
│ Ticker  │ 16 bytes      │ LTP (float32), LastTradeTime (uint32) │
│ (RC=2)  │               │                                       │
├─────────┼───────────────┼───────────────────────────────────────┤
│ Quote   │ 50 bytes      │ LTP, LTQ, LTT, ATP, Volume,           │
│ (RC=4)  │               │ TotalSellQty, TotalBuyQty,            │
│         │               │ Open, High, Low, Close (all float32)  │
├─────────┼───────────────┼───────────────────────────────────────┤
│ OI      │ 12 bytes      │ OpenInterest (uint32)                 │
│ (RC=5)  │               │                                       │
├─────────┼───────────────┼───────────────────────────────────────┤
│ Prev    │ 16 bytes      │ PrevClose (float32), PrevOI (uint32)  │
│ (RC=6)  │               │                                       │
├─────────┼───────────────┼───────────────────────────────────────┤
│ Full    │ 162 bytes     │ All Quote fields +                    │
│ (RC=8)  │               │ OI, HighOI, LowOI,                    │
│         │               │ 5-level depth (bid/ask price+qty)     │
├─────────┼───────────────┼───────────────────────────────────────┤
│ Disc    │ 10 bytes      │ ReasonCode (uint16)                   │
│ (RC=50) │               │                                       │
└─────────┴───────────────┴───────────────────────────────────────┘
```

**Binary Decoding Example**:

```python
def _decode_packet(self, data: bytes) -> WSMessage:
    # Header (8 bytes)
    response_code = struct.unpack('<B', data[0:1])[0]
    exchange_segment = struct.unpack('<B', data[1:2])[0]
    security_id = struct.unpack('<I', data[4:8])[0]

    # Map exchange segment code to string
    segment_str = _SEGMENT_MAP.get(exchange_segment, f"UNKNOWN_{exchange_segment}")

    # Decode payload based on response code
    if response_code == 2:  # Ticker
        ltp = struct.unpack('<f', data[8:12])[0]
        last_trade_time = struct.unpack('<I', data[12:16])[0]
        return WSMessage(
            response_code="TICKER",
            security_id=str(security_id),
            exchange_segment=segment_str,
            ltp=ltp,
            last_trade_time=last_trade_time,
        )

    elif response_code == 8:  # Full packet with depth
        # Decode OHLCV
        ltp = struct.unpack('<f', data[8:12])[0]
        ltq = struct.unpack('<I', data[12:16])[0]
        # ... more fields
        # Decode 5-level depth
        depth_bids = []
        depth_asks = []
        offset = 82  # Start of depth data
        for i in range(5):
            bid_price = struct.unpack('<f', data[offset:offset+4])[0]
            bid_qty = struct.unpack('<I', data[offset+4:offset+8])[0]
            depth_bids.append({"price": bid_price, "qty": bid_qty})
            offset += 8
        # ... similar for asks
```

**Subscription Flow**:

```python
# Send subscription message
subscription_msg = {
    "RequestCode": 15,  # Subscribe request
    "InstrumentCount": len(instruments),
    "InstrumentList": [
        {
            "ExchangeSegment": "NSE_FNO",
            "SecurityId": "35006"
        },
        # ... more instruments
    ]
}
await self._ws.send(json.dumps(subscription_msg))
```

**Reconnection Logic**:

```python
async def _reconnect(self):
    """Exponential backoff reconnection with subscription replay."""
    for attempt in range(self._max_reconnect_attempts):
        try:
            await self._connect()

            # Replay all subscriptions
            if self._subscriptions:
                instruments = [
                    {"ExchangeSegment": seg, "SecurityId": sid}
                    for sid, seg in self._sid_to_segment.items()
                    if sid in self._subscriptions
                ]
                await self._subscribe_instruments(instruments)

            self._reconnect_count = 0
            return

        except Exception as e:
            delay = min(self._reconnect_delay * (2 ** attempt), 60)
            logger.warning(f"Reconnect attempt {attempt+1} failed: {e}")
            await asyncio.sleep(delay)

    raise DhanWebSocketConnectionError("Max reconnection attempts reached")
```

### 4.3 Depth WebSocket Client (20/200 Level)

**File**: `broker/dhan/infrastructure/depth_websocket_client.py` (315 lines)

**Purpose**: Separate WebSocket connection for deep order book data.

**Differences from Main WebSocket**:
- Different URL endpoint
- Different binary protocol format
- Supports 20-level and 200-level depth
- Limited to NSE exchange only
- Max 50 instruments for 20-level, 1 instrument for 200-level

**Depth Packet Format**:
```
Header (same as main WS)
Payload:
  - Side (bid/ask indicator)
  - Number of levels
  - Array of {price: float32, qty: uint32} for each level
```

---

## 5. How Symbol Mapping Works

**File**: `broker/dhan/infrastructure/symbol_mapper.py` (867 lines)

### 5.1 Instrument Cache System

**Source**: Downloads from `https://images.dhan.co/api-data/api-scrip-master.csv`

**Size**: ~240,000 instruments covering all exchanges

**Cache Location**: `~/.cache/dhan_broker/instruments/`

**TTL**: 24 hours (configurable)

**Cache Structure**:

```python
class DhanSymbolMapper:
    # Primary lookup dictionaries
    _by_security_id: Dict[str, DhanInstrument]              # "12345" → instrument
    _by_symbol: Dict[str, DhanInstrument]                   # "RELIANCE:NSE_EQ" → instrument
    _by_trading_symbol: Dict[str, DhanInstrument]           # "RELIANCE" → instrument

    # Exchange-specific composites
    _by_trading_symbol_exchange: Dict[str, DhanInstrument]  # "RELIANCE:NSE_EQ" → instrument
    _by_trading_symbol_lower: Dict[str, DhanInstrument]     # "reliance:NSE_EQ" → instrument
    _by_symbol_lower: Dict[str, DhanInstrument]             # "reliance:NSE_EQ" → instrument

    # All instruments indexed by security_id
    _by_security_id: Dict[str, DhanInstrument]              # For iteration
```

### 5.2 Symbol Resolution Algorithm

**Resolution Priority** (6-step fallback chain):

```
Input: symbol="RELIANCE", exchange=Exchange.NSE

Step 1: Exact trading_symbol:exchange composite
    Key: "RELIANCE:NSE_EQ"
    Lookup: _by_trading_symbol_exchange
    If found → return security_id
    If not → continue

Step 2: Exact symbol:exchange key
    Key: "RELIANCE:NSE_EQ"
    Lookup: _by_symbol
    If found → return security_id
    If not → continue

Step 3: Case-insensitive trading_symbol match
    Key: "reliance:NSE_EQ"
    Lookup: _by_trading_symbol_lower
    If found → return security_id
    If not → continue

Step 4: Case-insensitive symbol match
    Key: "reliance:NSE_EQ"
    Lookup: _by_symbol_lower
    If found → return security_id
    If not → continue

Step 5: Canonical symbol matching
    Normalize: "RELIANCE" → canonicalize("RELIANCE")
    Iterate: _by_security_id values
    Compare: canonicalize(inst.trading_symbol) == canonical_input
    If match → return security_id
    If not → continue

Step 6: Fuzzy string matching
    Threshold: 0.8 (80% similarity)
    Iterate: _by_security_id values
    Score: fuzzy_match_score(symbol, inst.trading_symbol)
    Best match with score >= 0.8 → return security_id
    If no match → raise DhanSymbolNotFoundError
```

**Canonical Symbol Normalization**:

```python
def canonicalize_symbol(symbol: str) -> str:
    """Normalize symbol for comparison."""
    # Remove extra whitespace
    symbol = ' '.join(symbol.split())
    # Replace dashes/underscores with spaces
    symbol = symbol.replace('-', ' ').replace('_', ' ')
    # Uppercase
    symbol = symbol.upper()
    # Remove special characters except spaces
    symbol = re.sub(r'[^A-Z0-9\s]', '', symbol)
    return symbol
```

**Fuzzy Matching**:

```python
def fuzzy_match_score(s1: str, s2: str) -> float:
    """Calculate similarity score between two symbols."""
    # Uses sequence matcher from difflib
    # Returns 0.0-1.0 similarity score
    return SequenceMatcher(None, s1.lower(), s2.lower()).ratio()
```

### 5.3 Security ID Resolution Flow

**Called from**: `BaseDhanService._resolve_security_id()`

```python
async def _resolve_security_id(self, instrument: Instrument) -> str:
    """
    Resolution order:
    1. Pre-set security_id on the instrument
    2. Option symbol cache (for recently resolved options)
    3. Symbol mapper (with exchange segment conversion)
    """
    # Step 1: Check if security_id already set
    if instrument.security_id:
        return instrument.security_id

    # Step 2: Check option symbol cache
    cached_sid = self._option_symbol_cache.get(instrument.symbol)
    if cached_sid:
        return cached_sid

    # Step 3: Use symbol mapper
    if self._symbol_mapper:
        # Convert Exchange enum to Dhan segment
        segment = exchange_to_segment_name(instrument.exchange)
        exchange_segment = ExchangeSegment.from_name(segment)

        # Special case: Index underlyings use IDX_I segment
        if instrument.symbol.upper() in self._INDEX_UNDERLYINGS:
            exchange_segment = ExchangeSegment.IDX_I

        # Special case: MCX commodities need nearest futures contract
        if exchange_segment == ExchangeSegment.MCX:
            futures_inst = await self._symbol_mapper.get_nearest_futures_contract(
                instrument.symbol, exchange_segment
            )
            if futures_inst:
                return futures_inst.security_id

        # Standard resolution
        security_id = await self._symbol_mapper.get_security_id(
            instrument.symbol, exchange_segment
        )
        if security_id:
            return security_id

    raise DhanSymbolNotFoundError(...)
```

### 5.4 Parallel Instrument Resolution

**Used in**: Batch quote operations, streaming subscriptions

```python
async def _resolve_instruments_parallel(
    self, instruments: List[Instrument]
) -> Tuple[List[str], Dict[str, Instrument]]:
    """Resolve security IDs for multiple instruments concurrently."""
    async def _resolve_one(inst: Instrument):
        try:
            sid = await self._resolve_security_id(inst)
            return (inst, sid, None)
        except Exception as e:
            return (inst, None, e)

    # Concurrent resolution using asyncio.gather
    resolved = await asyncio.gather(*[_resolve_one(inst) for inst in instruments])

    security_ids = []
    instrument_map = {}
    for inst, sid, err in resolved:
        if err or not sid:
            logger.warning(f"Failed to resolve {inst.symbol}: {err}")
        else:
            security_ids.append(sid)
            instrument_map[sid] = inst

    return security_ids, instrument_map
```

---

## 6. How Option Methods Work

### 6.1 Option Chain Retrieval Flow

**File**: `broker/dhan/application/services/options_service.py` (257 lines)

**Two-Step API Process**:

```
Step 1: Get Expiry List
    POST /optionchain-expirylist
    Body: {"UnderlyingScrip": security_id, "UnderlyingSeg": "IDX_I"}
    Response: ["2024-03-28", "2024-04-04", "2024-04-11", ...]

Step 2: Get Option Chain for Selected Expiry
    POST /optionchain
    Body: {
        "UnderlyingScrip": security_id,
        "UnderlyingSeg": "IDX_I",
        "Expiry": "2024-03-28"
    }
    Response: {
        "last_price": 22100.50,  # Spot price
        "oc": {
            "21000": {
                "ce": {
                    "security_id": "12345",
                    "last_price": 1150.00,
                    "oi": 150000,
                    "volume": 25000,
                    "top_bid_price": 1145.00,
                    "top_ask_price": 1155.00,
                    "implied_volatility": 15.5,
                    "greeks": {
                        "delta": 0.85,
                        "gamma": 0.002,
                        "theta": -5.2,
                        "vega": 12.3
                    }
                },
                "pe": { ... }
            },
            "21500": { ... },
            ...
        }
    }
```

**Option Chain Construction**:

```python
async def get_option_chain_async(self, underlying, exchange, expiry_index=0):
    # 1. Resolve security ID for underlying
    security_id = await self._resolve_security_id(
        Instrument(symbol=underlying, exchange=exchange)
    )

    # 2. Determine API segment
    if underlying.upper() in self._INDEX_UNDERLYINGS:
        api_segment = "IDX_I"
    else:
        api_segment = exchange_to_option_chain_api_segment(exchange)

    # 3. Get expiry list
    expiry_response = await self._http_client.post(
        OPTIONCHAIN_EXPIRYLIST,
        {"UnderlyingScrip": int(security_id), "UnderlyingSeg": api_segment}
    )
    expiries = expiry_response.data.get("data", [])
    expiry = expiries[expiry_index]

    # 4. Get option chain
    response = await self._http_client.post(
        OPTIONCHAIN,
        {
            "UnderlyingScrip": int(security_id),
            "UnderlyingSeg": api_segment,
            "Expiry": expiry
        }
    )

    # 5. Parse response
    data = response.data.get("data", {})
    oc_data = data.get("oc", {})
    spot_price = float(data.get("last_price", 0))

    # 6. Build Option objects for each strike
    calls = {}
    puts = {}
    for strike_str, opt_data in oc_data.items():
        strike = float(strike_str)

        # Process CE
        ce_data = opt_data.get("ce", {})
        if ce_data and ce_data.get("security_id"):
            ce_symbol = self.format_option_symbol(underlying, expiry, strike, "CE")
            calls[strike] = Option(
                symbol=ce_symbol,
                security_id=str(ce_data["security_id"]),
                strike=strike,
                option_type="CE",
                expiry=datetime.strptime(expiry, "%Y-%m-%d"),
                ltp=float(ce_data.get("last_price", 0)),
                oi=int(ce_data.get("oi", 0)),
                volume=int(ce_data.get("volume", 0)),
                bid=float(ce_data.get("top_bid_price", 0)),
                ask=float(ce_data.get("top_ask_price", 0)),
                iv=float(ce_data.get("implied_volatility", 0)),
                delta=float(ce_greeks.get("delta", 0)),
                gamma=float(ce_greeks.get("gamma", 0)),
                theta=float(ce_greeks.get("theta", 0)),
                vega=float(ce_greeks.get("vega", 0)),
            )
            # Cache symbol → security_id for future lookups
            self._option_symbol_cache[ce_symbol] = str(ce_data["security_id"])

        # Process PE (similar logic)
        # ...

    # 7. Calculate ATM strike
    atm_strike = self._calculate_atm_strike(spot_price, exchange)

    return OptionChain(
        underlying=Instrument(symbol=underlying, exchange=exchange),
        expiry=datetime.strptime(expiry, "%Y-%m-%d"),
        spot_price=spot_price,
        atm_strike=atm_strike,
        step_size=get_step_size(underlying),
        calls=calls,
        puts=puts,
    )
```

### 6.2 Option Symbol Formatting

**Standard Format**: `{Underlying} {Day} {Month} {Strike} {Type}`

```python
@staticmethod
def format_option_symbol(underlying, expiry, strike, option_type):
    day = expiry.day                    # 27
    month = expiry.strftime("%b").upper()  # MAR
    strike_int = int(strike) if strike == int(strike) else strike  # 24000
    opt_text = "CALL" if option_type.upper() in ("CE", "CALL") else "PUT"
    return f"{underlying} {day} {month} {strike_int} {opt_text}"

# Examples:
# "NIFTY 27 MAR 24000 CALL"
# "BANKNIFTY 29 FEB 45000 PUT"
# "CRUDEOIL 17 MAR 6050 CALL"
```

### 6.3 Option Chain Analysis Methods

**ATM Calculation**:

```python
def _calculate_atm_strike(self, spot_price, exchange):
    """Find nearest strike to spot price."""
    step_size = get_step_size(underlying)  # e.g., 50 for NIFTY
    atm_strike = round(spot_price / step_size) * step_size
    return atm_strike
```

**Convenience Methods on OptionChain**:

```python
class OptionChain:
    def get_atm_options(self):
        """Return (ATM CE, ATM PE, ATM strike)"""
        ce = self.calls.get(self.atm_strike)
        pe = self.puts.get(self.atm_strike)
        return ce, pe, self.atm_strike

    def get_otm_options(self, distance=1):
        """Return (OTM CE, OTM PE) at distance from ATM"""
        ce_strike = self.atm_strike + (distance * self.step_size)
        pe_strike = self.atm_strike - (distance * self.step_size)
        return self.calls.get(ce_strike), self.puts.get(pe_strike)

    def get_itm_options(self, distance=1):
        """Return (ITM CE, ITM PE) at distance from ATM"""
        ce_strike = self.atm_strike - (distance * self.step_size)
        pe_strike = self.atm_strike + (distance * self.step_size)
        return self.calls.get(ce_strike), self.puts.get(pe_strike)

    def get_pcr(self):
        """Put/Call Ratio = Total Put OI / Total Call OI"""
        total_put_oi = sum(opt.oi for opt in self.puts.values() if opt.oi)
        total_call_oi = sum(opt.oi for opt in self.calls.values() if opt.oi)
        return total_put_oi / total_call_oi if total_call_oi > 0 else 0

    def get_max_pain_strike(self):
        """Strike with maximum combined OI"""
        oi_by_strike = {}
        for strike in self.calls.keys() | self.puts.keys():
            call_oi = self.calls.get(strike, Option(..., oi=0)).oi
            put_oi = self.puts.get(strike, Option(..., oi=0)).oi
            oi_by_strike[strike] = call_oi + put_oi
        return max(oi_by_strike, key=oi_by_strike.get)
```

### 6.4 Option Chain Streaming

**Reactive Polling**:

```python
def option_chain_stream(self, underlying, exchange, expiry_index=0, refresh_interval=5.0):
    """Periodic option chain snapshots via polling."""
    return self._create_timed_observable(
        lambda: self.get_option_chain(underlying, exchange, expiry_index),
        interval_seconds=refresh_interval
    )
```

**Diff Streaming** (incremental changes):

```python
def option_chain_diff_stream(self, underlying, exchange, expiry_index=0, refresh_interval=5.0):
    """Emits only changes between consecutive snapshots."""
    previous_chain = None

    def get_diff():
        nonlocal previous_chain
        current = self.get_option_chain(underlying, exchange, expiry_index)

        if previous_chain is None:
            previous_chain = current
            return {"spot": current.spot_price, "changes": {}}

        # Calculate OI changes per strike
        oi_changes = {}
        for strike in current.calls.keys() | previous_chain.calls.keys():
            curr_oi = current.calls.get(strike, Option(..., oi=0)).oi
            prev_oi = previous_chain.calls.get(strike, Option(..., oi=0)).oi
            if curr_oi != prev_oi:
                oi_changes[strike] = curr_oi - prev_oi

        previous_chain = current

        return {
            "spot": current.spot_price,
            "spot_change": current.spot_price - previous_chain.spot_price,
            "atm": current.atm_strike,
            "oi_changes": oi_changes,
        }

    return self._create_timed_observable(get_diff, interval_seconds=refresh_interval)
```

---

## 7. How Streaming Works

### 7.1 Streaming Service Architecture

**File**: `broker/dhan/application/services/streaming_service.py` (378 lines)

**Feed Types and Their Uses**:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         STREAMING FEED TYPES                                │
├──────────────┬────────────┬─────────────────────────────────────────────────┤
│ Feed         │ Method     │ Description                                     │
├──────────────┼────────────┼─────────────────────────────────────────────────┤
│ TICKER (2)   │ stream_    │ LTP + Volume only. Lightest feed.              │
│              │ ticker()   │ NSE/NFO only. Not for MCX.                     │
├──────────────┼────────────┼─────────────────────────────────────────────────┤
│ QUOTE (4)    │ stream_    │ OHLC + Bid/Ask + Volume. Medium weight.        │
│              │ quotes()   │ NSE/NFO only. Not for MCX.                     │
├──────────────┼────────────┼─────────────────────────────────────────────────┤
│ FULL (8)     │ stream_    │ Complete packet: OHLCV + 5-level depth + OI.   │
│              │ full()     │ ALL exchanges including MCX. Recommended feed. │
├──────────────┼────────────┼─────────────────────────────────────────────────┤
│ DEPTH 20     │ stream_    │ 20-level order book depth.                     │
│              │ depth_20() │ NSE only. Max 50 instruments.                  │
├──────────────┼────────────┼─────────────────────────────────────────────────┤
│ DEPTH 200    │ stream_    │ 200-level full depth.                          │
│              │ depth_200()│ NSE only. 1 instrument only.                   │
└──────────────┴────────────┴─────────────────────────────────────────────────┘
```

### 7.2 Streaming Flow

```
Client: async for tick in broker.stream_ticker([instrument]):
    │
    ▼
StreamingService.stream_ticker(instruments)
    │
    ├─ 1. Resolve security IDs for all instruments
    │      security_ids, inst_map = await self._resolve_instruments_parallel(instruments)
    │
    ├─ 2. Connect WebSocket if not connected
    │      await self._ws_client.connect()
    │
    ├─ 3. Subscribe to instruments
    │      await self._ws_client.subscribe(security_ids, feed_type=FEED_TYPE_TICKER)
    │
    ├─ 4. Start receiving messages
    │      async for msg in self._ws_client.receive():
    │          │
    │          ├─ Decode binary packet → WSMessage
    │          │
    │          ├─ Map WS security_id → REST security_id
    │          │      rest_sid = self._ws_sid_to_rest.get(msg.security_id)
    │          │
    │          ├─ Look up instrument
    │          │      inst = inst_map.get(rest_sid)
    │          │
    │          ├─ Convert to domain entity
    │          │      tick = Tick(instrument=inst, price=msg.ltp, ...)
    │          │
    │          └─ Yield to caller
    │                 yield tick
    │
    └─ 5. Handle disconnection
           - Auto-reconnect with subscription replay
           - Continue yielding after reconnect
```

### 7.3 Full Packet Streaming (MCX Support)

**Why `stream_full()` is special**:
- Only feed that works for MCX commodities
- Returns complete market data including 5-level depth
- Used as fallback when other feeds raise `DhanFeedNotSupportedError`

```python
async def stream_full(self, instruments):
    """Stream FULL packets for any exchange (including MCX)."""
    security_ids, inst_map = await self._resolve_instruments_parallel(instruments)

    await self._ws_client.connect()
    await self._ws_client.subscribe(security_ids, feed_type=FEED_TYPE_FULL)

    async for msg in self._ws_client.receive():
        if msg.response_code == "FULL":
            # Map WS security_id to REST security_id
            rest_sid = self._ws_sid_to_rest.get(msg.security_id)
            inst = inst_map.get(rest_sid)

            if inst:
                yield {
                    "symbol": inst.symbol,
                    "ltp": msg.ltp,
                    "open": msg.open,
                    "high": msg.high,
                    "low": msg.low,
                    "close": msg.close,
                    "volume": msg.volume,
                    "oi": msg.oi,
                    "atp": msg.atp,
                    "depth_bids": msg.depth_bids,  # 5 levels
                    "depth_asks": msg.depth_asks,  # 5 levels
                    "security_id": rest_sid,
                    "exchange_segment": msg.exchange_segment,
                    "timestamp": msg.timestamp,
                }
```

### 7.4 Depth Streaming (20/200 Level)

**File**: `broker/dhan/infrastructure/depth_websocket_client.py`

**Dedicated WebSocket Connection**:
- Separate from main market feed
- Different URL and protocol
- Binary decoding for depth levels

```python
async def stream_depth_20(self, instruments):
    """20-level depth via dedicated depth feed."""
    # Use DepthWebSocketClient instead of main WS
    depth_ws = DepthWebSocketClient()
    await depth_ws.connect()

    # Subscribe (max 50 instruments)
    await depth_ws.subscribe(instruments, depth_level=20)

    async for msg in depth_ws.receive():
        # msg contains: side (bid/ask), levels (list of {price, qty})
        yield MarketDepth(
            instrument=inst_map[msg.security_id],
            side=msg.side,
            levels=msg.levels,  # Up to 20 levels
        )
```

---

## 8. How Orders Work

### 8.1 Order Service Architecture

**File**: `broker/dhan/application/services/order_service.py` (140 lines)

**Order Flow**:

```
Client: broker.place_order(order)
    │
    ▼
DhanBroker.place_order(order)
    │
    ├─ _run_async(self._orders.place_order_async(order))
    │
    ▼
OrderService.place_order_async(order)
    │
    ├─ 1. Rate limit check
    │      await self._apply_rate_limit("order")
    │
    ├─ 2. Circuit breaker check
    │      response = await self._execute_with_cb(lambda: ...)
    │
    ├─ 3. Resolve security ID
    │      security_id = await self._resolve_security_id(order.instrument)
    │
    ├─ 4. Build API payload
    │      payload = {
    │          "orderType": order.order_type,        # MARKET, LIMIT, SL, SLM
    │          "transactionType": order.side,         # BUY, SELL
    │          "tradingSymbol": order.symbol,
    │          "exchangeSegment": segment,
    │          "quantity": order.quantity,
    │          "price": order.price or 0,
    │          "triggerPrice": order.trigger_price or 0,
    │          "validity": "DAY",                     # DAY, IOC
    │          "productType": order.product_type,     # INTRADAY, MARGIN, CO, BO
    │      }
    │
    ├─ 5. POST to Dhan API
    │      response = await self._http_client.post("/orders", payload)
    │
    ├─ 6. Parse response
    │      order_id = response.data.get("data", {}).get("orderId")
    │      status = response.data.get("data", {}).get("orderStatus")
    │
    └─ 7. Return updated Order
           return Order(order_id=order_id, status=status, ...)
```

**Order Types Supported**:

```python
# Order Types
MARKET   # Execute at current market price
LIMIT    # Execute at specified price or better
SL       # Stop Loss (triggers at trigger_price, executes at limit price)
SLM      # Stop Loss Market (triggers at trigger_price, executes at market)

# Product Types
INTRADAY # Square off by end of day
MARGIN   # Carry forward positions
CO       # Cover Order (with stop loss)
BO       # Bracket Order (with target and stop loss)

# Validity
DAY      # Valid for the trading day
IOC      # Immediate or Cancel
```

### 8.2 Order Status and Cancellation

```python
async def cancel_order_async(self, order_id: str) -> bool:
    """Cancel an existing order."""
    response = await self._http_client.put(f"/orders/{order_id}")
    return response.status_code in (200, 201)

async def get_order_status_async(self, order_id: str) -> Order:
    """Get current status of an order."""
    response = await self._http_client.get(f"/orders/{order_id}")
    data = response.data.get("data", {})
    return Order(
        order_id=data.get("orderId"),
        status=data.get("orderStatus"),
        symbol=data.get("tradingSymbol"),
        quantity=data.get("quantity"),
        price=data.get("price"),
        # ... other fields
    )

async def get_orderbook_async(self) -> List[Order]:
    """Get all orders in the orderbook."""
    response = await self._http_client.get("/orders")
    orders = response.data.get("data", [])
    return [self._parse_order(o) for o in orders]
```

---

## 9. How Portfolio Works

### 9.1 Portfolio Service Architecture

**File**: `broker/dhan/application/services/portfolio_service.py` (122 lines)

**Position Tracking**:

```python
async def get_positions_async(self) -> List[Position]:
    """Get all open positions."""
    response = await self._http_client.get("/positions")
    positions = response.data.get("data", [])
    return [self._parse_position(p) for p in positions]

def _parse_position(self, data: dict) -> Position:
    """Parse position data from API response."""
    return Position(
        symbol=data.get("tradingSymbol"),
        exchange=self._parse_exchange(data.get("exchangeSegment")),
        quantity=int(data.get("quantity", 0)),
        avg_price=float(data.get("averagePrice", 0)),
        current_price=float(data.get("currentPrice", 0)),
        pnl=float(data.get("profitLoss", 0)),
        product_type=data.get("productType"),
    )
```

**Trade History and P&L**:

```python
async def get_trade_history_async(self, from_date=None, to_date=None):
    """Get historical trades."""
    params = {}
    if from_date:
        params["from_date"] = from_date.strftime("%Y-%m-%d")
    if to_date:
        params["to_date"] = to_date.strftime("%Y-%m-%d")

    response = await self._http_client.get("/trade-history", params=params)
    return response.data.get("data", [])

async def get_pnl_async(self, from_date=None, to_date=None):
    """Get P&L summary."""
    params = {}
    if from_date:
        params["from_date"] = from_date.strftime("%Y-%m-%d")
    if to_date:
        params["to_date"] = to_date.strftime("%Y-%m-%d")

    response = await self._http_client.get("/pnl", params=params)
    return response.data.get("data", {})
```

---

## 10. How Authentication Works

**File**: `broker/dhan/infrastructure/auth_provider.py` (1045 lines)

### 10.1 Authentication Flow

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         AUTHENTICATION FLOW                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  1. Token Validation                                                        │
│     ┌─────────────────────────────────────────────────────────────────┐     │
│     │ Is token present?                                               │     │
│     │  ├─ Yes → Check expiry                                          │     │
│     │  │    ├─ Valid → Use existing token                             │     │
│     │  │    ├─ Near expiry (<5 min) → Refresh token                   │     │
│     │  │    └─ Expired → Generate new token                           │     │
│     │  └─ No → Generate new token                                     │     │
│     └─────────────────────────────────────────────────────────────────┘     │
│                                                                             │
│  2. Token Generation (if needed)                                            │
│     ┌─────────────────────────────────────────────────────────────────┐     │
│     │ POST /login                                                     │     │
│     │ Body: {"clientId": "...", "password": "..."}                    │     │
│     │ Response: {"data": {"token": "..."}}                            │     │
│     └─────────────────────────────────────────────────────────────────┘     │
│                                                                             │
│  3. TOTP Validation (if configured)                                         │
│     ┌─────────────────────────────────────────────────────────────────┐     │
│     │ Generate TOTP from secret                                       │     │
│     │ POST /validate-otp                                              │     │
│     │ Body: {"clientId": "...", "otp": "..."}                         │     │
│     │ Response: {"data": {"token": "..."}}                            │     │
│     └─────────────────────────────────────────────────────────────────┘     │
│                                                                             │
│  4. Token Persistence                                                       │
│     ┌─────────────────────────────────────────────────────────────────┐     │
│     │ Save to .env file:                                              │     │
│     │ DHAN_ACCESS_TOKEN=<new_token>                                   │     │
│     │ DHAN_TOKEN_EXPIRY=<expiry_timestamp>                            │     │
│     └─────────────────────────────────────────────────────────────────┘     │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 10.2 Token Management

```python
class DhanAuthProvider:
    def __init__(self, http_client=None):
        self._http = http_client
        self._totp_secret = None
        self._pin = None
        self._access_token = None
        self._client_id = None
        self._token_expiry = None

    def is_expired(self) -> bool:
        """Check if current token is expired."""
        if not self._token_expiry:
            return True
        return datetime.now() >= self._token_expiry

    def is_near_expiry(self, buffer_minutes=5) -> bool:
        """Check if token will expire soon."""
        if not self._token_expiry:
            return True
        buffer = timedelta(minutes=buffer_minutes)
        return datetime.now() + buffer >= self._token_expiry

    async def ensure_valid_token_sync(self, client_id: str) -> str:
        """
        Ensure valid token (sync wrapper for broker creation).
        Flow: valid → reuse | near-expiry → refresh | expired → generate
        """
        if self._access_token and not self.is_expired():
            if self.is_near_expiry():
                return await self.refresh_token()
            return self._access_token

        # Generate new token
        return await self.generate_token(client_id)

    async def generate_token(self, client_id: str) -> str:
        """Generate new access token via login + TOTP flow."""
        # Step 1: Login
        login_response = await self._http.post("/login", {
            "clientId": client_id,
            "password": self._password,
        })
        login_token = login_response.data["data"]["token"]

        # Step 2: TOTP validation (if configured)
        if self._totp_secret:
            totp = self._generate_totp()
            otp_response = await self._http.post("/validate-otp", {
                "clientId": client_id,
                "otp": totp,
            })
            access_token = otp_response.data["data"]["token"]
        else:
            access_token = login_token

        # Step 3: Set token and expiry
        self.set_token(access_token, client_id)

        # Step 4: Persist to .env
        self._persist_token(access_token)

        return access_token

    async def refresh_token(self) -> str:
        """Refresh existing token."""
        if self._totp_secret:
            totp = self._generate_totp()
            response = await self._http.post("/validate-otp", {
                "clientId": self._client_id,
                "otp": totp,
            })
            new_token = response.data["data"]["token"]
            self.set_token(new_token, self._client_id)
            self._persist_token(new_token)
            return new_token

        raise DhanTokenExpiredError("Token expired and no TOTP configured")
```

### 10.3 Runtime Token Refresh

**HTTP Client Integration**:

```python
class DhanHttpClient:
    async def _request_with_retry(self, method, url, **kwargs):
        for attempt in range(self.retry_config.max_retries + 1):
            response = await self._session.request(method, url, **kwargs)

            if response.status == 401 and self._auth_provider:
                # Auto-refresh token on 401
                new_token = await self._auth_provider.refresh_token()
                self._access_token = new_token
                # Update headers
                self._session.headers["access-token"] = new_token
                self._session.headers["Authorization"] = f"Bearer {new_token}"
                continue

            return self._map_response(response)
```

---

## 11. How Resilience Works

### 11.1 Circuit Breaker Pattern

**File**: `broker/dhan/infrastructure/resilience.py` (365 lines)

**State Machine**:

```
                    failure_count >= threshold
    ┌──────────────────────────────────────────┐
    │                                          │
    │                                          ▼
┌─────────┐   recovery_timeout elapsed   ┌──────────┐
│ CLOSED  │─────────────────────────────▶│   OPEN   │
│(Normal) │                              │(FailFast)│
└─────────┘                              └────┬─────┘
     ▲                                        │
     │ success_count >= threshold             │
     │                                        ▼
     │                                 ┌──────────────┐
     └─────────────────────────────────│  HALF_OPEN   │
          success                      │  (Testing)   │
                                       └──────────────┘
```

**Implementation**:

```python
class DhanCircuitBreaker:
    def __init__(
        self,
        failure_threshold=5,
        recovery_timeout=60.0,
        success_threshold=3,
    ):
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout
        self._success_threshold = success_threshold

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = None
        self._lock = asyncio.Lock()

    async def execute(self, operation):
        """Execute operation through circuit breaker."""
        async with self._lock:
            if self._state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self._state = CircuitState.HALF_OPEN
                else:
                    raise CircuitBreakerError("Circuit breaker is OPEN")

        try:
            result = await operation()

            async with self._lock:
                self._on_success()
            return result

        except Exception as e:
            async with self._lock:
                self._on_failure()
            raise

    def _on_success(self):
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self._success_threshold:
                self._state = CircuitState.CLOSED
                self._failure_count = 0
                self._success_count = 0
        else:
            self._failure_count = 0

    def _on_failure(self):
        self._failure_count += 1
        self._last_failure_time = datetime.now()

        if self._failure_count >= self._failure_threshold:
            self._state = CircuitState.OPEN

    def _should_attempt_reset(self):
        if not self._last_failure_time:
            return True
        elapsed = (datetime.now() - self._last_failure_time).total_seconds()
        return elapsed >= self._recovery_timeout
```

### 11.2 Rate Limiting

**Token Bucket Algorithm**:

```python
class TokenBucketRateLimiter:
    def __init__(self, capacity=100, refill_rate=10.0):
        self._capacity = capacity        # Max tokens
        self._refill_rate = refill_rate  # Tokens per second
        self._tokens = capacity
        self._last_refill = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, category="default"):
        """Acquire a token, waiting if necessary."""
        while True:
            async with self._lock:
                self._refill()
                if self._tokens >= 1:
                    self._tokens -= 1
                    return

            # Wait for token refill
            wait_time = 1.0 / self._refill_rate
            await asyncio.sleep(wait_time)

    def _refill(self):
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        new_tokens = elapsed * self._refill_rate
        self._tokens = min(self._capacity, self._tokens + new_tokens)
        self._last_refill = now
```

### 11.3 HTTP Retry Logic

```python
class RetryConfig:
    max_retries: int = 3
    backoff_factor: float = 0.5      # 0.5s, 1s, 2s
    max_delay: float = 30.0          # Cap at 30s
    retry_on_status: tuple = (408, 429, 500, 502, 503, 504)

    def get_delay(self, attempt: int) -> float:
        """Exponential backoff: 0.5 * 2^attempt"""
        delay = self.backoff_factor * (2 ** attempt)
        return min(delay, self.max_delay)
```

---

## 12. How Error Handling Works

### 12.1 Error Mapping Strategy

**HTTP Client Error Mapping**:

```python
def _map_error(self, status_code: int, response_data: dict) -> DhanError:
    """Map HTTP status codes to domain errors."""
    if status_code == 401:
        return DhanTokenExpiredError(
            message="Token expired",
            code="TOKEN_EXPIRED",
        )
    elif status_code == 429:
        return DhanRateLimitError(
            message="Rate limit exceeded",
            code="RATE_LIMIT",
        )
    elif status_code == 404:
        return DhanSymbolNotFoundError(
            message="Symbol not found",
            code="SYMBOL_NOT_FOUND",
        )
    elif status_code >= 500:
        return DhanConnectionError(
            message=f"Server error: {status_code}",
            code="SERVER_ERROR",
        )
    else:
        return DhanApiError(
            message=response_data.get("message", "Unknown error"),
            code=response_data.get("error_code", "UNKNOWN"),
        )
```

### 12.2 Error Propagation

**Sync Methods**: Exceptions bubble up directly to caller

**Async Methods**: Exceptions raised in async iterators

**Circuit Breaker**: Wraps exceptions in `CircuitBreakerError` when open

**Gateway Level**: `CircuitBreakerWrapper` catches and wraps errors

### 12.3 Structured Logging

**File**: `broker/logging/__init__.py`

```python
def get_logger(name: str):
    """Get logger with correlation ID support."""
    logger = logging.getLogger(name)

    # Add correlation ID to all log messages
    correlation_id = get_correlation_id()
    if correlation_id:
        logger = logging.LoggerAdapter(logger, {"correlation_id": correlation_id})

    return logger

# Usage
logger.info("Order placed", extra={
    "order_id": "12345",
    "symbol": "RELIANCE",
    "correlation_id": "abc-123-def",
})
```

---

## 13. Complete Flow Diagrams

### 13.1 Full System Flow: Quote Retrieval

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────┐
│   Client    │     │  BrokerGateway  │     │ CircuitBreaker  │     │   Broker    │
│             │     │                 │     │   Wrapper       │     │             │
└──────┬──────┘     └─────────┬───────┘     └─────────┬───────┘     └──────┬──────┘
       │                      │                       │                    │
       │ get_quote("RELIANCE")│                       │                    │
       │ Exchange.NSE         │                       │                    │
       └─────────────────────▶│                       │                    │
                              │                       │                    │
                              │ Instrument("RELIANCE")│                    │
                              │──────────────────────▶│                    │
                              │                       │                    │
                              │ can_execute()?        │                    │
                              │──────────────────────▶│                    │
                              │                       │                    │
                              │   CLOSED → allow      │                    │
                              │◀──────────────────────│                    │
                              │                       │                    │
                              │ get_quote(instrument) │                    │
                              │──────────────────────▶│                    │
                              │                       │                    │
                              │                       │  _run_async(...)   │
                              │                       │───────────────────▶│
                              │                       │                    │
                              │                       │  _market_data.     │
                              │                       │  get_quote_async() │
                              │                       │                    │
                              │                       │  Rate limit check  │
                              │                       │  Circuit breaker   │
                              │                       │  Resolve security  │
                              │                       │  HTTP POST /quote  │
                              │                       │                    │
                              │                       │   Quote response   │
                              │                       │◀───────────────────│
                              │                       │                    │
                              │      Quote            │                    │
                              │◀──────────────────────│                    │
                              │                       │                    │
                              │ record_success()      │                    │
                              │──────────────────────▶│                    │
                              │                       │                    │
       ◀──────────────────────┼───────────────────────┼────────────────────┼──────
       │                      │                       │                    │
       │       Quote          │                       │                    │
       │  ltp=2450.50         │                       │                    │
       │  volume=150000       │                       │                    │
       └──────────────────────│                       │                    │
                              │                       │                    │
```

### 13.2 Full System Flow: Streaming Subscription

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────┐
│   Client    │     │ ReactiveBroker  │     │  DhanBroker     │     │  WebSocket  │
│             │     │                 │     │                 │     │   Server    │
└──────┬──────┘     └─────────┬───────┘     └─────────┬───────┘     └──────┬──────┘
       │                      │                       │                    │
       │ ticker_stream(["NIFTY"])                     │                    │
       │ Exchange.NFO                                 │                    │
       └─────────────────────▶│                       │                    │
                              │                       │                    │
                              │ _to_instruments()     │                    │
                              │ Instrument("NIFTY")   │                    │
                              │──────────────────────▶│                    │
                              │                       │                    │
                              │ Observable[Tick]      │                    │
       ◀──────────────────────┼───────────────────────┼────────────────────┼──────
       │                      │                       │                    │
       │ subscribe(on_next)   │                       │                    │
       └─────────────────────▶│                       │                    │
                              │                       │                    │
                              │ New thread + loop     │                    │
                              │──────────────────────▶│                    │
                              │                       │                    │
                              │ stream_ticker([inst]) │                    │
                              │──────────────────────▶│                    │
                              │                       │                    │
                              │ resolve_security_id() │                    │
                              │ → "35006"             │                    │
                              │                       │                    │
                              │ ws.connect()          │                    │
                              │───────────────────────│───────────────────▶│
                              │                       │                    │
                              │ ws.subscribe(["35006"])                      │
                              │───────────────────────│───────────────────▶│
                              │                       │                    │
                              │   Binary packets      │                    │
                              │◀──────────────────────│────────────────────│
                              │                       │                    │
                              │ Decode → Tick         │                    │
                              │                       │                    │
                              │ on_next(tick)         │                    │
       ┌──────────────────────┼───────────────────────┼────────────────────┼──────
       │                      │                       │                    │
       │ tick callback        │                       │                    │
       │ Tick(price=22100)    │                       │                    │
       └──────────────────────│                       │                    │
                              │                       │                    │
```

### 13.3 Full System Flow: Option Chain Retrieval

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────┐
│   Client    │     │  BrokerGateway  │     │  DhanBroker     │     │  Dhan API   │
│             │     │                 │     │                 │     │             │
└──────┬──────┘     └─────────┬───────┘     └─────────┬───────┘     └──────┬──────┘
       │                      │                       │                    │
       │ get_option_chain(    │                       │                    │
       │  "NIFTY", NFO, 0)    │                       │                    │
       └─────────────────────▶│                       │                    │
                              │                       │                    │
                              │ _broker.get_option_   │                    │
                              │ chain("NIFTY", NFO, 0)                     │
                              │──────────────────────▶│                    │
                              │                       │                    │
                              │ _run_async(           │                    │
                              │  _options.            │                    │
                              │  get_option_chain_    │                    │
                              │  async(...))          │                    │
                              │                       │                    │
                              │                       │ 1. resolve_security│
                              │                       │    → "12345"       │
                              │                       │                    │
                              │                       │ 2. POST /optionchain│
                              │                       │    -expirylist     │
                              │                       │───────────────────▶│
                              │                       │                    │
                              │                       │ ["2024-03-28", ...]│
                              │                       │◀───────────────────│
                              │                       │                    │
                              │                       │ 3. POST /optionchain│
                              │                       │───────────────────▶│
                              │                       │                    │
                              │                       │ {last_price, oc: { │
                              │                       │  "22000": {ce,pe}, │
                              │                       │  ...}}             │
                              │                       │◀───────────────────│
                              │                       │                    │
                              │                       │ 4. Build OptionChain│
                              │                       │    - Parse strikes │
                              │                       │    - Create Options│
                              │                       │    - Calc ATM      │
                              │                       │                    │
                              │      OptionChain      │                    │
                              │◀──────────────────────│                    │
                              │                       │                    │
       ◀──────────────────────┼───────────────────────┼────────────────────┼──────
       │                      │                       │                    │
       │   OptionChain        │                       │                    │
       │   spot=22100         │                       │                    │
       │   atm=22100          │                       │                    │
       │   calls={...}        │                       │                    │
       │   puts={...}         │                       │                    │
       └──────────────────────│                       │                    │
                              │                       │                    │
```

### 13.4 Full System Flow: Order Placement

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────┐
│   Client    │     │  BrokerGateway  │     │  DhanBroker     │     │  Dhan API   │
│             │     │                 │     │                 │     │             │
└──────┬──────┘     └─────────┬───────┘     └─────────┬───────┘     └──────┬──────┘
       │                      │                       │                    │
       │ place_order(Order(   │                       │                    │
       │  symbol="RELIANCE",  │                       │                    │
       │  side="BUY",         │                       │                    │
       │  quantity=10,        │                       │                    │
       │  price=2450.00))     │                       │                    │
       └─────────────────────▶│                       │                    │
                              │                       │                    │
                              │ DRY_RUN check         │                    │
                              │ (if True, mock order) │                    │
                              │                       │                    │
                              │ _broker.place_order() │                    │
                              │──────────────────────▶│                    │
                              │                       │                    │
                              │ _run_async(           │                    │
                              │  _orders.             │                    │
                              │  place_order_async()) │                    │
                              │                       │                    │
                              │                       │ 1. Rate limit      │
                              │                       │ 2. Circuit breaker │
                              │                       │ 3. Resolve security│
                              │                       │ 4. Build payload   │
                              │                       │                    │
                              │                       │ 5. POST /orders    │
                              │                       │───────────────────▶│
                              │                       │                    │
                              │                       │ {orderId: "12345", │
                              │                       │  orderStatus: "..."│
                              │                       │ }                  │
                              │                       │◀───────────────────│
                              │                       │                    │
                              │      Order            │                    │
                              │◀──────────────────────│                    │
                              │                       │                    │
       ◀──────────────────────┼───────────────────────┼────────────────────┼──────
       │                      │                       │                    │
       │   Order              │                       │                    │
       │   order_id="12345"   │                       │                    │
       │   status="PENDING"   │                       │                    │
       └──────────────────────│                       │                    │
                              │                       │                    │
```

---

## 14. Exchange Support Matrix

| Feature | NSE_EQ | NSE_FNO | BSE_EQ | MCX_COMM | IDX_I |
|---------|--------|---------|--------|----------|-------|
| **Market Data** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **Historical Data** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **stream_full()** | ✅ | ✅ | ✅ | ✅ | ✅ |
| **stream_ticker()** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **stream_quotes()** | ✅ | ✅ | ❌ | ❌ | ❌ |
| **stream_depth_20()** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **stream_depth_200()** | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Option Chains** | ❌ | ✅ | ❌ | ✅ | ❌ |
| **Order Placement** | ✅ | ✅ | ✅ | ✅ | ❌ |
| **Position Tracking** | ✅ | ✅ | ✅ | ✅ | ❌ |

**Notes**:
- MCX requires `stream_full()` for market data (other feeds not supported)
- NSE depth feeds have symbol limits (50 for depth_20, 1 for depth_200)
- INDEX instruments are read-only (no trading)
- MCX options are supported via option chain API

---

## 15. Performance Characteristics

### 15.1 Latency Benchmarks

| Operation | Sync (HTTP) | Async (WebSocket) |
|-----------|-------------|-------------------|
| Single Quote | 100-300ms | 50-100ms (initial) |
| Batch Quotes (10) | 200-500ms | 50-100ms (initial) |
| Historical (1 day) | 500-2000ms | N/A |
| Stream Subscription | N/A | <50ms |
| Option Chain | 300-800ms | N/A |
| Order Placement | 200-500ms | N/A |

### 15.2 Memory Usage

- **Instrument Cache**: ~50MB (240K instruments)
- **WebSocket Connections**: ~1MB per connection
- **Circuit Breaker**: Minimal (<1KB)
- **RxPY Observables**: ~10-50KB per active stream

### 15.3 Concurrency Limits

- **HTTP Requests**: Rate limited (10-20 req/sec depending on plan)
- **WebSocket Feeds**: Up to 100 symbols per connection
- **Thread Pools**: 1 persistent event loop thread per broker instance
- **Circuit Breaker**: Configurable failure thresholds

---

## Appendix A: Complete File Structure

```
brokers/
├── __init__.py                    # Package exports and auto .env loading
├── gateway.py                     # BrokerGateway, BrokerFactory (422 lines)
├── reactive.py                    # ReactiveBroker with RxPY (896 lines)
├── requirements.txt               # Dependencies
├── ARCHITECTURE.md                # High-level architecture
├── ARCHITECTURE_REVIEW.md         # Issues and recommendations
├── AGENT.md                       # Agent integration guide
├── REACTIVE_QUICKSTART.md         # RxPY usage guide
│
├── broker/                        # Core broker abstraction
│   ├── __init__.py                # Re-exports: Exchange, Instrument, etc.
│   ├── ports.py                   # IBrokerPort, IReactiveBroker (804 lines)
│   ├── entities.py                # Re-exports from shared.entities
│   ├── types.py                   # Re-exports from shared.entities
│   ├── market_info.py             # Lot sizes, step sizes, market hours (321 lines)
│   ├── validation.py              # OHLC data validation
│   ├── symbol_matcher.py          # Symbol matching utilities
│   ├── mcx_futures.py             # MCX futures utilities
│   ├── bulk_historical.py         # Bulk historical download
│   ├── resilience.py              # Shared resilience patterns
│   │
│   ├── paper/                     # Paper trading implementation
│   │   └── broker.py              # In-memory broker (396 lines)
│   │
│   ├── utils/                     # Utility modules
│   │   ├── __init__.py
│   │   └── symbol.py              # Symbol canonicalization, fuzzy matching (276 lines)
│   │
│   ├── logging/                   # Structured logging
│   │   ├── __init__.py            # Logger factory, correlation IDs (71 lines)
│   │   ├── logging_config.py      # Logging configuration
│   │   └── logging_context.py     # Execution context tracking
│   │
│   └── dhan/                      # Dhan broker implementation
│       ├── __init__.py
│       │
│       ├── application/           # Application layer
│       │   ├── broker.py          # DhanBroker facade (822 lines)
│       │   ├── config.py          # DhanConfig
│       │   ├── facade.py          # Convenience facade
│       │   ├── converters.py      # Data converters
│       │   ├── exchange_resolver.py # Exchange detection
│       │   └── services/          # Business services
│       │       ├── base.py        # Base service (162 lines)
│       │       ├── market_data_service.py  # Quotes (172 lines)
│       │       ├── historical_service.py   # Historical data
│       │       ├── streaming_service.py    # WebSocket feeds (378 lines)
│       │       ├── options_service.py      # Option chains (257 lines)
│       │       ├── order_service.py        # Order management (140 lines)
│       │       └── portfolio_service.py    # Portfolio (122 lines)
│       │
│       ├── domain/                # Domain layer
│       │   ├── entities.py        # DhanInstrument, etc. (816 lines)
│       │   ├── value_objects.py   # Value objects
│       │   ├── errors.py          # Error hierarchy (597 lines)
│       │   ├── constants.py       # API URLs, segments, limits (271 lines)
│       │   └── segment_mapping.py # Exchange ↔ segment mapping (150 lines)
│       │
│       ├── infrastructure/        # Infrastructure layer
│       │   ├── http_client.py     # aiohttp REST client (707 lines)
│       │   ├── websocket_client.py # WebSocket binary decoder (689 lines)
│       │   ├── depth_websocket_client.py # 20/200 depth WS (315 lines)
│       │   ├── symbol_mapper.py   # CSV cache, symbol resolution (867 lines)
│       │   ├── auth_provider.py   # TOTP auth, JWT management (1045 lines)
│       │   └── resilience.py      # Rate limiter, circuit breaker (365 lines)
│       │
│       └── ports/                 # Dhan-specific protocols
│           ├── __init__.py        # Re-exports all ports
│           ├── http_port.py       # IHttpClient
│           ├── websocket_port.py  # IWebSocketClient
│           ├── mapper_port.py     # ISymbolMapper
│           ├── auth_port.py       # IAuthProvider
│           └── resilience_port.py # IRateLimiter, ICircuitBreaker
│
├── tests/                         # Integration tests
│   ├── test_dhan_broker.py
│   ├── test_gateway.py
│   ├── test_entities.py
│   ├── test_validation.py
│   └── ...
│
└── scripts/                       # Demo and verification scripts
    ├── test_connection.py
    ├── test_nse_mcx_live.py
    ├── test_full_quote_and_depth_live.py
    └── ...
```

## Appendix B: Key Design Patterns Summary

| Pattern | Implementation | Purpose |
|---------|---------------|---------|
| **Port/Adapter** | `IBrokerPort` + `DhanBroker` | Decouple domain from infrastructure |
| **Facade** | `DhanBroker` delegates to services | Simplify complex subsystem |
| **Factory** | `BrokerFactory.create()` | Centralized broker creation |
| **Decorator** | `CircuitBreakerWrapper` | Add cross-cutting concerns |
| **Observer** | RxPY Observables | Reactive event processing |
| **Strategy** | Multiple `IBrokerPort` implementations | Pluggable broker backends |
| **Circuit Breaker** | `DhanCircuitBreaker` | Fault tolerance |
| **Token Bucket** | `TokenBucketRateLimiter` | Rate limiting |
| **Repository** | `DhanSymbolMapper` cache | Efficient symbol resolution |
| **Service Layer** | `MarketDataService`, etc. | SRP for business logic |
