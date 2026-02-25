# Brokers Library — Agent Guide

> Comprehensive reference for AI agents integrating with the `brokers/` library.
> Read this file instead of diving into implementation internals.

## Quick Start

```python
from brokers.broker.dhan.application.broker import DhanBroker
from brokers.broker import Instrument, Exchange, FullPacket, DepthLevel

# 1. Create broker (reads DHAN_CLIENT_ID + DHAN_ACCESS_TOKEN from env)
broker = DhanBroker.create()

# 2. Initialize (loads instrument cache — ~240K instruments, takes ~15s)
await broker.initialize()

# 3. Build instruments using human-readable symbols
inst = Instrument(symbol="CRUDEOIL 17 MAR 6050 CALL", exchange=Exchange.MCX)

# 4. Use broker methods
quote = broker.get_quote(inst)
df = broker.get_historical(inst, from_date, to_date, interval="5")
```

## Instrument Construction

```python
from brokers.broker import Instrument, Exchange

# Equities
nifty = Instrument(symbol="NIFTY", exchange=Exchange.NSE)

# Futures / Options (NFO)
nifty_opt = Instrument(symbol="NIFTY 27 MAR 24000 CALL", exchange=Exchange.NFO)

# MCX Commodities
crude = Instrument(symbol="CRUDEOIL 17 MAR 6050 CALL", exchange=Exchange.MCX)
gold = Instrument(symbol="GOLD", exchange=Exchange.MCX)
```

The broker resolves `security_id` internally from the symbol + exchange.
You never need to set `security_id` manually.

## Exchange Enum

```python
from brokers.broker.types import Exchange

Exchange.NSE      # NSE equities + indices
Exchange.NFO      # NSE F&O
Exchange.MCX      # MCX commodities
Exchange.BSE      # BSE equities
Exchange.INDEX    # Index instruments
```

## Streaming

### `stream_full()` — Primary Live Feed

Works for **all exchanges including MCX**. This is the recommended feed.

```python
async for pkt in broker.stream_full([inst]):
    # pkt is a FullPacket (frozen dataclass)
    print(pkt.ltp, pkt.volume, pkt.oi)
    print(pkt.depth_bids)  # tuple of dicts: [{"price": ..., "qty": ...}, ...]
    print(pkt.depth_asks)
```

#### FullPacket Fields

| Field | Type | Description |
|-------|------|-------------|
| `symbol` | `str` | Human-readable symbol |
| `ltp` | `float` | Last traded price |
| `open` | `float` | Session open |
| `high` | `float` | Session high |
| `low` | `float` | Session low |
| `close` | `float` | Previous close |
| `volume` | `int` | **Cumulative daily volume** (not per-tick) |
| `oi` | `int` | Open interest (0 for equities) |
| `atp` | `float` | Average traded price (day VWAP) |
| `total_buy_qty` | `int` | Total bid quantity |
| `total_sell_qty` | `int` | Total ask quantity |
| `depth_bids` | `tuple` | 5-level bid depth: `({"price": float, "qty": int}, ...)` |
| `depth_asks` | `tuple` | 5-level ask depth: `({"price": float, "qty": int}, ...)` |
| `security_id` | `str` | Dhan internal ID |
| `exchange_segment` | `str` | e.g. `"NSE_EQ"`, `"MCX_COMM"` |
| `timestamp` | `datetime` | Server timestamp (IST) |

### `stream_ticker()` — LTP Only (NSE/NFO only)

```python
async for tick in broker.stream_ticker([inst]):
    print(tick.price, tick.volume)
```

**Not supported for MCX.** Raises `DhanFeedNotSupportedError`.

### `stream_quotes()` — OHLC + Bid/Ask (NSE/NFO only)

```python
async for quote in broker.stream_quotes([inst]):
    print(quote.ltp, quote.bid, quote.ask)
```

**Not supported for MCX.** Raises `DhanFeedNotSupportedError`.

### `stream_depth_20()` — 20-Level Depth (NSE only)

```python
async for depth in broker.stream_depth_20([inst]):
    print(depth.side, depth.levels)  # "bid" or "ask", list[DepthLevel]
```

Max 50 NSE instruments. **Not supported for MCX.**

### `stream_depth_200()` — 200-Level Full Depth (NSE only)

Single instrument only. **Not supported for MCX.**

### MCX Streaming Summary

| Feed | MCX Support |
|------|-------------|
| `stream_full()` | Yes |
| `stream_ticker()` | No |
| `stream_quotes()` | No |
| `stream_depth_20()` | No |
| `stream_depth_200()` | No |

## Sync vs Async Methods

