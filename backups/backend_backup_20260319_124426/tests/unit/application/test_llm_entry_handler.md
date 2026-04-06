# LLMEntryHandler Unit Test Cases

## Test File

`backend/tests/unit/application/test_llm_entry_handler.py`

## Test Purpose

Test the `LLMEntryHandler` class in complete isolation, with all external
dependencies (GenerativeAIService, EventBus, StoragePort, TradeManager,
entry_gate functions, session_context) replaced by mocks.

The handler is the critical gateway between raw market data and LLM-driven
entry decisions. Its responsibilities include:

- Pre-flight checks (`should_run`): throttle, model readiness, duplicate guard
- Three-Align Gate: block LLM calls when market state / location / confirmation
  do not align
- Session phase filtering (allow_entry flag)
- LLM inference delegation with timeout guard
- Response parsing and grade scoring (A/B/C setup quality)
- Signal construction and pending-signal handoff
- Error resilience (LLM crash, timeout, stale queue items)

## Test Cases Overview

| Case ID | Feature Description                          | Test Type     |
| ------- | -------------------------------------------- | ------------- |
| EH-01   | should_run blocks when ai_running is True    | Negative Test |
| EH-02   | should_run blocks when symbol has position   | Negative Test |
| EH-03   | should_run blocks when model not ready       | Negative Test |
| EH-04   | should_run blocks when degenerate AMT data   | Negative Test |
| EH-05   | should_run blocks during 10s cooldown        | Negative Test |
| EH-06   | should_run allows when all checks pass       | Positive Test |
| EH-07   | Three-Align gate blocks -> no LLM call       | Negative Test |
| EH-08   | Three-Align gate passes -> LLM called        | Positive Test |
| EH-09   | Session phase blocks entry (allow_entry=F)   | Negative Test |
| EH-10   | LLM timeout -> no crash, ai_running cleared  | Error Test    |
| EH-11   | LLM exception -> caught, logged, no crash    | Error Test    |
| EH-12   | LLM FLAT response -> no pending signal       | Negative Test |
| EH-13   | LLM LONG response -> pending signal set      | Positive Test |
| EH-14   | LLM SHORT blocked in BUY-only mode           | Negative Test |
| EH-15   | Queue full -> ai_running cleared gracefully   | Error Test    |
| EH-16   | Stale queue item dropped (>30s old)          | Boundary Test |
| EH-17   | Per-symbol worker thread created on first use | Positive Test |
| EH-18   | cleanup shuts down thread pools              | Positive Test |

## Detailed Test Steps

### EH-01: should_run blocks when ai_running is True

**Test Purpose**: Verify concurrent LLM call prevention via the `ai_running`
flag.

**Test Data Preparation**:
- Create LLMEntryHandler with mocked dependencies
- Prepare a valid AMTResult (poc > 0, vah > 0)

**Test Steps**:
1. Call `should_run(last_ai_time=0, ai_running=True, ...)`
2. Assert returns `False`

**Expected Results**:
- Returns False immediately without checking other conditions

### EH-02: should_run blocks when symbol has position

**Test Purpose**: Verify that the handler prevents duplicate entries on the
same symbol.

**Test Steps**:
1. Call `should_run(has_position=True, ...)`
2. Assert returns `False`

**Expected Results**:
- Returns False to prevent opening a second position on same symbol

### EH-03: should_run blocks when model not ready

**Test Purpose**: Verify model readiness check gates LLM calls.

**Test Steps**:
1. Mock gen_ai_service.is_ready() to return False
2. Call `should_run(ai_running=False, has_position=False, ...)`
3. Assert returns `False`

**Expected Results**:
- Returns False, preventing inference on unloaded model

### EH-04: should_run blocks when degenerate AMT data

**Test Purpose**: Verify guard against zero/negative POC or VAH.

**Test Steps**:
1. Create AMTResult with poc=0 or vah=0
2. Call should_run with this AMTResult
3. Assert returns False

**Expected Results**:
- Returns False to avoid meaningless analysis

### EH-05: should_run blocks during 10s cooldown

**Test Purpose**: Verify minimum 10-second gap between LLM calls.

**Test Steps**:
1. Set last_ai_time to current time (time.time())
2. Call should_run
3. Assert returns False (elapsed < 10)

**Expected Results**:
- Returns False when less than 10 seconds have elapsed

### EH-06: should_run allows when all checks pass

**Test Purpose**: Verify happy path where all preconditions are met.

**Test Steps**:
1. Set ai_running=False, has_position=False, model ready, valid AMT,
   last_ai_time=0 (well past cooldown)
2. Call should_run
3. Assert returns True

**Expected Results**:
- Returns True, allowing LLM entry analysis

### EH-07: Three-Align gate blocks -> no LLM call

**Test Purpose**: Verify that when three_align_check returns (False, _),
the LLM is never invoked and ai_running is cleared.

**Test Steps**:
1. Patch three_align_check to return (False, False)
2. Patch get_session_info to return allow_entry=True
3. Call run_entry
4. Assert gen_ai_service.analyze_market was NOT called
5. Assert session._ai_running is False
6. Assert session.last_ai_analysis["direction"] == "FLAT"

**Expected Results**:
- LLM is not called; session state reflects gate block with FLAT direction

### EH-08: Three-Align gate passes -> LLM called

