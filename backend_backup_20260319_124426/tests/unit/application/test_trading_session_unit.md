# TradingSessionService Unit Test Cases

## Test File

`backend/tests/unit/application/test_trading_session_unit.py`

## Test Purpose

Test the `TradingSessionService` class in isolation with all infrastructure
dependencies mocked (no DB, no network, no GPU, no MLX). The service is the
top-level coordinator that wires event subscriptions, manages per-symbol
session state, dispatches to handlers, and enforces idempotency and thread
safety.

## Test Cases Overview

| Case ID | Feature Description                              | Test Type     |
| ------- | ------------------------------------------------ | ------------- |
| TS-01   | Event subscription on init                       | Positive Test |
| TS-02   | First tick creates new SessionState               | Positive Test |
| TS-03   | Second tick reuses existing SessionState          | Positive Test |
| TS-04   | Signal idempotency (duplicate signal_id skipped) | Boundary Test |
| TS-05   | PositionClosed event triggers learning + journal  | Positive Test |
| TS-06   | Idle session eviction (>24h, no positions)       | Boundary Test |
| TS-07   | Thread safety: portfolio access uses lock         | Positive Test |
| TS-08   | Candle deduplication (sub-candle updates)         | Positive Test |
| TS-09   | MAX_CANDLES_PER_SYMBOL cap enforced              | Boundary Test |
| TS-10   | Pending signal drained on process_tick            | Positive Test |
| TS-11   | Session risk manager created per symbol           | Positive Test |
| TS-12   | Prior session profile loaded from storage         | Positive Test |
| TS-13   | State snapshot includes required keys             | Positive Test |
| TS-14   | Quant entry: high-conviction agent signal         | Positive Test |
| TS-15   | create_portfolio returns default portfolio        | Positive Test |

## Detailed Test Steps

### TS-01: Event subscription on init

**Test Purpose**: Verify that the service subscribes to TickReceived,
SignalGenerated, and PositionClosed events during initialization.

**Test Steps**:
1. Create TradingSessionService with mocked EventBusPort
2. Assert event_bus.subscribe was called 3 times
3. Assert it was called with TickReceived, SignalGenerated, PositionClosed

**Expected Results**:
- Three subscribe calls with correct event types

### TS-02: First tick creates new SessionState

**Test Purpose**: Verify session creation on first tick for a new symbol.

**Test Steps**:
1. Call process_tick("NIFTY", tick)
2. Assert "NIFTY" is in _sessions
3. Assert returned state has correct symbol

**Expected Results**:
- New SessionState created and returned

### TS-03: Second tick reuses existing SessionState

**Test Purpose**: Verify session reuse for same symbol.

**Test Steps**:
1. Call process_tick("NIFTY", tick1)
2. Call process_tick("NIFTY", tick2)
3. Assert same SessionState object is used both times

**Expected Results**:
- Session is reused, not recreated

### TS-04: Signal idempotency

**Test Purpose**: Verify duplicate signal_id is only executed once.

**Test Steps**:
1. Create a Signal with specific signal_id
2. Call _execute_signal twice with same signal
3. Assert broker.execute_order called only once

**Expected Results**:
- Second call logged as duplicate and skipped

### TS-05: PositionClosed event

**Test Purpose**: Verify position closed event triggers learning and journal.

**Test Steps**:
1. Create session with an open position
2. Publish PositionClosed event
3. Assert session.learning.learn was called

**Expected Results**:
- Learning engine updated with closed position data

### TS-06: Idle session eviction

**Test Purpose**: Verify sessions idle >24h with no positions are removed.

**Test Steps**:
1. Create session for "NIFTY"
2. Set _last_tick_time to 25 hours ago
3. Set _last_eviction_check to force check
4. Call get_or_create_session for different symbol (triggers eviction)
5. Assert "NIFTY" was removed from _sessions

**Expected Results**:
- Idle session evicted from memory

### TS-07: Thread safety

**Test Purpose**: Verify portfolio reads happen under session._lock.

