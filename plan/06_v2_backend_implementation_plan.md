# V2 Backend Implementation Plan
## GlassyTrade AI — Clean Room Rebuild

**Document Version:** 1.0
**Date:** 2026-03-18
**Status:** Ready for Review
**Source Documents:** plan/01-05, fulldoc.md, AMT Execution Engine Algorithm

---

## 1. Why V2?

### Current V1 Issues (from architecture audit)

| Issue | Impact | V2 Fix |
|-------|--------|--------|
| LLM-based entry decisions | Non-deterministic, 1-2s latency | Pure rule-based pipeline |
| God objects (TradingSessionService 1899 lines) | Hard to test, hard to maintain | Single-responsibility modules |
| Scattered constants | Inconsistent thresholds | Single `config.py` source |
| Unused pipeline/ code | Confusion, maintenance burden | Remove or wire properly |
| SQLite instead of DuckDB | Limited analytics | DuckDB with proper schema |
| Threading mixed with async | Race conditions, complexity | Pure asyncio |
| No delta volume profile | Missing Fabio's core methodology | Delta-colored profiles |
| No partition exits | Giving back profits | P1/P2/P3 system |
| No pyramiding | Missing structured adds | Pyramid manager |

### V2 Design Principles

1. **Pure Deterministic** — Zero ML/LLM in signal pipeline (BO-09)
2. **Single Responsibility** — Every module does one thing
3. **Async-Only** — No threading, no GIL issues
4. **Configuration-Driven** — All thresholds in one place
5. **Test-First** — Every module has unit tests before integration
6. **Instrument-Agnostic** — Same code for NSE and MCX

---

## 2. V2 Directory Structure

```
backend_v2/
├── pyproject.toml              # Dependencies (uv)
├── .env.example                # Environment template
├── src/
│   ├── __init__.py
│   ├── main.py                 # Entry point + FastAPI app
│   │
│   ├── config/
│   │   ├── __init__.py
│   │   ├── engine_config.py    # ALL thresholds (frozen dataclass)
│   │   └── instruments.py      # Per-symbol config (frozen dataclass)
│   │
│   ├── core/
│   │   ├── __init__.py
│   │   ├── tick_processor.py   # Tick normalization
│   │   ├── candle_builder.py   # OHLCV candle construction
│   │   ├── session_manager.py  # Session boundary detection
│   │   └── symbol_state.py     # Per-symbol state dataclass
│   │
│   ├── profile/
│   │   ├── __init__.py
│   │   ├── volume_profile.py   # Session + Leg + Delta profiles
│   │   ├── node_detector.py    # LVN/HVN detection + scoring
│   │   ├── leg_anchor.py       # Leg start/reset detection
│   │   └── profile_selector.py # Active profile selection
│   │
│   ├── orderflow/
│   │   ├── __init__.py
│   │   ├── cvd_engine.py       # CVD + slope + divergence
│   │   ├── footprint_engine.py # Per-candle bid/ask + imbalance
│   │   ├── bubble_detector.py  # Volume bubble (2σ)
│   │   ├── absorption_detector.py # Absorption detection
│   │   ├── big_trade_detector.py  # Institutional print clusters
│   │   ├── ofi_calculator.py   # Order Flow Imbalance
│   │   ├── vwap_engine.py      # VWAP + σ bands
│   │   └── ib_detector.py      # Initial Balance
│   │
│   ├── strategy/
│   │   ├── __init__.py
│   │   ├── market_state_engine.py    # BALANCED/IMBALANCED/PROBING/NO_TRADE
│   │   ├── drive_tracker.py          # First/Second/Third drive
│   │   ├── aggression_scorer.py      # Multi-signal scoring
│   │   ├── trade_constructor.py      # Entry/SL/Target/R:R/Cushion
│   │   ├── rationale_generator.py    # Rule-based rationale text
│   │   └── pipeline.py               # Master 12-gate pipeline
│   │
│   ├── risk/
│   │   ├── __init__.py
│   │   ├── session_risk_manager.py   # Daily loss/drawdown/consecutive
│   │   └── position_sizer.py         # Fixed fractional sizing
│   │
│   ├── trade_management/
│   │   ├── __init__.py
│   │   ├── partition_exit_manager.py # P1/P2/P3 + BE + counter-aggression
│   │   ├── pyramid_manager.py        # Pyramid eligibility + sizing
│   │   └── breakeven_manager.py      # Break-even trigger logic
│   │
│   ├── data/
│   │   ├── __init__.py
│   │   ├── dhan_ws_client.py         # WebSocket tick stream
│   │   ├── dhan_rest_client.py       # REST API (L2, option chain)
│   │   ├── duckdb_store.py           # DuckDB persistence
│   │   └── economic_calendar.py      # EIA suppression windows
│   │
│   ├── output/
│   │   ├── __init__.py
│   │   ├── schema.py                 # Pydantic OutputSchema
│   │   ├── signal_formatter.py       # Format signals for output
│   │   └── ws_publisher.py           # WebSocket broadcast
│   │
│   ├── scanner/
│   │   ├── __init__.py
│   │   ├── option_scanner.py         # Contract selection
│   │   └── subscription_manager.py   # Dynamic WS subscriptions
│   │
│   └── api/
│       ├── __init__.py
│       ├── main.py                   # FastAPI app factory
│       └── routers/
│           ├── signals.py
│           ├── profiles.py
│           ├── risk.py
│           ├── trades.py
│           └── config_router.py
│
├── tests/
│   ├── unit/
│   │   ├── test_profile.py           # 6 tests
│   │   ├── test_cvd.py               # 4 tests
│   │   ├── test_drive_tracker.py     # 5 tests
│   │   ├── test_aggression.py        # 5 tests
│   │   ├── test_risk_manager.py      # 6 tests
│   │   └── test_partition_exit.py    # 5 tests
│   ├── integration/
│   │   └── test_full_pipeline.py     # 6 tests
│   └── performance/
│       └── test_latency.py           # 3 tests
│
├── data/
│   └── db/
│       └── glasstrade.db             # DuckDB file
│
└── scripts/
    └── seed_prev_session.py          # Seed previous session data
```