**Test Purpose**: Verify that when gate passes, LLM inference is dispatched.

**Test Steps**:
1. Patch three_align_check to return (True, True)
2. Patch get_session_info to return allow_entry=True, allow_trend=False
3. Set gen_ai_service.analyze_market to return {"direction":"LONG","rationale":"test"}
4. Call run_entry and wait for worker thread
5. Assert gen_ai_service.analyze_market was called

**Expected Results**:
- LLM inference is triggered via the worker thread

### EH-09: Session phase blocks entry

**Test Purpose**: Verify Phase 5 (force_exit / no entry) blocks run_entry.

**Test Steps**:
1. Patch get_session_info to return allow_entry=False
2. Call run_entry
3. Assert session._ai_running is False
4. Assert session.last_ai_analysis["direction"] == "FLAT"

**Expected Results**:
- Entry blocked without invoking LLM or gate

### EH-10: LLM timeout -> no crash, ai_running cleared

**Test Purpose**: Verify timeout guard prevents hangs and clears state.

**Test Steps**:
1. Mock gen_ai_service.analyze_market to sleep(10)
2. Patch LLM_TIMEOUT_SECONDS to 0.1
3. Call run_entry and wait for worker
4. Assert session._ai_running is False (cleared on timeout)

**Expected Results**:
- TimeoutError caught, no crash, ai_running reset to False

### EH-11: LLM exception -> caught, logged, no crash

**Test Purpose**: Verify generic exception resilience.

**Test Steps**:
1. Mock gen_ai_service.analyze_market to raise RuntimeError
2. Call run_entry and wait for worker
3. Assert session._ai_running is False

**Expected Results**:
- Exception caught, handler continues operating

### EH-12: LLM FLAT response -> no pending signal

**Test Purpose**: Verify FLAT decisions do not generate trade signals.

**Test Steps**:
1. Mock LLM to return {"direction":"FLAT","rationale":"no setup"}
2. Call run_entry and wait for worker
3. Assert session._pending_signal is None

**Expected Results**:
- No pending signal enqueued

### EH-13: LLM LONG response -> pending signal set

**Test Purpose**: Verify valid entry decisions produce pending signals.

**Test Steps**:
1. Mock LLM to return {"direction":"LONG","rationale":"strong setup"}
2. Patch TradeManager.is_valid_rr to return True
3. Patch regime_detector.is_re_entry_blocked to return False
4. Call run_entry and wait for worker
5. Assert session._pending_signal is not None

**Expected Results**:
- Pending signal tuple (symbol, Signal) is set on session

### EH-14: LLM SHORT blocked in BUY-only mode

**Test Purpose**: Verify ALLOW_SHORT=false converts SHORT to FLAT.

**Test Steps**:
1. Patch settings.ALLOW_SHORT to False
2. Mock LLM to return {"direction":"SHORT","rationale":"sell"}
3. Call run_entry and wait for worker
4. Assert session.last_ai_analysis["direction"] == "FLAT"

**Expected Results**:
- SHORT direction overridden to FLAT

### EH-15: Queue full -> ai_running cleared gracefully

**Test Purpose**: Verify queue overflow does not leave ai_running stuck.

**Test Steps**:
1. Create handler and fill the symbol's queue to capacity (10 items)
2. Call run_entry which attempts put_nowait
3. Assert session._ai_running is False (cleared on queue.Full)

**Expected Results**:
- ai_running cleared so the handler is not permanently stuck

### EH-16: Stale queue item dropped

**Test Purpose**: Verify items older than 30 seconds are discarded.

**Test Steps**:
1. Enqueue item with enqueue_time = time.time() - 40
2. Worker picks it up
3. Assert the LLM was NOT called for the stale item
4. Assert session._ai_running is False

**Expected Results**:
- Stale items silently dropped

### EH-17: Per-symbol worker thread created

**Test Purpose**: Verify lazy creation of worker threads per symbol.

**Test Steps**:
1. Call run_entry for symbol "NIFTY"
2. Assert "NIFTY" in handler._llm_queues
3. Assert "NIFTY" in handler._worker_threads

**Expected Results**:
- Worker infrastructure created on first use

### EH-18: cleanup shuts down thread pools

**Test Purpose**: Verify orderly shutdown.

**Test Steps**:
1. Call handler.cleanup()
2. Assert executor pools are shut down

**Expected Results**:
- No hanging threads after cleanup

## Test Considerations

### Mock Strategy
- `GenerativeAIService`: Mock with `is_ready()` and `analyze_market()` stubs
- `EventBusPort`: Mock with `publish()` and `subscribe()` stubs
- `StoragePort`: Mock or None
- `entry_gate.three_align_check`: Patched to control gate pass/fail
- `entry_gate.cluster_aggressive_prints`: Patched to return []
- `session_context.get_session_info`: Patched to return controllable SessionInfo
- `app.config.settings`: Patched for ALLOW_SHORT, LLM_TIMEOUT_SECONDS

### Boundary Conditions
- Zero POC / VAH in AMTResult
- Queue capacity (10 items)
- Staleness threshold (30 seconds)
- Cooldown boundary (exactly 10 seconds)

### Asynchronous Operations
- Worker threads process queue items asynchronously; tests must join worker
  queues or wait for them to drain before asserting outcomes.
- Use `queue.join()` after `run_entry()` to synchronize.
