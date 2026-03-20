# Architectural Plan
## GlassyTrade AI — AMT Order Flow Strategy Engine

**Document Version:** 1.0
**Date:** 2026-03-17
**Status:** Draft
**Source Documents:** srs.md, fulldoc.md, startergy.md

---

## 1. Architecture Overview

### 1.1 System Context

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                          External Systems                                   │
│                                                                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐                  │
│  │  DhanHQ WS   │    │ DhanHQ REST  │    │  Economic    │                  │
│  │  (Tick Feed) │    │  (L2 DOM)    │    │  Calendar    │                  │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘                  │
│         │                   │                   │                           │
└─────────┼───────────────────┼───────────────────┼───────────────────────────┘
          │                   │                   │
          ▼                   ▼                   ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                        GlassyTrade AI Engine                                │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                         DATA LAYER                                   │   │
│  │  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐               │   │
│  │  │ DhanWSClient │  │DhanRESTClient│  │EconomicCal   │               │   │
│  │  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘               │   │
│  │         │                 │                 │                         │   │
│  │         └─────────────────┼─────────────────┘                         │   │
│  │                           ▼                                           │   │
│  │                  ┌─────────────────┐                                  │   │
│  │                  │  DuckDB Store   │                                  │   │
│  │                  └─────────────────┘                                  │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                       SIGNAL ENGINE                                  │   │
│  │                                                                      │   │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐              │   │
│  │  │TickProcessor│───►│CandleBuilder│───►│ProfileEngine│              │   │
│  │  └─────────────┘    └─────────────┘    └──────┬──────┘              │   │
│  │                                               │                      │   │
│  │  ┌─────────────────────────────────────────────┴──────────────────┐  │   │
│  │  │                    OrderFlowEngine                             │  │   │
│  │  │  ┌─────────┐ ┌───────────┐ ┌─────────┐ ┌──────────┐          │  │   │
│  │  │  │   CVD   │ │ Footprint │ │ Bubble  │ │Absorption│          │  │   │
│  │  │  └─────────┘ └───────────┘ └─────────┘ └──────────┘          │  │   │
│  │  │  ┌─────────┐ ┌───────────┐ ┌─────────┐ ┌──────────┐          │  │   │
│  │  │  │BigTrade │ │    OFI    │ │  VWAP   │ │    IB    │          │  │   │
│  │  │  └─────────┘ └───────────┘ └─────────┘ └──────────┘          │  │   │
│  │  └───────────────────────────────────────────────────────────────┘  │   │
│  │                                                                      │   │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐              │   │
│  │  │MarketState  │───►│ProfileSelect│───►│DriveTracker │              │   │
│  │  │  Engine     │    │             │    │             │              │   │
│  │  └─────────────┘    └─────────────┘    └──────┬──────┘              │   │
│  │                                               │                      │   │
│  │  ┌─────────────┐    ┌─────────────┐    ┌──────┴──────┐              │   │
│  │  │Aggression   │───►│TradeConstruc│───►│RiskManager  │              │   │
│  │  │  Scorer     │    │    tor      │    │             │              │   │
│  │  └─────────────┘    └─────────────┘    └─────────────┘              │   │
│  │                                                                      │   │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐              │   │
│  │  │PartitionExit│───►│  Pyramid    │───►│CounterAggres│              │   │
│  │  │  Manager    │    │  Manager    │    │   sion      │              │   │
│  │  └─────────────┘    └─────────────┘    └─────────────┘              │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
│  ┌──────────────────────────────────────────────────────────────────────┐   │
│  │                        OUTPUT LAYER                                  │   │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐              │   │
│  │  │SignalFormat │───►│OutputSchema │───►│WSPublisher  │───► Frontend │   │
│  │  └─────────────┘    └─────────────┘    └─────────────┘              │   │
│  └──────────────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Module Boundaries & Responsibilities

### 2.1 Core Layer (`src/core/`)

