# TDD Implementation Plan: Fix P0 Integration Gaps

**Created**: 2026-05-06  
**Status**: Ready for Implementation  
**Estimated Effort**: 3-5 days (4 P0 blockers)

---

## Overview

This plan implements the 4 critical blockers identified in the code review using TDD (Test-Driven Development) with vertical slices. Each blocker is tackled one at a time through red-green-refactor cycles.

### The 4 P0 Blockers

1. **Wire SessionStateManager to FastAPI** - Enable tick processing
2. **Create DhanFeedSource** - Stream live ticks from broker to pipeline
3. **Add AMTComputationStage** - Compute AMT analysis on each candle
4. **Wire AMT to WebSocket State** - Stream AMT results to frontend

### TDD Workflow

For each blocker:
```
RED   → Write test that fails (behavior specification)
GREEN → Write minimal code to pass test
REFACTOR → Clean up while keeping tests green
REPEAT → Next behavior
```

---

## BLOCKER 1: Wire SessionStateManager to FastAPI

### Problem
`_get_session_service()` in `gameloop.py` returns `None` because `app.state.session_service` is never set in `main.py` lifespan.

### Behaviors to Test
1. SessionStateManager can be instantiated and registered to FastAPI app
2. Client-driven mode can process ticks via `process_tick()`
3. Session state persists across multiple tick updates
4. WebSocket receives state updates after processing

### TDD Cycle 1.1: SessionStateManager Instantiation

**Test**: `test_session_state_manager_lifecycle()`

```python
# backendv2/tests/integration/test_session_manager_integration.py

def test_session_state_manager_lifecycle():
    """SessionStateManager is created and registered during app startup."""
    from app.api.main import app
    from app.application.service.session_state_manager import SessionStateManager
    
    # Simulate lifespan startup
    with TestClient(app) as client:
        session_service = app.state.session_service
        assert session_service is not None
        assert isinstance(session_service, SessionStateManager)
```