---

## 3. Implementation Phases

### Phase 0: Project Setup (Day 1)

**Tasks:**
- Create `backend_v2/` directory structure
- Create `pyproject.toml` with exact dependencies
- Create `.env.example` with all required variables
- Initialize DuckDB schema

**Dependencies (from fulldoc.md INSTRUCTION 001):**
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
pytest==8.3.0
pytest-asyncio==0.25.0
```

**Test:** `uv sync` completes with zero errors

---

### Phase 1: Config Layer (Day 1)

**Files:**
- `src/config/engine_config.py` — Frozen dataclass with ALL thresholds
- `src/config/instruments.py` — Per-symbol frozen dataclass

**Key Design:**
- `EngineConfig` is frozen (no mutation after init)
- `CFG` is module-level singleton
- All thresholds sourced from `CFG` — no magic numbers elsewhere

**Thresholds (from fulldoc.md INSTRUCTION 002):**
```python
@dataclass(frozen=True)
class EngineConfig:
    # Volume Profile
    value_area_pct: float = 0.70
    lvn_threshold_pct: float = 0.15
    hvn_threshold_pct: float = 2.00

    # CVD
    cvd_slope_window: int = 20
    cvd_strong_slope: float = 2.0

    # Footprint
    footprint_imbalance_ratio: float = 3.0
    footprint_imbalance_pct: float = 0.40

    # Aggression
    min_aggression_score: float = 2.0
    pyramid_aggression_score: float = 3.0

    # Risk
    risk_per_trade_pct: float = 0.005
    max_daily_loss_pct: float = 0.020
    max_consecutive_losses: int = 3
    max_drawdown_pct: float = 0.030

    # ... (all 50+ thresholds from fulldoc.md)
```

**Test:**
```python
from config.engine_config import CFG
assert CFG.value_area_pct == 0.70
assert CFG.min_aggression_score == 2.0
```

---

### Phase 2: Core Data Layer (Day 2)

**Files:**
- `src/core/tick_processor.py` — Tick dataclass + normalize function
- `src/core/candle_builder.py` — Candle dataclass + CandleBuilder class
- `src/core/session_manager.py` — Session boundary detection
- `src/core/symbol_state.py` — Per-symbol state dataclass

**Key Design:**
- `Tick` uses `__slots__` for memory efficiency
- `CandleBuilder` returns `Optional[Candle]` on candle close
- `SessionManager` handles warmup, dead zone, outside session
- `SymbolState` holds ALL per-symbol mutable state

**Test (from fulldoc.md INSTRUCTION 004-006):**
```python
# Tick normalization
tick = normalize_tick(raw)
assert tick.price == 9.35
assert tick.delta == 40

# Candle building
candle = builder.update(tick)
assert candle.open == 9.10
assert candle.close == 9.15

