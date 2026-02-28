---
name: infra
description: High-Performance Trading Infrastructure Review & Fix for production-grade low-latency trading
user-invocable: true
---

# /infra — High-Performance Trading Infrastructure Review & Fix

Review, analyze, and improve GlassyTrade AI's architecture, infrastructure, and code quality for a production-grade, low-latency trading system on Apple Silicon.

## Instructions

You are a senior systems engineer specializing in **high-frequency/low-latency trading infrastructure**. This is a real-time options scalping system (NSE/MCX) running on Apple Silicon (M1 Max) with:
- FastAPI + WebSocket backend (Python 3.14)
- MLX inference (Nanbeige 3B + LoRA) for entry decisions
- LightGBM probability engine
- React 19 + TradingView charts frontend
- Dhan broker integration (live market data + order execution)
- SQLite storage, in-process event bus, DDD ports/adapters

When invoked, systematically audit the codebase for performance issues, code smells, architectural violations, and production readiness gaps. Produce actionable findings with file locations and fixes.

---

## Tech Stack Reference

| Layer | Tech | Key Files |
|-------|------|-----------|
| API | FastAPI + Uvicorn | `backend/app/main.py`, `backend/app/api/routers/` |
| WebSocket | gameloop (server-driven) | `backend/app/api/websocket/gameloop.py` (707L) |
| DDD Domain | Pure business logic | `backend/app/domain/` |
| Application | Handlers + services | `backend/app/application/` |
| Infrastructure | Adapters, storage, event bus | `backend/app/infrastructure/` |
| Compute | MLX GPU + pure Python hot path | `backend/app/domain/fabio_ai/services/mlx_compute.py` |
| LLM Inference | MLX (Nanbeige 3B fused) | `backend/app/infrastructure/adapters/mlx_inference_adapter.py` |
| Probability | LightGBM | `backend/app/infrastructure/adapters/lgbm_probability_adapter.py` |
| Broker | Dhan via `brokers/` lib | `backend/app/infrastructure/adapters/dhan_adapter.py` |
| Storage | SQLite + threading.Lock | `backend/app/infrastructure/storage/database.py` |
| Event Bus | In-memory, synchronous | `backend/app/infrastructure/event_bus.py` |
| Frontend | React 19 + Vite 6 + TS 5.8 | `frontend/` |
| Charts | lightweight-charts 4.1.1 | `frontend/components/` |
| State | Single hook (no Redux) | `frontend/hooks/useServerTradingSystem.ts` |
| Config | python-dotenv + `config.py` | `backend/app/config.py` |

---

## Audit Categories

### 1. LATENCY & HOT PATH

**Critical for a scalping system — every millisecond matters on the tick-to-decision path.**

Check for:
- **Tick-to-signal latency**: Dhan WS → `process_tick()` → AMT → LLM → Signal. Measure/estimate each hop.
- **Blocking on async event loop**: `asyncio.to_thread()` usage in gameloop — verify CPU-bound work is OFF the event loop.
- **GIL contention**: Multiple `ThreadPoolExecutor` instances (LLM entry, LLM overseer, tick processing). Check for lock contention between them.
- **Allocation pressure on hot path**: `mlx_compute.py` uses pure Python for <100 element arrays (62x faster than MLX). Verify no accidental MLX conversion on per-tick path.
- **`gc.collect()` in gameloop**: Forced GC stalls all threads. Should use generational GC tuning instead, or only run GC during market close.
- **`tracemalloc.start()` in `main.py`**: Left on unconditionally — adds ~5-10% overhead on allocation-heavy paths. Must be behind a debug flag.
- **Event bus is synchronous**: All handlers run sequentially per event. A slow handler (e.g., footprint analysis) blocks the entire tick pipeline. Consider async dispatch or priority-based ordering.
- **LLM semaphore contention**: Module-level `threading.Semaphore(1)` in `llm_entry_handler.py` serializes ALL LLM calls. Entry and overseer compete for the same lock.
- **Delta compression**: `_compute_delta()` runs every tick to diff state snapshots for WS. Verify it's not doing deep comparison on large nested dicts.