| Module | File | Responsibility | Dependencies |
|---|---|---|---|
| TickProcessor | `tick_processor.py` | Normalize raw WebSocket ticks | None |
| CandleBuilder | `candle_builder.py` | Build OHLCV candles from tick stream | TickProcessor |
| SessionManager | `session_manager.py` | Session boundary detection, state init/reset | Config |
| SymbolState | `symbol_state.py` | SymbolState dataclass — all state per symbol | None |

### 2.2 Profile Layer (`src/profile/`)

| Module | File | Responsibility | Dependencies |
|---|---|---|---|
| VolumeProfile | `volume_profile.py` | Session + Leg profile build, POC, VAH/VAL | SymbolState |
| ProfileSelector | `profile_selector.py` | Which profile is active — SESSION/LEG/COMBINED | MarketState |
| NodeDetector | `node_detector.py` | LVN, HVN detection + LVN quality scoring | VolumeProfile |
| LegAnchor | `leg_anchor.py` | Auto-detect leg start, reset logic | VolumeProfile, MarketState |

### 2.3 OrderFlow Layer (`src/orderflow/`)

| Module | File | Responsibility | Dependencies |
|---|---|---|---|
| CVDEngine | `cvd_engine.py` | CVD, slope, divergence | SymbolState |
| FootprintEngine | `footprint_engine.py` | Per-candle per-level bid/ask + imbalance | SymbolState |
| BubbleDetector | `bubble_detector.py` | Volume bubble (2σ threshold) | FootprintEngine |
| AbsorptionDetector | `absorption_detector.py` | Absorption candle detection | SymbolState |
| BigTradeDetector | `big_trade_detector.py` | Institutional big trade cluster | SymbolState |
| OFICalculator | `ofi_calculator.py` | Order Flow Imbalance (10-candle rolling) | SymbolState |
| VWAPEngine | `vwap_engine.py` | VWAP + σ bands | SymbolState |
| IBDetector | `ib_detector.py` | Initial Balance + IB break | SymbolState |

### 2.4 Strategy Layer (`src/strategy/`)

| Module | File | Responsibility | Dependencies |
|---|---|---|---|
| MarketStateEngine | `market_state_engine.py` | BALANCED/IMBALANCED/PROBING/NO_TRADE | VolumeProfile |
| AggressionScorer | `aggression_scorer.py` | Multi-signal scoring (max 4.5 score) | All OrderFlow modules |
| TradeConstructor | `trade_constructor.py` | Entry, SL, target, R:R, cushion | AggressionScorer, RiskManager |
| ProfileSelector | `profile_selector.py` | Select active profile and key levels | MarketStateEngine, VolumeProfile |
| SessionRiskManager | `session_risk_manager.py` | Daily loss, drawdown, consecutive loss gates | Persistence |
| PositionSizer | `position_sizer.py` | Fixed fractional lot sizing | SessionRiskManager |
| PartitionExitManager | `partition_exit_manager.py` | P1/P2/P3 exits + BE + counter-aggression hard exit | CVDEngine |
| PyramidManager | `pyramid_manager.py` | Pyramid eligibility, add sizing, unified stop updates | VolumeProfile, AggressionScorer, SessionRiskManager |

### 2.5 Risk Layer (`src/risk/`)

Current implementation is consolidated under `src/strategy/` for risk and trade-management responsibilities. The `src/risk/` and `src/trade_management/` packages are present as placeholders for future extraction.

### 2.6 Trade Management Layer (`src/trade_management/`)

Current implementation is consolidated under `src/strategy/`:

- `partition_exit_manager.py` owns partition exit, break-even trigger, and counter-aggression hard exit behavior.
- `pyramid_manager.py` owns pyramid add gating, sizing, and stop updates.

### 2.7 Data Layer (`src/data/`)