# Session classification
assert sm.classify_time(t_warmup) == "WARMUP"
assert sm.classify_time(t_active) == "ACTIVE"
```

---

### Phase 3: Profile Engine (Day 3)

**Files:**
- `src/profile/volume_profile.py` — Session + Leg + Delta profiles
- `src/profile/node_detector.py` — LVN/HVN detection
- `src/profile/leg_anchor.py` — Leg start/reset
- `src/profile/profile_selector.py` — Active profile selection

**Key Design:**
- O(1) incremental bucket updates per tick
- Delta profile tracks buy_delta vs sell_delta per bucket
- LVN quality scoring: thinness (60%) + midpoint proximity (40%)
- Value area expansion: alternating up/down by highest-volume bucket

**Test (from fulldoc.md INSTRUCTION 007-009):**
```python
# POC calculation
assert eng.get_poc("session") == 9.10

# Value area
va = eng.get_value_area("session")
assert va["va_volume"] / total >= 0.70

# Delta profile
dp = eng.get_delta_profile("session")
assert dp[9.10]["buy_delta"] == 500
assert dp[9.10]["net_delta"] == 300

# LVN detection
lvns = NodeDetector.detect_lvns(profile, 0.15)
assert 9.30 in [l["price"] for l in lvns]
```

---

### Phase 4: Order Flow Engines (Day 4-5)

**Files:**
- `src/orderflow/cvd_engine.py` — CVD + slope + divergence
- `src/orderflow/footprint_engine.py` — Per-candle footprint
- `src/orderflow/bubble_detector.py` — Volume bubble (2σ)
- `src/orderflow/absorption_detector.py` — Absorption detection
- `src/orderflow/big_trade_detector.py` — Big trade clusters
- `src/orderflow/ofi_calculator.py` — OFI calculation
- `src/orderflow/vwap_engine.py` — VWAP + bands
- `src/orderflow/ib_detector.py` — Initial Balance

**Key Design:**
- Each engine is a pure function or stateful class with clear interface
- CVD uses numpy polyfit for slope calculation
- Footprint imbalance: 3:1 ratio threshold, 40% cell confirmation
- Bubble detection: 2σ above mean across 21-bar window
- Absorption: dual condition (small range + high volume)

**Test (from fulldoc.md INSTRUCTION 010-013):**
```python
# CVD accumulation
assert eng.get_current() == -150

# Footprint imbalance
result = eng.detect_imbalance(fp, "LONG")
assert result["confirmed"] == True

# Absorption
result = detect_absorption(candle, atr=0.20, avg_vol=1000.0)
assert result["detected"] == True
assert result["type"] == "SELL_ABSORBED"
```

---

### Phase 5: Strategy Core (Day 6-7)

**Files:**
- `src/strategy/market_state_engine.py` — State classification
- `src/strategy/drive_tracker.py` — First/Second/Third drive
- `src/strategy/aggression_scorer.py` — Multi-signal scoring
- `src/strategy/trade_constructor.py` — Entry/SL/Target
- `src/strategy/rationale_generator.py` — Rule-based text
- `src/strategy/pipeline.py` — Master 12-gate pipeline

**Key Design:**
- Market state: NO_TRADE > BALANCED > IMBALANCED > PROBING
- Drive tracker: per-level touch history with rejection detection
- Aggression scorer: 5 signals with specific weights from CFG
- Trade constructor: entry at level, SL beyond aggressive print, target at POC
- Pipeline: 12 sequential gates, first FAIL = output immediately

**Test (from fulldoc.md INSTRUCTION 014-016):**
```python
# Market state
state, zone = MarketStateEngine.detect(9.51, va, None, 0.20, [], 0.10)
assert state == "NO_TRADE"

# Drive tracking
result = tracker.classify_drive(8.91, 8.91, "LONG", ...)
assert result.drive_number == 1
assert result.entry_valid == False

# Aggression scoring
result = AggressionScorer.score(...)
assert result.score == 2.0
assert result.confirmed == True
```

---

### Phase 6: Risk Management (Day 8)

**Files:**
- `src/risk/session_risk_manager.py` — Kill switches
- `src/risk/position_sizer.py` — Fixed fractional sizing

**Key Design:**
- 3 kill switches: daily loss (2%), drawdown (3%), consecutive losses (3)
- Position sizing: risk_amount / risk_per_lot
- Hard ceiling: 1% per trade absolute maximum

**Test (from fulldoc.md INSTRUCTION 017-018):**
```python
# Consecutive losses
rm.register_trade_result(-500)
rm.register_trade_result(-500)
rm.register_trade_result(-500)
ok, reason = rm.can_trade()
assert ok == False
assert "CONSECUTIVE" in reason