**RED** → Test fails (AttributeError: session_service doesn't exist)

**GREEN** → Add to `main.py` lifespan:
```python
from app.application.service.session_state_manager import SessionStateManager

# After storage creation:
application.state.session_service = SessionStateManager(storage=application.state.storage)
```

**Verify**: Test passes ✓

---

### TDD Cycle 1.2: Client-Driven Tick Processing

**Test**: `test_process_tick_creates_session()`

```python
def test_process_tick_creates_session():
    """Processing a tick creates a session and returns state."""
    from app.api.websocket.gameloop import _get_session_service
    from app.domain.trading.model.value_objects import OHLC
    
    with TestClient(app) as client:
        session_service = _get_session_service(app)
        assert session_service is not None
        
        # Process tick
        tick = OHLC(
            time="2026-05-06T09:15:00",
            open=7250.0, high=7255.0, low=7248.0, close=7253.0,
            volume=100.0, vwap=7252.0, taker_buy_volume=60.0, delta=20.0
        )
        
        state = session_service.process_tick("CRUDEOIL", tick, None)
        assert state is not None
        assert state.symbol == "CRUDEOIL"
        assert len(state.data) > 0
```

**RED** → Test fails (process_tick doesn't exist or returns None)

**GREEN** → Add `process_tick()` to `SessionStateManager`:
```python
def process_tick(self, symbol: str, tick: OHLC, order_book: OrderBook | None) -> SessionState:
    session = self.get_or_create_session(symbol)
    with session._lock:
        session.data.append(tick)
        session._last_tick_time = time.time()
    return session
```

**Verify**: Test passes ✓

---

### TDD Cycle 1.3: WebSocket State Return

**Test**: `test_gameloop_returns_state_after_tick()`

```python
async def test_gameloop_returns_state_after_tick():
    """WebSocket gameloop returns state after processing tick."""
    from fastapi.testclient import TestClient
    import json
    
    with TestClient(app) as client:
        with client.websocket_connect("/api/trading/ws/gameloop") as ws:
            # Send tick in client-driven mode
            ws.send_json({
                "symbol": "CRUDEOIL",
                "tick": {
                    "time": "2026-05-06T09:15:00",
                    "open": 7250.0, "high": 7255.0,
                    "low": 7248.0, "close": 7253.0,
                    "volume": 100.0
                }
            })
            
            response = ws.receive_json()
            assert "error" not in response
            assert response.get("_symbol") == "CRUDEOIL"
```

**RED** → Test fails (WebSocket returns error or None)

**GREEN** → Fix `_get_session_service()` to find our new service:
```python
def _get_session_service(app):
    state = getattr(app, "state", None)
    if state is None:
        return None
    return (
        getattr(state, "trading_session", None)
        or getattr(state, "session_service", None)  # ← Now exists!
    )
```

**Verify**: Test passes ✓

---

### Acceptance Criteria for Blocker 1

- [ ] SessionStateManager instantiated in lifespan
- [ ] `process_tick()` creates sessions on first tick
- [ ] WebSocket returns state (not null) after tick
- [ ] Multiple ticks accumulate in session.data
- [ ] All tests pass: `pytest tests/integration/test_session_manager_integration.py -v`

---

## BLOCKER 2: Create DhanFeedSource

### Problem
`RuntimeOrchestrator` requires a `FeedSource` but DhanAdapter ticks never reach the pipeline.

### Behaviors to Test
1. DhanFeedSource wraps DhanAdapter and yields ticks
2. Ticks are normalized to pipeline `Tick` format
3. Feed starts/stops cleanly
4. Feed handles adapter disconnection gracefully

### TDD Cycle 2.1: Feed Source Interface

**Test**: `test_dhan_feed_source_yields_ticks()`

```python
# backendv2/tests/unit/runtime/feeds/test_dhan_feed.py

def test_dhan_feed_source_yields_ticks():
    """DhanFeedSource yields normalized ticks from adapter."""
    from unittest.mock import Mock
    from app.runtime.feeds.dhan_feed import DhanFeedSource
    
    # Mock DhanAdapter
    mock_adapter = Mock()
    mock_adapter.get_next_tick.return_value = {
        "symbol": "CRUDEOIL",
        "price": 7253.0,
        "volume": 100,
        "timestamp": 1714982100.0
    }
    
    feed = DhanFeedSource(mock_adapter)
    feed.start()
    
    tick = next(feed.stream())
    
    assert tick.symbol == "CRUDEOIL"
    assert tick.price == 7253.0
    assert tick.volume == 100
    
    feed.stop()
```

**RED** → Module doesn't exist

**GREEN** → Create `backendv2/app/runtime/feeds/dhan_feed.py`:
```python
from app.runtime.feeds import FeedSource
from app.runtime.pipeline.events import Tick

class DhanFeedSource(FeedSource):
    def __init__(self, market_data):
        self._market_data = market_data
        self._running = False
    
    def start(self):
        self._running = True
    
    def stop(self):
        self._running = False
    
    def stream(self):
        while self._running:
            raw = self._market_data.get_next_tick()
            if raw:
                yield Tick(
                    symbol=raw["symbol"],
                    price=raw["price"],
                    volume=raw["volume"],
                    timestamp=raw["timestamp"]
                )
            time.sleep(0.1)
```

**Verify**: Test passes ✓

---

### TDD Cycle 2.2: Feed Handles Empty Ticks

**Test**: `test_dhan_feed_skips_empty_ticks()`

```python
def test_dhan_feed_skips_empty_ticks():
    """Feed skips None/empty ticks without yielding."""
    from unittest.mock import Mock
    from app.runtime.feeds.dhan_feed import DhanFeedSource
    import threading
    import time
    
    mock_adapter = Mock()
    # Return None twice, then a valid tick
    mock_adapter.get_next_tick.side_effect = [None, None, {
        "symbol": "CRUDEOIL", "price": 7253.0,
        "volume": 100, "timestamp": 1714982100.0
    }]
    
    feed = DhanFeedSource(mock_adapter)
    feed.start()
    
    ticks = []
    def collect():
        for tick in feed.stream():
            ticks.append(tick)
    
    thread = threading.Thread(target=collect)
    thread.start()
    time.sleep(0.5)  # Wait for ticks to process
    feed.stop()
    thread.join(timeout=1.0)
    
    assert len(ticks) == 1  # Only the valid tick
    assert ticks[0].symbol == "CRUDEOIL"
```

**RED** → Test fails (feed yields None or hangs)

**GREEN** → Add None check:
```python
def stream(self):
    while self._running:
        raw = self._market_data.get_next_tick()
        if raw is None:
            time.sleep(0.1)
            continue
        if raw.get("price") is None or raw.get("price") <= 0:
            time.sleep(0.1)
            continue
        yield Tick(
            symbol=raw["symbol"],
            price=raw["price"],
            volume=raw["volume"],
            timestamp=raw["timestamp"]
        )
        time.sleep(0.1)
```

**Verify**: Test passes ✓

---

### TDD Cycle 2.3: Feed Integration with Orchestrator

**Test**: `test_feed_integrated_with_orchestrator()`

```python
def test_feed_integrated_with_orchestrator():
    """Orchestrator can create session with DhanFeedSource."""
    from unittest.mock import Mock
    from app.runtime.orchestrator import RuntimeOrchestrator
    from app.runtime.feeds.dhan_feed import DhanFeedSource
    
    mock_adapter = Mock()
    mock_adapter.get_next_tick.return_value = None  # No ticks yet
    
    orchestrator = RuntimeOrchestrator()
    feed = DhanFeedSource(mock_adapter)
    
    session = orchestrator.create_live_session(
        "test_001",
        feed,
        ["CRUDEOIL"]
    )
    
    assert session is not None
    assert session.symbols == ["CRUDEOIL"]
    
    # Start session
    orchestrator.start("test_001")
    assert session.is_running
    
    # Stop session
    orchestrator.stop("test_001")
    assert not session.is_running
```

**RED** → Test fails (orchestrator doesn't have create_live_session or feed issues)

**GREEN** → Already exists in `registry.py`, verify it works. May need to fix:
```python
def create_live_session(self, session_id: str, feed: FeedSource, symbols: list[str]):
    session = SessionRuntime(feed=feed, symbols=symbols, storage=self._storage)
    self._sessions[session_id] = session
    return session
```

**Verify**: Test passes ✓

---

### Acceptance Criteria for Blocker 2

- [ ] DhanFeedSource wraps DhanAdapter
- [ ] Feed yields normalized Tick objects
- [ ] Feed handles None/invalid ticks gracefully
- [ ] Feed integrates with RuntimeOrchestrator
- [ ] All tests pass: `pytest tests/unit/runtime/feeds/test_dhan_feed.py -v`

---

## BLOCKER 3: Add AMTComputationStage

### Problem
Pipeline has `MarketStructureAnalysis` stage but it never calls `AMTAnalyzer.analyze()`. AMT results are never computed.

### Behaviors to Test
1. AMTComputationStage processes candles and returns AMTResult
2. Stage maintains per-symbol candle history
3. Stage limits history to last N candles (memory management)
4. Stage integrates into SessionRuntime pipeline

### TDD Cycle 3.1: AMT Stage Processes Candle

**Test**: `test_amt_stage_computes_result()`

```python
# backendv2/tests/unit/runtime/pipeline/test_amt_computation.py

def test_amt_stage_computes_result():
    """AMTComputationStage processes candle and returns AMTResult."""
    from app.runtime.pipeline.amt_computation import AMTComputationStage
    from app.domain.amt.service.amt_analyzer import AMTAnalyzer
    from app.runtime.pipeline.events import Candle, CandleTimeframe
    
    stage = AMTComputationStage(AMTAnalyzer())
    
    candle = Candle(
        symbol="CRUDEOIL",
        timeframe=CandleTimeframe.M1,
        open=7250.0, high=7255.0, low=7248.0, close=7253.0,
        volume=100.0, timestamp=1714982100.0
    )
    
    result = stage.process(candle)
    
    assert result is not None
    assert hasattr(result, "market_state")
    assert hasattr(result, "poc")
    # First candle may have default values, but structure should exist
```

**RED** → Module doesn't exist

**GREEN** → Create `backendv2/app/runtime/pipeline/amt_computation.py`:
```python
from app.domain.amt.service.amt_analyzer import AMTAnalyzer
from app.domain.trading.model.value_objects import AMTResult
from app.runtime.pipeline.events import Candle

class AMTComputationStage:
    def __init__(self, analyzer: AMTAnalyzer, max_history: int = 200):
        self._analyzer = analyzer
        self._max_history = max_history
        self._history = {}
    
    def process(self, candle: Candle) -> AMTResult:
        sym = candle.symbol
        bars = self._history.setdefault(sym, [])
        
        # Convert candle to bar dict
        bar = {
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
            "buyVolume": candle.volume * 0.6,  # Estimate
            "sellVolume": candle.volume * 0.4,
        }
        bars.append(bar)
        
        # Limit history
        if len(bars) > self._max_history:
            bars[:] = bars[-self._max_history:]
        
        return self._analyzer.analyze(bars, symbol=sym)
    
    def snapshot(self):
        return {sym: len(bars) for sym, bars in self._history.items()}
```

**Verify**: Test passes ✓

---

### TDD Cycle 3.2: Stage Maintains Per-Symbol History

**Test**: `test_amt_stage_maintains_history_per_symbol()`

```python
def test_amt_stage_maintains_history_per_symbol():
    """Stage maintains separate history for each symbol."""
    from app.runtime.pipeline.amt_computation import AMTComputationStage
    from app.domain.amt.service.amt_analyzer import AMTAnalyzer
    from app.runtime.pipeline.events import Candle, CandleTimeframe
    
    stage = AMTComputationStage(AMTAnalyzer())
    
    # Process 3 candles for CRUDEOIL
    for i in range(3):
        candle = Candle(
            symbol="CRUDEOIL", timeframe=CandleTimeframe.M1,
            open=7250.0 + i, high=7255.0 + i,
            low=7248.0 + i, close=7253.0 + i,
            volume=100.0, timestamp=1714982100.0 + i*60
        )
        stage.process(candle)
    
    # Process 2 candles for NATURALGAS
    for i in range(2):
        candle = Candle(
            symbol="NATURALGAS", timeframe=CandleTimeframe.M1,
            open=285.0 + i, high=287.0 + i,
            low=284.0 + i, close=286.0 + i,
            volume=50.0, timestamp=1714982100.0 + i*60
        )
        stage.process(candle)
    
    snap = stage.snapshot()
    assert snap["CRUDEOIL"] == 3
    assert snap["NATURALGAS"] == 2
```

**RED** → Test fails (history not maintained correctly)

**GREEN** → Already implemented in cycle 3.1, verify ✓

**Verify**: Test passes ✓

---

### TDD Cycle 3.3: Stage Limits History Size

**Test**: `test_amt_stage_limits_history()`

```python
def test_amt_stage_limits_history():
    """Stage limits history to max_history candles."""
    from app.runtime.pipeline.amt_computation import AMTComputationStage
    from app.domain.amt.service.amt_analyzer import AMTAnalyzer
    from app.runtime.pipeline.events import Candle, CandleTimeframe
    
    stage = AMTComputationStage(AMTAnalyzer(), max_history=5)
    
    # Process 10 candles
    for i in range(10):
        candle = Candle(
            symbol="CRUDEOIL", timeframe=CandleTimeframe.M1,
            open=7250.0 + i, high=7255.0 + i,
            low=7248.0 + i, close=7253.0 + i,
            volume=100.0, timestamp=1714982100.0 + i*60
        )
        stage.process(candle)
    
    snap = stage.snapshot()
    assert snap["CRUDEOIL"] == 5  # Limited to 5
```

**RED** → Test fails (history grows beyond limit)

**GREEN** → Already implemented in cycle 3.1:
```python
if len(bars) > self._max_history:
    bars[:] = bars[-self._max_history:]
```

**Verify**: Test passes ✓

---

### TDD Cycle 3.4: Integrate into SessionRuntime

**Test**: `test_session_runtime_includes_amt_stage()`

```python
def test_session_runtime_includes_amt_stage():
    """SessionRuntime processes ticks and produces AMT results."""
    from app.runtime.orchestrator.session import SessionRuntime
    from app.runtime.feeds import FeedSource
    from app.domain.shared.port.storage import IStorage
    
    # Create mock feed that yields one tick
    class MockFeed(FeedSource):
        def __init__(self):
            self._running = False
            self._ticks_sent = 0
        
        def start(self):
            self._running = True
        
        def stop(self):
            self._running = False
        
        def stream(self):
            from app.runtime.pipeline.events import Tick
            while self._running and self._ticks_sent < 1:
                self._ticks_sent += 1
                yield Tick(
                    symbol="CRUDEOIL",
                    price=7253.0,
                    volume=100,
                    timestamp=1714982100.0
                )
    
    feed = MockFeed()
    session = SessionRuntime(feed=feed, symbols=["CRUDEOIL"], storage=None)
    
    # Verify AMT stage exists
    assert hasattr(session, "_amt")
    
    session.start()
    events = session.run_once(max_ticks=1)
    session.stop()
    
    # Check snapshot includes AMT
    snap = session.snapshot("CRUDEOIL")
    assert "market_structure" in snap or "amt" in snap
```

**RED** → Test fails (SessionRuntime doesn't have _amt stage)

**GREEN** → Add to `SessionRuntime.__init__()`:
```python
from app.runtime.pipeline.amt_computation import AMTComputationStage
from app.domain.amt.service.amt_analyzer import AMTAnalyzer

# In __init__:
self._amt = AMTComputationStage(AMTAnalyzer())

# In _process_tick(), after candle creation:
if candle_events:
    for candle in candle_events:
        if candle.timeframe == CandleTimeframe.M1:
            amt_result = self._amt.process(candle)
            # Store in session state for WebSocket
            self._history[candle.symbol].append({
                "amt": amt_result_to_dto(amt_result)
            })
```

**Verify**: Test passes ✓

---

### Acceptance Criteria for Blocker 3

- [ ] AMTComputationStage processes candles
- [ ] Stage maintains per-symbol history (max 200 candles)
- [ ] Stage returns AMTResult with all fields
- [ ] Stage integrated into SessionRuntime pipeline
- [ ] All tests pass: `pytest tests/unit/runtime/pipeline/test_amt_computation.py -v`

---

## BLOCKER 4: Wire AMT to WebSocket State

### Problem
Even if AMT is computed, it's never serialized and sent to frontend via WebSocket.

### Behaviors to Test
1. AMTResult is serialized to DTO format
2. WebSocket state dict includes "amt" key with serialized data
3. Frontend receives AMT data in delta updates
4. AMT data clears stale values on session reset

### TDD Cycle 4.1: AMT Serialization in State

**Test**: `test_amt_serialized_in_state()`

```python
# backendv2/tests/integration/test_amt_websocket_state.py

def test_amt_serialized_in_state():
    """AMTResult is serialized and included in WebSocket state."""
    from app.infrastructure.serialization.schemas import amt_result_to_dto
    from app.domain.trading.model.value_objects import AMTResult
    
    # Create AMTResult
    result = AMTResult(
        market_state="IMBALANCED",
        poc=7253.0,
        value_area_high=7260.0,
        value_area_low=7245.0,
        aggression=0.75,
        cvd_slope=150.0,
        session_vwap=7252.0,
    )
    
    dto = amt_result_to_dto(result)
    
    assert dto["marketState"] == "IMBALANCED"
    assert dto["poc"] == 7253.0
    assert dto["valueAreaHigh"] == 7260.0
    assert dto["valueAreaLow"] == 7245.0
    assert dto["sessionVwap"] == 7252.0
```

**RED** → May fail if AMTResult fields don't match serializer expectations

**GREEN** → Fix `amt_result_to_dto()` to handle missing fields:
```python
# Already exists in schemas.py, verify all fields map correctly
# May need to add missing fields from AMTResult dataclass
```

**Verify**: Test passes ✓

---

### TDD Cycle 4.2: WebSocket State Includes AMT

**Test**: `test_websocket_state_includes_amt()`

```python
def test_websocket_state_includes_amt():
    """WebSocket state dict includes serialized AMT data."""
    from app.runtime.orchestrator.session import SessionRuntime
    from app.runtime.feeds import FeedSource
    
    class MockFeed(FeedSource):
        def __init__(self):
            self._running = False
            self._ticks_sent = 0
        
        def start(self):
            self._running = True
        
        def stop(self):
            self._running = False
        
        def stream(self):
            from app.runtime.pipeline.events import Tick
            while self._running and self._ticks_sent < 5:
                self._ticks_sent += 1
                yield Tick(
                    symbol="CRUDEOIL",
                    price=7253.0,
                    volume=100,
                    timestamp=1714982100.0 + self._ticks_sent * 60
                )
    
    feed = MockFeed()
    session = SessionRuntime(feed=feed, symbols=["CRUDEOIL"], storage=None)
    session.start()
    session.run_once(max_ticks=5)
    
    snap = session.snapshot("CRUDEOIL")
    
    # Verify AMT is in snapshot
    assert "amt" in snap or "market_structure" in snap
    if "amt" in snap:
        assert isinstance(snap["amt"], dict)
        assert "marketState" in snap["amt"]
        assert "poc" in snap["amt"]
    
    session.stop()
```

**RED** → Test fails (snapshot doesn't include AMT)

**GREEN** → Add to `SessionRuntime.snapshot()`:
```python
def snapshot(self, symbol: str | None = None) -> dict:
    snapshot = {
        # ... existing keys ...
        "amt": self._amt.snapshot(),  # ← Add this
    }
    # ... rest of snapshot logic ...
```

Actually, need to store AMT results per tick, not just stage snapshot:
```python
# In SessionRuntime, add:
self._latest_amt = {}

# In _process_tick(), after AMT computation:
self._latest_amt[candle.symbol] = amt_result_to_dto(amt_result)

# In snapshot():
snapshot["amt"] = self._latest_amt.get(symbol)
```

**Verify**: Test passes ✓

---

### TDD Cycle 4.3: End-to-End WebSocket Stream

**Test**: `test_e2e_websocket_streams_amt()`

```python
async def test_e2e_websocket_streams_amt():
    """End-to-end: WebSocket streams AMT data to client."""
    from fastapi.testclient import TestClient
    from app.api.main import app
    import json
    
    # Start app with test feed
    with TestClient(app) as client:
        with client.websocket_connect("/api/trading/ws/gameloop") as ws:
            # Subscribe to symbol
            ws.send_json({"subscribe": "CRUDEOIL"})
            
            # Receive history_loaded
            history_msg = ws.receive_json()
            assert history_msg["status"] == "history_loaded"
            
            # Receive full state
            state_msg = ws.receive_json()
            assert state_msg["_symbol"] == "CRUDEOIL"
            assert "amt" in state_msg
            
            # Verify AMT structure
            if state_msg["amt"] is not None:
                assert "marketState" in state_msg["amt"]
                assert "poc" in state_msg["amt"]
                assert "valueAreaHigh" in state_msg["amt"]
                assert "valueAreaLow" in state_msg["amt"]
```

**RED** → Test fails (WebSocket doesn't stream AMT or AMT is null)

**GREEN** → Ensure:
1. Feed is started in lifespan
2. AMT stage is in pipeline
3. Snapshot includes AMT
4. WebSocket viewer loop sends state with AMT

May need to fix `main.py` lifespan:
```python
# After creating orchestrator and session_service:
from app.runtime.feeds.dhan_feed import DhanFeedSource

feed = DhanFeedSource(market_data)
session = orchestrator.create_live_session("live_001", feed, active_symbols)
orchestrator.bind_broker("live_001", market_data)
orchestrator.start("live_001")
```

**Verify**: Test passes ✓

---

### Acceptance Criteria for Blocker 4

- [ ] AMTResult serialized to DTO with all fields
- [ ] WebSocket state includes "amt" key
- [ ] Frontend receives AMT in delta updates
- [ ] End-to-end test passes (tick → AMT → WebSocket → state)
- [ ] All tests pass: `pytest tests/integration/test_amt_websocket_state.py -v`

---

## IMPLEMENTATION ORDER

### Day 1: Blocker 1 (SessionStateManager)
1. Write test 1.1 → Implement lifespan wiring
2. Write test 1.2 → Implement process_tick()
3. Write test 1.3 → Fix _get_session_service()
4. Run all tests, refactor if needed

### Day 2: Blocker 2 (DhanFeedSource)
1. Write test 2.1 → Create DhanFeedSource
2. Write test 2.2 → Handle empty ticks
3. Write test 2.3 → Integrate with orchestrator
4. Run all tests, refactor if needed

### Day 3: Blocker 3 (AMTComputationStage)
1. Write test 3.1 → Create AMT stage
2. Write test 3.2 → Per-symbol history
3. Write test 3.3 → History limit
4. Write test 3.4 → Integrate into SessionRuntime
5. Run all tests, refactor if needed

### Day 4-5: Blocker 4 (WebSocket AMT)
1. Write test 4.1 → Verify serialization
2. Write test 4.2 → Include AMT in snapshot
3. Write test 4.3 → End-to-end WebSocket
4. Run all tests, refactor if needed
5. **Integration test**: Start backend, connect frontend, verify AMT renders

---

## RUNNING TESTS

### Run All Tests for a Blocker
```bash
# Blocker 1
pytest tests/integration/test_session_manager_integration.py -v

# Blocker 2
pytest tests/unit/runtime/feeds/test_dhan_feed.py -v

# Blocker 3
pytest tests/unit/runtime/pipeline/test_amt_computation.py -v

# Blocker 4
pytest tests/integration/test_amt_websocket_state.py -v
```

### Run Single Test
```bash
pytest tests/integration/test_session_manager_integration.py::test_session_state_manager_lifecycle -v
```

### Watch Mode (TDD)
```bash
pytest tests/ -v --watch
```

---

## REFACTORING GUIDELINES

After all tests pass for a blocker:

1. **Extract duplication**: Common test setup → fixtures
2. **Deepen modules**: Move complexity behind simple interfaces
3. **Apply SOLID**: Single responsibility, dependency inversion
4. **Run tests after each change**: Never refactor while RED
5. **Keep commits small**: One refactor per commit

---

## ACCEPTANCE: ALL BLOCKERS COMPLETE

- [ ] All 4 blockers implemented and tested
- [ ] All tests pass: `pytest tests/ -v`
- [ ] Backend starts without errors
- [ ] Frontend connects and receives AMT data
- [ ] Chart renders Volume Profile, POC, VAH, VAL
- [ ] ModelStateBanner shows real AMT state
- [ ] No console errors in browser dev tools

---

## NEXT STEPS (After P0 Blockers)

Once all 4 blockers are complete:

1. **P1: Wire LLM Stage** - AMTResult → LLM inference → parse → state
2. **P1: Wire Agent Pipeline** - Regime + AMT → playbook → decision
3. **P2: Position Lifecycle** - Entry → pyramid → breakeven → scale-out → trail
4. **P2: Execute Trades** - Signal → broker order → fill → position update
5. **P2: Risk Circuit Breakers** - Daily loss limit, consecutive losses
6. **P3: Session Rules** - NY/London gates, EOD close, house money

---

## TROUBLESHOOTING

### Test Fails with Import Error
```bash
# Check Python path
cd backendv2
python -c "import sys; print(sys.path)"

# Ensure you're in venv
which python  # Should show backendv2/venv/bin/python
```

### Test Fails with ModuleNotFoundError
```bash
# Install dependencies
cd backendv2
pip install -r requirements.txt
pip install -e .
```

### WebSocket Test Times Out
```bash
# Increase timeout in test
# Add: client.timeout = 30  # seconds
```

### AMT Result Has All Zeros
- Check if enough candles accumulated (need >10 for meaningful analysis)
- Verify candle data has valid OHLC values
- Check AMTAnalyzer bucket_size estimation

---

**Ready to start? Begin with Blocker 1, Test 1.1!**