| Module | File | Responsibility | Dependencies |
|---|---|---|---|
| TickProcessor | `tick_processor.py` | Tick normalization and validation | None |
| CandleBuilder | `candle_builder.py` | Candle construction from ticks | TickProcessor |
| ATRCalculator | `atr_calculator.py` | ATR calculations for strategy/risk decisions | CandleBuilder |
| Persistence | `persistence.py` | Session/trade persistence utilities | DuckDB |

### 2.8 Output Layer (`src/output/`)

| Module | File | Responsibility | Dependencies |
|---|---|---|---|
| Output Package | `__init__.py` | Output layer placeholder | None |

### 2.9 Config Layer (`src/config/`)

| Module | File | Responsibility | Dependencies |
|---|---|---|---|
| Instruments | `instruments.py` | Per-symbol config (tick size, lot size, etc.) | None |
| EngineConfig | `engine_config.py` | Global thresholds (LVN %, ATR mult, etc.) | None |

---

## 3. Data Flow Architecture

### 3.1 Tick Processing Pipeline

```
NEW TICK ARRIVES
│
├─ 1. TickProcessor.process_tick() → normalized tick
│
├─ 2. CandleBuilder.update() → update current candle
│
├─ 3. ProfileEngine.update_session_bucket() → O(1) increment
│
├─ 4. CVDEngine.append_delta() → running CVD update
│
├─ 5. FootprintEngine.update_cell() → per-level bid/ask update
│
├─ 6. BubbleDetector.check() → fire if 2σ threshold crossed
│
├─ 7. On candle close: [triggered by time boundary]
│    ├─ Finalize candle → push to buffer
│    ├─ Recalculate ATR, AvgVol, OFI
│    ├─ Update VWAP state
│    ├─ Check IB break
│    └─ Recalculate full footprint for closed candle
│
├─ 8. MarketStateEngine.evaluate() → current state
│
├─ 9. If state valid: DriveTracker.classify_drive()
│
├─ 10. If drive 2 valid: AggressionScorer.score()
│
├─ 11. If score ≥ 2.0: TradeConstructor.build()
│
├─ 12. RiskManager.validate() → position size or block
│
├─ 13. If open trade: PartitionExitManager.check()
│                    PyramidManager.check()
│
└─ 14. SignalFormatter.format() → JSON output → push to UI
```

### 3.2 Concurrency Model

```python
# One async task per symbol — all run in single event loop
# No threading — avoids GIL and race conditions on shared state

async def symbol_pipeline(symbol: str, state: SymbolState, queue: asyncio.Queue):
    """
    Each symbol runs its own independent pipeline coroutine.
    Ticks are pushed to the queue by the WebSocket client.
    """
    while True:
        tick = await queue.get()
        await process_tick_pipeline(tick, state)
        queue.task_done()

async def main():
    states = {sym: SymbolState(sym) for sym in ACTIVE_SYMBOLS}
    queues = {sym: asyncio.Queue() for sym in ACTIVE_SYMBOLS}

    # WS client pushes to all queues
    ws_task = asyncio.create_task(dhan_ws_client(queues))

    # L2 DOM poller — 500ms per symbol
    l2_tasks = [asyncio.create_task(l2_poller(sym, states[sym]))
                for sym in ACTIVE_SYMBOLS]

    # Symbol pipelines
    pipelines = [asyncio.create_task(symbol_pipeline(sym, states[sym], queues[sym]))
                 for sym in ACTIVE_SYMBOLS]

    await asyncio.gather(ws_task, *l2_tasks, *pipelines)
```

---

## 4. Interface Specifications

### 4.1 Internal REST API (FastAPI)

| Endpoint | Method | Purpose | Response |
|---|---|---|---|
| `/api/symbols` | GET | List all active symbols | Symbol list with state |
| `/api/signal/{symbol}` | GET | Get latest signal for symbol | Full OutputSchema |
| `/api/profile/{symbol}` | GET | Get profile data for symbol | Profile with POC/VAH/VAL/LVNs |
| `/api/risk/session` | GET | Get session risk metrics | Risk state JSON |
| `/api/trade/entry` | POST | Manual trade entry override | Trade confirmation |
| `/api/trade/exit` | POST | Manual trade exit override | Exit confirmation |
| `/api/config/{symbol}` | GET | Get instrument config | Config JSON |
| `/api/config/{symbol}` | PUT | Update instrument config | Updated config |