# Position sizing
lots, risk_amt, risk_pct = PositionSizer.calculate(...)
assert lots == 100
assert risk_amt == 2500.0
```

---

### Phase 7: Trade Management (Day 9)

**Files:**
- `src/trade_management/partition_exit_manager.py` — P1/P2/P3
- `src/trade_management/pyramid_manager.py` — Pyramid adds
- `src/trade_management/breakeven_manager.py` — Break-even trigger

**Key Design:**
- P1: 30% at 33% R (weak momentum only)
- P2: 50% at target (always)
- P3: 20% trail if CVD strong, exit if weak
- Pyramid: max 2 adds, aggression ≥ 3.0, decreasing lot sizes
- Counter-aggression: 2+ signals = exit ALL immediately

**Test (from fulldoc.md INSTRUCTION 019-020):**
```python
# P1 skipped on strong momentum
# P2 always fires at target
# P3 exits with P2 when CVD weak
# Counter aggression exits all
```

---

### Phase 8: Data Layer (Day 10)

**Files:**
- `src/data/duckdb_store.py` — DuckDB schema + queries
- `src/data/dhan_ws_client.py` — WebSocket client
- `src/data/dhan_rest_client.py` — REST client
- `src/data/economic_calendar.py` — EIA suppression

**Key Design:**
- DuckDB schema: ticks, session_profiles, npoc_records, signals, trades, open_trades, session_risk, economic_events
- WebSocket: websockets library, orjson for parsing, exponential backoff reconnect
- REST: aiohttp for L2 DOM polling (500ms)
- Economic calendar: suppress signals during EIA windows

**Test (from fulldoc.md INSTRUCTION 021-022):**
```python
# Schema initialization (idempotent)
db.initialize_schema()
db.initialize_schema()  # No error

# Session profile save/load
db.save_session_profile("NATURALGAS", date(2026,3,17), 9.50, 10.20, 8.80, ...)
result = db.load_prev_session_profile("NATURALGAS")
assert result["POC"] == 9.50
```

---

### Phase 9: Output Layer (Day 11)

**Files:**
- `src/output/schema.py` — Pydantic OutputSchema
- `src/output/signal_formatter.py` — Format signals
- `src/output/ws_publisher.py` — WebSocket broadcast

**Key Design:**
- OutputSchema has 40+ fields (from BRD FR-11)
- SignalFormatter generates rationale via deterministic template
- WSPublisher broadcasts to all connected clients

---

### Phase 10: Scanner + API (Day 12)

**Files:**
- `src/scanner/option_scanner.py` — Contract selection
- `src/scanner/subscription_manager.py` — Dynamic subscriptions
- `src/api/main.py` — FastAPI app
- `src/api/routers/` — REST endpoints

**Key Design:**
- Scanner: exchange mode → option chain → filter → rank → subscribe
- Rebalance every 5 minutes
- API: REST + WebSocket endpoints

---

### Phase 11: Tests (Day 13-14)

**Unit Tests (31 tests):**
- `test_profile.py` — 6 tests
- `test_cvd.py` — 4 tests
- `test_drive_tracker.py` — 5 tests
- `test_aggression.py` — 5 tests
- `test_risk_manager.py` — 6 tests
- `test_partition_exit.py` — 5 tests

**Integration Tests (6 tests):**
- `test_full_pipeline.py` — End-to-end signal generation

**Performance Tests (3 tests):**
- `test_latency.py` — P99 < 500ms, O(1) profile update, 10 concurrent symbols

---

## 4. Key Architecture Decisions

### 4.1 Pure Async (No Threading)

```python
# V1 (WRONG): ThreadPoolExecutor for LLM
executor = ThreadPoolExecutor(max_workers=1)
future = executor.submit(llm_predict, prompt)

# V2 (CORRECT): asyncio.Queue only
async def symbol_pipeline(symbol: str, state: SymbolState, queue: asyncio.Queue):
    while True:
        tick = await queue.get()
        await process_tick_pipeline(tick, state)
        queue.task_done()
```

### 4.2 Configuration Singleton

```python
# V1 (WRONG): Magic numbers scattered
if cvd_slope > 50:  # Where does 50 come from?

# V2 (CORRECT): Single source of truth
from config.engine_config import CFG
if cvd_slope > CFG.cvd_strong_slope:  # 2.0, defined once
```

### 4.3 Pure Functions for Gates

```python
# V1 (WRONG): Gate logic mixed with I/O
def check_gate(self, tick):
    self.save_to_db(tick)  # Side effect!
    return tick.price > self.threshold