**Test Steps**:
1. Call _build_state_snapshot
2. Verify it acquires the lock (assert lock operations work)

**Expected Results**:
- Portfolio access is thread-safe

### TS-08: Candle deduplication

**Test Purpose**: Verify sub-candle updates replace rather than append.

**Test Steps**:
1. Call process_tick with tick at time T1
2. Call process_tick with another tick at same time T1 (sub-candle update)
3. Assert session.data still has length 1 (replaced, not appended)

**Expected Results**:
- Only one entry per candle time in session.data

### TS-09: MAX_CANDLES cap

**Test Purpose**: Verify candle history is bounded.

**Test Steps**:
1. Call process_tick with 2100 ticks (each with unique time)
2. Assert len(session.data) <= MAX_CANDLES_PER_SYMBOL (2000)

**Expected Results**:
- Oldest candles removed when capacity exceeded

### TS-10: Pending signal drained

**Test Purpose**: Verify pending signal from LLM worker is drained in
process_tick.

**Test Steps**:
1. Set session._pending_signal = ("NIFTY", mock_signal)
2. Call process_tick
3. Assert _pending_signal is None after process_tick
4. Assert broker.execute_order was called

**Expected Results**:
- Pending signal consumed and executed

### TS-11: Session risk manager per symbol

**Test Purpose**: Verify SessionRiskManager is created per symbol.

**Test Steps**:
1. Call get_or_create_session("NIFTY")
2. Assert session has _session_risk_manager attribute
3. Assert it is a SessionRiskManager instance

**Expected Results**:
- Each session has its own risk manager

### TS-12: Prior session profile loaded

**Test Purpose**: Verify prior session profile is loaded from storage on
session creation.

**Test Steps**:
1. Mock storage.get_previous_session_profile to return profile data
2. Call get_or_create_session("NIFTY")
3. Assert session._prior_profile is set

**Expected Results**:
- Prior profile loaded for gap analysis

### TS-13: State snapshot keys

**Test Purpose**: Verify _build_state_snapshot returns all required keys.

**Test Steps**:
1. Create a session with basic data
2. Call _build_state_snapshot
3. Assert keys: portfolio, amt, genAIAnalysis, stats, statsBySource, etc.

**Expected Results**:
- All expected keys present in snapshot

### TS-14: Quant entry

**Test Purpose**: Verify _execute_quant_entry creates correct signal.

**Test Steps**:
1. Create mock agent_decision with direction="LONG", probability=0.7
2. Call _execute_quant_entry
3. Assert broker.execute_order called with AGENT-sourced signal

**Expected Results**:
- Quant entry executed with correct parameters

### TS-15: create_portfolio

**Test Purpose**: Verify factory method returns default portfolio.

**Test Steps**:
1. Call create_portfolio()
2. Assert result is a Portfolio instance with default balance

**Expected Results**:
- Default portfolio returned

## Test Considerations

### Mock Strategy
- `EventBusPort`: Mock with subscribe/publish stubs; capture subscribed handlers
- `BrokerPort`: Mock execute_order to return a Position or None
- `GenerativeAIService`: Mock with is_ready(), analyze_market() stubs
- `StoragePort`: Mock all methods (save_tick, save_trade, etc.) or set to None
- `AMTHandler`: Mock analyze() to return (amt_result, amt_dto, fp_dto)
- `TradeJournal`: Mock all logging methods
- `ForwardTestLogger`: Patch import to prevent file I/O
- `SessionRiskManager`: Real instance (lightweight, no I/O)

### Boundary Conditions
- Empty session data (first tick)
- MAX_CANDLES overflow (2000+ candles)
- Idle eviction threshold (86400 seconds)
- Duplicate signal_id set size cap (1000 -> trim to 500)

### Asynchronous Operations
- TradingSessionService is synchronous in its main path (process_tick)
- LLM and Overseer run in background threads but are not directly tested here
  (tested via test_llm_entry_handler.py and test_overseer_handler.py)
- _on_signal_generated may be called from any thread, so we verify lock usage
