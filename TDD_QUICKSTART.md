# TDD Quick Start: Fix P0 Blockers

## Prerequisites

```bash
# Activate backendv2 venv
cd /Users/apple/Downloads/v5-of-glassytrade-ai/backendv2
source venv/bin/activate

# Verify pytest works
pytest --version

# Install dev dependencies if needed
pip install pytest pytest-asyncio pytest-watch
```

## Start TDD Cycle

### BLOCKER 1: Wire SessionStateManager

**Step 1: Create Test File**

```bash
cd /Users/apple/Downloads/v5-of-glassytrade-ai/backendv2
mkdir -p tests/integration
touch tests/integration/test_session_manager_integration.py
```

**Step 2: Write First Test (RED)**

Edit `tests/integration/test_session_manager_integration.py`:

```python
"""Integration tests for SessionStateManager wiring to FastAPI."""
import pytest
from fastapi.testclient import TestClient
from app.api.main import app
from app.application.service.session_state_manager import SessionStateManager


class TestSessionManagerLifecycle:
    """Test SessionStateManager is properly wired during app startup."""
    
    def test_session_service_registered_in_lifespan(self):
        """SessionStateManager is created and accessible via app.state."""
        with TestClient(app) as client:
            # Verify session_service exists
            assert hasattr(app.state, 'session_service')
            assert app.state.session_service is not None
            assert isinstance(app.state.session_service, SessionStateManager)
```

**Step 3: Run Test (Should FAIL)**

```bash
pytest tests/integration/test_session_manager_integration.py::TestSessionManagerLifecycle::test_session_service_registered_in_lifespan -v
```

Expected: `FAILED` with `AttributeError: session_service`

**Step 4: Implement Fix (GREEN)**

Edit `backendv2/app/api/main.py`, add import after line 45:

```python
from app.application.service.session_state_manager import SessionStateManager
```

Add after line 75 (after `application.state.storage` creation):

```python
application.state.session_service = SessionStateManager(storage=application.state.storage)
```

**Step 5: Run Test Again (Should PASS)**

```bash
pytest tests/integration/test_session_manager_integration.py::TestSessionManagerLifecycle::test_session_service_registered_in_lifespan -v
```

Expected: `PASSED` ✓

**Step 6: Write Second Test (RED)**

Add to test file:

```python
def test_process_tick_creates_session(self):
    """Processing a tick creates session and returns state."""
    from app.domain.trading.model.value_objects import OHLC
    
    with TestClient(app) as client:
        session_service = app.state.session_service
        
        # Create test tick
        tick = OHLC(
            time="2026-05-06T09:15:00",
            open=7250.0, high=7255.0, low=7248.0, close=7253.0,
            volume=100.0, vwap=7252.0, taker_buy_volume=60.0, delta=20.0
        )
        
        # Process tick
        state = session_service.process_tick("CRUDEOIL", tick, None)
        
        # Verify session created
        assert state is not None
        assert state.symbol == "CRUDEOIL"
        assert len(state.data) == 1
        assert state.data[0].close == 7253.0
```

**Step 7: Run Test (Should FAIL)**

```bash
pytest tests/integration/test_session_manager_integration.py::TestSessionManagerLifecycle::test_process_tick_creates_session -v
```

Expected: `FAILED` with `AttributeError: 'SessionStateManager' object has no attribute 'process_tick'`

**Step 8: Implement process_tick() (GREEN)**

Edit `backendv2/app/application/service/session_state_manager.py`, add method to `SessionStateManager` class:

```python
def process_tick(self, symbol: str, tick, order_book=None) -> SessionState:
    """Process incoming tick and update session state."""
    session = self.get_or_create_session(symbol)
    with session._lock:
        session.data.append(tick)
        session._last_tick_time = time.time()
    return session
```

**Step 9: Run All Blocker 1 Tests**

```bash
pytest tests/integration/test_session_manager_integration.py -v
```

Expected: All PASSED ✓

---

## Continue Pattern

Repeat this cycle for remaining tests in the plan:
- Test 1.3: WebSocket state return
- Test 2.1-2.3: DhanFeedSource
- Test 3.1-3.4: AMTComputationStage
- Test 4.1-4.3: WebSocket AMT wiring

---

## Useful Commands

### Run Single Test
```bash
pytest tests/integration/test_session_manager_integration.py::TestSessionManagerLifecycle::test_session_service_registered_in_lifespan -v
```

### Run All Tests for Blocker
```bash
pytest tests/integration/test_session_manager_integration.py -v
```

### Watch Mode (Auto-rerun on file change)
```bash
ptw tests/integration/test_session_manager_integration.py
```

### Run with Coverage
```bash
pytest tests/integration/test_session_manager_integration.py --cov=app.application.service.session_state_manager --cov-report=term-missing
```

### Debug Failed Test
```bash
pytest tests/integration/test_session_manager_integration.py -v --tb=long --capture=no
```

---

## Commit Strategy

After each test passes:

```bash
# Commit test + implementation together
git add tests/integration/test_session_manager_integration.py
git add backendv2/app/api/main.py
git add backendv2/app/application/service/session_state_manager.py
git commit -m "feat: wire SessionStateManager to FastAPI (Blocker 1.1)

- Add SessionStateManager to app.state in lifespan
- Implement process_tick() method
- Add integration test for session creation

TDD Cycle: RED→GREEN ✓"
```

---

## Troubleshooting

### Import Error: No module named 'app'
```bash
# Ensure you're in backendv2 directory and venv is active
cd /Users/apple/Downloads/v5-of-glassytrade-ai/backendv2
source venv/bin/activate
python -c "import app; print(app.__file__)"
```

### TestClient Fails with Lifespan Error
```bash
# Add this to test file if needed
@pytest.fixture(autouse=True)
def setup_app():
    """Ensure app lifespan runs."""
    with TestClient(app) as client:
        yield client
```

### OHLC Import Fails
```bash
# Check correct import path
python -c "from app.domain.trading.model.value_objects import OHLC; print(OHLC)"
```

---

## Next Steps

1. ✅ Complete Blocker 1 (SessionStateManager)
2. ⏳ Move to Blocker 2 (DhanFeedSource)
3. ⏳ Move to Blocker 3 (AMTComputationStage)
4. ⏳ Move to Blocker 4 (WebSocket AMT)
5. ⏳ Integration test: Start backend, verify frontend receives AMT

**See full plan**: `TDD_IMPLEMENTATION_PLAN.md`
