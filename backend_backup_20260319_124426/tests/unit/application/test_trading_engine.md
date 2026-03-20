# TradingEngine Unit Test Cases

## Test File

`tests/unit/application/test_trading_engine.py`

## Test Purpose

Test the `TradingEngine` class, the standalone engine that streams market data,
aggregates candles, and runs the full trading pipeline independently of the
frontend WebSocket. All external dependencies (MarketDataPort, TradingSessionService,
ServiceGraph) are mocked so the tests run without network, GPU, or database access.

## Test Cases Overview

| Case ID | Feature Description                                       | Test Type     |
| ------- | --------------------------------------------------------- | ------------- |
| TE-01   | Engine initialises with correct defaults                  | Positive Test |
| TE-02   | Double start is idempotent                                | Positive Test |
| TE-03   | Start seeds history for all active symbols                | Positive Test |
| TE-04   | Start creates expected background tasks                   | Positive Test |
| TE-05   | Stop cancels all running tasks                            | Positive Test |
| TE-06   | Stop is idempotent when already stopped                   | Positive Test |
| TE-07   | Generation counter starts at zero                         | Positive Test |
| TE-08   | _notify_viewers increments generation under condition     | Positive Test |
| TE-09   | wait_for_update returns new generation on notify          | Positive Test |
| TE-10   | wait_for_update returns current gen on timeout            | Positive Test |
| TE-11   | get_latest_state returns None for unknown symbol          | Positive Test |
| TE-12   | get_latest_state returns deep copy of stored state        | Positive Test |
| TE-13   | get_all_latest_states returns all known states            | Positive Test |
| TE-14   | get_active_symbols returns a copy of symbol list          | Positive Test |
| TE-15   | SymbolCircuitBreaker starts closed                        | Positive Test |
| TE-16   | SymbolCircuitBreaker opens after max failures             | Positive Test |
| TE-17   | SymbolCircuitBreaker resets on success                    | Positive Test |
| TE-18   | SymbolCircuitBreaker isolates symbols                     | Positive Test |
| TE-19   | SymbolCircuitBreaker closes after cooldown                | Positive Test |
| TE-20   | SymbolCircuitBreaker half-open re-opens on failure        | Positive Test |
| TE-21   | _validate_tick rejects NaN open                           | Error Test    |
| TE-22   | _validate_tick rejects negative close                     | Error Test    |
| TE-23   | _validate_tick rejects high < low                         | Error Test    |
| TE-24   | _validate_tick rejects negative volume                    | Error Test    |
| TE-25   | _validate_tick passes valid tick                          | Positive Test |
| TE-26   | _interval_to_seconds minutes                              | Positive Test |
| TE-27   | _interval_to_seconds hours                                | Positive Test |
| TE-28   | _interval_to_seconds days                                 | Positive Test |
| TE-29   | _new_candle_state returns fresh state dict                | Positive Test |
| TE-30   | _aggregate_candle creates new candle on start change      | Positive Test |
| TE-31   | _aggregate_candle updates high/low/close within candle    | Positive Test |
| TE-32   | _aggregate_candle handles cumulative volume correctly     | Positive Test |
| TE-33   | _aggregate_candle handles cumulative volume reset         | Positive Test |
| TE-34   | _aggregate_candle computes delta from buy/sell quantities | Positive Test |
| TE-35   | _aggregate_candle falls back to body-ratio delta          | Positive Test |
| TE-36   | _candle_start floors timestamp to interval boundary       | Positive Test |

## Detailed Test Steps

### TE-01: Engine initialises with correct defaults

**Test Purpose**: Verify the TradingEngine constructor sets all internal dictionaries
and state from the ServiceGraph.

**Test Data Preparation**:
- Mock ServiceGraph with market_data, trading_session, active_symbols

**Test Steps**:
1. Create TradingEngine with mock graph
2. Assert generation is 0, _running is False, _latest_states is empty

**Expected Results**:
- `engine._generation == 0`
- `engine._running is False`
- `engine._latest_states == {}`
- `engine._active_symbols` matches the graph's list

### TE-02: Double start is idempotent

**Test Purpose**: Ensure calling start() twice does not duplicate tasks.

**Test Data Preparation**:
- Mock graph, patch _seed_history and _load_greeks to no-op

**Test Steps**:
1. await engine.start()
2. Capture task references
3. await engine.start() again
4. Assert tasks are unchanged (early return on _running)

**Expected Results**:
- Second start() is a no-op
- _running remains True

### TE-03: Start seeds history for all active symbols

**Test Purpose**: Verify start() calls fetch_history for each symbol.

**Test Data Preparation**:
- Mock market_data.fetch_history to return sample OHLC list

**Test Steps**:
1. await engine.start()
2. Check fetch_history was called for each active symbol

**Expected Results**:
- fetch_history called once per symbol

### TE-04: Start creates expected background tasks

**Test Purpose**: Verify start() creates _stream_task, _depth_task, _watchdog_task,
_stale_watchdog_task.

**Test Steps**:
1. await engine.start()
2. Assert all four task references are not None

**Expected Results**:
- All task attributes are asyncio.Task instances

### TE-05: Stop cancels all running tasks

**Test Purpose**: Verify stop() cancels tasks and sets _running to False.

**Test Steps**:
1. await engine.start()
2. await engine.stop()
3. Assert _running is False

**Expected Results**:
- engine._running is False

### TE-06: Stop is idempotent when already stopped

**Test Purpose**: stop() on an engine that was never started should not raise.

**Test Steps**:
1. Create engine without calling start()
2. await engine.stop()

**Expected Results**:
- No exception raised

### TE-07 to TE-10: Generation counter and wait_for_update

See code-level docstrings. Tests use asyncio.Condition to verify
the notification mechanism.

### TE-11 to TE-14: State access methods

Verify get_latest_state, get_all_latest_states, get_active_symbols
handle missing keys, deep copies, and list isolation correctly.

### TE-15 to TE-20: SymbolCircuitBreaker

Already covered by the existing test_circuit_breaker.py. Re-verified here
as part of engine integration tests with the same assertions.

### TE-21 to TE-25: _validate_tick

Test boundary and error conditions on the module-level _validate_tick function.

### TE-26 to TE-28: _interval_to_seconds

Unit tests for the pure helper function.

### TE-29: _new_candle_state

Verify the factory function returns a fresh dict with expected keys.

### TE-30 to TE-36: _aggregate_candle

Test candle aggregation logic: new candle boundaries, OHLC accumulation,
cumulative volume deltas, and fallback body-ratio delta.

## Test Considerations

### Mock Strategy
- ServiceGraph: fully mocked with MagicMock/AsyncMock
- MarketDataPort methods: AsyncMock for fetch_history, stream_full
- TradingSessionService: MagicMock with get_or_create_session
- asyncio tasks: patched with create_task to capture but not run loops
- is_market_open: always patched to True to avoid time-of-day interference

### Boundary Conditions
- Empty active_symbols list
- NaN / Inf / negative prices and volumes
- High < low on tick data
- Zero volume candle
- Cumulative volume reset (session rollover)

### Asynchronous Operations
- wait_for_update tested with real asyncio.Condition + asyncio.wait_for
- start/stop tested as async functions with proper event loop
- Streaming loops not executed (patched to return immediately)