**Expected patterns:**
```python
# GOOD: Pure Python hot path
def ema(data: list[float], period: int) -> float:
    # list operations, no mx.array conversion

# BAD: MLX on per-tick data
def ema(data: list[float], period: int) -> float:
    arr = mx.array(data)  # conversion overhead dominates for <100 elements
```

### 2. MEMORY & RESOURCE MANAGEMENT

Check for:
- **Unbounded growth**: `MAX_CANDLES_PER_SYMBOL = 2000` caps candle history — verify enforcement. Check `CVDTracker._history`, `aggressive_prints`, `_failed_entries` in `regime_detector.py` for unbounded lists.
- **SQLite WAL accumulation**: WAL file can grow unbounded under heavy writes. Check for periodic `PRAGMA wal_checkpoint`.
- **ThreadPoolExecutor lifecycle**: Two executors created in `ServiceGraph.__init__` for warmup, then immediately shut down. But LLM handlers create their own executors — verify they're cleaned up on shutdown.
- **WebSocket connection cleanup**: On client disconnect, verify all per-connection state (candle buffers, stream tasks, timers) is released.
- **MLX model memory**: Singleton pattern via `__new__` on `MLXInferenceAdapter`. Verify model isn't loaded twice. Check VRAM usage.
- **Multiple SQLite DB files**: `glassytrade.db`, `*-shm`, `*-wal`, `*_backup_*.db`, `*_pre_optimization.db` — no cleanup strategy.

### 3. THREAD SAFETY & CONCURRENCY

Check for:
- **Race conditions in SessionState**: `threading.Lock` guards portfolio reads/writes. Verify ALL state mutations go through the lock, not just portfolio.
- **Race between TradeManager and Overseer**: Both can modify position state. TradeManager runs every tick, overseer every 10s on a separate thread. Partial close by TradeManager → overseer reads stale state.
- **Module-level mutable globals in gameloop**: `_active_stream_task`, `_last_dhan_connect_time` — work for single-process but break under multi-worker.
- **SQLite thread safety**: Single connection + `threading.Lock`. Check that the lock covers the full read-modify-write cycle, not just individual queries.
- **Event bus handler ordering**: Synchronous dispatch means handler A always runs before handler B. If B depends on A's side effects, this is fragile coupling.

**Expected patterns:**
```python
# GOOD: Lock covers full critical section
with self._lock:
    pos = self._portfolio.get_position(pos_id)
    pos.stop_loss = new_sl
    self._portfolio.update_position(pos)

# BAD: Lock only on read, mutation outside
with self._lock:
    pos = self._portfolio.get_position(pos_id)
pos.stop_loss = new_sl  # unprotected mutation
```

### 4. ERROR HANDLING & RESILIENCE

Check for:
- **Broad `except Exception:` (44 occurrences across 14 files)**: Swallows errors silently. Critical in trading — a swallowed exception could mean a missed exit signal.
  - `trading_session.py`: 14 occurrences
  - `gameloop.py`: 10 occurrences
  - Adapters: various
- **Specific exceptions that MUST NOT be swallowed:**
  - Broker order execution failures → must propagate or alert
  - SQLite write failures → must propagate (position state could be lost)
  - LLM inference failures → currently handled (timeout guard) but verify fallback
- **No circuit breaker on Dhan connection**: If Dhan WS drops repeatedly, the system retries without backoff. Could hammer the API.
- **No heartbeat monitor**: Planned but never built. If Dhan stops sending ticks silently (no disconnect, just silence), the system doesn't detect it.
- **No spread blowout detection**: Mid-trade liquidity crisis goes undetected.

**Expected patterns:**
```python
# GOOD: Specific exceptions with appropriate handling
try:
    await broker.place_order(signal)
except BrokerConnectionError:
    logger.error("Broker connection lost", exc_info=True)
    await notify_critical("Broker down — manual intervention needed")
    raise
except InsufficientMarginError as e:
    logger.warning("Margin insufficient: %s", e)
    return None

# BAD: Catch-all that hides real failures
try:
    result = self._process_complex_logic()
except Exception:
    logger.warning("Something failed")  # What failed? Why?
```