| Method | Sync/Async | Notes |
|--------|-----------|-------|
| `DhanBroker.create()` | Sync | Factory, no I/O |
| `broker.initialize()` | **Async** | Loads instrument cache |
| `broker.get_quote()` | Sync | HTTP call |
| `broker.get_quotes_batch()` | Sync | HTTP call |
| `broker.get_historical()` | Sync | HTTP call, returns DataFrame |
| `broker.get_ltp()` | Sync | HTTP call |
| `broker.get_option_chain()` | Sync | HTTP call |
| `broker.get_expiry_list()` | Sync | HTTP call |
| `broker.place_order()` | Sync | HTTP call |
| `broker.cancel_order()` | Sync | HTTP call |
| `broker.get_positions()` | Sync | HTTP call |
| `broker.stream_full()` | **Async generator** | WebSocket |
| `broker.stream_ticker()` | **Async generator** | WebSocket |
| `broker.stream_quotes()` | **Async generator** | WebSocket |
| `broker.stream_depth_20()` | **Async generator** | WebSocket |

## Error Hierarchy

```
Exception
└── DhanError                         # Base for all broker errors
    ├── DhanApiError                   # HTTP API failures (code, message)
    ├── DhanAuthError                  # Authentication failures
    ├── DhanSymbolNotFoundError        # Symbol resolution failed
    ├── DhanFeedNotSupportedError      # Feed type not supported for exchange
    ├── DhanRateLimitError             # API rate limit exceeded
    └── DhanConnectionError            # WebSocket / network failures
```

All errors in `brokers/broker/dhan/domain/errors.py`.

## MarketDataPort (Backend Domain Contract)

The backend uses `MarketDataPort` (abstract class) to decouple from broker internals.
Implemented by `DhanMarketDataAdapter` in `backend/app/infrastructure/adapters/dhan_adapter.py`.

### Methods

| Method | Returns | Empty/No-Data | Error |
|--------|---------|---------------|-------|
| `ensure_initialized_sync(timeout)` | `None` | N/A | Raises on failure |
| `fetch_history(symbol, interval, limit)` | `list[OHLC]` | `[]` | `[]` (logged) |
| `fetch_order_book(symbol)` | `OrderBook \| None` | `None` | `None` (logged) |
| `get_ltp(symbol)` | `float` | `0.0` | `0.0` (logged) |
| `stream_full(symbols)` | `AsyncIterator[dict]` | Generator ends | Raises |
| `get_option_chain(underlying, exchange, expiry_index)` | `OptionChain \| None` | `None` | Raises |

### stream_full() Dict Keys (from DhanMarketDataAdapter)

The adapter converts `FullPacket` → `dict` via `dataclasses.asdict()`.
Keys match FullPacket field names exactly.

## Initialization Sequence

```
DhanBroker.create(client_id, access_token)
    → DhanBroker instance (not yet initialized)

await broker.initialize()
    → Downloads/loads instrument cache (~240K instruments)
    → Populates symbol → security_id mapping
    → broker.is_initialized = True

# From backend adapter (sync path):
adapter.ensure_initialized_sync(timeout=120)
    → Creates temp event loop
    → Runs broker.initialize() with timeout
    → Thread-safe via _init_lock
```

## Data Formats

- **Timestamps**: IST `datetime` objects (UTC+5:30)
- **Volume**: Cumulative daily volume (not per-tick delta)
- **Depth**: 5-level from `stream_full()`, each level is `{"price": float, "qty": int}`
- **Historical intervals**: `"1"` (1m), `"5"` (5m), `"15"` (15m), `"25"` (25m), `"60"` (1h), `"1d"` (daily)
- **Option symbols**: `"CRUDEOIL 17 MAR 6050 CALL"` format (underlying + DD MMM strike type)

## File Structure

```
brokers/
├── AGENT.md                          ← This file
├── broker/
│   ├── __init__.py                   # Re-exports: Exchange, Instrument, FullPacket, etc.
│   ├── types.py                      # Enums: Exchange, OptionType, OrderSide, etc.
│   ├── entities.py                   # Domain entities: Instrument, FullPacket, Quote, etc.
│   ├── ports.py                      # IBrokerPort abstract class
│   ├── market_info.py                # Lot sizes, step sizes
│   └── dhan/
│       ├── application/
│       │   ├── broker.py             # DhanBroker — main entry point
│       │   └── services/
│       │       ├── streaming_service.py   # WebSocket streaming
│       │       ├── market_data_service.py # Quotes, historical
│       │       ├── order_service.py       # Order placement
│       │       └── options_service.py     # Option chains
│       ├── domain/
│       │   ├── constants.py          # API URLs, feed type codes
│       │   ├── errors.py             # Error hierarchy
│       │   └── segment_mapping.py    # Exchange → segment string
│       ├── infrastructure/
│       │   ├── websocket_client.py   # Binary protocol decoder
│       │   ├── depth_websocket_client.py  # 20/200-level depth
│       │   └── http_client.py        # REST API client
│       └── ports/
│           ├── __init__.py           # Re-exports all port protocols
│           ├── http_port.py          # IHttpClient protocol
│           ├── websocket_port.py     # IWebSocketClient protocol
│           ├── mapper_port.py        # ISymbolMapper protocol
│           ├── auth_port.py          # IAuthProvider protocol
│           └── resilience_port.py    # IRateLimiter, ICircuitBreaker
```