### 4.2 WebSocket Push API (Frontend)

**Endpoint:** `ws://localhost:8000/ws/signals`

| Message Type | Description | Payload |
|---|---|---|
| `SIGNAL` | New trade signal | Full OutputSchema |
| `TRADE_UPDATE` | Trade management update | Trade ID, action, lots, price, reason |
| `RISK_EVENT` | Session risk event | Event type, value, reason |
| `STATE_CHANGE` | Market state change | Symbol, from, to, direction, timestamp |
| `DRIVE_ALERT` | Drive level alert | Symbol, drive number, level, action |
| `DATA_QUALITY` | Data quality alert | Symbol, quality, gap_seconds |
| `HEARTBEAT` | Connection heartbeat | Timestamp, symbols_active |

### 4.3 DhanHQ Integration Contracts

#### WebSocket Subscription
```json
{
  "RequestCode": 15,
  "InstrumentCount": 1,
  "InstrumentList": [
    {
      "ExchangeSegment": "MCX_COMM",
      "SecurityId": "428199"
    }
  ]
}
```

#### Expected Tick Payload
```json
{
  "type":        "ticker",
  "symbol":      "NATURALGAS",
  "LTP":         9.35,
  "buy_qty":     125,
  "sell_qty":    75,
  "trade_size":  200,
  "timestamp":   "2026-03-17T19:45:00.123456+05:30",
  "exchange":    "MCX"
}
```

#### L2 DOM Poll
```
GET https://api.dhan.co/marketfeed/ohlc
Headers: access-token: {token}
Body: {"NSE_FO": ["428199"]}
```

---

## 5. Database Schema (DuckDB)

### 5.1 Tables

```sql
-- Session profiles persisted at close
CREATE TABLE session_profiles (
    date        DATE,
    symbol      VARCHAR,
    poc         DECIMAL(10,2),
    vah         DECIMAL(10,2),
    val         DECIMAL(10,2),
    total_vol   BIGINT,
    profile_json JSON,
    created_at  TIMESTAMP
);

-- All ticks stored intraday, purged daily
CREATE TABLE ticks (
    timestamp   TIMESTAMP,
    symbol      VARCHAR,
    price       DECIMAL(10,2),
    ask_vol     INTEGER,
    bid_vol     INTEGER,
    trade_size  INTEGER,
    delta       INTEGER
);

-- Signal log — every output schema written here
CREATE TABLE signals (
    timestamp       TIMESTAMP,
    symbol          VARCHAR,
    direction       VARCHAR,
    confidence      VARCHAR,
    aggression_score DECIMAL(4,2),
    entry_zone      DECIMAL(10,2),
    stop_loss       DECIMAL(10,2),
    target          DECIMAL(10,2),
    risk_reward     DECIMAL(4,2),
    market_state    VARCHAR,
    drive_number    INTEGER,
    rationale       TEXT,
    full_json       JSON
);

-- Trade log — entries, exits, PnL
CREATE TABLE trades (
    trade_id        UUID,
    symbol          VARCHAR,
    entry_time      TIMESTAMP,
    exit_time       TIMESTAMP,
    direction       VARCHAR,
    entry_price     DECIMAL(10,2),
    exit_price      DECIMAL(10,2),
    lots            INTEGER,
    pnl             DECIMAL(10,2),
    risk_pct        DECIMAL(5,3),
    partition       INTEGER,
    exit_reason     VARCHAR
);

-- Session risk log
CREATE TABLE session_risk (
    date            DATE,
    symbol          VARCHAR,
    daily_pnl       DECIMAL(10,2),
    max_drawdown    DECIMAL(5,3),
    total_trades    INTEGER,
    win_rate        DECIMAL(4,3),
    consecutive_losses INTEGER,
    session_killed  BOOLEAN
);
```