### 5. CODE SMELLS & ARCHITECTURE

Check for:
- **God classes:**
  - `amt_analyzer.py` (1,428 lines) — VP, LVN/HVN, aggression, CVD, profile shape, VWAP, IB, gap classification, market state. Should be 4-5 focused classes.
  - `trading_session.py` (818 lines) — coordinator but contains snapshot assembly, Greek caching, forward logger logic.
  - `gameloop.py` (707 lines) — candle aggregation, depth streaming, Greek refresh, footprint accumulation, delta compression, WS management all in one function.
- **Duplicate singleton patterns**: `MLXInferenceAdapter` uses `__new__` Borg pattern. `get_service_graph()` uses `@lru_cache`. Pick one.
- **`sys.path` manipulation**: `DhanMarketDataAdapter` inserts project root into `sys.path` to import `brokers/`. Should be a proper editable install (`pip install -e brokers/`).
- **Orphaned code**: `TickFootprintAccumulator` in `footprint_analyzer.py` has `get_all()` but nothing calls it. Dead code should be removed or integrated.
- **Inline test stubs**: Integration tests define stub adapters as nested classes inside test methods. Extract to shared `conftest.py` fixtures.
- **Missing deps in `requirements.txt`**: `mlx`, `mlx_lm`, `lightgbm`, `numpy` are NOT declared. Fresh install breaks.
- **Unused frontend deps**: `expo ^54` + `react-native-web ^0.21` appear unused — inflates node_modules.

### 6. PRODUCTION READINESS

Check for:
- **No Docker/containerization**: Direct `uvicorn` on Mac. No reproducible deployment.
- **No CI/CD**: No automated tests, linting, or deployment pipeline.
- **No linting/formatting**: No ruff, flake8, mypy, ESLint, Prettier configured. Type annotations exist but are never checked.
- **No DB migrations**: SQLite schema changes are manual. No Alembic or equivalent.
- **No structured logging standard**: `JSONFormatter` configured but check if all log calls use structured fields (not f-strings with data embedded).
- **No health check beyond `/api/health`**: No readiness probe (is LLM loaded? is Dhan connected? is DB writable?).
- **No metrics/observability**: `infrastructure/metrics.py` exists but check if it's wired. No Prometheus, no OpenTelemetry.
- **No graceful shutdown**: FastAPI lifespan has shutdown hook but verify ThreadPoolExecutors, Dhan WS connections, and SQLite connections are properly closed.
- **No rate limiting on API endpoints**: `/api/ai/command` accepts arbitrary user input → potential abuse.
- **No secret management**: `.env` file with `DHAN_ACCESS_TOKEN`, `TELEGRAM_BOT_TOKEN`. Check `.gitignore` includes `.env`.

### 7. DATA INTEGRITY & SAFETY

Critical for a system that manages real money:
- **Position state persistence**: `OpenPositionStoragePort` → SQLite. Verify positions survive server restart.
- **Order execution idempotency**: If the system crashes after sending an order but before recording it, does it re-send on restart?
- **Trade journal completeness**: `ForwardTestLogger` writes CSVs. Verify no gaps in logging (especially during errors).
- **Daily loss limit enforcement**: `MAX_DAILY_LOSSES = 3` — verify this survives server restart (loaded from DB, not just in-memory counter).
- **Clock accuracy**: Trading decisions depend on `datetime.now()`. No NTP sync verification. A clock drift of seconds could cause incorrect session phase detection.

### 8. FRONTEND PERFORMANCE

Check for:
- **WebSocket message rate**: Server sends state updates per tick. At 5+ symbols with 1-tick-per-second, that's 5+ WS messages/sec. Check if frontend handles backpressure.
- **React re-render storms**: Single `useServerTradingSystem` hook manages all state. Any state update re-renders all subscribed components. Should use `useMemo` / `useCallback` / state splitting.
- **3D rendering cost**: Three.js canvas runs continuously. Check if it pauses when tab is not visible.
- **Chart memory**: `lightweight-charts` with streaming data — verify old candles are pruned.
- **Type safety**: `tsconfig.json` extends `expo/tsconfig.base` with `skipLibCheck: true`. No `strict: true`. Null safety not enforced.

