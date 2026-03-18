Here is the complete next set of documents in the SDLC chain — **TDD, API Contract, Test Plan, Deployment Architecture, Operations Runbook, and Data Dictionary**. [scribd](https://www.scribd.com/document/923519913/Fabio-Playbook)

***

# Document Set 2 — Technical Design, API, Testing, Deployment & Operations

***

# Document 1 — Technical Design Document (TDD)

***

## TDD-01 — Module Breakdown & Responsibilities

```
src/
│
├── core/
│   ├── tick_processor.py         # Normalize raw WebSocket ticks
│   ├── candle_builder.py         # Build OHLCV candles from tick stream
│   ├── session_manager.py        # Session boundary detection, state init/reset
│   └── symbol_state.py           # SymbolState dataclass — all state per symbol
│
├── profile/
│   └── volume_profile_engine.py  # Session + Leg profile build, POC, VAH/VAL
│
├── orderflow/
│   ├── cvd_engine.py             # CVD, slope, divergence
│   ├── footprint_engine.py       # Per-candle per-level bid/ask + imbalance
│   ├── bubble_detector.py        # Volume bubble (2σ threshold)
│   ├── absorption_detector.py    # Absorption candle detection
│   ├── big_trade_detector.py     # Institutional big trade cluster
│   ├── ofi_calculator.py         # Order Flow Imbalance (10-candle rolling)
│   ├── vwap_engine.py            # VWAP + σ bands
│   └── ib_detector.py            # Initial Balance + IB break
│
├── strategy/
│   ├── market_state_engine.py    # BALANCED/IMBALANCED/PROBING/NO_TRADE
│   ├── aggression_scorer.py      # Multi-signal scoring (max 4.5 score)
│   ├── trade_constructor.py      # Entry, SL, target, R:R, cushion
│   ├── profile_selector.py       # Which profile is active — SESSION/LEG
│   ├── session_risk_manager.py   # Daily loss, drawdown, consecutive loss gates
│   ├── position_sizer.py         # Fixed fractional lot sizing
│   ├── partition_exit_manager.py # P1/P2/P3 + BE + counter-aggression exits
│   └── pyramid_manager.py        # Pyramid add conditions + sizing
│
├── data/
│   ├── tick_processor.py         # Tick normalization and validation
│   ├── candle_builder.py         # Candle construction from ticks
│   ├── atr_calculator.py         # ATR metrics for strategy/risk logic
│   └── persistence.py            # Persistence primitives
│
├── output/
│   └── __init__.py               # Output package placeholder
│
├── config/
│   ├── instruments.py            # Per-symbol config (tick size, lot size, etc.)
│   └── engine_config.py          # Global thresholds (LVN %, ATR mult, etc.)
│
└── tests/                        # Unit + integration coverage
```

***

## TDD-02 — Data Structures (All Key Types)

```python
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict
from collections import deque

@dataclass
class Tick:
    price:       float
    ask_vol:     int
    bid_vol:     int
    volume:      int
    trade_size:  int
    delta:       int
    timestamp:   datetime

@dataclass
class Candle:
    start_ts:   datetime
    end_ts:     datetime
    open:       float
    high:       float
    low:        float
    close:      float
    volume:     int
    ask_vol:    int
    bid_vol:    int
    delta:      int
    tick_count: int

@dataclass
class ValueArea:
    POC:          float
    VAH:          float
    VAL:          float
    total_volume: int
    va_volume:    int

@dataclass
class LVN:
    price:         float
    volume:        int
    quality_score: float
    sigma_below_mean: float

@dataclass
class DriveRecord:
    level:        float
    timestamp:    datetime
    was_rejected: bool
    rejection_type: Optional[str]  # WICK | CLOSE | None

@dataclass
class AggressionResult:
    score:     float
    confirmed: bool   # score >= 2.0
    signals:   List[str]
    breakdown: Dict[str, float]  # {"footprint": 1.0, "cvd": 1.0, ...}

@dataclass
class TradeSetup:
    direction:       str      # LONG | SHORT
    confidence:      str      # High | Medium | Low
    entry_zone:      float
    stop_loss:       float
    sl_ticks:        int
    cushion_quality: str
    target:          float
    risk_reward:     float
    invalidation:    float
    break_even_at:   float
    lots:            int
    risk_amount:     float
    risk_pct:        float
    drive_number:    int
    aggression:      AggressionResult

@dataclass
class OpenEntry:
    entry_id:    str
    price:       float
    lots:        int
    stop_loss:   float
    add_number:  int    # 1 = first, 2 = pyramid 1, 3 = pyramid 2
    timestamp:   datetime
    pnl:         float = 0.0

@dataclass
class SymbolState:
    symbol:              str
    # Profiles
    session_profile:     Dict[float, int] = field(default_factory=dict)
    session_va:          Optional[ValueArea] = None
    prev_session_va:     Optional[ValueArea] = None
    leg_profile:         Dict[float, int] = field(default_factory=dict)
    leg_anchor:          Optional[dict] = None
    # Buffers
    tick_buffer:         deque = field(default_factory=lambda: deque(maxlen=10000))
    candle_buffer:       deque = field(default_factory=lambda: deque(maxlen=200))
    cvd_series:          List[dict] = field(default_factory=list)
    # State
    drive_tracker:       Optional[object] = None
    risk_manager:        Optional[object] = None
    open_entries:        List[OpenEntry] = field(default_factory=list)
    # Indicators
    atr:                 float = 0.0
    avg_vol:             float = 0.0
    avg_trade_size:      float = 0.0
    vwap_state:          dict = field(default_factory=dict)
    ib:                  dict = field(default_factory=dict)
    ofi:                 float = 0.0
    # Session
    session_start_ts:    Optional[datetime] = None
    is_session_active:   bool = False
    data_quality:        str = "LIVE"
    last_tick_ts:        Optional[datetime] = None
    last_signal:         Optional[dict] = None
```

***

## TDD-03 — Concurrency Model

```python
# One async task per symbol — all run in single event loop
# No threading — avoids GIL and race conditions on shared state

import asyncio

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

***

## TDD-04 — Profile Incremental Update (O(1) per tick)

```python
class VolumeProfileEngine:
    """
    Incremental bucket update — avoids full rebuild every tick.
    Session profile and leg profile maintained independently.
    """
    def __init__(self, bucket_size: float):
        self.bucket_size = bucket_size
        self.session:  Dict[float, int] = {}
        self.leg:      Dict[float, int] = {}
        self._leg_active = False

    def update(self, tick: Tick):
        bucket = round(tick.price / self.bucket_size) * self.bucket_size

        # Always update session profile
        self.session[bucket] = self.session.get(bucket, 0) + tick.volume

        # Update leg profile only when leg is active
        if self._leg_active:
            self.leg[bucket] = self.leg.get(bucket, 0) + tick.volume

    def start_leg(self):
        self.leg = {}
        self._leg_active = True

    def stop_leg(self):
        self._leg_active = False

    def reset_session(self):
        self.session = {}
        self.leg = {}
        self._leg_active = False

    def get_poc(self, profile: str = "session") -> float:
        p = self.session if profile == "session" else self.leg
        return max(p, key=p.get) if p else 0.0

    def get_value_area(self, profile: str = "session") -> ValueArea:
        p = self.session if profile == "session" else self.leg
        poc = self.get_poc(profile)
        return expand_value_area(p, poc)
```

***

## TDD-05 — WebSocket Client with Reconnect

```python
import asyncio, json, websockets
from datetime import datetime

class DhanWSClient:
    def __init__(self, access_token: str, queues: Dict[str, asyncio.Queue]):
        self.token   = access_token
        self.queues  = queues
        self.uri     = "wss://api-feed.dhan.co"
        self.reconnect_delay = 2   # seconds, doubles on each failure (max 30)

    async def connect(self):
        while True:
            try:
                async with websockets.connect(
                    self.uri,
                    extra_headers={"access-token": self.token},
                    ping_interval=20,
                    ping_timeout=10
                ) as ws:
                    await self.subscribe(ws)
                    self.reconnect_delay = 2  # Reset on success
                    async for message in ws:
                        await self.handle_message(message)
            except Exception as e:
                # Mark all symbols as RECONNECTING
                for sym in self.queues:
                    pass  # update state.data_quality = "RECONNECTING"
                await asyncio.sleep(min(self.reconnect_delay, 30))
                self.reconnect_delay = min(self.reconnect_delay * 2, 30)

    async def handle_message(self, raw: str):
        data = json.loads(raw)
        tick = Tick(
            price      = data["LTP"],
            ask_vol    = data.get("buy_qty",  0),
            bid_vol    = data.get("sell_qty", 0),
            volume     = data.get("buy_qty", 0) + data.get("sell_qty", 0),
            trade_size = data.get("trade_size", 1),
            delta      = data.get("buy_qty", 0) - data.get("sell_qty", 0),
            timestamp  = datetime.fromisoformat(data["timestamp"])
        )
        symbol = data["symbol"]
        if symbol in self.queues:
            await self.queues[symbol].put(tick)

    async def subscribe(self, ws):
        payload = {
            "RequestCode": 15,
            "InstrumentCount": len(self.queues),
            "InstrumentList": [
                {"ExchangeSegment": "NSE_FO", "SecurityId": sid}
                for sid in ACTIVE_SECURITY_IDS
            ]
        }
        await ws.send(json.dumps(payload))
```

***

# Document 2 — API Contract

***

## API-01 — Internal REST API (FastAPI)

### GET /api/symbols
```json
Response:
{
  "symbols": [
    {
      "symbol":       "NATURALGAS",
      "strike":       280,
      "option_type":  "PE",
      "is_active":    true,
      "session_state": "BALANCED",
      "last_signal_ts": "2026-03-17T19:45:00+05:30"
    }
  ]
}
```

### GET /api/signal/{symbol}
```json
Response: Full OutputSchema JSON (as defined in BRD FR-11)
```

### GET /api/profile/{symbol}
```json
Response:
{
  "symbol":       "NATURALGAS",
  "profile_type": "SESSION",
  "poc":          9.25,
  "vah":          11.78,
  "val":          8.91,
  "lvns":         [8.20, 7.90],
  "hvns":         [9.10, 9.40],
  "profile_data": {"8.91": 1200, "9.00": 3400, ...}
}
```

### GET /api/risk/session
```json
Response:
{
  "daily_pnl":           -2500.00,
  "daily_pnl_pct":       -0.83,
  "consecutive_losses":  2,
  "trades_today":        5,
  "session_active":      true,
  "kill_switch_active":  false,
  "risk_remaining_pct":  1.17
}
```

### POST /api/trade/entry (manual override)
```json
Request:
{
  "symbol":    "NATURALGAS",
  "direction": "LONG",
  "lots":      4,
  "override_reason": "Manual entry confirmation"
}
Response:
{
  "trade_id": "uuid",
  "accepted": true,
  "risk_amount": 1250.00
}
```

### POST /api/trade/exit (manual override)
```json
Request:
{
  "trade_id":   "uuid",
  "lots":       4,
  "exit_reason": "Manual counter-aggression"
}
```

### GET /api/config/{symbol}
```json
Response: Full instrument config from INSTRUMENTS registry
```

### PUT /api/config/{symbol}
```json
Request: Partial instrument config update
{
  "big_trade_threshold": 75,
  "risk_per_trade_pct":  0.003
}
```

***

## API-02 — WebSocket Push API (Frontend)

**Endpoint:** `ws://localhost:8000/ws/signals`

**Message types pushed to frontend:**

```json
// Type 1: New signal
{
  "type":    "SIGNAL",
  "data":    { /* full OutputSchema */ }
}

// Type 2: Trade management update (partition, pyramid, BE)
{
  "type":    "TRADE_UPDATE",
  "trade_id": "uuid",
  "action":   "EXIT_P1 | EXIT_P2 | EXIT_P3 | PYRAMID_ADD | MOVE_TO_BREAKEVEN | TRAIL_SL | EXIT_ALL",
  "lots":     2,
  "price":    9.10,
  "reason":   "Seed recovery — weak momentum"
}

// Type 3: Session risk event
{
  "type":   "RISK_EVENT",
  "event":  "DAILY_LOSS_LIMIT | DRAWDOWN_LIMIT | CONSECUTIVE_LOSSES | SESSION_KILLED",
  "value":  -2.0,
  "reason": "2% daily loss limit reached"
}

// Type 4: Market state change
{
  "type":      "STATE_CHANGE",
  "symbol":    "NATURALGAS",
  "from":      "BALANCED",
  "to":        "IMBALANCED",
  "direction": "DOWN",
  "timestamp": "2026-03-17T19:45:00+05:30"
}

// Type 5: Drive alert
{
  "type":      "DRIVE_ALERT",
  "symbol":    "NATURALGAS",
  "drive":     1,
  "level":     8.91,
  "action":    "FIRST_DRIVE_RECORDED — set alert for return"
}

// Type 6: Data quality alert
{
  "type":    "DATA_QUALITY",
  "symbol":  "NATURALGAS",
  "quality": "STALE",
  "gap_seconds": 45
}

// Type 7: Heartbeat (every 5s)
{
  "type": "HEARTBEAT",
  "ts":   "2026-03-17T19:45:05+05:30",
  "symbols_active": 3
}
```

***

## API-03 — DhanHQ Integration Contracts

### WebSocket Subscription Payload
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

### Expected Tick Payload (inbound)
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

### L2 DOM Poll (REST)
```
GET https://api.dhan.co/marketfeed/ohlc
Headers: access-token: {token}
Body: {"NSE_FO": ["428199"]}

Response field mapping:
  depth.buy[0..4]  → bid levels (price, quantity, orders)
  depth.sell[0..4] → ask levels (price, quantity, orders)
```

***

# Document 3 — Test Plan

***

## TP-01 — Unit Tests

### Profile Engine Tests
```python
def test_poc_calculation():
    profile = {9.0: 1000, 9.1: 5000, 9.2: 2000}
    assert calc_poc(profile) == 9.1

def test_value_area_70_pct():
    # Ensure VA expands until exactly 70% accumulated
    profile = build_synthetic_profile()
    poc     = calc_poc(profile)
    va      = calc_value_area(profile, poc)
    total   = sum(profile.values())
    assert va.va_volume / total >= 0.70
    assert va.VAH > va.POC > va.VAL

def test_lvn_threshold():
    profile = {9.0: 100, 9.1: 5, 9.2: 110, 9.3: 8}
    nodes   = detect_nodes(profile)
    # Mean = 55.75, threshold = 55.75 × 0.15 = 8.36
    # 9.1 (5) and 9.3 (8) should be LVNs
    assert 9.1 in nodes["LVNs"]
    assert 9.3 in nodes["LVNs"]
    assert 9.0 not in nodes["LVNs"]

def test_lvn_score_midpoint_bonus():
    # LVN at leg midpoint should score higher
    score_mid = score_lvn(10.0, 5, 9.0, 11.0, {10.0: 5, 9.5: 100, 10.5: 100})
    score_far = score_lvn(9.1, 5, 9.0, 11.0, {9.1: 5, 9.5: 100, 10.5: 100})
    assert score_mid > score_far
```

### CVD Tests
```python
def test_cvd_accumulation():
    ticks = [
        Tick(price=9.0, ask_vol=100, bid_vol=50, ...),
        Tick(price=9.1, ask_vol=80,  bid_vol=120, ...),
    ]
    cvd = calc_cvd(ticks, ticks[0].timestamp)
    assert cvd[0]["cvd"] == 50   # 100-50
    assert cvd [scribd](https://www.scribd.com/document/923519913/Fabio-Playbook)["cvd"] == -10  # 50 + (80-120)

def test_cvd_bull_divergence():
    # Prices go lower but CVD higher = bullish divergence
    prices = [{"close": 9.0}, {"close": 8.9}, {"close": 8.8}]
    cvd    = [{"cvd": -100}, {"cvd": -80}, {"cvd": -60}]
    result = detect_cvd_divergence(prices, cvd, lookback=3)
    assert result["bull"] == True
    assert result["bear"] == False
```

### Aggression Scorer Tests
```python
def test_minimum_score_gate():
    # Score of 1.5 must NOT generate trade signal
    result = mock_aggression_score(1.5)
    assert result["confirmed"] == False

def test_pyramid_requires_3():
    # Score of 2.5 is enough for entry but NOT pyramid
    assert 2.5 >= CONFIG["min_aggression_score"]        # passes entry
    assert 2.5 < 3.0                                     # fails pyramid

def test_score_breakdown():
    # Verify each signal contributes correct weight
    score = calculate_aggression_score_isolated(
        footprint=True, cvd=True, big_trade=False,
        absorption=False, ofi=False
    )
    assert score == 2.0
```

### Drive Tracker Tests
```python
def test_first_drive_no_entry():
    tracker = DriveTracker(tick_size=0.10)
    result  = classify_drive(9.40, 9.40, tracker, candles, "SHORT", atr, cvd, fp)
    assert result["entry_valid"] == False
    assert result["drive_number"] == 1

def test_second_drive_with_rejection_valid():
    tracker = DriveTracker(tick_size=0.10)
    # Simulate first drive + rejection
    tracker.record_touch(9.40, ts1, was_rejected=True)
    result = classify_drive(9.40, 9.40, tracker, candles, "SHORT", atr, cvd, fp)
    assert result["drive_number"] == 2
    assert result["entry_valid"] == True

def test_second_drive_without_rejection_invalid():
    tracker = DriveTracker(tick_size=0.10)
    tracker.record_touch(9.40, ts1, was_rejected=False)  # no rejection
    result  = classify_drive(9.40, 9.40, tracker, candles, "SHORT", atr, cvd, fp)
    assert result["entry_valid"] == False
```

### Risk Manager Tests
```python
def test_daily_loss_kill_switch():
    rm = SessionRiskManager(account_equity=500000)
    rm.register_trade_result(-5000)   # -1%
    rm.register_trade_result(-5000)   # -2% → should kill
    can, reason = rm.can_trade()
    assert can == False
    assert "DAILY LOSS" in reason

def test_consecutive_loss_pause():
    rm = SessionRiskManager(account_equity=500000)
    for _ in range(3):
        rm.register_trade_result(-500)
    can, reason = rm.can_trade()
    assert can == False
    assert "consecutive" in reason.lower()

def test_win_resets_consecutive():
    rm = SessionRiskManager(account_equity=500000)
    rm.register_trade_result(-500)
    rm.register_trade_result(-500)
    rm.register_trade_result(+2000)  # win resets counter
    assert rm.consecutive_losses == 0
```

### Partition Exit Tests
```python
def test_p1_skipped_on_strong_momentum():
    # Strong CVD slope → P1 should NOT fire
    result = partition_exit_manager(
        direction="LONG", entry_price=8.91, current_price=9.02,
        target_price=9.25, total_lots=6,
        cvd_series=strong_cvd_series,   # slope > 2.0
        ...
    )
    actions = [a["action"] for a in result]
    assert "EXIT_P1" not in actions

def test_p2_always_fires_at_target():
    result = partition_exit_manager(
        direction="LONG", entry_price=8.91, current_price=9.25,
        target_price=9.25, total_lots=6, ...
    )
    actions = [a["action"] for a in result]
    assert "EXIT_P2" in actions

def test_counter_aggression_exits_all():
    result = partition_exit_manager(
        direction="LONG", ...,
        counter_aggression_score=2  # mock 2+ counter signals
    )
    assert result[0]["action"] == "EXIT_ALL"
```

***

## TP-02 — Integration Tests

```python
# Full pipeline test — tick to signal
def test_full_pipeline_balanced_long():
    """
    Simulate: market is BALANCED, price at VAL,
    second drive confirmed, aggression ≥ 2.0
    Expected: LONG signal with full output schema
    """
    state   = build_mock_state("BALANCED", price_at="VAL")
    ticks   = build_mock_ticks(at_val=True, buy_pressure=True)
    result  = run_strategy_full(ticks, candles, ...)
    assert result["direction"] == "LONG"
    assert result["confidence"] in ("Medium", "High")
    assert result["drive_number"] == 2
    assert result["aggression_score"] >= 2.0
    assert result["stop_loss"] < result["entry_zone"]
    assert result["target"] > result["entry_zone"]

def test_no_trade_at_poc():
    state  = build_mock_state("BALANCED", price_at="POC")
    result = run_strategy_full(...)
    assert result["direction"] == "FLAT"
    assert "POC dead zone" in result["rationale"]

def test_session_kill_switch_blocks_signal():
    rm = SessionRiskManager(500000)
    rm.register_trade_result(-10000)   # exceed 2% daily loss
    result = run_strategy_full(..., risk_manager=rm)
    assert result["action"] == "SESSION_STOPPED"

def test_first_drive_suppresses_entry():
    state   = build_mock_state("BALANCED", price_at="VAH")
    tracker = DriveTracker(tick_size=0.10)  # no prior drives
    result  = run_strategy_full(..., drive_tracker=tracker)
    assert result["direction"] == "FLAT"
    assert result["drive_number"] == 1

def test_pyramid_add_at_new_lvn():
    # First entry at 8.91 in profit, price at 9.02 LVN
    entries = [OpenEntry(price=8.91, lots=4, ...)]
    result  = manage_pyramid(
        direction="LONG", entries=entries, current_price=9.02,
        first_pnl=0.11,  # in profit
        aggression_score=3.0, ...
    )
    assert result["action"] == "PYRAMID_ADD"
    assert result["add_lots"] == 2   # 50% of 4
```

***

## TP-03 — Performance Tests

```python
# Signal latency must be < 500ms end-to-end
def test_signal_latency():
    import time
    t_start = time.time()
    run_strategy_full(ticks=live_tick_batch, ...)
    latency_ms = (time.time() - t_start) * 1000
    assert latency_ms < 500, f"Latency {latency_ms:.1f}ms exceeds 500ms"

# Profile update O(1) per tick
def test_profile_update_constant_time():
    import time
    engine = VolumeProfileEngine(bucket_size=0.10)
    # Pre-populate with 100k ticks
    for _ in range(100000):
        engine.update(mock_tick())
    # Time a single update — should be constant regardless of profile size
    t0 = time.time()
    engine.update(mock_tick())
    t1 = time.time()
    assert (t1 - t0) * 1000 < 1.0, "Profile update > 1ms — not O(1)"

# 10 concurrent symbols no degradation
def test_concurrent_symbols():
    import asyncio
    async def run():
        tasks = [symbol_pipeline(sym, ...) for sym in 10_symbols]
        await asyncio.gather(*tasks)
    asyncio.run(asyncio.wait_for(run(), timeout=1.0))  # 10 symbols in < 1s
```

***

## TP-04 — Strategy Backtesting Validation Tests

```python
# Run strategy on 30 days of historical tick data
# Validate statistical edge exists

def test_backtest_win_rate():
    results = backtest_strategy(
        tick_data  = load_ticks("2026-01-01", "2026-02-28"),
        instrument = "NATURALGAS"
    )
    assert results["win_rate"] >= 0.45, "Win rate below 45% — no edge"
    assert results["avg_rr"]   >= 1.5,  "Average R:R below 1.5"

def test_backtest_second_drive_vs_first():
    results_d1 = backtest_strategy(drive_filter=1, ...)
    results_d2 = backtest_strategy(drive_filter=2, ...)
    assert results_d2["win_rate"] > results_d1["win_rate"], "Second drive not better than first"

def test_backtest_no_middle_trades():
    results = backtest_strategy(allow_poc_trades=True, ...)
    results_no_mid = backtest_strategy(allow_poc_trades=False, ...)
    assert results_no_mid["win_rate"] > results["win_rate"]
```

***

# Document 4 — Deployment Architecture

***

## DEPLOY-01 — Environment Stack

```
┌──────────────────────────────────────────────────────────┐
│                  LOCAL MACHINE (Primary)                  │
│                                                          │
│  ┌──────────────────────────────────────────────────┐   │
│  │               Docker Compose Stack               │   │
│  │                                                  │   │
│  │  ┌─────────────┐   ┌──────────────────────────┐ │   │
│  │  │  FastAPI     │   │   GlassyTrade Engine     │ │   │
│  │  │  (Port 8000) │   │   (Python async)         │ │   │
│  │  │  REST + WS   │   │   All strategy modules   │ │   │
│  │  └──────┬───────┘   └──────────┬───────────────┘ │   │
│  │         │                      │                  │   │
│  │  ┌──────▼──────────────────────▼──────────────┐  │   │
│  │  │              DuckDB                        │  │   │
│  │  │  (local file: glasstrade.db)               │  │   │
│  │  │  Ticks, Profiles, Signals, Trades, Risk   │  │   │
│  │  └────────────────────────────────────────────┘  │   │
│  │                                                  │   │
│  │  ┌────────────────────────────────────────────┐  │   │
│  │  │     React Frontend (Port 5190)             │  │   │
│  │  │     GlassyTrade AI UI                      │  │   │
│  │  └────────────────────────────────────────────┘  │   │
│  └──────────────────────────────────────────────────┘   │
│                                                          │
│  External Connections:                                   │
│  ├── DhanHQ WebSocket wss://api-feed.dhan.co            │
│  ├── DhanHQ REST    https://api.dhan.co                 │
│  └── EIA Calendar  https://ir.eia.gov/ngs/ngs.html      │
└──────────────────────────────────────────────────────────┘
```

***

## DEPLOY-02 — docker-compose.yml

```yaml
version: "3.9"

services:
  engine:
    build: ./engine
    container_name: glasstrade_engine
    environment:
      - DHAN_ACCESS_TOKEN=${DHAN_ACCESS_TOKEN}
      - DHAN_CLIENT_ID=${DHAN_CLIENT_ID}
      - DB_PATH=/data/glasstrade.db
      - LOG_LEVEL=INFO
    volumes:
      - ./data:/data
      - ./logs:/logs
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "python", "-c", "import requests; requests.get('http://localhost:8000/health')"]
      interval: 30s
      timeout: 10s
      retries: 3

  frontend:
    build: ./frontend
    container_name: glasstrade_ui
    ports:
      - "5190:5190"
    depends_on:
      - engine
    restart: unless-stopped

  api:
    build: ./api
    container_name: glasstrade_api
    ports:
      - "8000:8000"
    environment:
      - DB_PATH=/data/glasstrade.db
    volumes:
      - ./data:/data
    depends_on:
      - engine
    restart: unless-stopped
```

***

## DEPLOY-03 — Environment Variables (.env)

```bash
# DhanHQ
DHAN_ACCESS_TOKEN=your_token_here
DHAN_CLIENT_ID=your_client_id

# Engine
ACCOUNT_EQUITY=500000          # Starting equity in INR
ACTIVE_SYMBOLS=NATURALGAS,NIFTY,BANKNIFTY
MAX_CONCURRENT_SYMBOLS=10
LOG_LEVEL=INFO

# Risk Overrides (optional — defaults in engine_config.py)
RISK_PER_TRADE_PCT=0.005
MAX_DAILY_LOSS_PCT=0.02
MAX_CONSECUTIVE_LOSSES=3

# DB
DB_PATH=./data/glasstrade.db
TICK_RETENTION_DAYS=1          # Purge ticks older than N days

# EIA Calendar
EIA_SUPPRESS_MINUTES_BEFORE=15
EIA_SUPPRESS_MINUTES_AFTER=15
```

***

## DEPLOY-04 — Startup & Shutdown Sequence

```python
# main.py startup sequence
async def startup():
    # 1. Load instrument configs
    load_instrument_registry()

    # 2. Init DuckDB — create tables if not exist
    db = DuckDBStore(DB_PATH)
    db.initialize_schema()

    # 3. Load previous session profiles for each symbol
    for sym in ACTIVE_SYMBOLS:
        prev_va = db.load_prev_session_profile(sym)
        states[sym].prev_session_va = prev_va

    # 4. Init session state per symbol
    for sym in ACTIVE_SYMBOLS:
        states[sym].session_start_ts = get_session_open(sym)
        states[sym].risk_manager = SessionRiskManager(ACCOUNT_EQUITY)
        states[sym].drive_tracker = DriveTracker(INSTRUMENTS[sym]["tick_size"])

    # 5. Start WebSocket client
    ws = DhanWSClient(DHAN_ACCESS_TOKEN, queues)
    asyncio.create_task(ws.connect())

    # 6. Start L2 pollers
    for sym in ACTIVE_SYMBOLS:
        asyncio.create_task(l2_poller(sym, states[sym]))

    # 7. Start signal pipelines
    for sym in ACTIVE_SYMBOLS:
        asyncio.create_task(symbol_pipeline(sym, states[sym], queues[sym]))

    # 8. Start FastAPI server
    # (handled by uvicorn)

async def shutdown():
    # Save all completed session profiles to DuckDB
    for sym in ACTIVE_SYMBOLS:
        if states[sym].session_va:
            db.save_session_profile(sym, states[sym].session_va)

    # Flush all pending signals
    await signal_queue.join()

    # Log final session risk summary
    for sym in ACTIVE_SYMBOLS:
        db.save_session_risk(sym, states[sym].risk_manager.session_summary())
```

***

# Document 5 — Operations Runbook

***

## OPS-01 — Daily Pre-Market Checklist

```
□ 1. Verify DHAN token not expired (tokens expire daily — renew by 08:45 IST)
□ 2. Confirm previous session profiles loaded: GET /api/profile/{symbol}
     → prev_session_va must not be null
□ 3. Confirm risk manager reset: GET /api/risk/session
     → daily_pnl = 0, consecutive_losses = 0
□ 4. Check EIA release calendar — if release today, suppress window confirmed?
□ 5. Confirm WebSocket connected: GET /api/health
     → ws_status: "CONNECTED"
□ 6. Verify data quality: all symbols showing data_quality = "LIVE"
□ 7. Set account equity for the session: PUT /api/config/equity
□ 8. Confirm DuckDB size < 5GB (purge old ticks if needed)
```

***

## OPS-02 — During Session Monitoring

```
Every 30 minutes:
□ Check /api/risk/session — daily_pnl within limits?
□ Check WebSocket heartbeat last received < 10s ago?
□ Any symbol showing data_quality = "STALE"?

On STALE alert:
□ Check DhanHQ status page
□ Engine will auto-reconnect — wait 60s before manual restart
□ If reconnected: profiles rebuild from tick buffer — no action needed
□ If down > 5 min: do not trade until LIVE quality restored

On SESSION_KILLED event:
□ All signals suppressed automatically
□ Do not manually override — session is over
□ Review trade log for session: GET /api/trades/today
```

***

## OPS-03 — EOD Close Procedure

```
After market close (15:30 NSE / 23:30 MCX):
□ 1. Session profiles auto-saved to DuckDB — verify:
     SELECT * FROM session_profiles WHERE date = today
□ 2. Export session trade log: GET /api/trades/export?date=today
□ 3. Review consecutive losses — if ≥ 2, review strategy fit next day
□ 4. Purge today's tick data if size > 2GB:
     DELETE FROM ticks WHERE timestamp < (session_close - 1hr)
□ 5. Renew DhanHQ access token for next day
□ 6. Review any OPEN_ITEMS from BRD — are gaps resolved?
```

***

## OPS-04 — Error Handling Reference

| Error | Cause | Auto Recovery | Manual Action |
|---|---|---|---|
| `WS_DISCONNECTED` | Network drop | Auto-reconnect with backoff | If 5+ min: restart engine container |
| `DATA_STALE` | No ticks > 30s | Alert fired | Check DhanHQ status |
| `PROFILE_EMPTY` | Session just started | Auto resolves after warm-up | Wait for warm-up window |
| `PREV_SESSION_NULL` | First day run or DB issue | Engine runs without reference | Manually seed prev_session_va |
| `DB_LOCKED` | Concurrent write | Auto retry 3x | Restart DuckDB connection |
| `TOKEN_EXPIRED` | DhanHQ token stale | None — signals suppressed | Renew token via DhanHQ portal |
| `RISK_SESSION_KILLED` | Daily loss / drawdown | Intentional — no recovery | Session over; restart tomorrow |
| `CUSHION_INVALID` | Setup has > 10 tick stop | Signal suppressed | Review tick size config |

***

# Document 6 — Data Dictionary

All fields used across the system, precisely defined:

| Field | Type | Unit | Source | Description |
|---|---|---|---|---|
| `price` | float | INR | Tick | Last traded price, rounded to tick_size |
| `ask_vol` | int | lots | Tick (`buy_qty`) | Volume executed at ask = aggressive buyer |
| `bid_vol` | int | lots | Tick (`sell_qty`) | Volume executed at bid = aggressive seller |
| `trade_size` | int | lots | Tick | Size of single trade print |
| `delta` | int | lots | Derived | `ask_vol - bid_vol` per tick |
| `POC` | float | INR | Profile | Price level with highest cumulative volume |
| `VAH` | float | INR | Profile | Upper boundary of 70% value area |
| `VAL` | float | INR | Profile | Lower boundary of 70% value area |
| `LVN` | float | INR | Profile | Price level with volume < 15% of mean row vol |
| `HVN` | float | INR | Profile | Price level with volume > 200% of mean row vol |
| `cvd` | int | lots | Derived | Cumulative sum of delta from session open |
| `cvd_slope` | float | lots/candle | Derived | Rate of change of CVD over 20 candles |
| `footprint_score` | float | ratio | Derived | % of cells with ≥3:1 imbalance in candle |
| `absorption` | bool | — | Derived | `range < ATR×0.3` AND `volume > avg×2.0` |
| `bubble_sigma` | float | σ | Derived | Standard deviations above mean for volume bubble |
| `ofi` | float | ratio | Derived | `(ask_vol - bid_vol) / total_vol` rolling 10 bars |
| `atr` | float | INR | Derived | Average True Range, 14-period |
| `avg_vol` | float | lots | Derived | Simple moving average of volume, 20-period |
| `ib_high` | float | INR | Candle | High of first 2 session candles |
| `ib_low` | float | INR | Candle | Low of first 2 session candles |
| `drive_number` | int | count | DriveTracker | How many times price has touched this level |
| `aggression_score` | float | points | Derived | Sum of all confirmed signal weights |
| `cushion_ticks` | int | ticks | Derived | `abs(entry - stop_loss) / tick_size` |
| `risk_pct` | float | % | Derived | `lots × risk_per_lot / account_equity` |
| `risk_reward` | float | ratio | Derived | `abs(target - entry) / abs(entry - stop)` |
| `pnl` | float | INR | Trade | `(exit - entry) × lots × point_value` |
| `daily_pnl_pct` | float | % | Risk | `daily_pnl / session_start_equity` |
| `session_state` | enum | — | Engine | `BALANCED | IMBALANCED | PROBING | NO_TRADE` |
| `active_profile` | enum | — | Engine | `SESSION | LEG | COMBINED | NONE` |
| `confidence` | enum | — | Engine | `High (≥3.0) | Medium (≥2.0) | Low (<2.0)` |
| `data_quality` | enum | — | Monitor | `LIVE | STALE | RECONNECTING` |


Here is the **complete audit of everything critical that is pending** — items that, if skipped, will break the strategy or leave the system incomplete. [youtube](https://www.youtube.com/watch?v=Jpd96fLqr5M)

***

## CRITICAL (System Breaks Without These)

***

### ❌ 1 — Delta Volume Profile (Wrong Profile Type Used Throughout)

**This is the single biggest gap.** Every profile in the current design uses plain `total volume` per price level. Fabio explicitly uses **Delta-colored volume profiles** — where each row shows `buy_delta` vs `sell_delta`, not just total volume. [reddit](https://www.reddit.com/r/OrderFlow_Trading/comments/1qdgy0c/question_about_the_type_of_volume_profile_fabio/)

```
WHAT WE BUILT (WRONG):
  Price  │ Total Volume Bar
  9.10   │ ████████████████  ← only total volume shown

WHAT FABIO ACTUALLY USES (CORRECT):
  Price  │ Buy Delta (green)│ Sell Delta (red)
  9.10   │ ██████████ +650  │ ████ -180   ← net buyers dominating
  9.05   │ ███ +120         │ ███████ -580 ← net sellers dominating ← HIGH SELL DELTA ZONE
  9.00   │ ████████ +430    │ ██ -90      ← buyers defending level
```

**Why it matters:** High sell delta zones (strong negative delta) in the left side of a leg profile = trapped sellers = LONG entry zones. High buy delta zones = LONG defended levels. The POC in a delta profile can be **different from the POC in a volume profile**. [youtube](https://www.youtube.com/watch?v=QPTkRoD9GE4)

```python
# REQUIRED ADDITION: Delta Profile Build
def build_delta_profile(ticks, start_ts, end_ts):
    bucket_size = CONFIG["profile_bucket_size"]
    delta_profile = {}     # {price: {"buy_delta": int, "sell_delta": int, "net_delta": int}}

    for tick in ticks:
        if not (start_ts <= tick.timestamp <= end_ts):
            continue
        bucket = round(tick.price / bucket_size) * bucket_size
        if bucket not in delta_profile:
            delta_profile[bucket] = {"buy_delta": 0, "sell_delta": 0, "net_delta": 0}
        delta_profile[bucket]["buy_delta"]  += tick.ask_vol
        delta_profile[bucket]["sell_delta"] += tick.bid_vol
        delta_profile[bucket]["net_delta"]  += tick.delta

    return delta_profile

# HIGH SELL DELTA ZONE = trapped sellers = LONG entry
def detect_high_delta_zones(delta_profile, direction):
    """
    For LONG setups: find levels with very high SELL delta (net_delta very negative)
                     = sellers trapped here = buyers will appear on retest
    For SHORT setups: find levels with very high BUY delta (net_delta very positive)
                      = buyers trapped here = sellers will appear on retest
    """
    net_deltas = [abs(v["net_delta"]) for v in delta_profile.values()]
    mean_abs   = sum(net_deltas) / len(net_deltas)
    threshold  = mean_abs * 2.5   # 250% of mean = significant delta concentration

    zones = []
    for price, data in delta_profile.items():
        if direction == "LONG"  and data["net_delta"] < -(threshold):
            zones.append({"price": price, "type": "HIGH_SELL_DELTA", "delta": data["net_delta"]})
        if direction == "SHORT" and data["net_delta"] > +(threshold):
            zones.append({"price": price, "type": "HIGH_BUY_DELTA",  "delta": data["net_delta"]})

    return sorted(zones, key=lambda x: abs(x["delta"]), reverse=True)
```

**Impact on aggression scoring:** High delta zone at entry level adds +0.5 to aggression score — must add `FR-06-NEW: Delta zone confluence` to the aggression engine.

***

### ❌ 2 — Naked POC (NPOC) — Previous Unfilled POCs

Fabio specifically watches for **Naked POCs** — previous session POCs that have not yet been revisited by price. These are the **strongest magnet levels** in the entire framework because price is statistically obligated to revisit them. [youtube](https://www.youtube.com/watch?v=Jpd96fLqr5M)

```python
class NPOCTracker:
    """
    Tracks all previous session POCs.
    A POC is "naked" until price trades through it.
    Once touched, it is removed from the naked list.
    """
    def __init__(self):
        self.naked_pocs = []   # [{date, price, direction_of_unfill}]

    def add_session_poc(self, date, poc_price):
        self.naked_pocs.append({
            "date":    date,
            "price":   poc_price,
            "touched": False
        })

    def check_and_fill(self, current_price, tick_size):
        zone = tick_size * 2
        for npoc in self.naked_pocs:
            if not npoc["touched"] and abs(current_price - npoc["price"]) <= zone:
                npoc["touched"] = True  # NPOC filled — remove from magnet list

    def get_active_npocs(self, current_price, lookback_days=5):
        """Return nearest unfilled NPOCs above and below current price."""
        active = [n for n in self.naked_pocs[-lookback_days:] if not n["touched"]]
        above  = [n for n in active if n["price"] > current_price]
        below  = [n for n in active if n["price"] < current_price]
        return {
            "nearest_above": min(above, key=lambda x: x["price"]) if above else None,
            "nearest_below": max(below, key=lambda x: x["price"]) if below else None
        }
```

**How NPOCs change the strategy:**
- Nearest NPOC above price → **additional pull target** for LONG trades — can extend P3 toward NPOC instead of stopping at POC
- Price approaching NPOC from below → **area where reversal is possible** — reduce confidence if entering LONG into an NPOC above

***

### ❌ 3 — Anomaly Zone Detection (Fabio's Core Term)

Fabio labels price trading **below VAL or above VAH as an "anomaly"**. This is not just "imbalanced" — it has a specific meaning: [youtube](https://www.youtube.com/watch?v=Jpd96fLqr5M)

> "An anomaly is a price area where value has not yet been established. The market MUST return to fill this anomaly or establish a new value area there."

```python
def detect_anomaly_zone(current_price, session_va, prev_session_va):
    """
    Anomaly = price outside the COMPOSITE value area
    (both current session AND previous session value areas).
    Stronger signal than simple imbalance.
    """
    # Single session anomaly
    single_anomaly = current_price > session_va["VAH"] or current_price < session_va["VAL"]

    # Double anomaly = outside BOTH current and previous session VA
    if prev_session_va:
        composite_vah = max(session_va["VAH"], prev_session_va["VAH"])
        composite_val = min(session_va["VAL"], prev_session_va["VAL"])
        double_anomaly = current_price > composite_vah or current_price < composite_val
    else:
        double_anomaly = False

    return {
        "is_anomaly":       single_anomaly,
        "is_double_anomaly": double_anomaly,
        "anomaly_type":     "ABOVE" if current_price > session_va["VAH"] else "BELOW" if current_price < session_va["VAL"] else None,
        "composite_vah":    composite_vah if prev_session_va else session_va["VAH"],
        "composite_val":    composite_val if prev_session_va else session_va["VAL"],
        # Double anomaly = strongest mean reversion setup
        "trade_bias":       "STRONG_MEAN_REVERSION" if double_anomaly else "TREND_FOLLOW" if single_anomaly else "NEUTRAL"
    }
```

***

### ❌ 4 — Composite / Multi-Session Volume Profile

Fabio overlays a **Composite Profile** — multiple sessions merged — to find the larger-timeframe value area. This gives the **weekly or multi-day value context** that the single session profile alone cannot provide. [reddit](https://www.reddit.com/r/OrderFlow_Trading/comments/1qdgy0c/question_about_the_type_of_volume_profile_fabio/)

```python
def build_composite_profile(session_profiles_list):
    """
    Merge last N session profiles into one composite.
    Reveals multi-day acceptance zones (strong HVNs) and voids (strong LVNs).
    Used to set WEEKLY bias before any intraday trade.
    """
    composite = {}
    for session in session_profiles_list:   # last 5 sessions for weekly
        for price, vol in session.items():
            composite[price] = composite.get(price, 0) + vol

    poc  = calc_poc(composite)
    va   = calc_value_area(composite, poc)
    nodes = detect_nodes(composite)

    return {
        "composite_profile": composite,
        "weekly_poc":        poc,
        "weekly_vah":        va["VAH"],
        "weekly_val":        va["VAL"],
        "weekly_lvns":       nodes["LVNs"],
        "weekly_hvns":       nodes["HVNs"]
    }

# Weekly bias filter — must be added to GATE 0
def apply_weekly_bias_filter(direction, current_price, composite):
    """
    If weekly POC is above current price → weekly bias is LONG
    If weekly POC is below current price → weekly bias is SHORT
    Only take trades aligned with weekly bias for highest conviction.
    """
    weekly_poc = composite["weekly_poc"]
    weekly_bias = "LONG" if weekly_poc > current_price else "SHORT"

    if direction != weekly_bias:
        return {"aligned": False, "confidence_reduction": 0.5,
                "reason": f"Trade against weekly bias (bias={weekly_bias})"}
    return {"aligned": True, "confidence_boost": 0.5}
```

***

### ❌ 5 — Open Interest (OI) Logic

Your current AI Commander outputs **"No OI pressure"** but the entire OI detection layer was never designed. Fabio himself does NOT use OI — but your system references it, so it either needs a definition or needs to be removed cleanly. [localhost](http://localhost:5190/)

```python
def check_oi_pressure(symbol, strike, option_type, dhan_rest_client):
    """
    OI pressure = large OI concentration at current strike vs surrounding strikes.
    High OI = max pain wall / institutional positioning = potential resistance.
    """
    oi_data = dhan_rest_client.get_option_chain(symbol)

    current_strike_oi = oi_data[strike][option_type]["oi"]
    surrounding_oi    = [
        oi_data.get(strike + i, {}).get(option_type, {}).get("oi", 0)
        for i in [-200, -100, +100, +200]
    ]
    avg_surrounding   = sum(surrounding_oi) / len(surrounding_oi) if surrounding_oi else 1

    oi_ratio = current_strike_oi / avg_surrounding if avg_surrounding > 0 else 1.0

    if oi_ratio >= 3.0:
        return {"pressure": "HIGH",   "oi_ratio": oi_ratio, "signal": "RESISTANCE"}
    elif oi_ratio >= 1.5:
        return {"pressure": "MEDIUM", "oi_ratio": oi_ratio, "signal": "CAUTION"}
    else:
        return {"pressure": "LOW",    "oi_ratio": oi_ratio, "signal": "CLEAR"}
```

***

### ❌ 6 — Pre-Alert System (How Alerts Are Triggered)

Drive 1 fires a `SET_ALERT_FOR_RETURN` action throughout the entire design but **no alert mechanism was ever built**. [scribd](https://www.scribd.com/document/923519913/Fabio-Playbook)

```python
class AlertManager:
    def __init__(self, ws_publisher):
        self.active_alerts  = {}  # {alert_id: alert_dict}
        self.ws             = ws_publisher

    def set_price_alert(self, symbol, price, direction,
                        level_type, tick_size):
        """Set alert to fire when price returns within 3 ticks of level."""
        alert_id = f"{symbol}_{price}_{level_type}"
        self.active_alerts[alert_id] = {
            "symbol":     symbol,
            "price":      price,
            "direction":  direction,
            "level_type": level_type,  # VAH | VAL | LVN | PYRAMID
            "zone_upper": price + tick_size * 3,
            "zone_lower": price - tick_size * 3,
            "fired":      False,
            "created_at": datetime.now()
        }

    def check_alerts(self, current_price, symbol):
        """Called every tick — fire any alerts within zone."""
        fired = []
        for aid, alert in self.active_alerts.items():
            if alert["symbol"] != symbol or alert["fired"]:
                continue
            if alert["zone_lower"] <= current_price <= alert["zone_upper"]:
                alert["fired"] = True
                # Push to frontend immediately
                self.ws.push({
                    "type":        "PRICE_ALERT",
                    "alert_id":    aid,
                    "symbol":      symbol,
                    "level_type":  alert["level_type"],
                    "level_price": alert["price"],
                    "current_price": current_price,
                    "message":     f"Price approaching {alert['level_type']} at {alert['price']} — watch for second drive aggression"
                })
                fired.append(aid)
        return fired

    def clear_session_alerts(self, symbol):
        """Clear all alerts at session close — they belong to current session only."""
        self.active_alerts = {
            k: v for k, v in self.active_alerts.items()
            if v["symbol"] != symbol
        }
```

***

### ❌ 7 — Backtesting Framework (Referenced but Never Built)

Tests reference `backtest_strategy()` and `load_ticks()` but neither exists anywhere in the design.

```python
class BacktestEngine:
    """
    Replay historical tick data through the exact same strategy pipeline.
    Produces trade-by-trade PnL log and statistical summary.
    """
    def __init__(self, instrument_config, engine_config):
        self.cfg    = instrument_config
        self.ecfg   = engine_config
        self.trades = []

    def run(self, tick_data: list, start_date: str, end_date: str):
        """
        Replay ticks chronologically.
        Reset all state at each session boundary exactly as live engine does.
        """
        state        = SymbolState(self.cfg["symbol"])
        session_open = None

        for tick in tick_data:
            # Detect session boundary
            if self.is_new_session(tick.timestamp, session_open, self.cfg):
                # Save completed session profile
                if state.session_va:
                    state.prev_session_va = state.session_va
                # Reset session state
                state = self.reset_session_state(state, tick.timestamp)
                session_open = tick.timestamp

            # Run exact same pipeline as live
            result = run_strategy_full(
                ticks          = list(state.tick_buffer),
                candles        = list(state.candle_buffer),
                session_start_ts = session_open,
                prev_session_va  = state.prev_session_va,
                leg_data         = state.leg_anchor,
                account_equity   = self.ecfg["account_equity"],
                drive_tracker    = state.drive_tracker,
                risk_manager     = state.risk_manager,
                point_value      = self.cfg["point_value"]
            )

            # Record any trade signals
            if result.get("action") == "TRADE":
                self.record_backtest_trade(result, tick)

        return self.compute_summary()

    def compute_summary(self):
        if not self.trades:
            return {"error": "No trades generated"}

        pnls    = [t["pnl"] for t in self.trades]
        wins    = [p for p in pnls if p > 0]
        losses  = [p for p in pnls if p < 0]

        return {
            "total_trades":     len(self.trades),
            "win_rate":         len(wins) / len(self.trades),
            "avg_rr":           abs(sum(wins)/len(wins)) / abs(sum(losses)/len(losses)) if losses else 999,
            "total_pnl":        round(sum(pnls), 2),
            "max_drawdown":     self.calc_max_drawdown(pnls),
            "profit_factor":    abs(sum(wins)) / abs(sum(losses)) if losses else 999,
            "avg_win":          round(sum(wins)/len(wins), 2) if wins else 0,
            "avg_loss":         round(sum(losses)/len(losses), 2) if losses else 0,
            "second_drive_win_rate": self.calc_drive_win_rate(drive=2),
            "trades":           self.trades
        }
```

***

### ❌ 8 — Mid-Trade State Recovery (Engine Restart During Open Trade)

Never addressed. If the engine restarts with an open trade, the entire position, partition state, and pyramid entries are lost.

```python
def save_open_trade_state(state: SymbolState, db: DuckDBStore):
    """Called every time an entry is made or updated."""
    db.upsert_open_trade({
        "symbol":        state.symbol,
        "entries":       [e.__dict__ for e in state.open_entries],
        "pyramid_count": state.pyramid_count,
        "direction":     state.last_signal.get("direction"),
        "target":        state.last_signal.get("target"),
        "snapshot_ts":   datetime.now().isoformat()
    })

def recover_open_trade(symbol: str, db: DuckDBStore) -> list:
    """Called at startup — restore any open trades from last session."""
    raw = db.load_open_trade(symbol)
    if not raw:
        return []
    return [OpenEntry(**e) for e in raw["entries"]]
```

***

## HIGH PRIORITY (Significantly Degrades Edge Without These)

| # | What | Why Missing Hurts |
|---|---|---|
| **9** | **Footprint candle resolution spec** | Should be 1min footprint — never explicitly stated. Using wrong resolution changes all imbalance readings |
| **10** | **MCX evening session handling** | MCX NATURALGAS trades until 23:30 IST. Second session after 17:00 has different liquidity — never handled |
| **11** | **Options-specific profile** | System profiles option premiums (8.91 etc.), not the underlying. Theta decay corrupts profile structure — must profile underlying and use for signals, options only for sizing |
| **12** | **Weekly bias gate (Composite Profile)** | All trades currently use only intraday session context — no higher timeframe filter. Counter-trend intraday signals on strong trend days get falsely triggered |
| **13** | **Delta zones in aggression scorer** | +0.5 weight for high sell/buy delta zone confluence missing from FR-06. Score calculations are currently incomplete |
| **14** | **NPOC as secondary target** | P3 trailing has no upper target defined — NPOC is the logical P3 target, currently missing |
| **15** | **Alert clear on drive 3+** | When level becomes drive 3+, existing alerts for that level must be cancelled. AlertManager has `clear_session_alerts()` but not per-level cancel |

***

## Complete Pending Items Master List

```
CRITICAL (breaks system):
├── ❌ Delta Volume Profile — wrong profile type used throughout
├── ❌ Naked POC (NPOC) tracker + target usage
├── ❌ Anomaly zone detection (Fabio's specific term)
├── ❌ Composite / Multi-session profile (weekly bias)
├── ❌ OI pressure calculation (referenced in output, never designed)
├── ❌ Pre-alert system (AlertManager) — Drive 1 alerts never implemented
├── ❌ Backtesting framework — BacktestEngine + load_ticks()
└── ❌ Mid-trade state recovery on engine restart

HIGH PRIORITY (degrades edge):
├── ⚠️  Footprint candle resolution explicitly set to 1min
├── ⚠️  MCX evening session boundary + separate session profile
├── ⚠️  Options vs underlying profiling separation
├── ⚠️  Weekly bias gate from composite profile → GATE 0 addition
├── ⚠️  Delta zone confluence → FR-06-NEW aggression weight +0.5
├── ⚠️  NPOC as P3 trailing target
└── ⚠️  Per-level alert cancellation when drive 3+ detected

OPEN ITEMS FROM BRD (still unresolved):
├── OI-01: DhanHQ WS exact field names — need live test
├── OI-02: MCX big trade threshold calibration — need 1-week data
├── OI-03: MCX evening session — design decision needed
├── OI-04: Multi-symbol threading model — async confirmed, validate
├── OI-05: DhanHQ L2 rate limits — check API docs
├── OI-06: EIA calendar API source — pick reliable source
├── OI-07: Options vs underlying profile — design decision
└── OI-08: Frontend push mechanism — WebSocket confirmed
```


This is a fundamental redesign of the **entry point of the entire system** — instead of hardcoding symbols, the system discovers and selects option contracts dynamically. Here is the complete redesign of the scanning layer. [dhanhq](https://dhanhq.co/docs/v2/option-chain/)

***

# GlassyTrade AI — Option Scanner Layer

## The Core Flow Change

```
OLD (broken):    hardcoded symbols → strategy pipeline
NEW (correct):   Exchange Mode → Option Chain Scan → Contract Filter
                 → Strike Selection → Dynamic Subscribe → Strategy Pipeline
```

***

## Layer 0 — Exchange Mode Configuration

```python
from enum import Enum
from dataclasses import dataclass

class ExchangeMode(Enum):
    NSE  = "NSE_FNO"    # NSE Futures & Options  (NIFTY, BANKNIFTY, stocks)
    MCX  = "MCX_COMM"   # MCX Commodities        (NATURALGAS, CRUDEOIL, GOLD, etc.)

# DhanHQ segment codes — from Annexure
EXCHANGE_SEGMENTS = {
    ExchangeMode.NSE: {
        "segment":     "NSE_FNO",
        "instrument":  "OPTIDX",       # OPTIDX for index options, OPTSTK for stock
        "expiry_type": "WEEK",         # NSE has weekly expiries
        "session_open":  "09:15",
        "session_close": "15:30",
    },
    ExchangeMode.MCX: {
        "segment":     "MCX_COMM",
        "instrument":  "OPTFUT",       # Options on Commodity Futures
        "expiry_type": "MONTH",        # MCX has monthly expiries
        "session_open":  "09:00",
        "session_close": "23:30",
    }
}

# Underlyings available per mode
UNDERLYINGS = {
    ExchangeMode.NSE: [
        {"name": "NIFTY",     "security_id": 13,     "strike_step": 50,   "atm_range": 5},
        {"name": "BANKNIFTY", "security_id": 25,     "strike_step": 100,  "atm_range": 5},
        {"name": "FINNIFTY",  "security_id": 27,     "strike_step": 50,   "atm_range": 4},
        {"name": "MIDCPNIFTY","security_id": 26,     "strike_step": 25,   "atm_range": 4},
    ],
    ExchangeMode.MCX: [
        {"name": "NATURALGAS","security_id": 428199, "strike_step": 10,   "atm_range": 3},
        {"name": "CRUDEOIL",  "security_id": 428214, "strike_step": 100,  "atm_range": 3},
        {"name": "GOLD",      "security_id": 428219, "strike_step": 100,  "atm_range": 3},
        {"name": "SILVER",    "security_id": 428220, "strike_step": 500,  "atm_range": 3},
    ]
}
```

***

## Layer 1 — Option Chain Scanner

### Step 1.1 — Fetch Expiry List
```python
async def fetch_expiry_list(underlying_security_id: int,
                             segment: str,
                             rest_client: DhanRESTClient) -> list[str]:
    """
    POST /optionchain/expirylist
    Returns sorted list of active expiry dates.
    Rate limit: 1 unique request per 3 seconds.
    """
    payload = {
        "UnderlyingScri": underlying_security_id,
        "UnderlyingSeg":  segment
    }
    response = await rest_client.post("/optionchain/expirylist", payload)
    return sorted(response["data"])   # ["2026-03-27", "2026-04-27", ...]

def select_expiry(expiry_list: list[str], mode: str = "NEAR") -> str:
    """
    NEAR  = nearest expiry (most liquid, highest gamma)
    NEXT  = second expiry  (when near expiry has < 3 days left, roll to next)
    FAR   = third expiry   (for swing trades only)
    """
    from datetime import date
    today = date.today()

    valid = [e for e in expiry_list if date.fromisoformat(e) >= today]
    if not valid:
        raise ValueError("No valid expiries found")

    near = valid[0]
    days_to_expiry = (date.fromisoformat(near) - today).days

    # Auto-roll: if expiry < 3 days away, switch to next
    if mode == "NEAR" and days_to_expiry < 3 and len(valid) > 1:
        return valid [dhanhq](https://dhanhq.co/docs/v2/option-chain/)
    elif mode == "NEXT" and len(valid) > 1:
        return valid [dhanhq](https://dhanhq.co/docs/v2/option-chain/)
    elif mode == "FAR"  and len(valid) > 2:
        return valid [dhanhq](https://dhanhq.co/docs/v2/instruments/)

    return near
```

### Step 1.2 — Fetch Full Option Chain
```python
async def fetch_option_chain(underlying_security_id: int,
                              segment: str,
                              expiry: str,
                              rest_client: DhanRESTClient) -> dict:
    """
    POST /optionchain
    Returns ALL strikes for the given underlying + expiry.
    Each strike has: LTP, OI, volume, IV, greeks, bid/ask
    Rate limit: 1 unique request per 3 seconds.
    """
    payload = {
        "UnderlyingScri": underlying_security_id,
        "UnderlyingSeg":  segment,
        "Expiry":         expiry           # "2026-03-27"
    }
    response = await rest_client.post("/optionchain", payload)
    return response["data"]   # dict keyed by strike price

# Response structure per strike:
# {
#   "280": {
#     "call": {"security_id": 123, "ltp": 9.35, "oi": 45000,
#              "volume": 1200, "iv": 45.8, "bid": 9.30, "ask": 9.40,
#              "delta": 0.42, "theta": -0.08, "vega": 0.12},
#     "put":  {"security_id": 456, "ltp": 8.75, "oi": 52000, ...}
#   }
# }
```

### Step 1.3 — ATM Strike Finder
```python
def find_atm_strike(option_chain: dict, underlying_ltp: float,
                    strike_step: float) -> float:
    """
    ATM = strike closest to underlying's current price.
    Rounded to nearest strike step.
    """
    return round(underlying_ltp / strike_step) * strike_step

def select_strikes_to_scan(option_chain: dict, atm_strike: float,
                            strike_step: float, atm_range: int) -> list[float]:
    """
    Returns ATM ± N strikes to monitor.
    Example: atm=280, step=10, range=3 → [250,260,270,280,290,300,310]
    """
    strikes = []
    for i in range(-atm_range, atm_range + 1):
        strike = atm_strike + (i * strike_step)
        if str(int(strike)) in option_chain:
            strikes.append(strike)
    return sorted(strikes)
```

***

## Layer 2 — Contract Filter & Selection Logic

### Step 2.1 — Contract Quality Filters
```python
@dataclass
class ContractFilter:
    """Configurable filters — all must pass for contract to be scanned."""
    min_oi:           int   = 1000     # Minimum open interest
    min_volume:       int   = 100      # Minimum volume today
    max_iv:           float = 150.0    # Maximum IV% (avoid illiquid far OTM)
    min_iv:           float = 5.0      # Minimum IV% (avoid zero-priced)
    max_spread_pct:   float = 0.10     # Max bid-ask spread as % of LTP
    min_ltp:          float = 0.50     # Minimum option price (avoid sub-1 rupee)
    max_ltp:          float = 500.0    # Maximum option price
    min_delta_abs:    float = 0.10     # Minimum absolute delta (not too far OTM)
    max_delta_abs:    float = 0.90     # Maximum absolute delta (not too deep ITM)

def passes_filter(contract: dict, f: ContractFilter) -> tuple[bool, list[str]]:
    """Returns (passed, list_of_failed_reasons)"""
    failures = []
    ltp    = contract.get("ltp", 0)
    oi     = contract.get("oi", 0)
    volume = contract.get("volume", 0)
    iv     = contract.get("iv", 0)
    bid    = contract.get("bid", 0)
    ask    = contract.get("ask", 0)
    delta  = abs(contract.get("delta", 0))

    spread_pct = (ask - bid) / ltp if ltp > 0 else 999

    if oi     < f.min_oi:           failures.append(f"OI {oi} < {f.min_oi}")
    if volume < f.min_volume:       failures.append(f"Vol {volume} < {f.min_volume}")
    if iv     > f.max_iv:           failures.append(f"IV {iv}% > {f.max_iv}%")
    if iv     < f.min_iv:           failures.append(f"IV {iv}% < {f.min_iv}%")
    if ltp    < f.min_ltp:          failures.append(f"LTP {ltp} < {f.min_ltp}")
    if ltp    > f.max_ltp:          failures.append(f"LTP {ltp} > {f.max_ltp}")
    if spread_pct > f.max_spread_pct: failures.append(f"Spread {spread_pct:.1%} > {f.max_spread_pct:.1%}")
    if delta  < f.min_delta_abs:    failures.append(f"Delta {delta:.2f} < {f.min_delta_abs}")
    if delta  > f.max_delta_abs:    failures.append(f"Delta {delta:.2f} > {f.max_delta_abs}")

    return len(failures) == 0, failures
```

### Step 2.2 — Rank Contracts by Tradability Score
```python
def rank_contracts(filtered_contracts: list[dict]) -> list[dict]:
    """
    Score each contract — highest score = most tradable.
    Used to pick top N contracts when too many pass the filter.
    """
    for c in filtered_contracts:
        score = 0.0

        # Higher OI = more institutional interest
        score += min(c["oi"] / 10000, 5.0)           # max 5 pts

        # Higher volume = more active today
        score += min(c["volume"] / 500, 3.0)          # max 3 pts

        # Tighter spread = more liquid
        spread_pct = (c["ask"] - c["bid"]) / c["ltp"] if c["ltp"] > 0 else 1
        score += max(0, 2.0 - spread_pct * 20)        # max 2 pts

        # ATM proximity bonus (delta closest to 0.5)
        delta_dist = abs(abs(c["delta"]) - 0.5)
        score += max(0, 1.0 - delta_dist * 2)          # max 1 pt

        c["tradability_score"] = round(score, 2)

    return sorted(filtered_contracts, key=lambda x: x["tradability_score"], reverse=True)
```

***

## Layer 3 — Dynamic Subscription Manager

### Step 3.1 — Subscription State
```python
class SubscriptionManager:
    """
    Manages which security IDs are currently subscribed on WS.
    Handles adds and removes without full reconnect.
    """
    def __init__(self, ws_client: DhanWSClient, max_symbols: int = 100):
        self.ws            = ws_client
        self.max_symbols   = max_symbols
        self.subscribed:   dict[str, dict] = {}  # {security_id: contract_meta}
        self.scan_results: dict[str, dict] = {}  # {security_id: latest signal}

    async def subscribe_contracts(self, contracts: list[dict]):
        """Subscribe to WS tick feed for new contracts."""
        new_ids = [
            c["security_id"] for c in contracts
            if str(c["security_id"]) not in self.subscribed
        ]
        if not new_ids:
            return

        # DhanHQ WS subscribe packet
        payload = {
            "RequestCode":     15,
            "InstrumentCount": len(new_ids),
            "InstrumentList": [
                {"ExchangeSegment": c["segment"], "SecurityId": str(c["security_id"])}
                for c in contracts if c["security_id"] in new_ids
            ]
        }
        await self.ws.send(payload)

        for c in contracts:
            if c["security_id"] in new_ids:
                self.subscribed[str(c["security_id"])] = c

    async def unsubscribe_contracts(self, security_ids: list[str]):
        """Unsubscribe stale contracts (e.g., now too far OTM after price move)."""
        payload = {
            "RequestCode":     16,       # Unsubscribe code
            "InstrumentCount": len(security_ids),
            "InstrumentList": [
                {"ExchangeSegment": self.subscribed[sid]["segment"],
                 "SecurityId": sid}
                for sid in security_ids if sid in self.subscribed
            ]
        }
        await self.ws.send(payload)
        for sid in security_ids:
            self.subscribed.pop(sid, None)

    async def rebalance(self, new_contracts: list[dict]):
        """
        Called every 5 min — add new ATM contracts, remove far OTM ones.
        Keeps subscription set fresh as underlying price moves.
        """
        new_ids  = {str(c["security_id"]) for c in new_contracts}
        curr_ids = set(self.subscribed.keys())

        to_add   = [c for c in new_contracts if str(c["security_id"]) not in curr_ids]
        to_remove = list(curr_ids - new_ids)

        if to_remove:
            await self.unsubscribe_contracts(to_remove)
        if to_add:
            await self.subscribe_contracts(to_add)
```

***

## Layer 4 — Scanner Orchestrator (Full Flow)

```python
class OptionScanner:
    """
    The top-level scanner that:
    1. Detects exchange mode (NSE or MCX)
    2. Fetches option chains for all underlyings in that mode
    3. Filters and ranks contracts
    4. Subscribes to selected contracts
    5. Routes ticks to strategy pipeline per symbol
    6. Rebalances subscriptions as price moves
    """
    def __init__(self,
                 mode:         ExchangeMode,
                 rest_client:  DhanRESTClient,
                 ws_client:    DhanWSClient,
                 strategy_engine,
                 db:           DuckDBStore,
                 contract_filter: ContractFilter = ContractFilter()):
        self.mode     = mode
        self.rest     = rest_client
        self.ws       = ws_client
        self.engine   = strategy_engine
        self.db       = db
        self.filter   = contract_filter
        self.sub_mgr  = SubscriptionManager(ws_client)
        self.states:  dict[str, SymbolState] = {}
        self.queues:  dict[str, asyncio.Queue] = {}

    # ── STARTUP SCAN ────────────────────────────────────────────────────────
    async def initial_scan(self):
        """Run once at session open. Discovers and subscribes all valid contracts."""
        underlyings = UNDERLYINGS[self.mode]
        all_contracts = []

        for underlying in underlyings:
            contracts = await self._scan_underlying(underlying)
            all_contracts.extend(contracts)

        # Sort by tradability
        ranked = rank_contracts(all_contracts)

        # Subscribe top N
        top_n = ranked[:self.sub_mgr.max_symbols]
        await self.sub_mgr.subscribe_contracts(top_n)

        # Init state for each
        for c in top_n:
            sid = str(c["security_id"])
            self.queues[sid] = asyncio.Queue()
            self.states[sid] = await self._init_symbol_state(c)
            asyncio.create_task(
                self.engine.symbol_pipeline(sid, self.states[sid], self.queues[sid])
            )

    async def _scan_underlying(self, underlying: dict) -> list[dict]:
        """Fetch chain, find ATM, filter strikes for one underlying."""
        seg    = EXCHANGE_SEGMENTS[self.mode]["segment"]
        expiry = select_expiry(
            await fetch_expiry_list(underlying["security_id"], seg, self.rest)
        )
        chain  = await fetch_option_chain(underlying["security_id"], seg, expiry, self.rest)

        # Get underlying LTP
        underlying_ltp = await self.rest.get_ltp(underlying["security_id"], seg)

        atm = find_atm_strike(chain, underlying_ltp, underlying["strike_step"])
        strikes = select_strikes_to_scan(chain, atm, underlying["strike_step"], underlying["atm_range"])

        contracts = []
        for strike in strikes:
            for option_type in ("call", "put"):
                raw = chain.get(str(int(strike)), {}).get(option_type)
                if not raw:
                    continue
                passed, reasons = passes_filter(raw, self.filter)
                if passed:
                    contracts.append({
                        **raw,
                        "underlying":  underlying["name"],
                        "strike":      strike,
                        "option_type": option_type.upper(),
                        "expiry":      expiry,
                        "segment":     seg,
                        "atm_offset":  int((strike - atm) / underlying["strike_step"])
                    })

        return contracts

    # ── PERIODIC REBALANCE ───────────────────────────────────────────────────
    async def rebalance_loop(self):
        """
        Every 5 minutes: re-scan all underlyings.
        If underlying has moved, add new ATM contracts, remove stale far OTM ones.
        """
        while True:
            await asyncio.sleep(300)   # 5 minutes
            try:
                underlyings = UNDERLYINGS[self.mode]
                all_contracts = []
                for underlying in underlyings:
                    contracts = await self._scan_underlying(underlying)
                    all_contracts.extend(contracts)

                ranked = rank_contracts(all_contracts)
                top_n  = ranked[:self.sub_mgr.max_symbols]

                await self.sub_mgr.rebalance(top_n)

                # Init state for newly added contracts
                for c in top_n:
                    sid = str(c["security_id"])
                    if sid not in self.states:
                        self.queues[sid] = asyncio.Queue()
                        self.states[sid] = await self._init_symbol_state(c)
                        asyncio.create_task(
                            self.engine.symbol_pipeline(sid, self.states[sid], self.queues[sid])
                        )

            except Exception as e:
                log.error("rebalance_failed", error=str(e))

    # ── TICK ROUTER ──────────────────────────────────────────────────────────
    async def route_tick(self, tick: Tick, security_id: str):
        """Called by WS client for every incoming tick — routes to correct queue."""
        if security_id in self.queues:
            await self.queues[security_id].put(tick)

    # ── STATE INIT ───────────────────────────────────────────────────────────
    async def _init_symbol_state(self, contract: dict) -> SymbolState:
        state = SymbolState(
            symbol      = f"{contract['underlying']}_{int(contract['strike'])}_{contract['option_type']}",
            strike      = contract["strike"],
            option_type = contract["option_type"],
            underlying  = contract["underlying"],
            security_id = contract["security_id"],
            expiry      = contract["expiry"],
            segment     = contract["segment"]
        )
        # Load previous session profile
        state.prev_session_va = self.db.load_prev_session_profile(
            contract["underlying"]   # ← Profile built on UNDERLYING, not option price
        )
        return state
```

***

## Critical Design Decision — Profile on Underlying, Not Option

This was in the pending items list. Options pricing has theta decay that corrupts profiles: [dhanhq](https://dhanhq.co/docs/v2/option-chain/)

```python
# WRONG: Profiling option LTP (8.75, 9.35 etc.) — theta eats this
build_volume_profile(ticks=option_ltp_ticks, ...)   # ❌

# CORRECT: Profile built on UNDERLYING spot price
# Option tick feed → extract underlying price from option chain
# Build profiles on underlying → use those levels for entries
# Option contract = vehicle for entry, not source of profile levels

class UnderlyingProfileRouter:
    """
    Routes option ticks to the correct UNDERLYING's profile engine.
    All volume profiles, LVNs, VAH/VAL are built on underlying price.
    Option contract is used only for: position sizing, expiry selection, OI check.
    """
    def __init__(self):
        self.underlying_engines: dict[str, VolumeProfileEngine] = {}

    def get_engine(self, underlying: str) -> VolumeProfileEngine:
        if underlying not in self.underlying_engines:
            cfg = next(u for u in UNDERLYINGS[ExchangeMode.MCX]
                      if u["name"] == underlying)
            self.underlying_engines[underlying] = VolumeProfileEngine(
                bucket_size = cfg["strike_step"] / 10   # Finer than strike step
            )
        return self.underlying_engines[underlying]

    def update(self, tick: Tick, underlying: str, underlying_price: float):
        """
        Each option tick arrives with underlying_price in the chain data.
        Update the underlying's profile with this price.
        """
        engine = self.get_engine(underlying)
        # Create a synthetic tick at underlying price
        underlying_tick = Tick(
            price      = underlying_price,
            ask_vol    = tick.ask_vol,
            bid_vol    = tick.bid_vol,
            volume     = tick.volume,
            trade_size = tick.trade_size,
            delta      = tick.delta,
            timestamp  = tick.timestamp
        )
        engine.update(underlying_tick)
```

***

## Complete Startup Flow (Revised `main.py`)

```python
async def startup(mode: ExchangeMode):

    # 1. Init clients
    rest_client = DhanRESTClient(DHAN_ACCESS_TOKEN)
    ws_client   = DhanWSClient(DHAN_ACCESS_TOKEN)
    db          = DuckDBStore(DB_PATH)
    db.initialize_schema()

    # 2. Init underlying profile router
    profile_router = UnderlyingProfileRouter()

    # 3. Init strategy engine
    strategy_engine = StrategyEngine(db, profile_router)

    # 4. Init scanner with exchange mode
    scanner = OptionScanner(
        mode             = mode,           # ExchangeMode.NSE or ExchangeMode.MCX
        rest_client      = rest_client,
        ws_client        = ws_client,
        strategy_engine  = strategy_engine,
        db               = db,
        contract_filter  = ContractFilter(
            min_oi    = 500   if mode == ExchangeMode.MCX else 5000,
            min_volume= 50    if mode == ExchangeMode.MCX else 500,
            atm_range = 3     if mode == ExchangeMode.MCX else 5,
        )
    )

    # 5. Connect WebSocket
    asyncio.create_task(ws_client.connect(on_tick=scanner.route_tick))

    # 6. Initial option chain scan + subscribe
    await scanner.initial_scan()

    # 7. Start 5-minute rebalance loop
    asyncio.create_task(scanner.rebalance_loop())

    # 8. Start FastAPI
    # (uvicorn handles this)
    log.info("startup_complete", mode=mode.value,
             subscribed=len(scanner.sub_mgr.subscribed))
```

***

## Updated Scanner UI — What the Frontend Shows

The scanner table now auto-populates from the chain scan: [dhanhq](https://dhanhq.co/docs/v2/option-chain/)

```
MODE: [NSE ▼] / [MCX ▼]          Subscribed: 47 contracts

UNDERLYING   STRIKE  TYPE  LTP    STATE      SCORE  DRIVE  SIGNAL
─────────────────────────────────────────────────────────────────────
NATURALGAS   280     PE    9.35   BALANCED   2.5    2      ⚡ LONG
NATURALGAS   290     PE    6.20   IMBALANCED 3.0    2      🔥 SHORT
NATURALGAS   270     CE    11.40  NO_TRADE   —      1      ⏳ FLAT
NIFTY        22500   CE    145.0  BALANCED   1.5    1      ⏳ FLAT
NIFTY        22400   PE    98.0   BALANCED   2.0    2      ⚡ SHORT
BANKNIFTY    47000   CE    320.0  IMBALANCED 3.5    2      🔥 LONG

[ Filter: All | Active Signals Only | High Confidence Only ]
[ Rebalance in: 3:42 ]
```

***

## DhanHQ API Rate Limit Management

```python
class ScanRateLimiter:
    """
    Option chain: 1 unique request per 3 seconds (per DhanHQ docs).
    Scan all underlyings sequentially with proper spacing.
    """
    def __init__(self):
        self.last_chain_call = 0.0

    async def wait_for_chain_call(self):
        elapsed = asyncio.get_event_loop().time() - self.last_chain_call
        if elapsed < 3.0:
            await asyncio.sleep(3.0 - elapsed)
        self.last_chain_call = asyncio.get_event_loop().time()

# Usage — scan 4 MCX underlyings = 4 × 3s = 12s total startup time
# Acceptable — runs once at open, then rebalances every 5 min
```


Here is the complete redesigned architecture incorporating every layer from all previous documents — one unified system.

***

# GlassyTrade AI — Redesigned Architecture & Flows

***

## System Context Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              EXTERNAL SYSTEMS                                   │
│                                                                                 │
│   DhanHQ WS Feed          DhanHQ REST API         EIA Economic Calendar        │
│   (tick stream)            (option chain,           (suppression windows)       │
│   wss://api-feed.dhan.co   L2 DOM, LTP, OI)        ir.eia.gov                  │
│         │                        │                        │                    │
└─────────┼────────────────────────┼────────────────────────┼────────────────────┘
          │                        │                        │
          ▼                        ▼                        ▼
┌─────────────────────────────────────────────────────────────────────────────────┐
│                         GLASSTRADE AI ENGINE                                    │
│                         (single Python process, asyncio + uvloop)               │
└─────────────────────────────────────────────────────────────────────────────────┘
```

***

## Layer Architecture (7 Layers)

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│  LAYER 7 — PRESENTATION                                                         │
│  React Frontend (Port 5190)                                                     │
│  Scanner Table │ Volume Profile │ Footprint │ AI Commander │ Risk Dashboard     │
└────────────────────────────────┬────────────────────────────────────────────────┘
                                 │ WebSocket (ws://localhost:8000/ws/signals)
┌────────────────────────────────▼────────────────────────────────────────────────┐
│  LAYER 6 — API GATEWAY                                                          │
│  FastAPI + uvicorn                                                              │
│  REST: /api/signal /api/profile /api/risk /api/trade /api/config               │
│  WS:   /ws/signals  (broadcast hub — reads from WSPublisher queue)             │
└────────────────────────────────┬────────────────────────────────────────────────┘
                                 │ in-process asyncio.Queue
┌────────────────────────────────▼────────────────────────────────────────────────┐
│  LAYER 5 — OUTPUT & ALERTS                                                      │
│  SignalFormatter → OutputSchema (Pydantic) → WSPublisher                       │
│  AlertManager → pre-alerts, drive alerts, risk kill events                     │
│  NotificationClient → Telegram push (mobile)                                   │
└────────────────────────────────┬────────────────────────────────────────────────┘
                                 │ OutputSchema
┌────────────────────────────────▼────────────────────────────────────────────────┐
│  LAYER 4 — STRATEGY ENGINE (per-symbol coroutine)                               │
│  ┌──────────────────────────────────────────────────────────────────────────┐   │
│  │  12-GATE PIPELINE (runs every tick)                                      │   │
│  │  G0:Time │ G1:Quality │ G2:Risk │ G3:Dead │ G4:Probing │ G5:Profile    │   │
│  │  G6:Zone │ G7:Drive   │ G8:Aggr │ G9:Cush │ G10:RR    │ G11:Size      │   │
│  │  G12:EIA │                                                               │   │
│  │                                                                          │   │
│  │  MarketState → AnomalyDetector → ProfileSelector → DriveTracker        │   │
│  │  → AggressionScorer → TradeConstructor → RiskManager                   │   │
│  │  → PartitionExitMgr → PyramidMgr → RationaleGenerator                  │   │
│  └──────────────────────────────────────────────────────────────────────────┘   │
│                                                                                 │
│  UNDERLYING PROFILE ROUTER (shared across all option symbols)                  │
│  UnderlyingProfileRouter → VolumeProfileEngine (delta + plain)                 │
│  NPOCTracker │ CompositeProfile (weekly bias)                                  │
└────────────────────────────────┬────────────────────────────────────────────────┘
                                 │ Tick objects
┌────────────────────────────────▼────────────────────────────────────────────────┐
│  LAYER 3 — ORDER FLOW ENGINE (feeds Layer 4 every tick)                         │
│  CVDEngine │ FootprintEngine │ BubbleDetector │ AbsorptionDetector              │
│  BigTradeDetector │ OFICalculator │ VWAPEngine │ IBDetector │ L2Monitor         │
└────────────────────────────────┬────────────────────────────────────────────────┘
                                 │ normalized Tick
┌────────────────────────────────▼────────────────────────────────────────────────┐
│  LAYER 2 — SCANNER & SUBSCRIPTION MANAGER                                       │
│  OptionScanner → ExchangeMode (NSE|MCX) → OptionChainFetcher                  │
│  ContractFilter → ContractRanker → SubscriptionManager                         │
│  RebalanceLoop (5min) → dynamic add/remove subscriptions                       │
└────────────────────────────────┬────────────────────────────────────────────────┘
                                 │ raw WS messages
┌────────────────────────────────▼────────────────────────────────────────────────┐
│  LAYER 1 — DATA INGESTION                                                       │
│  DhanWSClient (tick stream) │ DhanRESTClient (chain, L2, OI)                  │
│  TickProcessor │ CandleBuilder │ SessionManager                                │
│  EconomicCalendar (EIA suppression)                                             │
└────────────────────────────────┬────────────────────────────────────────────────┘
                                 │ persist / recover
┌────────────────────────────────▼────────────────────────────────────────────────┐
│  LAYER 0 — PERSISTENCE                                                          │
│  DuckDB: ticks, session_profiles, signals, trades, session_risk, open_trades   │
│  Pickle+lzma: SymbolState crash snapshots                                       │
└─────────────────────────────────────────────────────────────────────────────────┘
```

***

## Master Data Flow

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                          STARTUP SEQUENCE                                            │
│                                                                                      │
│  1. Load .env config                                                                 │
│  2. DuckDB init + schema create                                                      │
│  3. Load prev session profiles per underlying → SymbolState.prev_session_va         │
│  4. EIA calendar load → suppression windows                                          │
│  5. DhanHQ REST: fetch option chains for all underlyings (mode = NSE|MCX)           │
│  6. ContractFilter + rank → select top N contracts                                  │
│  7. DhanHQ WS: connect + subscribe selected security IDs                            │
│  8. Init SymbolState per contract, start per-symbol pipeline coroutines             │
│  9. Start L2 DOM poller (500ms)                                                     │
│  10. Start rebalance loop (5min)                                                    │
│  11. FastAPI server ready                                                           │
└──────────────────────────────────────────────────────────────────────────────────────┘
```

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│                      PER-TICK PIPELINE FLOW (runs every tick, per symbol)           │
│                                                                                      │
│  DhanHQ WS tick arrives                                                             │
│         │                                                                            │
│         ▼                                                                            │
│  TickProcessor.normalize()                                                          │
│  → Tick {price, ask_vol, bid_vol, volume, trade_size, delta, timestamp}             │
│         │                                                                            │
│         ├──────────────────────────────────────────────────────────┐               │
│         │                                                           │               │
│         ▼                                                           ▼               │
│  SymbolState tick_buffer.append(tick)              UnderlyingProfileRouter          │
│  CandleBuilder.update(tick)                        .update(tick, underlying,        │
│                  │                                  underlying_price)               │
│                  │ on candle close:                       │                         │
│                  ▼                                        ▼                         │
│         candle_buffer.append(candle)         VolumeProfileEngine                   │
│         recalc: ATR, AvgVol                  .session_profile[bucket] += vol       │
│         OFICalculator.update()               .leg_profile[bucket] += vol           │
│         VWAPEngine.update()                  .delta_profile[bucket] updated        │
│         IBDetector.check_ib_break()                                                │
│                  │                                                                  │
│                  ▼                                                                  │
│         FootprintEngine.finalize_candle()                                          │
│         BubbleDetector.update(footprint_history)                                   │
│                  │                                                                  │
│         ◄────────┘                                                                  │
│         │                                                                           │
│         ▼                                                                           │
│  ═══════════════════════════════════════════════════                               │
│                    12-GATE PIPELINE                                                 │
│  ═══════════════════════════════════════════════════                               │
│                                                                                     │
│  GATE 0: SessionManager.is_in_warmup() OR is_in_dead_zone()                        │
│          → BLOCKED: return OutputSchema(action="TIME_BLOCKED")                     │
│          ↓ PASS                                                                     │
│                                                                                     │
│  GATE 1: state.data_quality == "STALE" (gap > 30s since last tick)                │
│          → STALE: return OutputSchema(action="DATA_STALE")                         │
│          ↓ PASS                                                                     │
│                                                                                     │
│  GATE 2: SessionRiskManager.can_trade()                                            │
│          daily_loss ≥ 2% OR consecutive_losses ≥ 3 OR drawdown ≥ 3%              │
│          → SESSION_STOPPED: return OutputSchema(action="SESSION_STOPPED")          │
│          ↓ PASS                                                                     │
│                                                                                     │
│  GATE 3: EconomicCalendar.is_suppression_window(timestamp)                        │
│          → SUPPRESSED: return OutputSchema(action="EIA_WINDOW")                    │
│          ↓ PASS                                                                     │
│                                                                                     │
│  GATE 4: MarketStateEngine.detect()                                               │
│          → NO_TRADE (POC ±2 ticks): return FLAT                                   │
│          → PROBING (unconfirmed break): return WAIT                               │
│          → BALANCED or IMBALANCED: continue                                        │
│          ↓ PASS (BALANCED or IMBALANCED)                                           │
│                                                                                     │
│  [PARALLEL COMPUTE — all run simultaneously on candle close]                       │
│  ├── AnomalyDetector.detect(price, session_va, prev_va)                           │
│  ├── NPOCTracker.check_and_fill(price) + get_active_npocs()                       │
│  ├── CompositeProfile.apply_weekly_bias_filter(direction, price)                   │
│  └── L2Monitor.detect_liquidity_wall(price)                                       │
│          ↓                                                                          │
│                                                                                     │
│  GATE 5: ProfileSelector.select_active_profile(market_state)                     │
│          → NONE / WAIT / BUILDING_LEG: return FLAT                                │
│          → SESSION or LEG or COMBINED: key_level identified                        │
│          ↓ PASS (key_level exists)                                                 │
│                                                                                     │
│  GATE 6: abs(current_price - key_level) ≤ 3 ticks?                               │
│          → NO: AlertManager.set_price_alert(key_level)                             │
│                return OutputSchema(action="ALERT_SET")                             │
│          ↓ YES                                                                      │
│                                                                                     │
│  GATE 7: DriveTracker.classify_drive(current_price, key_level)                   │
│          → drive == 1: record touch, return FLAT (first drive — no entry)         │
│          → drive == 2 + first rejected: ENTRY ZONE VALID                          │
│          → drive ≥ 3: level exhausted, return FLAT                                │
│          ↓ PASS (drive == 2, rejected)                                             │
│                                                                                     │
│  [AGGRESSION COMPUTE]                                                              │
│  FootprintEngine.detect_imbalance(direction)         → score += 1.0              │
│  CVDEngine.get_slope() + detect_divergence()          → score += 1.0              │
│  BigTradeDetector.detect_cluster(key_level)           → score += 1.0              │
│  AbsorptionDetector.detect(candle, atr, avg_vol)      → score += 0.5             │
│  OFICalculator.calc_ofi()                             → score += 0.5             │
│  BubbleDetector.bubble_confirms_entry()               → score += 0.5             │
│  DeltaZoneDetector.detect_high_delta_zones()          → score += 0.5             │
│  AnomalyDetector.double_anomaly_bonus()               → score += 0.5             │
│  CompositeProfile.weekly_bias_aligned()               → score += 0.5             │
│          ↓                                                                          │
│                                                                                     │
│  GATE 8: aggression_score ≥ 2.0?                                                  │
│          → NO: return OutputSchema(action="WAIT", score=x)                        │
│          ↓ YES                                                                      │
│                                                                                     │
│  GATE 9: calculate_cushion(entry, stop) ≤ 10 ticks?                              │
│          → NO (INVALID): return FLAT                                               │
│          ↓ YES                                                                      │
│                                                                                     │
│  GATE 10: risk_reward ≥ 1.5?                                                      │
│           → NO: return FLAT (bad setup geometry)                                   │
│           ↓ YES                                                                     │
│                                                                                     │
│  GATE 11: PositionSizer.calculate() — risk budget available?                      │
│           → BLOCKED: return SessionRisk block                                      │
│           ↓ YES                                                                     │
│                                                                                     │
│  GATE 12: OI pressure check — is_high_oi_wall(strike) ?                          │
│           → HIGH OI: reduce confidence (not block)                                 │
│           ↓ PASS                                                                    │
│                                                                                     │
│  ═══ ALL GATES PASSED → TRADE SIGNAL ═══                                          │
│                                                                                     │
│  TradeConstructor.build() → TradeSetup                                            │
│  RationaleGenerator.generate() → string                                           │
│  SignalFormatter.format() → OutputSchema                                           │
│         │                                                                           │
│         ├── DuckDB.save_signal()                                                   │
│         ├── WSPublisher.broadcast_signal()  → Frontend                             │
│         └── AlertManager.notify_drive_alert() → Telegram                          │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

***

## Open Trade Management Flow (Separate Loop)

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  OPEN TRADE MANAGEMENT LOOP (runs every tick when open_entries is not empty)       │
│                                                                                     │
│  [EVERY TICK]                                                                       │
│         │                                                                           │
│         ▼                                                                           │
│  CounterAggressionDetector.check()                                                 │
│         │                                                                           │
│         ├── 2+ counter signals? ──► EXIT ALL IMMEDIATELY                           │
│         │                          PartitionExitManager.exit_all()                 │
│         │                          DuckDB.save_trade() × all lots                  │
│         │                          WSPublisher.broadcast_trade_update("EXIT_ALL")  │
│         │                          SessionRiskManager.register_trade_result(pnl)   │
│         │                                                                           │
│         └── counter < 2: continue                                                  │
│                  │                                                                  │
│                  ▼                                                                  │
│  BreakevenManager.check_trigger(current_price, entry, target, direction)           │
│         │                                                                           │
│         ├── 35% to target reached? ──► MOVE SL TO BREAKEVEN                       │
│         │                              update all OpenEntry.stop_loss = entry      │
│         │                              WSPublisher.broadcast("MOVE_TO_BREAKEVEN")  │
│         │                                                                           │
│         └── not yet: continue                                                      │
│                  │                                                                  │
│                  ▼                                                                  │
│  PartitionExitManager.check()                                                      │
│         │                                                                           │
│         ├── P1 trigger (33% R, weak CVD)? ──► exit 30% lots                       │
│         ├── P2 trigger (target reached)?   ──► exit 50% lots (ALWAYS)             │
│         │         └── strong CVD? → trail P3   weak CVD? → exit P3                │
│         └── not yet: continue                                                      │
│                  │                                                                  │
│                  ▼                                                                  │
│  PyramidManager.check()  (only if first entry in profit)                           │
│         │                                                                           │
│         ├── new LVN exists between current price and target?                       │
│         ├── price AT pyramid level (±3 ticks)?                                     │
│         ├── aggression_score ≥ 3.0 (higher bar)?                                  │
│         └── YES ALL: PYRAMID ADD                                                   │
│                    lot size = 50% of first entry (add 1) or 25% (add 2)           │
│                    ALL stops → SL of new entry                                     │
│                    DuckDB.save_open_trade_state()  ← crash recovery               │
│                    WSPublisher.broadcast("PYRAMID_ADD")                            │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

***

## Rebalance Flow (Every 5 Minutes)

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  SCANNER REBALANCE LOOP (asyncio task, runs every 300s)                            │
│                                                                                     │
│  For each underlying in ExchangeMode:                                              │
│    1. Rate-limit wait (3s per chain call)                                          │
│    2. DhanHQ REST: fetch_option_chain(underlying, expiry)                          │
│    3. get_underlying_ltp()                                                          │
│    4. find_atm_strike(ltp)                                                          │
│    5. select_strikes_to_scan(atm ± N)                                              │
│    6. passes_filter() for each strike × CE/PE                                      │
│    7. rank_contracts() by tradability score                                         │
│                                                                                     │
│  Diff against current subscriptions:                                               │
│    NEW contracts (ATM moved) ──► subscribe_contracts() + init SymbolState         │
│    STALE contracts (now far OTM) ──► unsubscribe_contracts()                      │
│                                      cleanup SymbolState + queues                  │
│                                      do NOT kill if trade is open on that contract │
│                                                                                     │
│  Check expiry roll:                                                                 │
│    days_to_expiry < 3? ──► switch all contracts to next expiry                    │
│    re-subscribe with new security IDs                                              │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

***

## Session Boundary Flow (Daily Reset)

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│  SESSION BOUNDARY HANDLER (fires at session open time per exchange)                │
│                                                                                     │
│  SessionManager detects new session:                                               │
│                                                                                     │
│  FOR EACH UNDERLYING:                                                              │
│    1. Save completed session profile to DuckDB                                     │
│       session_profiles: {date, underlying, poc, vah, val, profile_json}           │
│    2. Add session POC to NPOCTracker                                               │
│    3. Update CompositeProfile (add session to rolling 5-session window)            │
│    4. state.prev_session_va = state.session_va                                     │
│    5. Reset VolumeProfileEngine (session_profile = {})                             │
│    6. Reset CVDEngine (cvd = 0)                                                    │
│    7. Reset DriveTracker (all drives = {})                                         │
│    8. Reset AlertManager (all alerts cleared)                                      │
│    9. Reset SessionRiskManager (daily_pnl = 0, consecutive = 0)                   │
│    10. Reset IBDetector                                                             │
│    11. Reload prev session profiles for new prev reference                         │
│                                                                                     │
│  Re-run initial_scan() for new session contracts                                   │
│  (option chain refreshes daily — new strikes, new security IDs possible)           │
│                                                                                     │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

***

## Component Interaction Map

```
                    ┌─────────────────┐
                    │  OptionScanner  │ ← ExchangeMode (NSE|MCX)
                    └────────┬────────┘
                             │ selected contracts
                    ┌────────▼────────┐
                    │SubscriptionMgr  │ ← 5-min rebalance
                    └────────┬────────┘
                             │ security_id → asyncio.Queue
          ┌──────────────────┼──────────────────────────────┐
          ▼                  ▼                              ▼
   SymbolState[A]     SymbolState[B]              SymbolState[N]
          │                  │                              │
          ▼                  ▼                              ▼
   pipeline_coro     pipeline_coro               pipeline_coro
          │
          ├── tick_buffer / candle_buffer
          ├── CVDEngine (session-scoped)
          ├── FootprintEngine (candle-scoped)
          ├── BubbleDetector (21-bar window)
          ├── DriveTracker (session-scoped)
          ├── AlertManager (session-scoped)
          ├── SessionRiskManager (session-scoped)
          └── open_entries (trade-scoped)
          │
          └──► UnderlyingProfileRouter [SHARED]
                    │
                    ├── VolumeProfileEngine[NATURALGAS]  ← session + leg + delta
                    ├── VolumeProfileEngine[NIFTY]
                    ├── VolumeProfileEngine[BANKNIFTY]
                    ├── NPOCTracker[NATURALGAS]
                    ├── NPOCTracker[NIFTY]
                    └── CompositeProfile[all underlyings] ← weekly bias
```

***

## State Object per Symbol (Revised)

```python
@dataclass
class SymbolState:
    # Identity
    symbol:         str          # "NATURALGAS_280_PE"
    security_id:    str          # DhanHQ security ID
    underlying:     str          # "NATURALGAS"
    strike:         float        # 280.0
    option_type:    str          # "CE" or "PE"
    expiry:         str          # "2026-03-27"
    segment:        str          # "MCX_COMM"

    # Tick/Candle buffers
    tick_buffer:    deque        # maxlen=10000
    candle_buffer:  deque        # maxlen=200

    # Order flow (option-level — per-contract)
    cvd_engine:     CVDEngine
    footprint_engine: FootprintEngine
    bubble_detector: BubbleDetector
    big_trade_detector: BigTradeDetector
    ib:             dict         # IB high/low for this contract

    # Strategy state
    drive_tracker:  DriveTracker
    alert_manager:  AlertManager

    # Risk & trade
    risk_manager:   SessionRiskManager
    open_entries:   list[OpenEntry]
    pyramid_count:  int

    # Cached indicators (refreshed on candle close)
    atr:            float
    avg_vol:        float
    avg_trade_size: float
    ofi:            float
    vwap_state:     dict

    # Session
    session_start_ts: datetime
    data_quality:   str          # LIVE | STALE | RECONNECTING
    last_tick_ts:   datetime
    last_signal:    dict

    # NOTE: profiles live in UnderlyingProfileRouter[underlying]
    # NOT in SymbolState — one profile per underlying, shared across all its strikes
```

***

## Persistence Flow

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  DUCKDB WRITE EVENTS                                                         │
│                                                                              │
│  Every tick:          ticks table (append)                                   │
│  Every candle close:  (no write — in-memory only)                           │
│  Every signal:        signals table (append)                                 │
│  Every entry/exit:    trades table + open_trades (upsert)                   │
│  Every risk event:    session_risk table (upsert)                            │
│  Session close:       session_profiles table (insert)                        │
│                                                                              │
│  CRASH RECOVERY WRITES (every trade state change):                           │
│  pickle.dump(SymbolState) → data/snapshots/{symbol}_state.pkl.xz             │
│                                                                              │
│  STARTUP READS:                                                              │
│  session_profiles WHERE date = yesterday → prev_session_va                  │
│  open_trades WHERE not closed → recover mid-session trades                  │
│  session_profiles last 5 rows per underlying → composite profile            │
└──────────────────────────────────────────────────────────────────────────────┘
```

***

## Frontend Data Flow

```
┌──────────────────────────────────────────────────────────────────────────────┐
│  REACT FRONTEND                                                               │
│                                                                              │
│  useWebSocket hook                                                           │
│  └── onmessage(msg) → route by msg.type                                     │
│        │                                                                     │
│        ├── "SIGNAL"       → signalStore.updateSignal(symbol, data)          │
│        ├── "TRADE_UPDATE" → signalStore.updateTrade(trade_id, action)       │
│        ├── "RISK_EVENT"   → riskStore.handleEvent(event)                    │
│        ├── "STATE_CHANGE" → signalStore.updateState(symbol, from, to)       │
│        ├── "DRIVE_ALERT"  → alertStore.addAlert(symbol, drive, level)       │
│        ├── "DATA_QUALITY" → signalStore.setQuality(symbol, quality)         │
│        └── "HEARTBEAT"    → connectionStore.updateHeartbeat(ts)             │
│                                                                              │
│  Scanner Table (zustand signalStore)                                         │
│  └── re-renders only changed rows (zustand shallow selector)                │
│                                                                              │
│  VolumeProfile Component                                                     │
│  └── Canvas 2D — redraws only on profile REST fetch (every 30s)             │
│  └── NOT re-rendering on every tick — profile is batch-updated              │
│                                                                              │
│  Footprint Component                                                         │
│  └── Canvas 2D — redraws on every candle close signal                       │
│                                                                              │
│  AICommander Panel                                                           │
│  └── Shows last signal JSON — updates on SIGNAL message only                │
│                                                                              │
│  RiskDashboard                                                               │
│  └── Shows daily_pnl, consecutive_losses, kill_switch_status                │
│  └── Red banner auto-appears on SESSION_STOPPED event                       │
└──────────────────────────────────────────────────────────────────────────────┘
```

***

## Revised `main.py` (Single Entry Point — Everything Starts Here)

```python
import asyncio, uvloop
from config.instruments import ExchangeMode
from data.dhan_ws_client import DhanWSClient
from data.dhan_rest_client import DhanRESTClient
from data.duckdb_store import DuckDBStore
from scanner.option_scanner import OptionScanner
from strategy.underlying_profile_router import UnderlyingProfileRouter
from strategy.pipeline import StrategyEngine
from output.ws_publisher import WSPublisher
from api.main import create_api_app
import uvicorn, structlog

log = structlog.get_logger()

async def main():
    uvloop.install()

    # ── Config ────────────────────────────────────────────────────────────────
    from dotenv import load_dotenv; load_dotenv()
    import os
    MODE       = ExchangeMode[os.getenv("EXCHANGE_MODE", "MCX")]
    EQUITY     = float(os.getenv("ACCOUNT_EQUITY", 500000))
    DB_PATH    = os.getenv("DB_PATH", "./data/db/glasstrade.db")

    # ── Layer 0: Persistence ─────────────────────────────────────────────────
    db = DuckDBStore(DB_PATH)
    db.initialize_schema()

    # ── Layer 1: Data clients ─────────────────────────────────────────────────
    rest = DhanRESTClient(os.getenv("DHAN_ACCESS_TOKEN"))
    ws   = DhanWSClient(os.getenv("DHAN_ACCESS_TOKEN"))

    # ── Layer 5: Output ───────────────────────────────────────────────────────
    publisher = WSPublisher()

    # ── Layer 4: Strategy engine + shared underlying profiles ─────────────────
    profile_router = UnderlyingProfileRouter(MODE)
    engine         = StrategyEngine(db, profile_router, publisher, EQUITY)

    # ── Layer 2: Scanner ──────────────────────────────────────────────────────
    scanner = OptionScanner(MODE, rest, ws, engine, db)
    ws.on_tick = scanner.route_tick        # wire tick router

    # ── Start all async tasks ─────────────────────────────────────────────────
    await asyncio.gather(
        ws.connect(),                      # L1: WebSocket
        scanner.initial_scan(),            # L2: First option chain scan
        scanner.rebalance_loop(),          # L2: 5-min rebalance
        rest.l2_poll_loop(engine),         # L1: L2 DOM 500ms
        run_api(publisher),                # L6: FastAPI server
    )

async def run_api(publisher: WSPublisher):
    app = create_api_app(publisher)
    config = uvicorn.Config(app, host="0.0.0.0", port=8000, loop="none")
    server = uvicorn.Server(config)
    await server.serve()

if __name__ == "__main__":
    asyncio.run(main())
```

Continuing from the architecture redesign — here is the complete implementation of every remaining module in build order.

***

# GlassyTrade AI — Complete Implementation (Continued)

***

## `config/instruments.py` — Master Config (Build First, Everything Imports This)

```python
from enum import Enum
from dataclasses import dataclass
from typing import Optional

class ExchangeMode(Enum):
    NSE = "NSE_FNO"
    MCX = "MCX_COMM"

class OptionType(Enum):
    CE = "CE"
    PE = "PE"

@dataclass(frozen=True)
class InstrumentConfig:
    name:                str
    security_id:         int
    segment:             str
    strike_step:         float
    tick_size:           float
    lot_size:            int
    point_value:         float     # 1 tick move in INR per lot
    atm_range:           int       # ±N strikes from ATM to scan
    big_trade_threshold: int       # min lots to flag as institutional
    avg_trade_size_init: float     # seed value before enough data
    profile_bucket_size: float     # volume profile bucket width
    session_open:        str       # "HH:MM" IST
    session_close:       str       # "HH:MM" IST
    warmup_minutes:      int       # no signals for first N minutes
    atr_period:          int       # ATR lookback
    mode:                ExchangeMode

INSTRUMENTS: dict[str, InstrumentConfig] = {
    "NATURALGAS": InstrumentConfig(
        name                = "NATURALGAS",
        security_id         = 428199,
        segment             = "MCX_COMM",
        strike_step         = 10.0,
        tick_size           = 0.10,
        lot_size            = 1250,
        point_value         = 125.0,      # 1 rupee move = ₹125 per lot
        atm_range           = 3,
        big_trade_threshold = 50,
        avg_trade_size_init = 5.0,
        profile_bucket_size = 0.10,
        session_open        = "09:00",
        session_close       = "23:30",
        warmup_minutes      = 15,
        atr_period          = 14,
        mode                = ExchangeMode.MCX,
    ),
    "CRUDEOIL": InstrumentConfig(
        name                = "CRUDEOIL",
        security_id         = 428214,
        segment             = "MCX_COMM",
        strike_step         = 100.0,
        tick_size           = 1.0,
        lot_size            = 100,
        point_value         = 100.0,
        atm_range           = 3,
        big_trade_threshold = 20,
        avg_trade_size_init = 3.0,
        profile_bucket_size = 1.0,
        session_open        = "09:00",
        session_close       = "23:30",
        warmup_minutes      = 15,
        atr_period          = 14,
        mode                = ExchangeMode.MCX,
    ),
    "GOLD": InstrumentConfig(
        name                = "GOLD",
        security_id         = 428219,
        segment             = "MCX_COMM",
        strike_step         = 100.0,
        tick_size           = 1.0,
        lot_size            = 100,
        point_value         = 100.0,
        atm_range           = 3,
        big_trade_threshold = 10,
        avg_trade_size_init = 2.0,
        profile_bucket_size = 1.0,
        session_open        = "09:00",
        session_close       = "23:30",
        warmup_minutes      = 15,
        atr_period          = 14,
        mode                = ExchangeMode.MCX,
    ),
    "NIFTY": InstrumentConfig(
        name                = "NIFTY",
        security_id         = 13,
        segment             = "NSE_FNO",
        strike_step         = 50.0,
        tick_size           = 0.05,
        lot_size            = 75,
        point_value         = 75.0,
        atm_range           = 5,
        big_trade_threshold = 500,
        avg_trade_size_init = 50.0,
        profile_bucket_size = 5.0,
        session_open        = "09:15",
        session_close       = "15:30",
        warmup_minutes      = 15,
        atr_period          = 14,
        mode                = ExchangeMode.NSE,
    ),
    "BANKNIFTY": InstrumentConfig(
        name                = "BANKNIFTY",
        security_id         = 25,
        segment             = "NSE_FNO",
        strike_step         = 100.0,
        tick_size           = 0.05,
        lot_size            = 30,
        point_value         = 30.0,
        atm_range           = 5,
        big_trade_threshold = 300,
        avg_trade_size_init = 30.0,
        profile_bucket_size = 10.0,
        session_open        = "09:15",
        session_close       = "15:30",
        warmup_minutes      = 15,
        atr_period          = 14,
        mode                = ExchangeMode.NSE,
    ),
}

def get_instrument(name: str) -> InstrumentConfig:
    if name not in INSTRUMENTS:
        raise ValueError(f"Unknown instrument: {name}. Available: {list(INSTRUMENTS.keys())}")
    return INSTRUMENTS[name]

def get_instruments_by_mode(mode: ExchangeMode) -> list[InstrumentConfig]:
    return [i for i in INSTRUMENTS.values() if i.mode == mode]
```

***

## `config/engine_config.py` — All Thresholds in One Place

```python
from dataclasses import dataclass

@dataclass(frozen=True)
class EngineConfig:
    # Volume Profile
    value_area_pct:           float = 0.70    # 70% value area
    lvn_threshold_pct:        float = 0.15    # LVN = vol < 15% of mean
    hvn_threshold_pct:        float = 2.00    # HVN = vol > 200% of mean
    lvn_score_thinness_wt:    float = 0.60
    lvn_score_midpoint_wt:    float = 0.40

    # Leg Detection
    leg_displacement_atr_mult: float = 1.5
    leg_volume_avg_mult:       float = 1.5
    leg_reset_inside_va:       bool  = True

    # CVD
    cvd_slope_window:          int   = 20
    cvd_divergence_lookback:   int   = 5
    cvd_strong_slope:          float = 2.0    # slope > 2.0 = strong trend

    # Footprint
    footprint_imbalance_ratio: float = 3.0    # 3:1 = imbalance
    footprint_imbalance_pct:   float = 0.40   # 40% of cells must be imbalanced

    # Volume Bubble
    bubble_sigma_threshold:    float = 2.0    # 2σ above mean
    bubble_window:             int   = 21     # candles for mean/std

    # Absorption
    absorption_atr_mult:       float = 0.30   # range < ATR × 0.30
    absorption_vol_mult:       float = 2.00   # volume > avg × 2.0

    # Big Trade
    big_trade_size_mult:       float = 5.00   # trade_size ≥ avg × 5.0
    big_trade_cluster_min:     int   = 3      # 3+ prints within 2 ticks
    big_trade_tick_range:      int   = 2      # within 2 ticks of level

    # OFI
    ofi_window:                int   = 10
    ofi_long_threshold:        float = 0.10   # OFI > 0.10 = buy pressure
    ofi_short_threshold:       float = -0.10  # OFI < -0.10 = sell pressure

    # Market State
    poc_dead_zone_ticks:       int   = 2      # ±2 ticks = no trade
    probing_confirmation_atr:  float = 1.5    # displacement candle threshold

    # Drive Tracker
    level_touch_ticks:         int   = 3      # within 3 ticks = touch
    drive_momentum_fade_pct:   float = 0.5    # CVD slope must be < 50% of drive 1

    # Aggression Scoring
    min_aggression_score:      float = 2.0
    pyramid_aggression_score:  float = 3.0

    # Aggression weights
    score_footprint:           float = 1.0
    score_cvd:                 float = 1.0
    score_big_trade:           float = 1.0
    score_absorption:          float = 0.5
    score_ofi:                 float = 0.5
    score_bubble:              float = 0.5
    score_delta_zone:          float = 0.5
    score_combined_confluence: float = 0.5
    score_anomaly_bonus:       float = 0.5
    score_weekly_bias:         float = 0.5

    # Cushion
    cushion_excellent_ticks:   int   = 3
    cushion_acceptable_ticks:  int   = 6
    cushion_wide_ticks:        int   = 10     # reduce size 50%
    cushion_invalid_ticks:     int   = 10     # > 10 = no trade

    # Trade geometry
    min_risk_reward:           float = 1.5

    # Partition exits
    p1_r_threshold:            float = 0.33   # exit P1 at 33% of R
    p1_lots_pct:               float = 0.30
    p2_lots_pct:               float = 0.50
    p3_lots_pct:               float = 0.20
    breakeven_r_threshold:     float = 0.35   # move SL at 35% to target
    p3_trail_cvd_min:          float = 2.0    # only trail P3 if CVD slope > 2.0
    p3_trail_factor:           float = 0.40   # trail SL = remaining × 0.40

    # Pyramid
    pyramid_max_adds:          int   = 2
    pyramid_lots_pcts:         tuple = (1.0, 0.50, 0.25)
    pyramid_risk_ceiling_mult: float = 1.5    # max 1.5× base risk

    # Risk
    risk_per_trade_pct:        float = 0.005
    max_daily_loss_pct:        float = 0.020
    max_consecutive_losses:    int   = 3
    max_drawdown_pct:          float = 0.030
    max_risk_per_trade_pct:    float = 0.010  # hard ceiling

    # Delta profile
    delta_zone_sigma_mult:     float = 2.5    # high delta = abs(net) > mean × 2.5

    # Composite profile
    composite_session_window:  int   = 5      # rolling 5 sessions

    # Time filters (IST)
    dead_zone_start:           str   = "12:00"
    dead_zone_end:             str   = "13:30"
    best_window_1_start:       str   = "09:30"
    best_window_1_end:         str   = "11:30"
    best_window_2_start:       str   = "14:00"
    best_window_2_end:         str   = "15:30"

    # Data quality
    stale_tick_gap_seconds:    int   = 30

    # L2 DOM
    l2_poll_interval_ms:       int   = 500
    l2_wall_avg_mult:          float = 5.0    # size ≥ avg × 5.0 = wall

    # EIA
    eia_suppress_before_min:   int   = 15
    eia_suppress_after_min:    int   = 15

    # Scanner
    rebalance_interval_sec:    int   = 300    # 5 minutes
    option_chain_rate_limit_s: float = 3.0    # DhanHQ: 1 call per 3s
    max_subscriptions:         int   = 100
    expiry_roll_days:          int   = 3      # roll when expiry < 3 days

CFG = EngineConfig()
```

***

## `data/duckdb_store.py` — Complete Schema + All Queries

```python
import duckdb
import json
import pickle
import lzma
from pathlib import Path
from datetime import date, datetime
from typing import Optional
import structlog

log = structlog.get_logger()

SCHEMA_SQL = """
-- Tick data (high volume — partition by date in production)
CREATE TABLE IF NOT EXISTS ticks (
    id            BIGINT PRIMARY KEY,
    symbol        VARCHAR NOT NULL,
    underlying    VARCHAR NOT NULL,
    security_id   VARCHAR NOT NULL,
    price         DOUBLE NOT NULL,
    ask_vol       INTEGER NOT NULL,
    bid_vol       INTEGER NOT NULL,
    volume        INTEGER NOT NULL,
    trade_size    INTEGER NOT NULL,
    delta         INTEGER NOT NULL,
    timestamp     TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ticks_symbol_ts ON ticks(symbol, timestamp);

-- Session volume profiles (end-of-day save per underlying)
CREATE TABLE IF NOT EXISTS session_profiles (
    id              BIGINT PRIMARY KEY,
    underlying      VARCHAR NOT NULL,
    session_date    DATE NOT NULL,
    poc             DOUBLE NOT NULL,
    vah             DOUBLE NOT NULL,
    val             DOUBLE NOT NULL,
    total_volume    BIGINT NOT NULL,
    profile_json    JSON NOT NULL,          -- {price: volume} full bucket map
    delta_json      JSON NOT NULL,          -- {price: {buy, sell, net}} delta map
    saved_at        TIMESTAMPTZ NOT NULL,
    UNIQUE(underlying, session_date)
);

-- NPOC tracking
CREATE TABLE IF NOT EXISTS npoc_records (
    id              BIGINT PRIMARY KEY,
    underlying      VARCHAR NOT NULL,
    session_date    DATE NOT NULL,
    poc_price       DOUBLE NOT NULL,
    is_filled       BOOLEAN DEFAULT FALSE,
    filled_at       TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL
);

-- All signals generated
CREATE TABLE IF NOT EXISTS signals (
    id              BIGINT PRIMARY KEY,
    symbol          VARCHAR NOT NULL,
    underlying      VARCHAR NOT NULL,
    strike          DOUBLE NOT NULL,
    option_type     VARCHAR NOT NULL,
    direction       VARCHAR NOT NULL,
    confidence      VARCHAR NOT NULL,
    aggression_score DOUBLE NOT NULL,
    entry_zone      DOUBLE,
    stop_loss       DOUBLE,
    target          DOUBLE,
    risk_reward     DOUBLE,
    market_state    VARCHAR NOT NULL,
    drive_number    INTEGER,
    rationale       TEXT,
    signal_json     JSON NOT NULL,          -- full OutputSchema
    timestamp       TIMESTAMPTZ NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signals_symbol_ts ON signals(symbol, timestamp);

-- Trade records (one row per trade open, updated on close)
CREATE TABLE IF NOT EXISTS trades (
    trade_id        VARCHAR PRIMARY KEY,
    symbol          VARCHAR NOT NULL,
    underlying      VARCHAR NOT NULL,
    direction       VARCHAR NOT NULL,
    entry_price     DOUBLE NOT NULL,
    exit_price      DOUBLE,
    lots            INTEGER NOT NULL,
    stop_loss       DOUBLE NOT NULL,
    target          DOUBLE NOT NULL,
    pnl             DOUBLE,
    pnl_r           DOUBLE,                -- PnL in R multiples
    exit_reason     VARCHAR,               -- TARGET|SL|COUNTER|MANUAL|SESSION_END
    entry_at        TIMESTAMPTZ NOT NULL,
    exit_at         TIMESTAMPTZ,
    drive_number    INTEGER,
    aggression_score DOUBLE,
    add_number      INTEGER DEFAULT 1,     -- 1=base, 2=pyramid1, 3=pyramid2
    parent_trade_id VARCHAR,               -- links pyramid adds to base trade
    session_date    DATE NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trades_symbol_date ON trades(symbol, session_date);

-- Open trades (upserted every state change — crash recovery)
CREATE TABLE IF NOT EXISTS open_trades (
    symbol          VARCHAR PRIMARY KEY,
    entries_json    JSON NOT NULL,          -- list of OpenEntry dicts
    pyramid_count   INTEGER NOT NULL,
    direction       VARCHAR NOT NULL,
    target          DOUBLE NOT NULL,
    snapshot_ts     TIMESTAMPTZ NOT NULL
);

-- Session risk log
CREATE TABLE IF NOT EXISTS session_risk (
    id              BIGINT PRIMARY KEY,
    underlying      VARCHAR NOT NULL,
    session_date    DATE NOT NULL,
    start_equity    DOUBLE NOT NULL,
    end_equity      DOUBLE,
    daily_pnl       DOUBLE,
    daily_pnl_pct   DOUBLE,
    total_trades    INTEGER DEFAULT 0,
    winning_trades  INTEGER DEFAULT 0,
    max_drawdown    DOUBLE DEFAULT 0,
    kill_switch_hit BOOLEAN DEFAULT FALSE,
    kill_reason     VARCHAR,
    UNIQUE(underlying, session_date)
);

-- Economic calendar cache
CREATE TABLE IF NOT EXISTS economic_events (
    id              BIGINT PRIMARY KEY,
    event_name      VARCHAR NOT NULL,
    event_datetime  TIMESTAMPTZ NOT NULL,
    instrument      VARCHAR,               -- NULL = affects all
    suppress_before INTEGER NOT NULL,      -- minutes
    suppress_after  INTEGER NOT NULL       -- minutes
);
"""

class DuckDBStore:
    def __init__(self, db_path: str):
        self.db_path     = db_path
        self._conn:      Optional[duckdb.DuckDBPyConnection] = None
        self._tick_id    = 0
        self._signal_id  = 0

    def connect(self):
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(self.db_path)
        return self

    def initialize_schema(self):
        self._conn.execute(SCHEMA_SQL)
        log.info("schema_initialized", db=self.db_path)

    # ── TICKS ─────────────────────────────────────────────────────────────────
    def save_tick(self, tick, symbol, underlying, security_id):
        self._tick_id += 1
        self._conn.execute("""
            INSERT INTO ticks VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, [self._tick_id, symbol, underlying, security_id,
              tick.price, tick.ask_vol, tick.bid_vol,
              tick.volume, tick.trade_size, tick.delta, tick.timestamp])

    def purge_old_ticks(self, retain_days: int = 1):
        cutoff = f"CURRENT_DATE - INTERVAL '{retain_days} days'"
        deleted = self._conn.execute(
            f"DELETE FROM ticks WHERE timestamp < {cutoff} RETURNING COUNT(*)"
        ).fetchone()[0]
        log.info("ticks_purged", count=deleted)

    # ── SESSION PROFILES ─────────────────────────────────────────────────────
    def save_session_profile(self, underlying: str, session_date: date,
                              poc: float, vah: float, val: float,
                              total_volume: int, profile: dict, delta_profile: dict):
        self._conn.execute("""
            INSERT INTO session_profiles
            (underlying, session_date, poc, vah, val, total_volume,
             profile_json, delta_json, saved_at)
            VALUES (?,?,?,?,?,?,?,?,NOW())
            ON CONFLICT (underlying, session_date) DO UPDATE SET
                poc=excluded.poc, vah=excluded.vah, val=excluded.val,
                total_volume=excluded.total_volume,
                profile_json=excluded.profile_json,
                delta_json=excluded.delta_json,
                saved_at=NOW()
        """, [underlying, session_date, poc, vah, val, total_volume,
              json.dumps(profile), json.dumps(delta_profile)])

    def load_prev_session_profile(self, underlying: str) -> Optional[dict]:
        row = self._conn.execute("""
            SELECT poc, vah, val, total_volume, profile_json, delta_json, session_date
            FROM session_profiles
            WHERE underlying = ?
            ORDER BY session_date DESC
            LIMIT 1
        """, [underlying]).fetchone()
        if not row:
            return None
        return {
            "POC": row[0], "VAH": row [localhost](http://localhost:5190/), "VAL": row[2],
            "total_volume": row[3],
            "profile": json.loads(row[4]),
            "delta_profile": json.loads(row[5]),
            "date": row[6]
        }

    def load_composite_profiles(self, underlying: str,
                                 window: int = 5) -> list[dict]:
        rows = self._conn.execute("""
            SELECT profile_json, session_date
            FROM session_profiles
            WHERE underlying = ?
            ORDER BY session_date DESC
            LIMIT ?
        """, [underlying, window]).fetchall()
        return [{"profile": json.loads(r[0]), "date": r [localhost](http://localhost:5190/)} for r in rows]

    # ── NPOC ─────────────────────────────────────────────────────────────────
    def save_npoc(self, underlying: str, session_date: date, poc_price: float):
        self._conn.execute("""
            INSERT INTO npoc_records (underlying, session_date, poc_price, created_at)
            VALUES (?,?,?,NOW())
        """, [underlying, session_date, poc_price])

    def mark_npoc_filled(self, underlying: str, poc_price: float, tolerance: float):
        self._conn.execute("""
            UPDATE npoc_records
            SET is_filled=TRUE, filled_at=NOW()
            WHERE underlying=? AND is_filled=FALSE
              AND ABS(poc_price - ?) <= ?
        """, [underlying, poc_price, tolerance])

    def get_active_npocs(self, underlying: str, lookback_days: int = 5) -> list[dict]:
        rows = self._conn.execute("""
            SELECT poc_price, session_date
            FROM npoc_records
            WHERE underlying=? AND is_filled=FALSE
              AND session_date >= CURRENT_DATE - INTERVAL ? DAY
            ORDER BY session_date DESC
        """, [underlying, lookback_days]).fetchall()
        return [{"price": r[0], "date": r [localhost](http://localhost:5190/)} for r in rows]

    # ── SIGNALS ──────────────────────────────────────────────────────────────
    def save_signal(self, signal: dict):
        self._signal_id += 1
        self._conn.execute("""
            INSERT INTO signals
            (id, symbol, underlying, strike, option_type, direction,
             confidence, aggression_score, entry_zone, stop_loss, target,
             risk_reward, market_state, drive_number, rationale, signal_json, timestamp)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, [self._signal_id, signal["symbol"], signal["underlying"],
              signal["strike"], signal["option_type"], signal["direction"],
              signal["confidence"], signal["aggression_score"],
              signal.get("entry_zone"), signal.get("stop_loss"),
              signal.get("target"), signal.get("risk_reward"),
              signal["market_state"], signal.get("drive_number"),
              signal.get("rationale"), json.dumps(signal),
              signal["timestamp"]])

    # ── TRADES ───────────────────────────────────────────────────────────────
    def save_trade_open(self, trade: dict):
        self._conn.execute("""
            INSERT INTO trades
            (trade_id, symbol, underlying, direction, entry_price,
             lots, stop_loss, target, entry_at, drive_number,
             aggression_score, add_number, parent_trade_id, session_date)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, [trade["trade_id"], trade["symbol"], trade["underlying"],
              trade["direction"], trade["entry_price"], trade["lots"],
              trade["stop_loss"], trade["target"], trade["entry_at"],
              trade.get("drive_number"), trade.get("aggression_score"),
              trade.get("add_number", 1), trade.get("parent_trade_id"),
              date.today()])

    def save_trade_close(self, trade_id: str, exit_price: float,
                          pnl: float, pnl_r: float, exit_reason: str):
        self._conn.execute("""
            UPDATE trades
            SET exit_price=?, pnl=?, pnl_r=?, exit_reason=?, exit_at=NOW()
            WHERE trade_id=?
        """, [exit_price, pnl, pnl_r, exit_reason, trade_id])

    # ── OPEN TRADE RECOVERY ──────────────────────────────────────────────────
    def upsert_open_trade(self, symbol: str, data: dict):
        self._conn.execute("""
            INSERT INTO open_trades (symbol, entries_json, pyramid_count,
                                     direction, target, snapshot_ts)
            VALUES (?,?,?,?,?,NOW())
            ON CONFLICT (symbol) DO UPDATE SET
                entries_json=excluded.entries_json,
                pyramid_count=excluded.pyramid_count,
                direction=excluded.direction,
                target=excluded.target,
                snapshot_ts=NOW()
        """, [symbol, json.dumps(data["entries"]),
              data["pyramid_count"], data["direction"], data["target"]])

    def load_open_trade(self, symbol: str) -> Optional[dict]:
        row = self._conn.execute(
            "SELECT entries_json, pyramid_count, direction, target FROM open_trades WHERE symbol=?",
            [symbol]
        ).fetchone()
        if not row:
            return None
        return {
            "entries":       json.loads(row[0]),
            "pyramid_count": row [localhost](http://localhost:5190/),
            "direction":     row[2],
            "target":        row[3]
        }

    def clear_open_trade(self, symbol: str):
        self._conn.execute("DELETE FROM open_trades WHERE symbol=?", [symbol])

    # ── SESSION RISK ─────────────────────────────────────────────────────────
    def save_session_risk(self, underlying: str, summary: dict):
        self._conn.execute("""
            INSERT INTO session_risk
            (underlying, session_date, start_equity, end_equity, daily_pnl,
             daily_pnl_pct, total_trades, winning_trades, max_drawdown,
             kill_switch_hit, kill_reason)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT (underlying, session_date) DO UPDATE SET
                end_equity=excluded.end_equity,
                daily_pnl=excluded.daily_pnl,
                daily_pnl_pct=excluded.daily_pnl_pct,
                total_trades=excluded.total_trades,
                winning_trades=excluded.winning_trades,
                max_drawdown=excluded.max_drawdown,
                kill_switch_hit=excluded.kill_switch_hit,
                kill_reason=excluded.kill_reason
        """, [underlying, date.today(),
              summary["start_equity"], summary["end_equity"],
              summary["daily_pnl"], summary["daily_pnl_pct"],
              summary["total_trades"], summary["winning_trades"],
              summary["max_drawdown"], summary["kill_switch_hit"],
              summary.get("kill_reason")])

    # ── ECONOMIC CALENDAR ────────────────────────────────────────────────────
    def save_economic_event(self, event_name: str, event_datetime: datetime,
                             instrument: Optional[str],
                             suppress_before: int, suppress_after: int):
        self._conn.execute("""
            INSERT INTO economic_events
            (event_name, event_datetime, instrument, suppress_before, suppress_after)
            VALUES (?,?,?,?,?)
        """, [event_name, event_datetime, instrument, suppress_before, suppress_after])

    def get_suppression_events(self, now: datetime) -> list[dict]:
        rows = self._conn.execute("""
            SELECT event_name, event_datetime, instrument,
                   suppress_before, suppress_after
            FROM economic_events
            WHERE event_datetime BETWEEN
                ? - INTERVAL '2 hours' AND ? + INTERVAL '2 hours'
        """, [now, now]).fetchall()
        return [{"name": r[0], "dt": r [localhost](http://localhost:5190/), "instrument": r[2],
                 "before": r[3], "after": r[4]} for r in rows]
```

***

## `strategy/pipeline.py` — Master 12-Gate Pipeline

```python
import asyncio
from datetime import datetime
from dataclasses import dataclass
from typing import Optional
import structlog

from core.symbol_state import SymbolState
from core.tick_processor import Tick
from core.session_manager import SessionManager
from profile.underlying_profile_router import UnderlyingProfileRouter
from profile.profile_selector import ProfileSelector
from profile.node_detector import NodeDetector
from orderflow.cvd_engine import CVDEngine
from orderflow.footprint_engine import FootprintEngine
from orderflow.bubble_detector import BubbleDetector
from orderflow.absorption_detector import AbsorptionDetector
from orderflow.big_trade_detector import BigTradeDetector
from orderflow.ofi_calculator import calc_ofi
from orderflow.l2_monitor import L2Monitor
from strategy.market_state_engine import MarketStateEngine
from strategy.anomaly_detector import AnomalyDetector
from strategy.drive_tracker import DriveTracker
from strategy.aggression_scorer import AggressionScorer
from strategy.trade_constructor import TradeConstructor
from strategy.rationale_generator import RationaleGenerator
from risk.session_risk_manager import SessionRiskManager
from risk.position_sizer import PositionSizer
from trade_management.partition_exit_manager import PartitionExitManager
from trade_management.pyramid_manager import PyramidManager
from trade_management.breakeven_manager import BreakevenManager
from trade_management.counter_aggression import CounterAggressionDetector
from output.signal_formatter import SignalFormatter
from output.schema import OutputSchema
from data.duckdb_store import DuckDBStore
from data.economic_calendar import EconomicCalendar
from alerts.alert_manager import AlertManager
from config.engine_config import CFG
import time

log = structlog.get_logger()

class StrategyEngine:

    def __init__(self, db: DuckDBStore,
                 profile_router: UnderlyingProfileRouter,
                 publisher, account_equity: float):
        self.db             = db
        self.profile_router = profile_router
        self.publisher      = publisher
        self.equity         = account_equity
        self.calendar       = EconomicCalendar(db)
        self.formatter      = SignalFormatter()

    async def symbol_pipeline(self, security_id: str,
                               state: SymbolState,
                               queue: asyncio.Queue):
        """One coroutine per symbol — runs forever, processes ticks."""
        while True:
            tick: Tick = await queue.get()
            t0 = time.monotonic()
            try:
                signal = await self.process_tick(tick, state)
                if signal:
                    latency_ms = (time.monotonic() - t0) * 1000
                    log.info("signal_emitted",
                             symbol=state.symbol,
                             direction=signal.direction,
                             latency_ms=round(latency_ms, 1))
                    await self.publisher.broadcast_signal(signal.dict())
                    self.db.save_signal(signal.dict())
            except Exception as e:
                log.error("pipeline_error", symbol=state.symbol, error=str(e))
            finally:
                queue.task_done()

    async def process_tick(self, tick: Tick,
                            state: SymbolState) -> Optional[OutputSchema]:
        """
        The 12-gate pipeline.
        Returns OutputSchema for EVERY tick (FLAT, WAIT, TRADE, etc.)
        Only TRADE actions are broadcast and saved.
        """
        cfg  = CFG
        sym  = state.symbol
        inst = state.instrument_config

        # ── Update buffers (always, regardless of gates) ──────────────────────
        state.tick_buffer.append(tick)
        state.last_tick_ts = tick.timestamp
        state.data_quality = "LIVE"

        # Update underlying profile via shared router
        underlying_price = state.underlying_ltp or tick.price  # updated from chain data
        self.profile_router.update(tick, state.underlying, underlying_price)

        # Update order flow engines
        state.cvd_engine.append(tick)
        candle = state.candle_builder.update(tick)

        on_candle_close = candle is not None
        if on_candle_close:
            state.candle_buffer.append(candle)
            state.footprint_engine.finalize_candle(candle)
            state.bubble_detector.update(state.footprint_engine.history)
            state._refresh_indicators(candle)  # ATR, AvgVol, OFI, VWAP

        # ── OPEN TRADE MANAGEMENT (runs first if in a trade) ──────────────────
        if state.open_entries:
            mgmt_action = await self._manage_open_trade(tick, state)
            if mgmt_action:
                return mgmt_action

        # ══════════════════════════════════════════════════════════════════════
        #  12-GATE SIGNAL PIPELINE
        # ══════════════════════════════════════════════════════════════════════

        # ── GATE 0: Time filter ───────────────────────────────────────────────
        session_mgr = SessionManager(inst)
        time_status = session_mgr.classify_time(tick.timestamp)

        if time_status in ("WARMUP", "DEAD_ZONE", "OUTSIDE_SESSION"):
            return self.formatter.flat(sym, f"TIME_{time_status}", state)

        # ── GATE 1: Data quality ──────────────────────────────────────────────
        if state.data_quality == "STALE":
            return self.formatter.flat(sym, "DATA_STALE", state)

        # ── GATE 2: Session risk ──────────────────────────────────────────────
        can_trade, risk_reason = state.risk_manager.can_trade()
        if not can_trade:
            return self.formatter.flat(sym, risk_reason, state)

        # ── GATE 3: EIA / Economic suppression ───────────────────────────────
        if self.calendar.is_suppression_window(tick.timestamp, state.underlying):
            return self.formatter.flat(sym, "EIA_SUPPRESSION_WINDOW", state)

        # Need at least 1 full candle for any analysis
        if len(state.candle_buffer) < 2:
            return self.formatter.flat(sym, "INSUFFICIENT_DATA", state)

        # ── Pull profile data for this underlying ─────────────────────────────
        prof_engine  = self.profile_router.get_engine(state.underlying)
        session_va   = prof_engine.get_value_area("session")
        prev_va      = state.prev_session_va
        delta_prof   = prof_engine.get_delta_profile("session")

        if not session_va:
            return self.formatter.flat(sym, "PROFILE_BUILDING", state)

        current_price = tick.price

        # ── GATE 4: Market state ──────────────────────────────────────────────
        market_state, balance_zone = MarketStateEngine.detect(
            current_price, session_va, prev_va,
            state.atr, list(state.candle_buffer), inst.tick_size
        )

        if market_state == "NO_TRADE":
            return self.formatter.flat(sym, "POC_DEAD_ZONE", state,
                                        market_state=market_state)
        if market_state == "PROBING":
            return self.formatter.wait(sym, "UNCONFIRMED_BREAK", state,
                                        market_state=market_state)

        # ── PARALLEL COMPUTE (runs on candle close) ───────────────────────────
        if on_candle_close:
            anomaly       = AnomalyDetector.detect(current_price, session_va, prev_va)
            npocs         = self.db.get_active_npocs(state.underlying)
            composite     = self.profile_router.get_composite(state.underlying)
            weekly_bias   = composite.apply_weekly_bias_filter(
                                self._infer_direction(market_state, balance_zone),
                                current_price) if composite else None
            state.last_anomaly   = anomaly
            state.active_npocs   = npocs
            state.weekly_bias    = weekly_bias

        anomaly     = getattr(state, "last_anomaly", None)
        npocs       = getattr(state, "active_npocs", [])
        weekly_bias = getattr(state, "weekly_bias", None)

        # ── GATE 5: Profile + key level ───────────────────────────────────────
        lvns = NodeDetector.detect_lvns(
            prof_engine.get_active_profile(),
            cfg.lvn_threshold_pct
        )
        active_profile, key_level, direction = ProfileSelector.select(
            market_state   = market_state,
            balance_zone   = balance_zone,
            current_price  = current_price,
            session_va     = session_va,
            lvns           = lvns,
            tick_size      = inst.tick_size
        )

        if not key_level or not direction:
            return self.formatter.flat(sym, "NO_KEY_LEVEL", state,
                                        market_state=market_state)

        # ── GATE 6: Price in entry zone ───────────────────────────────────────
        dist_ticks = abs(current_price - key_level) / inst.tick_size
        if dist_ticks > cfg.level_touch_ticks:
            # Set alert for return to level
            state.alert_manager.set_price_alert(
                symbol=sym, price=key_level, direction=direction,
                level_type=active_profile, tick_size=inst.tick_size
            )
            return self.formatter.wait(sym, "PRICE_NOT_AT_LEVEL", state,
                                        market_state=market_state,
                                        key_level=key_level, dist_ticks=dist_ticks)

        # ── GATE 7: Drive classification ──────────────────────────────────────
        drive_result = state.drive_tracker.classify_drive(
            current_price = current_price,
            key_level     = key_level,
            direction     = direction,
            candles       = list(state.candle_buffer),
            atr           = state.atr,
            cvd_engine    = state.cvd_engine,
            tick_size     = inst.tick_size
        )

        if drive_result.drive_number == 1:
            return self.formatter.wait(sym, "FIRST_DRIVE_RECORDED", state,
                                        market_state=market_state,
                                        drive_number=1, key_level=key_level)
        if not drive_result.entry_valid:
            reason = "DRIVE_NO_REJECTION" if drive_result.drive_number == 2 \
                     else "LEVEL_EXHAUSTED"
            return self.formatter.flat(sym, reason, state,
                                        market_state=market_state,
                                        drive_number=drive_result.drive_number)

        # ── GATE 8: Aggression score ──────────────────────────────────────────
        aggr = AggressionScorer.score(
            direction      = direction,
            current_price  = current_price,
            key_level      = key_level,
            tick_size      = inst.tick_size,
            candles        = list(state.candle_buffer),
            cvd_engine     = state.cvd_engine,
            footprint      = state.footprint_engine.last_candle,
            bubble_result  = state.bubble_detector.last_result,
            absorption     = AbsorptionDetector.detect(
                                 state.candle_buffer[-1], state.atr, state.avg_vol),
            big_trade      = state.big_trade_detector.detect_cluster(
                                 key_level, inst.tick_size),
            ofi            = state.ofi,
            delta_profile  = delta_prof,
            anomaly        = anomaly,
            weekly_bias    = weekly_bias,
            cfg            = cfg
        )

        if not aggr.confirmed:
            return self.formatter.wait(sym, "AGGRESSION_INSUFFICIENT", state,
                                        score=aggr.score,
                                        market_state=market_state)

        # ── GATE 9: Cushion quality ───────────────────────────────────────────
        setup = TradeConstructor.build(
            direction      = direction,
            entry_zone     = key_level,
            current_price  = current_price,
            session_va     = session_va,
            prev_va        = prev_va,
            npocs          = npocs,
            candles        = list(state.candle_buffer),
            cvd_engine     = state.cvd_engine,
            big_trade      = state.big_trade_detector.detect_cluster(
                                 key_level, inst.tick_size),
            tick_size      = inst.tick_size,
            drive_result   = drive_result,
            aggr           = aggr
        )

        if setup.cushion_quality == "INVALID":
            return self.formatter.flat(sym, "CUSHION_INVALID", state,
                                        sl_ticks=setup.sl_ticks)

        # ── GATE 10: R:R ─────────────────────────────────────────────────────
        if setup.risk_reward < cfg.min_risk_reward:
            return self.formatter.flat(sym, "RR_INSUFFICIENT", state,
                                        rr=setup.risk_reward)

        # ── GATE 11: Position sizing + risk budget ────────────────────────────
        lots, risk_amount, risk_pct = PositionSizer.calculate(
            equity         = self.equity,
            entry          = setup.entry_zone,
            stop           = setup.stop_loss,
            point_value    = inst.point_value,
            lot_size       = inst.lot_size,
            cushion_quality= setup.cushion_quality,
            risk_manager   = state.risk_manager,
            cfg            = cfg
        )
        if lots == 0:
            return self.formatter.flat(sym, "ZERO_LOTS_COMPUTED", state)

        # ── GATE 12: OI wall check ────────────────────────────────────────────
        oi_check = state.last_oi_data.get(str(int(inst.strike)), {}) \
                        .get(direction.lower(), {})
        oi_pressure = oi_check.get("pressure", "LOW")
        # Not a hard gate — reduces confidence only

        # ══════════════════════════════════════════════════════════════════════
        #  ALL GATES PASSED → BUILD TRADE SIGNAL
        # ══════════════════════════════════════════════════════════════════════

        rationale = RationaleGenerator.generate(
            market_state   = market_state,
            balance_zone   = balance_zone,
            direction      = direction,
            drive_number   = drive_result.drive_number,
            aggr           = aggr,
            setup          = setup,
            anomaly        = anomaly,
            weekly_bias    = weekly_bias,
            oi_pressure    = oi_pressure
        )

        signal = self.formatter.trade(
            state          = state,
            tick           = tick,
            market_state   = market_state,
            balance_zone   = balance_zone,
            session_va     = session_va,
            active_profile = active_profile,
            drive_result   = drive_result,
            aggr           = aggr,
            setup          = setup,
            lots           = lots,
            risk_amount    = risk_amount,
            risk_pct       = risk_pct,
            rationale      = rationale,
            oi_pressure    = oi_pressure,
            anomaly        = anomaly,
            npocs          = npocs
        )

        return signal

    # ── OPEN TRADE MANAGEMENT ─────────────────────────────────────────────────
    async def _manage_open_trade(self, tick: Tick,
                                  state: SymbolState) -> Optional[OutputSchema]:
        inst = state.instrument_config

        # 1. Counter-aggression hard exit
        counter = CounterAggressionDetector.check(
            direction   = state.open_entries[0].direction,
            candles     = list(state.candle_buffer),
            cvd_engine  = state.cvd_engine,
            footprint   = state.footprint_engine.last_candle,
            atr         = state.atr
        )
        if counter.exit_all:
            return await self._execute_exit_all(
                tick, state, "COUNTER_AGGRESSION", counter.reason)

        # 2. SL hit check
        for entry in state.open_entries:
            sl_hit = (entry.direction == "LONG"  and tick.price <= entry.stop_loss) or \
                     (entry.direction == "SHORT" and tick.price >= entry.stop_loss)
            if sl_hit:
                return await self._execute_exit_all(
                    tick, state, "STOP_LOSS_HIT",
                    f"SL hit at {tick.price}")

        # 3. Breakeven
        BreakevenManager.check_and_update(tick.price, state, CFG)

        # 4. Partition exits
        partition_actions = PartitionExitManager.check(
            tick=tick, state=state, cfg=CFG)
        if partition_actions:
            for action in partition_actions:
                await self._execute_partition_action(action, tick, state)
            self.db.upsert_open_trade(state.symbol, state.to_open_trade_dict())

        # 5. Pyramid
        if state.pyramid_count < CFG.pyramid_max_adds:
            pyramid = PyramidManager.check(tick, state, CFG)
            if pyramid.add:
                await self._execute_pyramid_add(pyramid, tick, state)

        return None  # No output schema for management actions — broadcast separately

    def _infer_direction(self, market_state: str, balance_zone: str) -> str:
        if balance_zone == "NEAR_VAL":  return "LONG"
        if balance_zone == "NEAR_VAH":  return "SHORT"
        if market_state == "IMBALANCED_UP":   return "LONG"
        if market_state == "IMBALANCED_DOWN": return "SHORT"
        return "FLAT"
```

***

## `output/schema.py` — Complete Pydantic OutputSchema

```python
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

class PartitionPlan(BaseModel):
    lots:      int
    pct:       float
    target:    Optional[float] = None
    condition: str

class TradeManagementPlan(BaseModel):
    stage_1:   str    # "Exit 30% at 33% R if momentum weak"
    stage_2:   str    # "Exit 50% at target (session POC) — always"
    stage_3:   str    # "Trail 20% if CVD strong, else exit with P2"
    hard_exit: str    # "Exit ALL on 2+ counter-aggression signals"

class PyramidPlan(BaseModel):
    level:     float
    direction: str
    lots:      int
    condition: str

class OutputSchema(BaseModel):
    # Identity
    symbol:              str
    underlying:          str
    strike:              float
    option_type:         str           # CE | PE
    security_id:         str
    expiry:              str
    segment:             str
    timestamp:           datetime

    # Decision
    action:              str           # TRADE | WAIT | FLAT | SESSION_STOPPED | etc.
    direction:           str           # LONG | SHORT | FLAT
    confidence:          str           # High | Medium | Low | -
    no_trade_reason:     Optional[str] = None

    # Market context
    market_state:        str           # BALANCED | IMBALANCED | PROBING | NO_TRADE
    balance_zone:        Optional[str] = None  # NEAR_VAH | NEAR_VAL | NEAR_POC
    anomaly_type:        Optional[str] = None  # ABOVE | BELOW | DOUBLE
    weekly_bias:         Optional[str] = None  # LONG | SHORT | NEUTRAL
    oi_pressure:         str = "LOW"           # LOW | MEDIUM | HIGH

    # Profile
    session_poc:         Optional[float] = None
    session_vah:         Optional[float] = None
    session_val:         Optional[float] = None
    prev_poc:            Optional[float] = None
    active_profile:      str = "NONE"  # SESSION | LEG | COMBINED | NONE
    nearest_npoc_above:  Optional[float] = None
    nearest_npoc_below:  Optional[float] = None

    # Drive
    drive_number:        Optional[int] = None
    drive_rejected:      Optional[bool] = None

    # Trade setup
    entry_zone:          Optional[float] = None
    stop_loss:           Optional[float] = None
    sl_ticks:            Optional[int] = None
    cushion_quality:     Optional[str] = None
    target:              Optional[float] = None
    invalidation:        Optional[float] = None
    break_even_at:       Optional[float] = None
    risk_reward:         Optional[float] = None

    # Sizing
    lots:                Optional[int] = None
    risk_amount:         Optional[float] = None
    risk_pct:            Optional[float] = None

    # Aggression
    aggression_score:    Optional[float] = None
    aggression_signals:  List[str] = Field(default_factory=list)
    score_breakdown:     dict = Field(default_factory=dict)

    # Order flow
    cvd_current:         Optional[float] = None
    cvd_slope:           Optional[float] = None
    cvd_divergence:      Optional[bool] = None
    footprint_score:     Optional[float] = None
    absorption_detected: Optional[bool] = None
    big_trade_cluster:   Optional[bool] = None
    volume_bubble:       Optional[str] = None  # BUY | SELL | NEUTRAL
    delta_zone_type:     Optional[str] = None  # HIGH_BUY_DELTA | HIGH_SELL_DELTA
    ofi:                 Optional[float] = None
    vwap:                Optional[float] = None
    ib_high:             Optional[float] = None
    ib_low:              Optional[float] = None
    ib_break:            Optional[bool] = None

    # Session risk
    session_pnl:         Optional[float] = None
    session_pnl_pct:     Optional[float] = None
    consecutive_losses:  Optional[int] = None
    trades_today:        Optional[int] = None

    # Trade management plans
    partition_plan:      Optional[dict] = None
    trade_management:    Optional[TradeManagementPlan] = None
    pyramid_plan:        Optional[PyramidPlan] = None

    # Rationale
    rationale:           Optional[str] = None
    latency_ms:          Optional[float] = None
```

***

## `api/main.py` — FastAPI App

```python
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio, structlog

log = structlog.get_logger()

def create_api_app(publisher) -> FastAPI:

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log.info("api_startup")
        yield
        log.info("api_shutdown")

    app = FastAPI(title="GlassyTrade AI", version="1.0.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["*"],
                       allow_methods=["*"], allow_headers=["*"])

    # Mount routers
    from api.routers import signals, profiles, risk, trades, config_router
    app.include_router(signals.router,        prefix="/api")
    app.include_router(profiles.router,       prefix="/api")
    app.include_router(risk.router,           prefix="/api")
    app.include_router(trades.router,         prefix="/api")
    app.include_router(config_router.router,  prefix="/api")

    # Connected WebSocket clients
    clients: list[WebSocket] = []

    @app.get("/health")
    async def health():
        return {"status": "ok", "clients": len(clients)}

    @app.websocket("/ws/signals")
    async def ws_signals(ws: WebSocket):
        await ws.accept()
        clients.append(ws)
        log.info("ws_client_connected", total=len(clients))
        try:
            # Heartbeat + signal broadcast loop
            while True:
                msg = await asyncio.wait_for(
                    publisher.queue.get(), timeout=5.0
                )
                # Broadcast to all connected clients
                dead = []
                for client in clients:
                    try:
                        await client.send_json(msg)
                    except Exception:
                        dead.append(client)
                for d in dead:
                    clients.remove(d)
        except asyncio.TimeoutError:
            # Send heartbeat
            try:
                await ws.send_json({
                    "type": "HEARTBEAT",
                    "ts":   str(asyncio.get_event_loop().time())
                })
            except Exception:
                pass
        except WebSocketDisconnect:
            clients.remove(ws)
            log.info("ws_client_disconnected", remaining=len(clients))

    return app
```

***

## `frontend/src/hooks/useWebSocket.ts`

```typescript
import { useEffect, useRef } from 'react'
import { useSignalStore } from '../stores/signalStore'
import { useRiskStore } from '../stores/riskStore'

const WS_URL = 'ws://localhost:8000/ws/signals'
const RECONNECT_MS = 3000

export function useWebSocket() {
  const ws = useRef<WebSocket | null>(null)
  const updateSignal  = useSignalStore(s => s.updateSignal)
  const updateTrade   = useSignalStore(s => s.updateTrade)
  const updateState   = useSignalStore(s => s.updateMarketState)
  const handleRisk    = useRiskStore(s => s.handleEvent)
  const setQuality    = useSignalStore(s => s.setDataQuality)

  const connect = () => {
    ws.current = new WebSocket(WS_URL)

    ws.current.onmessage = (e) => {
      const msg = JSON.parse(e.data)
      switch (msg.type) {
        case 'SIGNAL':        updateSignal(msg.data.symbol, msg.data); break
        case 'TRADE_UPDATE':  updateTrade(msg.trade_id, msg.action, msg); break
        case 'STATE_CHANGE':  updateState(msg.symbol, msg.from, msg.to); break
        case 'RISK_EVENT':    handleRisk(msg); break
        case 'DATA_QUALITY':  setQuality(msg.symbol, msg.quality); break
        case 'DRIVE_ALERT':
          // Show toast notification
          console.log(`🎯 Drive ${msg.drive} at ${msg.level} for ${msg.symbol}`)
          break
        case 'HEARTBEAT': break   // connection alive
      }
    }

    ws.current.onclose = () => {
      setTimeout(connect, RECONNECT_MS)  // auto-reconnect
    }
  }

  useEffect(() => {
    connect()
    return () => ws.current?.close()
  }, [])
}
```

***

## `frontend/src/stores/signalStore.ts`

```typescript
import { create } from 'zustand'
import { subscribeWithSelector } from 'zustand/middleware'

interface SignalRow {
  symbol:          string
  underlying:      string
  strike:          number
  option_type:     string
  direction:       string
  confidence:      string
  aggression_score?: number
  market_state:    string
  drive_number?:   number
  entry_zone?:     number
  stop_loss?:      number
  target?:         number
  risk_reward?:    number
  rationale?:      string
  data_quality:    string
  last_updated:    number
}

interface SignalStore {
  signals:         Record<string, SignalRow>
  updateSignal:    (symbol: string, data: any) => void
  updateTrade:     (tradeId: string, action: string, data: any) => void
  updateMarketState: (symbol: string, from: string, to: string) => void
  setDataQuality:  (symbol: string, quality: string) => void
  getActiveSignals: () => SignalRow[]
}

export const useSignalStore = create<SignalStore>()(
  subscribeWithSelector((set, get) => ({
    signals: {},

    updateSignal: (symbol, data) => set(state => ({
      signals: {
        ...state.signals,
        [symbol]: { ...state.signals[symbol], ...data, last_updated: Date.now() }
      }
    })),

    updateTrade: (tradeId, action, data) => {
      // Update relevant signal row
      set(state => {
        const sym = data.symbol
        if (!sym || !state.signals[sym]) return state
        return {
          signals: {
            ...state.signals,
            [sym]: { ...state.signals[sym], trade_action: action, last_updated: Date.now() }
          }
        }
      })
    },

    updateMarketState: (symbol, from, to) => set(state => ({
      signals: {
        ...state.signals,
        [symbol]: { ...state.signals[symbol], market_state: to, last_updated: Date.now() }
      }
    })),

    setDataQuality: (symbol, quality) => set(state => ({
      signals: {
        ...state.signals,
        [symbol]: { ...state.signals[symbol], data_quality: quality }
      }
    })),

    getActiveSignals: () =>
      Object.values(get().signals)
        .filter(s => s.direction !== 'FLAT')
        .sort((a, b) => (b.aggression_score ?? 0) - (a.aggression_score ?? 0))
  }))
)
```

***

## `.env.example`

```bash
# Exchange
EXCHANGE_MODE=MCX              # NSE or MCX

# DhanHQ
DHAN_ACCESS_TOKEN=your_token
DHAN_CLIENT_ID=your_id
DHAN_WS_URL=wss://api-feed.dhan.co
DHAN_REST_URL=https://api.dhan.co

# Account
ACCOUNT_EQUITY=500000

# Risk
RISK_PER_TRADE_PCT=0.005
MAX_DAILY_LOSS_PCT=0.020
MAX_CONSECUTIVE_LOSSES=3
MAX_DRAWDOWN_PCT=0.030

# Database
DB_PATH=./data/db/glasstrade.db
TICK_RETENTION_DAYS=1

# Notifications
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json

# Frontend
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000/ws/signals
```



# GlassyTrade AI — Coding Agent Build Instructions

Every instruction is atomic, testable, and unambiguous. No interpretation required.

***

## HOW TO USE THESE INSTRUCTIONS

```
Each module has:
  TASK:        What to build — exact behavior, no ambiguity
  INPUTS:      What it receives
  OUTPUTS:     What it must return
  RULES:       Non-negotiable constraints
  TEST:        Exact assertion to verify correctness before moving on

DO NOT proceed to next module until current module's TEST passes.
DO NOT add any feature not listed in TASK.
DO NOT use any library not listed in tech stack.
```

***

## PHASE 0 — Project Setup

***

### INSTRUCTION 000 — Repository Structure

**TASK:**
Create the following exact folder structure. Every folder must have an `__init__.py`. No extra folders.

```
glasstrade/
├── engine/
│   ├── core/
│   ├── profile/
│   ├── orderflow/
│   ├── strategy/
│   ├── risk/
│   ├── trade_management/
│   ├── data/
│   ├── output/
│   ├── alerts/
│   ├── config/
│   ├── backtest/
│   └── tests/
│       ├── unit/
│       ├── integration/
│       └── performance/
├── api/
│   └── routers/
├── frontend/
│   └── src/
│       ├── components/
│       ├── stores/
│       └── hooks/
├── scripts/
├── data/
│   ├── db/
│   └── snapshots/
└── logs/
```

**RULES:**
- Python version: 3.12 exactly
- Use `uv` for package management, not pip
- Install packages from `pyproject.toml` only — no ad-hoc installs
- Node version: 20 LTS

**TEST:**
Run `find engine -name "__init__.py" | wc -l` — must return exactly 11.
Run `python --version` — must show 3.12.x.

***

### INSTRUCTION 001 — `pyproject.toml`

**TASK:**
Create `engine/pyproject.toml` with exactly these dependencies and no others:

```
uvloop==0.21.0
websockets==13.1
aiohttp==3.11.0
numpy==2.2.0
pandas==2.2.0
orjson==3.10.0
fastapi==0.115.0
uvicorn[standard]==0.34.0
pydantic==2.10.0
duckdb==1.2.0
python-dotenv==1.0.0
structlog==25.1.0
prometheus-client==0.21.0
aiosmtplib==3.0.0
pytest==8.3.0
pytest-asyncio==0.25.0
plotly==6.0.0
```

**TEST:**
Run `uv sync` — must complete with zero errors.
Run `python -c "import uvloop, websockets, duckdb, fastapi, pydantic"` — must not raise ImportError.

***

## PHASE 1 — Config Layer

***

### INSTRUCTION 002 — `config/engine_config.py`

**TASK:**
Create a frozen dataclass `EngineConfig` with a module-level singleton `CFG = EngineConfig()`.
Every threshold used anywhere in the system must live here and only here.
No magic numbers anywhere else in the codebase — always import from `CFG`.

**EXACT VALUES TO SET:**

| Field | Value |
|---|---|
| `value_area_pct` | 0.70 |
| `lvn_threshold_pct` | 0.15 |
| `hvn_threshold_pct` | 2.00 |
| `lvn_score_thinness_wt` | 0.60 |
| `lvn_score_midpoint_wt` | 0.40 |
| `leg_displacement_atr_mult` | 1.5 |
| `leg_volume_avg_mult` | 1.5 |
| `cvd_slope_window` | 20 |
| `cvd_divergence_lookback` | 5 |
| `cvd_strong_slope` | 2.0 |
| `footprint_imbalance_ratio` | 3.0 |
| `footprint_imbalance_pct` | 0.40 |
| `bubble_sigma_threshold` | 2.0 |
| `bubble_window` | 21 |
| `absorption_atr_mult` | 0.30 |
| `absorption_vol_mult` | 2.00 |
| `big_trade_size_mult` | 5.00 |
| `big_trade_cluster_min` | 3 |
| `big_trade_tick_range` | 2 |
| `ofi_window` | 10 |
| `ofi_long_threshold` | 0.10 |
| `ofi_short_threshold` | -0.10 |
| `poc_dead_zone_ticks` | 2 |
| `level_touch_ticks` | 3 |
| `min_aggression_score` | 2.0 |
| `pyramid_aggression_score` | 3.0 |
| `score_footprint` | 1.0 |
| `score_cvd` | 1.0 |
| `score_big_trade` | 1.0 |
| `score_absorption` | 0.5 |
| `score_ofi` | 0.5 |
| `score_bubble` | 0.5 |
| `score_delta_zone` | 0.5 |
| `score_combined_confluence` | 0.5 |
| `score_anomaly_bonus` | 0.5 |
| `score_weekly_bias` | 0.5 |
| `cushion_excellent_ticks` | 3 |
| `cushion_acceptable_ticks` | 6 |
| `cushion_wide_ticks` | 10 |
| `cushion_invalid_ticks` | 10 |
| `min_risk_reward` | 1.5 |
| `p1_r_threshold` | 0.33 |
| `p1_lots_pct` | 0.30 |
| `p2_lots_pct` | 0.50 |
| `p3_lots_pct` | 0.20 |
| `breakeven_r_threshold` | 0.35 |
| `p3_trail_cvd_min` | 2.0 |
| `p3_trail_factor` | 0.40 |
| `pyramid_max_adds` | 2 |
| `pyramid_risk_ceiling_mult` | 1.5 |
| `risk_per_trade_pct` | 0.005 |
| `max_daily_loss_pct` | 0.020 |
| `max_consecutive_losses` | 3 |
| `max_drawdown_pct` | 0.030 |
| `max_risk_per_trade_pct` | 0.010 |
| `delta_zone_sigma_mult` | 2.5 |
| `composite_session_window` | 5 |
| `dead_zone_start` | "12:00" |
| `dead_zone_end` | "13:30" |
| `stale_tick_gap_seconds` | 30 |
| `l2_poll_interval_ms` | 500 |
| `l2_wall_avg_mult` | 5.0 |
| `eia_suppress_before_min` | 15 |
| `eia_suppress_after_min` | 15 |
| `rebalance_interval_sec` | 300 |
| `option_chain_rate_limit_s` | 3.0 |
| `max_subscriptions` | 100 |
| `expiry_roll_days` | 3 |

**RULES:**
- `frozen=True` on the dataclass — no mutation after init
- `CFG` is a module-level singleton — `from config.engine_config import CFG`

**TEST:**
```python
from config.engine_config import CFG
assert CFG.value_area_pct == 0.70
assert CFG.min_aggression_score == 2.0
assert CFG.max_daily_loss_pct == 0.020
```

***

### INSTRUCTION 003 — `config/instruments.py`

**TASK:**
Create `InstrumentConfig` frozen dataclass and `INSTRUMENTS` dict with exactly these 5 instruments:
`NATURALGAS`, `CRUDEOIL`, `GOLD`, `NIFTY`, `BANKNIFTY`.

Also create:
- `ExchangeMode` enum with `NSE` and `MCX`
- `get_instrument(name: str) -> InstrumentConfig` — raises `ValueError` if not found
- `get_instruments_by_mode(mode: ExchangeMode) -> list[InstrumentConfig]`

**EXACT INSTRUMENT VALUES:**

| Field | NATURALGAS | CRUDEOIL | GOLD | NIFTY | BANKNIFTY |
|---|---|---|---|---|---|
| `security_id` | 428199 | 428214 | 428219 | 13 | 25 |
| `segment` | MCX_COMM | MCX_COMM | MCX_COMM | NSE_FNO | NSE_FNO |
| `strike_step` | 10.0 | 100.0 | 100.0 | 50.0 | 100.0 |
| `tick_size` | 0.10 | 1.0 | 1.0 | 0.05 | 0.05 |
| `lot_size` | 1250 | 100 | 100 | 75 | 30 |
| `point_value` | 125.0 | 100.0 | 100.0 | 75.0 | 30.0 |
| `atm_range` | 3 | 3 | 3 | 5 | 5 |
| `big_trade_threshold` | 50 | 20 | 10 | 500 | 300 |
| `profile_bucket_size` | 0.10 | 1.0 | 1.0 | 5.0 | 10.0 |
| `session_open` | "09:00" | "09:00" | "09:00" | "09:15" | "09:15" |
| `session_close` | "23:30" | "23:30" | "23:30" | "15:30" | "15:30" |
| `warmup_minutes` | 15 | 15 | 15 | 15 | 15 |
| `atr_period` | 14 | 14 | 14 | 14 | 14 |
| `mode` | MCX | MCX | MCX | NSE | NSE |

**TEST:**
```python
from config.instruments import get_instrument, get_instruments_by_mode, ExchangeMode
ng = get_instrument("NATURALGAS")
assert ng.tick_size == 0.10
assert ng.lot_size == 1250
mcx_list = get_instruments_by_mode(ExchangeMode.MCX)
assert len(mcx_list) == 3
nse_list = get_instruments_by_mode(ExchangeMode.NSE)
assert len(nse_list) == 2
try:
    get_instrument("FAKESYMBOL")
    assert False, "Should have raised ValueError"
except ValueError:
    pass
```

***

## PHASE 2 — Core Data Layer

***

### INSTRUCTION 004 — `core/tick_processor.py`

**TASK:**
Create a `Tick` dataclass with `__slots__` and the following fields:
`price: float`, `ask_vol: int`, `bid_vol: int`, `volume: int`, `trade_size: int`, `delta: int`, `timestamp: float` (Unix float).

Create `normalize_tick(raw: dict) -> Tick` function that:
- Maps `raw["LTP"]` → `price`
- Maps `raw["buy_qty"]` → `ask_vol`
- Maps `raw["sell_qty"]` → `bid_vol`
- Computes `volume = ask_vol + bid_vol`
- Maps `raw.get("trade_size", 1)` → `trade_size`
- Computes `delta = ask_vol - bid_vol`
- Parses `raw["timestamp"]` ISO string → Unix float

**RULES:**
- `__slots__` must be set — no `__dict__`
- If any required key is missing in `raw`, raise `KeyError` with the missing key name
- `timestamp` must be a `float`, not a `datetime` object

**TEST:**
```python
from core.tick_processor import Tick, normalize_tick
import time

raw = {
    "LTP": 9.35, "buy_qty": 100, "sell_qty": 60,
    "trade_size": 10, "timestamp": "2026-03-17T09:30:00+05:30",
    "symbol": "NATURALGAS"
}
tick = normalize_tick(raw)
assert tick.price == 9.35
assert tick.ask_vol == 100
assert tick.bid_vol == 60
assert tick.volume == 160
assert tick.delta == 40
assert isinstance(tick.timestamp, float)
assert not hasattr(tick, '__dict__')  # __slots__ verified
```

***

### INSTRUCTION 005 — `core/candle_builder.py`

**TASK:**
Create a `Candle` dataclass with fields:
`start_ts: float`, `end_ts: float`, `open: float`, `high: float`, `low: float`, `close: float`, `volume: int`, `ask_vol: int`, `bid_vol: int`, `delta: int`, `tick_count: int`

Create `CandleBuilder` class with:
- `__init__(self, resolution_seconds: int)` — default 60 (1-minute candles)
- `update(tick: Tick) -> Optional[Candle]` — returns `Candle` when candle closes, else `None`
- `reset()` — clear current candle state

**RULES:**
- Candle closes when `tick.timestamp >= candle_start + resolution_seconds`
- On first tick of new candle: previous candle is finalized and returned
- `high` = max price seen in candle window
- `low` = min price seen in candle window
- Timestamps are Unix floats — no datetime arithmetic

**TEST:**
```python
from core.candle_builder import CandleBuilder
from core.tick_processor import Tick

builder = CandleBuilder(resolution_seconds=60)
t0 = 1710000000.0  # arbitrary Unix ts

ticks = [
    Tick(9.10, 100, 50, 150, 10, 50, t0 + 5),
    Tick(9.20, 80,  90, 170, 8,  -10, t0 + 30),
    Tick(9.15, 120, 70, 190, 12,  50, t0 + 59),
    Tick(9.25, 60,  40, 100, 6,   20, t0 + 61),  # triggers candle close
]
results = [builder.update(t) for t in ticks]
assert results[0] is None
assert results [localhost](http://localhost:5190/) is None
assert results[2] is None
candle = results[3]
assert candle is not None
assert candle.open  == 9.10
assert candle.high  == 9.20
assert candle.low   == 9.10
assert candle.close == 9.15
assert candle.volume == 510
assert candle.delta  == 90   # 50 - 10 + 50
assert candle.tick_count == 3
```

***

### INSTRUCTION 006 — `core/session_manager.py`

**TASK:**
Create `SessionManager` class that takes an `InstrumentConfig` in `__init__`.

Methods:
- `classify_time(unix_ts: float) -> str` — returns one of: `"OUTSIDE_SESSION"`, `"WARMUP"`, `"DEAD_ZONE"`, `"ACTIVE"`
- `is_new_session(unix_ts: float, last_session_open_ts: float) -> bool`
- `get_session_open_ts(date_str: str) -> float` — parses date + session_open time → Unix float

**RULES:**
- All time operations in IST (UTC+5:30)
- WARMUP = first `warmup_minutes` after `session_open`
- DEAD_ZONE = 12:00–13:30 IST for MCX instruments, not applicable for NSE
- OUTSIDE_SESSION = before `session_open` or after `session_close`
- New session = tick timestamp date differs from `last_session_open_ts` date in IST

**TEST:**
```python
from config.instruments import get_instrument
from core.session_manager import SessionManager
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))
inst = get_instrument("NATURALGAS")
sm   = SessionManager(inst)

# 09:05 IST = warmup
t_warmup    = datetime(2026,3,17,9,5,0, tzinfo=IST).timestamp()
# 09:30 IST = active
t_active    = datetime(2026,3,17,9,30,0, tzinfo=IST).timestamp()
# 12:15 IST = dead zone
t_dead      = datetime(2026,3,17,12,15,0, tzinfo=IST).timestamp()
# 08:00 IST = outside session
t_outside   = datetime(2026,3,17,8,0,0, tzinfo=IST).timestamp()

assert sm.classify_time(t_warmup)  == "WARMUP"
assert sm.classify_time(t_active)  == "ACTIVE"
assert sm.classify_time(t_dead)    == "DEAD_ZONE"
assert sm.classify_time(t_outside) == "OUTSIDE_SESSION"
```

***

## PHASE 3 — Profile Engine

***

### INSTRUCTION 007 — `profile/volume_profile.py`

**TASK:**
Create `VolumeProfileEngine` class:
- `__init__(self, bucket_size: float)`
- `update(tick: Tick)` — incremental O(1) bucket update for session profile
- `update_leg(tick: Tick)` — incremental O(1) bucket update for leg profile
- `start_leg()` — clear leg profile and set `_leg_active = True`
- `stop_leg()` — set `_leg_active = False`
- `reset_session()` — clear session, leg, delta profiles
- `get_poc(profile: str) -> float` — `profile` = "session" or "leg"
- `get_value_area(profile: str) -> dict` — returns `{POC, VAH, VAL, total_volume, va_volume}`
- `get_delta_profile(profile: str) -> dict` — returns `{price: {buy_delta, sell_delta, net_delta}}`

**Value area expansion algorithm — EXACT:**
1. Start with POC bucket
2. Expand one bucket at a time: always take the HIGHER-volume adjacent bucket (up or down)
3. Stop when accumulated volume >= `total_volume × 0.70`
4. VAH = highest price included, VAL = lowest price included

**Delta profile — EXACT:**
- `buy_delta` per bucket += `tick.ask_vol` (aggressive buyers = trades at ask)
- `sell_delta` per bucket += `tick.bid_vol` (aggressive sellers = trades at bid)
- `net_delta` = `buy_delta - sell_delta`

**RULES:**
- Use `round(tick.price / bucket_size) * bucket_size` as bucket key — exact float rounding
- No numpy in this module — pure Python dicts
- O(1) per tick for all update operations

**TEST:**
```python
from profile.volume_profile import VolumeProfileEngine
from core.tick_processor import Tick

eng = VolumeProfileEngine(bucket_size=0.10)
ticks = [
    Tick(9.00, 100, 50,  150, 10, 50,  1.0),
    Tick(9.10, 500, 200, 700, 10, 300, 2.0),  # highest volume
    Tick(9.20, 80,  60,  140, 8,  20,  3.0),
]
for t in ticks: eng.update(t)

assert eng.get_poc("session") == 9.10

va = eng.get_value_area("session")
assert va["POC"] == 9.10
assert va["VAH"] >= 9.10
assert va["VAL"] <= 9.10
total = sum([150, 700, 140])
assert va["va_volume"] / total >= 0.70

dp = eng.get_delta_profile("session")
assert dp[9.10]["buy_delta"]  == 500
assert dp[9.10]["sell_delta"] == 200
assert dp[9.10]["net_delta"]  == 300
```

***

### INSTRUCTION 008 — `profile/node_detector.py`

**TASK:**
Create `NodeDetector` class with static methods:
- `detect_lvns(profile: dict, threshold_pct: float) -> list[dict]` — each dict: `{price, volume, quality_score}`
- `detect_hvns(profile: dict, threshold_pct: float) -> list[dict]`
- `score_lvn(price: float, volume: int, leg_low: float, leg_high: float, profile: dict) -> float`
- `detect_high_delta_zones(delta_profile: dict, direction: str, sigma_mult: float) -> list[dict]`

**LVN rule — EXACT:**
- `mean_vol = sum(profile.values()) / len(profile)`
- LVN if `volume < mean_vol × threshold_pct` (0.15)

**LVN quality score — EXACT:**
- `thinness_score = 1.0 - (volume / (mean_vol × threshold_pct))`  — clamped 0–1
- `leg_midpoint = (leg_high + leg_low) / 2`
- `midpoint_score = 1.0 - abs(price - leg_midpoint) / ((leg_high - leg_low) / 2)`  — clamped 0–1
- `quality_score = thinness_score × 0.60 + midpoint_score × 0.40`

**Delta zone rule — EXACT:**
- `mean_abs_delta = mean of abs(net_delta) across all buckets`
- `threshold = mean_abs_delta × sigma_mult` (2.5)
- HIGH_SELL_DELTA (for LONG entry): `net_delta < -threshold`
- HIGH_BUY_DELTA (for SHORT entry): `net_delta > +threshold`

**TEST:**
```python
from profile.node_detector import NodeDetector

profile = {9.00: 1000, 9.10: 5000, 9.20: 2000, 9.30: 80}
# mean = (1000+5000+2000+80)/4 = 2020
# threshold = 2020 × 0.15 = 303
# 9.30 (80) is LVN, 9.00 (1000) is NOT (1000 > 303)

lvns = NodeDetector.detect_lvns(profile, 0.15)
lvn_prices = [l["price"] for l in lvns]
assert 9.30 in lvn_prices
assert 9.00 not in lvn_prices

hvns = NodeDetector.detect_hvns(profile, 2.00)
# mean = 2020, threshold = 2020 × 2.0 = 4040
# 9.10 (5000) is HVN
assert 9.10 in [h["price"] for h in hvns]
```

***

### INSTRUCTION 009 — `profile/leg_anchor.py`

**TASK:**
Create `LegAnchorDetector` with two static methods:
- `auto_detect_leg_anchor(candles: list, session_va: dict, atr: float, avg_vol: float, tick_size: float) -> Optional[dict]`
- `should_reset_leg(current_price: float, session_va: dict) -> bool`

**Leg anchor detection — EXACT conditions (ALL must be true):**
1. Candle close is outside session VAH or session VAL
2. Candle range `(high - low) > atr × 1.5`
3. Candle volume `> avg_vol × 1.5`

**If all 3 met:** return `{start_ts, direction: "UP"/"DOWN", origin_price}`

**Leg reset condition — EXACT:**
- Return `True` if `session_va["VAL"] <= current_price <= session_va["VAH"]` (price returned inside value area)

**TEST:**
```python
from profile.leg_anchor import LegAnchorDetector
from core.candle_builder import Candle

session_va = {"VAH": 10.0, "VAL": 9.0, "POC": 9.5}

# Candle breaks below VAL with displacement + volume
candle_leg = Candle(
    start_ts=1000.0, end_ts=1060.0,
    open=9.05, high=9.10, low=8.70, close=8.75,
    volume=3000, ask_vol=800, bid_vol=2200,
    delta=-1400, tick_count=30
)
result = LegAnchorDetector.auto_detect_leg_anchor(
    candles=[candle_leg], session_va=session_va,
    atr=0.20, avg_vol=1000.0, tick_size=0.10
)
assert result is not None
assert result["direction"] == "DOWN"

# Price returned inside VA → reset leg
assert LegAnchorDetector.should_reset_leg(9.45, session_va) == True
assert LegAnchorDetector.should_reset_leg(8.75, session_va) == False
```

***

## PHASE 4 — Order Flow Engines

***

### INSTRUCTION 010 — `orderflow/cvd_engine.py`

**TASK:**
Create `CVDEngine` class:
- `__init__(self)` — internal deque of `{ts, cvd}` dicts
- `append(tick: Tick)` — add delta to running CVD
- `reset()` — clear all state
- `get_current() -> float` — current CVD value
- `get_slope(window: int = 20) -> float` — linear regression slope over last `window` CVD values using `numpy.polyfit`
- `detect_divergence(price_candles: list, lookback: int = 5) -> dict` — returns `{bull: bool, bear: bool}`

**CVD accumulation — EXACT:**
- `running_cvd += tick.delta` on every `append`
- Store `{ts: tick.timestamp, cvd: running_cvd}` in deque

**Divergence — EXACT:**
- Bull divergence: price close at `lookback` ago > price close now (lower low), AND CVD at `lookback` ago < CVD now (higher CVD)
- Bear divergence: price close at `lookback` ago < price close now (higher high), AND CVD at `lookback` ago > CVD now (lower CVD)

**TEST:**
```python
from orderflow.cvd_engine import CVDEngine
from core.tick_processor import Tick

eng = CVDEngine()
eng.append(Tick(9.0, 100, 60, 160, 10, 40, 1.0))   # cvd = 40
eng.append(Tick(9.1, 80, 120, 200, 8, -40, 2.0))   # cvd = 0
eng.append(Tick(9.0, 50, 200, 250, 5, -150, 3.0))  # cvd = -150

assert eng.get_current() == -150

# Bull divergence test: prices going lower, CVD going higher
from core.candle_builder import Candle
candles_bull = [
    Candle(0.0, 60.0, 9.5, 9.6, 9.4, 9.50, 1000, 500, 500, 0, 10),  # lookback[0]
    Candle(60.0, 120.0, 9.3, 9.4, 9.2, 9.25, 1000, 400, 600, -200, 8),  # lookback [localhost](http://localhost:5190/)
]
# Mock CVD to simulate bull divergence scenario in detect_divergence
```

***

### INSTRUCTION 011 — `orderflow/footprint_engine.py`

**TASK:**
Create `FootprintEngine` class:
- `__init__(self, bucket_size: float)`
- `update(tick: Tick, candle_start_ts: float)` — build current candle's footprint
- `finalize_candle(candle: Candle) -> dict` — close current candle, return footprint, add to history
- `detect_imbalance(footprint: dict, direction: str) -> dict` — returns `{confirmed: bool, imbalanced_cell_pct: float, score: float}`

**Footprint structure — EXACT:**
```python
{
  9.10: {"ask": 450, "bid": 80},   # 450 at ask : 80 at bid
  9.00: {"ask": 30,  "bid": 350},  # 30 at ask : 350 at bid
}
```

**Imbalance detection — EXACT:**
- For LONG: imbalanced cell = `ask / bid >= 3.0` (3:1 ratio)
- For SHORT: imbalanced cell = `bid / ask >= 3.0`
- Skip cells where either side is 0
- `confirmed = True` if `imbalanced_cell_pct >= 0.40` (40% of cells are imbalanced)
- `score = imbalanced_cell_pct` normalized 0–1

**TEST:**
```python
from orderflow.footprint_engine import FootprintEngine
from core.tick_processor import Tick
from core.candle_builder import Candle

eng = FootprintEngine(bucket_size=0.10)

# Build a footprint with ask dominance (LONG pressure)
ticks = [
    Tick(9.10, 400, 80,  480, 40,  320, 1.0),
    Tick(9.00, 350, 80,  430, 35,  270, 2.0),
    Tick(9.20, 300, 90,  390, 30,  210, 3.0),
    Tick(9.10, 380, 100, 480, 38,  280, 4.0),
]
for t in ticks:
    eng.update(t, 0.0)

candle = Candle(0.0, 60.0, 9.0, 9.2, 9.0, 9.1, 1780, 1430, 350, 1080, 4)
fp = eng.finalize_candle(candle)

result = eng.detect_imbalance(fp, "LONG")
assert result["confirmed"] == True  # most cells have ask:bid >= 3:1
```

***

### INSTRUCTION 012 — `orderflow/absorption_detector.py`

**TASK:**
Create function `detect_absorption(candle: Candle, atr: float, avg_vol: float) -> dict`
Returns `{detected: bool, absorption_type: str, direction_implication: str}`

**Detection — EXACT (both conditions required simultaneously):**
1. `candle.high - candle.low < atr × 0.30`
2. `candle.volume > avg_vol × 2.0`

**Classification — EXACT:**
- If detected AND `candle.close >= candle.open` → `absorption_type = "SELL_ABSORBED"`, `direction_implication = "LONG"`
- If detected AND `candle.close < candle.open` → `absorption_type = "BUY_ABSORBED"`, `direction_implication = "SHORT"`

**TEST:**
```python
from orderflow.absorption_detector import detect_absorption
from core.candle_builder import Candle

# Absorption candle: tiny range, huge volume, bullish close
c = Candle(0.0, 60.0, 9.0, 9.04, 8.98, 9.03, 5000, 2800, 2200, 600, 50)
result = detect_absorption(c, atr=0.20, avg_vol=1000.0)
# range = 0.06 < 0.20×0.30 = 0.06 — exactly on boundary, use strict <
assert result["detected"] == True
assert result["absorption_type"] == "SELL_ABSORBED"
assert result["direction_implication"] == "LONG"

# Normal candle: large range
c2 = Candle(0.0, 60.0, 9.0, 9.30, 8.90, 9.25, 5000, 2800, 2200, 600, 50)
result2 = detect_absorption(c2, atr=0.20, avg_vol=1000.0)
assert result2["detected"] == False
```

***

### INSTRUCTION 013 — `orderflow/bubble_detector.py`

**TASK:**
Create `BubbleDetector` class:
- `__init__(self, window: int = 21, sigma_threshold: float = 2.0)`
- `update(footprint_history: list)` — called on each candle close with last 21 footprints
- `detect_bubbles(current_footprint: dict) -> list[dict]` — returns list of `{price, type, volume, sigma_above_mean}`
- `bubble_confirms_entry(direction: str, entry_zone: float, tick_size: float) -> bool`

**Bubble detection — EXACT:**
- Per price level: `total_vol = ask + bid`
- Collect `total_vol` across last 21 candles per level
- `mean = mean(total_vols)`, `std = std(total_vols)`
- Bubble if `current_total_vol > mean + sigma_threshold × std`
- `type`: if `ask > bid × 2` → "BUY", if `bid > ask × 2` → "SELL", else → "NEUTRAL"

**Entry confirmation — EXACT:**
- LONG: confirm if BUY bubble OR NEUTRAL bubble within `3 × tick_size` of `entry_zone`
- SHORT: confirm if SELL bubble OR NEUTRAL bubble within `3 × tick_size` of `entry_zone`

**TEST:**
```python
from orderflow.bubble_detector import BubbleDetector

bd = BubbleDetector(window=5, sigma_threshold=2.0)
# Build 5 candles of normal volume at 9.10
normal_fps = [
    {9.10: {"ask": 50, "bid": 40}} for _ in range(5)
]
# Spike candle at 9.10 — 10× normal
spike_fp = {9.10: {"ask": 800, "bid": 300}}

bd.update(normal_fps)
bubbles = bd.detect_bubbles(spike_fp)
assert len(bubbles) > 0
assert bubbles[0]["price"] == 9.10
assert bubbles[0]["type"] == "BUY"  # ask >> bid

assert bd.bubble_confirms_entry("LONG", 9.12, 0.10) == True
```

***

## PHASE 5 — Strategy Core

***

### INSTRUCTION 014 — `strategy/market_state_engine.py`

**TASK:**
Create `MarketStateEngine` with one static method:
`detect(price: float, session_va: dict, prev_va: dict, atr: float, candles: list, tick_size: float) -> tuple[str, Optional[str]]`

Returns `(market_state, balance_zone)`.

**State classification — EXACT priority order:**

1. **NO_TRADE** (highest priority): `abs(price - session_va["POC"]) <= 2 × tick_size`
2. **BALANCED**: `session_va["VAL"] <= price <= session_va["VAH"]`
   - `balance_zone = "NEAR_VAH"` if `price > midpoint between POC and VAH`
   - `balance_zone = "NEAR_VAL"` if `price < midpoint between VAL and POC`
   - `balance_zone = "NEAR_POC"` otherwise (→ also NO_TRADE, already caught above)
3. **IMBALANCED**: price outside VA + last candle range `> atr × 1.5` + last candle `volume > avg × 1.5`
4. **PROBING**: price outside VA but no displacement confirmation

**TEST:**
```python
from strategy.market_state_engine import MarketStateEngine
from core.candle_builder import Candle

va = {"POC": 9.50, "VAH": 10.20, "VAL": 8.80}

# POC dead zone
state, zone = MarketStateEngine.detect(9.51, va, None, 0.20, [], 0.10)
assert state == "NO_TRADE"

# Near VAL
state, zone = MarketStateEngine.detect(8.85, va, None, 0.20, [], 0.10)
assert state == "BALANCED"
assert zone == "NEAR_VAL"

# Probing — outside VA but no candle confirmation
state, zone = MarketStateEngine.detect(8.60, va, None, 0.20, [], 0.10)
assert state == "PROBING"
```

***

### INSTRUCTION 015 — `strategy/drive_tracker.py`

**TASK:**
Create `DriveTracker` class:
- `__init__(self, tick_size: float)`
- `record_touch(level: float, ts: float, was_rejected: bool, rejection_type: Optional[str])`
- `classify_drive(current_price: float, key_level: float, direction: str, candles: list, atr: float, cvd_engine, tick_size: float) -> DriveResult`
- `detect_rejection(candles: list, level: float, direction: str, atr: float, tick_size: float) -> dict`
- `reset()` — clear all records at session open

Create `DriveResult` dataclass:
`drive_number: int`, `entry_valid: bool`, `was_rejected: bool`, `reason: str`

**Drive classification — EXACT:**
1. Look up `touch_history[level]` — list of `DriveRecord` for this level
2. `drive_number = len(touch_history[level]) + 1` (current touch)
3. Drive 1: `entry_valid = False`, record touch with rejection check
4. Drive 2: `entry_valid = True` ONLY if drive 1 was rejected AND CVD slope momentum fading
5. Drive 3+: `entry_valid = False` always

**Rejection detection — EXACT:**
- Wick rejection: candle wick crosses level by ≥ 2 ticks AND candle closes on opposite side of level
- Level grouping: treat levels within `3 × tick_size` as the same level

**TEST:**
```python
from strategy.drive_tracker import DriveTracker

tracker = DriveTracker(tick_size=0.10)

# First touch at 8.91 — no entry
result = tracker.classify_drive(8.91, 8.91, "LONG", candles=[], atr=0.2,
                                  cvd_engine=None, tick_size=0.10)
assert result.drive_number == 1
assert result.entry_valid == False

# Manually record first drive with rejection
tracker.record_touch(8.91, 1000.0, was_rejected=True, rejection_type="WICK")

# Second touch — entry valid
result2 = tracker.classify_drive(8.91, 8.91, "LONG", candles=[], atr=0.2,
                                   cvd_engine=None, tick_size=0.10)
assert result2.drive_number == 2
assert result2.entry_valid == True

# Third touch
tracker.record_touch(8.91, 2000.0, was_rejected=False, rejection_type=None)
result3 = tracker.classify_drive(8.91, 8.91, "LONG", candles=[], atr=0.2,
                                   cvd_engine=None, tick_size=0.10)
assert result3.drive_number == 3
assert result3.entry_valid == False
```

***

### INSTRUCTION 016 — `strategy/aggression_scorer.py`

**TASK:**
Create `AggressionScorer` with one static method:
`score(...) -> AggressionResult`

Create `AggressionResult` dataclass:
`score: float`, `confirmed: bool`, `signals: list[str]`, `breakdown: dict`

**Scoring — EXACT weights (import from `CFG`):**

| Signal | Condition | Weight |
|---|---|---|
| Footprint | `imbalance.confirmed == True` | `CFG.score_footprint` = 1.0 |
| CVD | slope confirms direction OR divergence detected | `CFG.score_cvd` = 1.0 |
| Big trade | cluster at entry level confirmed | `CFG.score_big_trade` = 1.0 |
| Absorption | detected in trade direction | `CFG.score_absorption` = 0.5 |
| OFI | > 0.10 for LONG, < -0.10 for SHORT | `CFG.score_ofi` = 0.5 |
| Bubble | directional bubble within 3 ticks | `CFG.score_bubble` = 0.5 |
| Delta zone | high delta zone at entry level | `CFG.score_delta_zone` = 0.5 |
| Combined confluence | LVN + session level overlap | `CFG.score_combined_confluence` = 0.5 |
| Anomaly bonus | double anomaly detected | `CFG.score_anomaly_bonus` = 0.5 |
| Weekly bias | trade aligned with weekly composite bias | `CFG.score_weekly_bias` = 0.5 |

**RULES:**
- `confirmed = score >= CFG.min_aggression_score` (2.0)
- Confidence: `score >= 3.0` → "High", `>= 2.0` → "Medium", `< 2.0` → "Low"
- `signals` list must contain human-readable string for every confirmed signal
- `breakdown` dict must show `{signal_name: weight_added}` for every signal checked

**TEST:**
```python
from strategy.aggression_scorer import AggressionScorer, AggressionResult

# Only footprint + CVD confirmed → score = 2.0 → Medium
result = AggressionScorer.score(
    direction="LONG", current_price=8.91, key_level=8.91, tick_size=0.10,
    candles=[], cvd_engine=mock_cvd(slope=3.0),
    footprint={"confirmed": True, "imbalanced_cell_pct": 0.55},
    bubble_result=None, absorption={"detected": False},
    big_trade={"confirmed": False}, ofi=0.05,
    delta_profile={}, anomaly=None, weekly_bias=None, cfg=CFG
)
assert result.score == 2.0
assert result.confirmed == True
assert "footprint" in result.breakdown
assert "cvd" in result.breakdown
assert result.breakdown["footprint"] == 1.0
```

***

## PHASE 6 — Risk Management

***

### INSTRUCTION 017 — `risk/session_risk_manager.py`

**TASK:**
Create `SessionRiskManager` class:
- `__init__(self, account_equity: float)`
- `can_trade() -> tuple[bool, str]` — returns `(True, "")` or `(False, reason_string)`
- `register_trade_result(pnl: float)` — update all counters
- `update_equity_peak(current_equity: float)` — track drawdown
- `session_summary() -> dict`
- `reset_session(new_equity: float)` — called at session open

**Kill switch conditions — EXACT (checked in this order):**
1. `daily_pnl / session_start_equity <= -CFG.max_daily_loss_pct` → reason: "DAILY_LOSS_LIMIT_REACHED"
2. `(equity_peak - current_equity) / equity_peak >= CFG.max_drawdown_pct` → reason: "MAX_DRAWDOWN_REACHED"
3. `consecutive_losses >= CFG.max_consecutive_losses` → reason: "CONSECUTIVE_LOSSES_LIMIT"

**RULES:**
- A win resets `consecutive_losses` to 0
- A loss increments `consecutive_losses` by 1
- `session_start_equity` is set at `reset_session` and does not change during session
- Once kill switch fires, `can_trade()` returns `False` for remainder of session

**TEST:**
```python
from risk.session_risk_manager import SessionRiskManager
from config.engine_config import CFG

rm = SessionRiskManager(account_equity=500000)

# 3 consecutive losses → pause
rm.register_trade_result(-500)
rm.register_trade_result(-500)
rm.register_trade_result(-500)
ok, reason = rm.can_trade()
assert ok == False
assert "CONSECUTIVE" in reason

# Win resets counter
rm.register_trade_result(+2000)
ok2, _ = rm.can_trade()
assert ok2 == True
assert rm.consecutive_losses == 0

# Daily loss limit
rm2 = SessionRiskManager(500000)
rm2.register_trade_result(-10001)  # -2.0002% > 2.0%
ok3, reason3 = rm2.can_trade()
assert ok3 == False
assert "DAILY" in reason3
```

***

### INSTRUCTION 018 — `risk/position_sizer.py`

**TASK:**
Create `PositionSizer` with static method:
`calculate(equity, entry, stop, point_value, lot_size, cushion_quality, risk_manager, cfg) -> tuple[int, float, float]`

Returns `(lots, risk_amount_inr, risk_pct)`.

**Sizing formula — EXACT:**
1. `risk_amount = equity × cfg.risk_per_trade_pct` (0.5% of equity)
2. If `cushion_quality == "WIDE"`: `risk_amount = risk_amount × 0.50` (50% size reduction)
3. `risk_per_lot = abs(entry - stop) × point_value`
4. `lots = floor(risk_amount / risk_per_lot)`
5. If `lots × risk_per_lot > equity × cfg.max_risk_per_trade_pct`: reduce lots to fit hard ceiling
6. Return `(lots, lots × risk_per_lot, (lots × risk_per_lot) / equity)`
7. If `lots == 0`: return `(0, 0.0, 0.0)`

**TEST:**
```python
from risk.position_sizer import PositionSizer
from config.engine_config import CFG
import math

# equity=500000, entry=8.91, stop=8.71, tick=0.10, point_value=125
# risk_per_lot = abs(8.91-8.71) × 125 = 0.20 × 125 = 25
# risk_amount  = 500000 × 0.005 = 2500
# lots = floor(2500 / 25) = 100
lots, risk_amt, risk_pct = PositionSizer.calculate(
    equity=500000, entry=8.91, stop=8.71,
    point_value=125.0, lot_size=1,
    cushion_quality="ACCEPTABLE",
    risk_manager=None, cfg=CFG
)
assert lots == 100
assert risk_amt == 2500.0
assert abs(risk_pct - 0.005) < 0.0001
```

***

## PHASE 7 — Trade Management

***

### INSTRUCTION 019 — `trade_management/partition_exit_manager.py`

**TASK:**
Create `PartitionExitManager` with static method:
`check(tick, state, cfg) -> list[dict]`

Returns list of action dicts: `{action, lots, price, reason}`.

**Partition logic — EXACT:**

**P1 (seed recovery):**
- Trigger: `price >= entry + R × 0.33` for LONG (or `<= entry - R × 0.33` for SHORT)
- Condition: CVD slope `< cfg.cvd_strong_slope` (2.0) — weak momentum only
- If triggered: exit `floor(total_lots × 0.30)` lots
- If momentum strong (slope >= 2.0): SKIP P1, let run

**P2 (target exit):**
- Trigger: LONG `price >= target`, SHORT `price <= target`
- Always fires regardless of momentum — no condition
- Exit `floor(total_lots × 0.50)` lots from remaining

**P3 (remainder):**
- If CVD slope `>= 2.0` at P2 exit time: trail remaining lots
- If CVD slope `< 2.0`: exit remaining lots with P2
- Trail formula: `trail_sl = current_price - (remaining_to_target × 0.40)` for LONG

**Counter-aggression override:**
- If `counter_aggression_count >= 2`: return `[{action: "EXIT_ALL", ...}]` — no partitions

**TEST:**
```python
# Test P1 skipped when strong momentum
# Test P2 always fires at target
# Test P3 exits with P2 when CVD weak
# Test counter aggression exits all

assert True  # placeholder — tests are in tests/unit/test_partition_exit.py
# See test file instructions in PHASE 9
```

***

### INSTRUCTION 020 — `trade_management/pyramid_manager.py`

**TASK:**
Create `PyramidManager` with static method:
`check(tick, state, cfg) -> PyramidResult`

Create `PyramidResult` dataclass: `add: bool`, `level: Optional[float]`, `lots: int`, `reason: str`

**Pyramid conditions — ALL must be true:**
1. `state.open_entries` is not empty (trade must be open)
2. First entry is in profit: LONG `current_price > state.open_entries[0].price`, SHORT opposite
3. `state.pyramid_count < cfg.pyramid_max_adds` (max 2 adds)
4. A new LVN exists between `current_price` and `target` (different from first entry level)
5. `current_price` within `3 × tick_size` of that LVN
6. `aggression_score >= cfg.pyramid_aggression_score` (3.0)
7. Total risk after add `<= cfg.pyramid_risk_ceiling_mult × base_risk`

**Lot sizing for pyramid — EXACT:**
- Add 1: 100% of first entry lots
- Add 2: 50% of first entry lots
- Add 3: 25% of first entry lots (not used — max 2 adds)

**After pyramid add:**
- Move ALL open stops to the NEW entry's stop loss
- Increment `state.pyramid_count`
- Save open trade state to DuckDB

***

## PHASE 8 — Data Layer

***

### INSTRUCTION 021 — `data/duckdb_store.py`

**TASK:**
Implement `DuckDBStore` class with exactly these tables and methods as specified in the architecture document. No extra tables, no extra columns.

**Tables — EXACT schema:**
- `ticks` — append-only tick storage
- `session_profiles` — one row per underlying per date, `UNIQUE(underlying, session_date)`
- `npoc_records` — naked POC tracking with `is_filled` flag
- `signals` — append-only signal log
- `trades` — one row per trade, updated on close
- `open_trades` — `UNIQUE(symbol)`, upserted on every trade state change
- `session_risk` — `UNIQUE(underlying, session_date)`
- `economic_events` — EIA and other suppression events

**RULES:**
- `initialize_schema()` must be idempotent — safe to call on every startup
- All JSON fields stored as `JSON` type in DuckDB
- All timestamps stored as `TIMESTAMPTZ`
- Connection is opened once in `connect()` and reused — not reopened per query

**TEST:**
```python
from data.duckdb_store import DuckDBStore
import tempfile, os

with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
    db_path = f.name

db = DuckDBStore(db_path).connect()
db.initialize_schema()

# Idempotent — call twice
db.initialize_schema()

# Save and load session profile
from datetime import date
db.save_session_profile(
    "NATURALGAS", date(2026,3,17), 9.50, 10.20, 8.80,
    50000, {"9.50": 5000, "9.40": 3000}, {"9.50": {"buy_delta": 3000, "sell_delta": 2000, "net_delta": 1000}}
)
result = db.load_prev_session_profile("NATURALGAS")
assert result is not None
assert result["POC"] == 9.50
assert result["VAH"] == 10.20

os.unlink(db_path)
```

***

### INSTRUCTION 022 — `data/dhan_ws_client.py`

**TASK:**
Implement `DhanWSClient` class:
- `__init__(self, access_token: str)`
- `connect()` — async method, runs forever with exponential backoff reconnect
- `subscribe(ws, security_ids: list[dict])` — send DhanHQ subscription packet
- `handle_message(raw: bytes, queues: dict)` — parse JSON with `orjson`, create `Tick`, push to correct queue
- `on_tick` — callable set externally, called with `(tick: Tick, security_id: str)` for every tick

**Reconnect backoff — EXACT:**
- Initial delay: 2 seconds
- Doubles on each failure: 2, 4, 8, 16, 30 (capped at 30)
- Resets to 2 on successful connection

**DhanHQ subscription packet — EXACT:**
```python
{
    "RequestCode": 15,
    "InstrumentCount": len(security_ids),
    "InstrumentList": [
        {"ExchangeSegment": item["segment"], "SecurityId": str(item["security_id"])}
        for item in security_ids
    ]
}
```

**RULES:**
- Use `websockets` library — no `aiohttp` for WS
- Use `orjson.loads()` for all JSON parsing — not stdlib json
- On disconnect, set all subscribed symbol states to `data_quality = "RECONNECTING"` via callback
- Ping interval: 20 seconds, ping timeout: 10 seconds

***

## PHASE 9 — Tests

***

### INSTRUCTION 023 — `tests/unit/` All Unit Tests

**TASK:**
Create the following test files. Each must import only from the engine modules — no mocks of internal logic.

**`tests/unit/test_profile.py` — 6 tests:**
1. `test_poc_calculation` — profile with clear max-volume bucket
2. `test_value_area_70_pct` — VA must accumulate ≥ 70% of total volume
3. `test_vah_above_poc_val_below_poc` — structural invariant
4. `test_lvn_threshold` — volumes below 15% of mean are LVNs
5. `test_lvn_score_midpoint_bonus` — LVN closer to midpoint scores higher
6. `test_delta_zone_detection` — high net_delta zones flagged correctly

**`tests/unit/test_cvd.py` — 4 tests:**
1. `test_cvd_accumulation` — running sum correct across ticks
2. `test_cvd_slope_direction` — positive slope on buy pressure ticks
3. `test_cvd_bull_divergence` — lower price + higher CVD → bull=True
4. `test_cvd_bear_divergence` — higher price + lower CVD → bear=True

**`tests/unit/test_drive_tracker.py` — 5 tests:**
1. `test_first_drive_no_entry`
2. `test_second_drive_with_rejection_valid`
3. `test_second_drive_without_rejection_invalid`
4. `test_third_drive_invalid`
5. `test_drive_resets_on_session_reset`

**`tests/unit/test_aggression.py` — 5 tests:**
1. `test_score_below_threshold_no_signal` — score 1.5 → confirmed=False
2. `test_footprint_plus_cvd_equals_two` — score exactly 2.0
3. `test_pyramid_requires_three` — score 2.5 < 3.0 fails pyramid gate
4. `test_score_breakdown_correct_weights` — every weight matches CFG
5. `test_confidence_labels` — 3.0=High, 2.0=Medium, 1.5=Low

**`tests/unit/test_risk_manager.py` — 6 tests:**
1. `test_daily_loss_kill_switch`
2. `test_drawdown_kill_switch`
3. `test_consecutive_loss_pause`
4. `test_win_resets_consecutive`
5. `test_kill_switch_permanent_in_session`
6. `test_session_reset_clears_all`

**`tests/unit/test_partition_exit.py` — 5 tests:**
1. `test_p1_fires_on_weak_momentum`
2. `test_p1_skipped_on_strong_momentum`
3. `test_p2_always_fires_at_target`
4. `test_p3_exits_with_p2_weak_cvd`
5. `test_counter_aggression_exits_all`

***

### INSTRUCTION 024 — `tests/integration/test_full_pipeline.py` — 6 tests

**TASK:**
These tests run the complete `process_tick_pipeline()`. Build mock tick sequences that trigger exactly the right conditions.

1. `test_balanced_market_second_drive_long_signal`
   - Build: market BALANCED, price at VAL, second drive confirmed, aggression ≥ 2.0
   - Assert: `direction == "LONG"`, `drive_number == 2`, `aggression_score >= 2.0`, `stop_loss < entry_zone`, `target > entry_zone`

2. `test_no_trade_at_poc`
   - Build: price within 2 ticks of session POC
   - Assert: `direction == "FLAT"`, `no_trade_reason` contains "POC"

3. `test_probing_state_returns_wait`
   - Build: price outside VA, no displacement candle
   - Assert: `action == "WAIT"`, `market_state == "PROBING"`

4. `test_first_drive_returns_flat`
   - Build: second drive has never happened, price at VAH
   - Assert: `drive_number == 1`, `direction == "FLAT"`

5. `test_session_kill_switch_blocks_all_signals`
   - Build: force `daily_pnl` to exceed 2% daily loss
   - Assert: `action == "SESSION_STOPPED"` for every subsequent tick

6. `test_eia_suppression_blocks_signal`
   - Build: insert EIA event for current timestamp
   - Assert: `action == "EIA_WINDOW"`

***

### INSTRUCTION 025 — `tests/performance/test_latency.py` — 3 tests

**TASK:**
All performance tests must pass on the development machine before any deployment.

1. `test_signal_latency_under_500ms`
   - Run 100 ticks through full pipeline
   - Assert: P99 latency < 500ms

2. `test_profile_update_constant_time`
   - Pre-populate profile engine with 100,000 ticks
   - Time a single additional update
   - Assert: single update time < 1ms

3. `test_ten_concurrent_symbols_no_degradation`
   - Run 10 symbol pipelines concurrently for 1 second
   - Assert: no dropped ticks, no asyncio warnings, all 10 complete

***

## PHASE 10 — Frontend

***

### INSTRUCTION 026 — Frontend Setup

**TASK:**
Initialize React frontend in `frontend/` with:
```
npx create-vite@latest . --template react-ts
npm install zustand lightweight-charts tailwindcss
npm install -D @types/react
```

Create `.env.local`:
```
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000/ws/signals
```

***

### INSTRUCTION 027 — `useWebSocket.ts` Hook

**TASK:**
Create hook that connects to `VITE_WS_URL`, routes messages by `type` field, auto-reconnects after 3 seconds on close, and dispatches to correct zustand stores.

**Message routing — EXACT:**

| `msg.type` | Action |
|---|---|
| `SIGNAL` | `signalStore.updateSignal(msg.data.symbol, msg.data)` |
| `TRADE_UPDATE` | `signalStore.updateTrade(msg.trade_id, msg.action, msg)` |
| `STATE_CHANGE` | `signalStore.updateMarketState(msg.symbol, msg.to)` |
| `RISK_EVENT` | `riskStore.handleEvent(msg)` |
| `DATA_QUALITY` | `signalStore.setDataQuality(msg.symbol, msg.quality)` |
| `DRIVE_ALERT` | `alertStore.addAlert(msg)` |
| `HEARTBEAT` | no-op (connection alive) |

**TEST:**
Open browser console — must see no WebSocket errors after backend starts.
`HEARTBEAT` messages must appear every 5 seconds in browser network tab.

***

### INSTRUCTION 028 — Scanner Table Component

**TASK:**
Create `components/Scanner/index.tsx`.
- Reads from `signalStore.signals`
- One row per symbol
- Columns: `Symbol`, `Strike`, `Type`, `LTP`, `State`, `Score`, `Drive`, `Signal`
- Signal column shows badge: 🔥 red for SHORT score≥3, ⚡ amber for LONG score≥2, ⏳ grey for FLAT
- Data quality STALE: show row in muted color with "⚠ STALE" label
- Filter buttons: "All" | "Active Signals" | "High Confidence"
- Re-renders only changed rows using `zustand` shallow selector

***

## PHASE 11 — Final Validation

***

### INSTRUCTION 029 — End-to-End Smoke Test

**TASK:**
Run this exact checklist before marking system complete:

```
□ 1.  pytest tests/unit/ -v                    → 31 tests, 0 failures
□ 2.  pytest tests/integration/ -v             → 6 tests, 0 failures
□ 3.  pytest tests/performance/ -v             → 3 tests, 0 failures
□ 4.  python -m ruff check engine/            → 0 errors
□ 5.  python -m mypy engine/                  → 0 errors
□ 6.  docker-compose up -d                    → all containers start
□ 7.  curl http://localhost:8000/health        → {"status": "ok"}
□ 8.  wscat -c ws://localhost:8000/ws/signals  → HEARTBEAT appears within 5s
□ 9.  open http://localhost:5190               → Scanner table renders
□ 10. python scripts/seed_prev_session.py      → loads without error
□ 11. Engine log shows: "startup_complete"     → session profiles loaded
□ 12. Engine log shows: "initial_scan_done"    → N contracts subscribed
□ 13. After 5 min: log shows "rebalance_done" → subscription count updated
□ 14. Force kill engine: restart it            → open_trades recovered from DuckDB
□ 15. Simulate tick gap > 30s: DATA_STALE     → appears in frontend scanner
```

***

### INSTRUCTION 030 — Do Not Build List

**These items must NOT be built, even if they seem useful:**

```
❌ Any ML model, neural network, or LLM inference in the signal pipeline
❌ Redis, Kafka, RabbitMQ — use asyncio.Queue only
❌ SQLAlchemy or any ORM — raw DuckDB SQL only
❌ threading or multiprocessing — asyncio only
❌ pandas in the tick processing hot path — only in backtest/analysis
❌ requests library anywhere — aiohttp for all HTTP
❌ datetime.now() for latency measurement — use time.monotonic()
❌ Any feature not listed in these instructions
❌ Any threshold value not sourced from CFG
❌ Auto-trading execution (order placement) — signal generation only
```