---

## 6. State Management

### 6.1 Per-Symbol State (SymbolState)

```python
@dataclass
class SymbolState:
    symbol:              str
    # Profiles
    session_profile:     Dict[float, int]
    session_va:          Optional[ValueArea]
    prev_session_va:     Optional[ValueArea]
    leg_profile:         Dict[float, int]
    leg_anchor:          Optional[dict]
    # Buffers
    tick_buffer:         deque  # maxlen=10000
    candle_buffer:       deque  # maxlen=200
    cvd_series:          List[dict]
    # State
    drive_tracker:       Optional[DriveTracker]
    risk_manager:        Optional[SessionRiskManager]
    open_entries:        List[OpenEntry]
    # Indicators
    atr:                 float
    avg_vol:             float
    avg_trade_size:      float
    vwap_state:          dict
    ib:                  dict
    ofi:                 float
    # Session
    session_start_ts:    Optional[datetime]
    is_session_active:   bool
    data_quality:        str  # LIVE | STALE | RECONNECTING
    last_tick_ts:        Optional[datetime]
    last_signal:         Optional[dict]
```

---

## 7. Deployment Architecture

### 7.1 Single-Process Design

The engine runs as a single Python process with async event loop:
- No multi-process complexity
- No shared memory concerns
- All state in-memory per symbol
- DuckDB for persistence only

### 7.2 Startup Sequence

1. Load configuration (instruments, engine config)
2. Initialize DuckDB connection
3. Load previous session profiles from DuckDB
4. Create SymbolState for each active symbol
5. Start WebSocket client task
6. Start L2 DOM poller tasks
7. Start symbol pipeline tasks
8. Start FastAPI server for API + WebSocket push

### 7.3 Shutdown Sequence

1. Stop accepting new ticks
2. Flush all pending calculations
3. Persist session profiles to DuckDB
4. Close WebSocket connections
5. Close DuckDB connection
6. Exit

---

## 8. Error Handling & Recovery

### 8.1 WebSocket Reconnection

```python
class DhanWSClient:
    async def connect(self):
        while True:
            try:
                async with websockets.connect(self.uri, ...) as ws:
                    await self.subscribe(ws)
                    self.reconnect_delay = 2  # Reset on success
                    async for message in ws:
                        await self.handle_message(message)
            except Exception as e:
                # Mark all symbols as RECONNECTING
                for sym in self.queues:
                    update_state_quality(sym, "RECONNECTING")
                await asyncio.sleep(min(self.reconnect_delay, 30))
                self.reconnect_delay = min(self.reconnect_delay * 2, 30)
```

### 8.2 Data Quality States

| State | Trigger | Action |
|---|---|---|
| `LIVE` | Normal operation | Process all signals |
| `STALE` | Gap > 30 seconds | Suppress all signals |
| `RECONNECTING` | WebSocket disconnect | Suppress all signals, attempt reconnect |

---

## 9. Performance Considerations

### 9.1 O(1) Profile Updates

```python
class VolumeProfileEngine:
    def update(self, tick: Tick):
        bucket = round(tick.price / self.bucket_size) * self.bucket_size
        self.session[bucket] = self.session.get(bucket, 0) + tick.volume
        if self._leg_active:
            self.leg[bucket] = self.leg.get(bucket, 0) + tick.volume
```

### 9.2 Buffer Management

- Tick buffer: 10,000 ticks max (rolling window)
- Candle buffer: 200 candles max
- CVD series: unbounded (session-scoped, reset daily)

---

## 10. Security Considerations

- DhanHQ access token stored in environment variable
- No secrets in code or config files
- API endpoints should be localhost-only in production
- WebSocket connections authenticated via token

---

**Document Control:**
- Created: 2026-03-17
- Last Modified: 2026-03-17
- Next Review: TBD
- Approved By: TBD