---

## How to Run an Audit

1. **Quick scan** (`/infra`): Check the top 5 highest-impact issues (latency, thread safety, error handling, god classes, missing deps)
2. **Full audit** (`/infra full`): Systematically go through all 8 categories above
3. **Focused audit** (`/infra latency`, `/infra safety`, `/infra errors`, `/infra smells`): Deep-dive one category
4. **Fix mode** (`/infra fix <issue>`): Read the affected files, propose specific code changes

For each finding, produce:
```
[SEVERITY] Category — Title
File: path/to/file.py:line
Issue: What's wrong
Impact: Why it matters for a trading system
Fix: Specific code change or approach
```

Severity levels:
- **CRITICAL**: Can cause financial loss, data corruption, or system failure
- **HIGH**: Degrades performance, reliability, or maintainability significantly
- **MEDIUM**: Code smell or suboptimal pattern that compounds over time
- **LOW**: Cosmetic or minor improvement

---

## Known Architecture Decisions (Do NOT flag as issues)

These are intentional design choices:
- Pure Python for per-tick compute (<100 elements) instead of MLX — this is 62x faster due to conversion overhead
- SQLite instead of PostgreSQL — single-process, single-machine deployment; acceptable
- In-memory event bus instead of Redis/Kafka — same-process, low-latency by design
- No Redux/Zustand on frontend — single hook is sufficient at current component count
- `PaperBrokerAdapter` for development — live broker adapter exists separately
- LLM for entries only, deterministic rules for exits — architectural decision, not a bug (see `/fabio` skill for nuanced discussion)
- Delta compression on WS — intentional optimization, not premature

---

## Quick Reference: File Sizes (Complexity Indicators)

```
1428L  backend/app/domain/fabio_ai/services/amt_analyzer.py      ← GOD CLASS
 818L  backend/app/application/services/trading_session.py        ← too large for coordinator
 707L  backend/app/api/websocket/gameloop.py                      ← monolithic WS handler
 ~500L backend/app/domain/fabio_ai/services/trade_manager.py
 ~400L backend/app/domain/fabio_ai/services/prompt_builder.py
 ~400L backend/app/domain/fabio_ai/entry_gate.py
 ~350L backend/app/domain/fabio_ai/services/footprint_analyzer.py
 ~300L backend/app/domain/fabio_ai/services/regime_detector.py
 ~290L backend/app/domain/fabio_ai/services/mlx_compute.py
 ~280L backend/app/infrastructure/storage/database.py
 ~250L backend/app/domain/fabio_ai/services/market_structure_classifier.py
 ~250L backend/app/application/handlers/llm_entry_handler.py
 ~200L backend/app/application/handlers/llm_overseer_handler.py
 ~200L backend/app/domain/fabio_ai/services/session_context.py
```

## Trading-Specific Code Review Checklist

Beyond general software engineering, a trading system demands:

- [ ] **No silent failures on order path** — every order attempt must be logged and acknowledged
- [ ] **Position state is always consistent** — no partial updates visible to other threads
- [ ] **Daily loss limit is crash-safe** — persisted, not just in-memory
- [ ] **Market hours enforcement is fail-closed** — if `is_market_open()` errors, assume closed
- [ ] **All prices use Decimal or consistent float handling** — no floating point comparison bugs on price levels
- [ ] **Stop loss can NEVER be widened programmatically** — only tightened or moved to breakeven
- [ ] **No unbounded retries on broker API** — exponential backoff with max attempts
- [ ] **Graceful degradation** — if LLM fails, system should not enter new positions (already implemented via `model_ready` check)
- [ ] **Audit trail** — every decision (entry, exit, skip, override) logged with timestamp and reason
- [ ] **Time zone handling** — all timestamps in IST for NSE/MCX, UTC for storage. No naive datetimes.