# V2 (CORRECT): Pure function
def check_gate(price: float, threshold: float) -> bool:
    return price > threshold  # No side effects
```

### 4.4 Delta Volume Profile

```python
# V1 (WRONG): Plain volume profile
profile[bucket] += tick.volume

# V2 (CORRECT): Delta-colored profile
profile[bucket]["buy_delta"] += tick.ask_vol
profile[bucket]["sell_delta"] += tick.bid_vol
profile[bucket]["net_delta"] += tick.delta
```

---

## 5. Migration Strategy

### Option A: Big Bang (Recommended)
- Build `backend_v2/` from scratch
- Run both v1 and v2 in parallel during development
- Switch frontend to v2 when tests pass
- Delete v1

### Option B: Incremental
- Replace modules one by one in v1
- Higher risk of breaking existing functionality
- Not recommended given v1's architecture issues

**Recommendation:** Option A — Clean room rebuild

---

## 6. Success Criteria

| Criterion | Target | Validation |
|-----------|--------|------------|
| All unit tests pass | 31/31 | `pytest tests/unit/ -v` |
| All integration tests pass | 6/6 | `pytest tests/integration/ -v` |
| All performance tests pass | 3/3 | `pytest tests/performance/ -v` |
| Zero lint errors | 0 | `ruff check src/` |
| Zero type errors | 0 | `mypy src/` |
| Signal latency P99 | < 500ms | Performance test |
| Profile update O(1) | < 1ms | Performance test |
| 10 concurrent symbols | No degradation | Performance test |
| DuckDB schema idempotent | Yes | Integration test |
| WebSocket heartbeat | Every 5s | Manual test |
| Crash recovery | Open trades recovered | Manual test |

---

## 7. Timeline Summary

| Phase | Duration | Deliverable |
|-------|----------|-------------|
| Phase 0: Setup | Day 1 | Project structure + dependencies |
| Phase 1: Config | Day 1 | engine_config.py + instruments.py |
| Phase 2: Core | Day 2 | Tick processor + candle builder + session manager |
| Phase 3: Profile | Day 3 | Volume profile + LVN/HVN + leg anchor |
| Phase 4: OrderFlow | Day 4-5 | 8 order flow engines |
| Phase 5: Strategy | Day 6-7 | Market state + drive + aggression + pipeline |
| Phase 6: Risk | Day 8 | Session risk + position sizer |
| Phase 7: Trade Mgmt | Day 9 | Partition exits + pyramid + breakeven |
| Phase 8: Data | Day 10 | DuckDB + Dhan clients + economic calendar |
| Phase 9: Output | Day 11 | Schema + formatter + publisher |
| Phase 10: Scanner + API | Day 12 | Option scanner + FastAPI |
| Phase 11: Tests | Day 13-14 | 40 tests (31 unit + 6 integration + 3 performance) |

**Total: 14 days for complete v2 backend**

---

## 8. What V2 Keeps from V1

| Component | V1 Location | V2 Location | Changes |
|-----------|-------------|-------------|---------|
| FastAPI app | `backend/app/main.py` | `src/api/main.py` | Simplified |
| Dhan adapter | `backend/app/infrastructure/adapters/dhan_adapter.py` | `src/data/dhan_ws_client.py` | Pure async |
| AMT analyzer logic | `backend/app/domain/fabio_ai/services/amt_analyzer.py` | `src/profile/volume_profile.py` | Refactored |
| Entry gate logic | `backend/app/domain/fabio_ai/services/entry_gate.py` | `src/strategy/pipeline.py` | Integrated into pipeline |
| Trade manager | `backend/app/domain/fabio_ai/services/trade_manager.py` | `src/trade_management/` | Split into 3 modules |
| Risk manager | `backend/app/domain/trading/services/risk_manager.py` | `src/risk/session_risk_manager.py` | Simplified |
| Frontend | `frontend/` | No change | Connects to v2 API |

---

## 9. What V2 Removes from V1

| Component | Reason |
|-----------|--------|
| LLM inference | BO-09: Zero ML/LLM in signal pipeline |
| ThreadPoolExecutor | Pure async only |
| pipeline/ directory | Unused code, confusion |
| GenerativeAIService | Not needed for deterministic engine |
| MLXInferenceAdapter | Not needed for deterministic engine |
| LGBMProbabilityAdapter | Not needed for deterministic engine |
| LearningEngine | Not needed for deterministic engine |
| RegimeDetector | Not needed for deterministic engine |
| PromptBuilder | Not needed for deterministic engine |

---

*Plan created: 2026-03-18*
*Ready for review and approval*
