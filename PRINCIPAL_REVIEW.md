# Principal Review — GlassyTrade AI Trading Platform

**Role:** Principal Trading Systems Architect & Senior Code Reviewer
**Scope:** Full-system audit (backend, backendv2, brokers, brokersv2, frontend, shared)
**Severity framing:** This is treated as a **real-money trading system**. Every finding is graded:

| Grade | Meaning |
|---|---|
| 🔴 **CRITICAL** | Can cause financial loss, wrong orders, or unrecoverable state |
| 🟠 **HIGH** | Will cause divergence between modes or maintenance collapse |
| 🟡 **MEDIUM** | Correctness risk under edge cases; significant debt |
| 🟢 **LOW** | Cleanup / hygiene |

---

## 0. Executive Summary

The platform does **not** currently have one trading system — it has **four parallel half-systems**:

1. `backend/` — **legacy live runtime** (this is what `start.sh` actually boots: `uvicorn app.main:app` on :9090)
2. `backendv2/` — a **parallel rewrite** ("Ported from backend/…" appears in source files) with its own pipeline runtime, **but no start script boots it**
3. `brokers/` — **legacy broker gateway** (sync HTTP client, explicitly marked "temporary solution until the broker is fully migrated to async")
4. `brokersv2/` — a **parallel institutional broker stack** (clean layering, OMS, risk gateway, replay infra) that is not wired into the booted backend

Quantified duplication:

- **130 same-named Python files** exist in both `backend/app` and `backendv2/app` (77 in `domain/` alone)
- **≥ 7 distinct VWAP implementations**: `backendv2/app/domain/amt/service/volume_profile.py`, `backendv2/app/domain/services/vwap_tracker.py`, `backendv2/app/domain/services/market_data_utils.py`, `backend/app/domain/services/market_data_utils.py`, `backend/app/domain/services/vwap_tracker.py`, `brokersv2/analytics/vwap.py`, `frontend/components/chart/VolumeSeriesManager.ts`, `frontend/components/chart/AMTLevelsOverlay.ts`
- **≥ 5 distinct `Candle` types** (plus two more `CandleAggregator` classes): `brokersv2/marketdata/candle_builder.py`, `brokersv2/domain/market/models.py`, `brokersv2/domain/market/events.py` (`CandleEvent`), `backendv2/app/runtime/pipeline/events.py`, `backendv2/app/domain/trading/model/value_objects.py` (`OHLC`), `frontend/types.ts` (`OHLCData`)
- **The WebSocket gameloop file is copy-pasted** between `backend/` and `backendv2/` (near-identical 400-line files)
- **Frontend re-implements backend logic**: VWAP (`calculateVWAP`), gap-fill / forward-fill of candles (`mergeCandleData`), cumulative-delta derivation, and a vestigial `dataSource: 'DHAN' | 'SERVER'` config flag (no actual Dhan client exists in the frontend today, but the flag advertises a direct-broker path and is a trap for future misuse)
- **Replay exists only in the broker layer** (`brokersv2/replay/` — EventClock, EventStore, ReplayEngine) with a TODO-flagged determinism module; the **trading engine has no replay mode**, so replay-vs-live parity is unenforced

**Bottom line:** The system works today by virtue of the legacy path being the only booted path. Every new feature is being written twice (or three times). This is the single most expensive architectural debt in the codebase, and it is a **safety hazard** because the two stacks can silently drift.

---

## 1. System Audit & Gap Analysis

### 1.1 Duplicate logic (backend ↔ backendv2 ↔ brokersv2 ↔ frontend)

| Concept | Locations | Impact |
|---|---|---|
| VWAP | 7+ implementations (listed above) | 🟠 Divergent math across stacks; frontend & backend can disagree on the same candle |
| Candle / OHLC | 5+ types + OHLC value objects in `backendv2/app/domain/trading/model/value_objects.py`, `backend/app/domain/trading/models/value_objects.py`, pipeline events, broker models | 🟠 Wire contracts drift; converters multiply |
| Signal | `backendv2/app/domain/trading/model/entities.py` (`Signal`), `backendv2/app/runtime/pipeline/events.py` (`Signal`), `backendv2/app/domain/trading/model/canonical_objects.py` (`TradingSignal`), `backend/app/domain/trading/models/entities.py` (legacy `Signal`) | 🟠 Three-plus signal contracts across the stacks |
| Position | `backendv2/app/domain/trading/model/entities.py`, `backendv2/app/runtime/pipeline/events.py` (`PositionEvent`), backend `domain/trading/models/entities.py`, frontend `TradePosition` (with lifecycle fields) | 🟠 Lifecycle semantics leak into the UI type |
| Risk manager | `backendv2/app/domain/trading/service/risk_manager.py` says **"Ported from backend/app/domain/trading/services/risk_manager.py"** | 🟠 Direct evidence of copy-port without consolidation |
| Exit engine | `backendv2/app/domain/exit/service/exit_engine.py` — "Ported from backend/…" | 🟠 Same |
| Session state manager | `backendv2/app/application/service/session_state_manager.py` — "Ported from backend/…" | 🟠 Same |
| Tick processor | `backendv2/app/application/service/tick_processor.py` — "Ported from backend/…" | 🟠 Same |
| Gameloop WebSocket | `backend/app/api/websocket/gameloop.py` ≈ `backendv2/app/api/websocket/gameloop.py` | 🟠 Copy-paste maintenance hazard |
| State bus invariant validation | `backend/app/domain/services/state_bus.py`, `backendv2/app/domain/services/state_bus.py` | 🟡 Duplicated anomaly detection (VWAP extremes etc.) |

### 1.2 Dead / obsolete / deprecated code

- `brokersv2/broker_factory.py` — file header says deprecated; routes to `brokersv2.app.bootstrap`
- `brokersv2/websocket/manager.py` — header: "deprecated placeholder. Use `brokersv2.infrastructure.dhan_adapter.websocket.DhanWebSocketManager`"
- `brokersv2/websocket/connection/manager.py` — same deprecation notice
- `brokersv2/oms/order_machine.py` — deprecation notice pointing to `domain/order/models.OrderStateMachine`
- `brokers/broker/dhan/infrastructure/http_client_sync.py` — "temporary solution until the broker is fully migrated to async"
- `brokersv2/resilience/policies/retry.py` — references BOTH `infrastructure/retry_manager.py` and `gateway/retry_manager.py` (two competing retry implementations)
- `backendv2/tests/e2e/test_rl_model_lifecycle.py` — **all tests are TODO stubs** ("TODO: Replace with real env/trainer/load/predict integration checks")
- `backendv2/tests/integration/test_frontend_api_contract.py` — **entirely TODO** (asserts nothing)
- `backendv2/tests/replay/test_replay_infrastructure.py` — "TODO: Add determinism module before running these tests"

### 1.3 SOLID / SoC / SSOT violations

- **S (SRP):** `useServerTradingSystem.ts` (~700 lines) does: WS lifecycle, heartbeat, reconnection, delta merging, candle gap-fill, forward-fill, LLM history dedup, runtime-safety derivation, RAF batching. It is the entire backend in a hook.
- **O (OCP):** broker adapters are concrete (`dhan_adapter.py`) in both backends; adding Zerodha means touching every import site. `brokersv2` is closer to correct (IBrokerAdapter port) but is not wired in.
- **L (LSP):** `backendv2/app/api/main.py` and backend expose different DTO field conventions for the same concepts (see §7).
- **I (ISP):** `shared/entities/models.py` imports `from brokers.broker.types import Exchange` — **shared code depends on the broker layer** (dependency inversion violation).
- **D (DIP):** `backend/app/infrastructure/adapters/dhan_broker_adapter.py` manipulates repo import paths to reach `brokers` — infra reaching across package boundaries ad hoc.

**Single Source of Truth:** None. VWAP has 7 sources of truth; Candle has 5; the wire contract is hand-duplicated in `backend/schemas.py`, `backendv2/schemas.py`, `frontend/types.ts`, and `frontend/types_generated.ts` (the latter generated by `scripts/generate_types.py`, but the former three drift independently).

### 1.4 Frontend implementing backend logic (FORBIDDEN per §3)

- `frontend/components/chart/VolumeSeriesManager.ts` → `calculateVWAP(data)` — indicator math in the UI
- `frontend/components/chart/AMTLevelsOverlay.ts` → `calculateVWAPColor(data)` — derives VWAP band *positions/colors* from raw candles, meaning the UI re-derives what the backend computes
- `frontend/hooks/useServerTradingSystem.ts` → `mergeCandleData()` with **forward-fill synthesising fake candles** (`vwap = close`, `volume = 0`) — the UI fabricates market data for rendering; this masks real gaps and can visually mislead an operator
- `frontend/hooks/useServerTradingSystem.ts` → `cumulativeDeltas` derived in the hook
- `frontend/types.ts` `dataSource: 'DHAN' | 'SERVER'` + `frontend/constants.ts` default `'DHAN'` — a vestigial config flag advertising a direct-broker data path. No Dhan URL/WS client exists in the frontend today (grep for `api.dhan.co`/`wss://…dhan` in `frontend/` returns 0 matches), so it is dead config — but it is an architectural trap: anyone wiring it up would bypass the server entirely. Remove it.

### 1.5 Replay vs Live divergence

- **Broker layer (brokersv2) has replay infra**: `replay/event_clock.py` (LiveClock/ReplayClock), `replay/event_store.py`, `replay/event_capture.py`, `replay/replay_engine.py`, `replay/replay_scheduler.py`, `replay/historical_replay.py`. Tests exist but the determinism module is a TODO.
- **Trading engine has NO replay path.** `backend/app/application/engine.py` (`TradingEngine`) streams live ticks only; `backendv2/app/runtime/orchestrator/session.py` processes live ticks via pipeline. There is no `ReplayEngine` for the trading pipeline, no candle-level time-travel, and no parity harness.
- The **only** "replay-like" path is the WebSocket **client-driven mode** (frontend pushes `{"tick": …}` back into the server) — which is both an architecture violation (client drives the engine) and a source of parity divergence (live path = engine→client; "replay" path = client→engine).
- **No test asserts live == replay.** The only parity-ish test is `backendv2/tests/e2e/test_scanner_parity.py` (legacy vs backendv2 scanner snapshots) — it compares two backends, not replay vs live.

---

## 2. Domain Model Re-Design

### 2.1 Principles

1. **One domain model, three runtimes** — Backtest, Replay, and Live must construct the same domain objects from the same canonical events. Mode is an *infrastructure concern*, never a domain concern.
2. **No UI fields in domain** — no `color`, `display`, `chartMode`, `gap_fill` hints.
3. **No broker fields in domain** — no `securityId`, `exchangeSegment`, Dhan product codes. Broker mapping lives in the adapter.
4. **Money is `Decimal`** (already partially done in `backendv2/domain/trading/model/value_objects.py` — good; keep it everywhere).
5. **Time is one canonical type** — ISO-8601 UTC strings are acceptable over the wire, but domain objects must carry a typed instant. Today OHLC uses `time: str` (backendv2) and the pipeline uses `timestamp: float (Unix ns)` — two clocks in one stack. Choose **one**.

### 2.2 Canonical domain objects (target)

```text
Candle
  - symbol, exchange (canonical enum), timeframe (enum), open/high/low/close (Decimal)
  - volume, taker_buy_volume, delta (Decimal)
  - ts_open, ts_close (canonical instant)
  - source (enum: EXCHANGE | SYNTHETIC),  # provenance — lets UI stop fabricating
  - vwap_band_ref (Optional[VWAPProfileSnapshot])  # NOT a number — a typed band reference

Indicator            (stateful, incremental — NEVER recompute from scratch)
  - update(candle) -> IndicatorState      # pure, deterministic, order-independent of wall clock
  - snapshot() -> IndicatorSnapshot       # serialisable, versioned

Signal
  - symbol, direction (LONG/SHORT/FLAT), setup (enum), confidence (0..1)
  - entry/sl/tp (Decimal), risk_reward, reason, source (enum: RULE | LLM | RL | PIPELINE)
  - generated_at (canonical instant), candle_ref (index/ts of triggering candle)

Order
  - id (broker-agnostic), symbol, side, quantity, type (LIMIT/MARKET/SL), price/trigger (Decimal)
  - validity, status (state machine: PENDING→OPEN→PARTIAL→FILLED|CANCELLED|REJECTED)
  - correlation_id (pipeline trace), position_id

Position (aggregate)
  - id, symbol, side, entry (Decimal), size, sl/tp (Decimal), pnl (Decimal)
  - lifecycle state machine (OPEN→PARTIAL→CLOSED) with invariants:
      * no mutation after CLOSED
      * sl < entry < tp for LONG (validated at entry)
  - cushion/scale metadata allowed ONLY as explicit domain concepts, not a bag of flags

RiskParameters (value object, immutable)
  - max_position_size, max_notional, max_daily_loss, max_consecutive_losses
  - max_drawdown, kill_switch_enabled, time_stop_sec

Session / TradingDay (aggregate)
  - session_id, date, exchange_hours, phase (enum: PRE_OPEN|AUCTION|MORNING|LUNCH|AFTERNOON|CLOSED)
  - market_state (enum: BALANCED|IMBALANCED|TRENDING…)
  - portfolio ref, risk_state ref, prior_day_levels (POC/VAH/VAL), session_vwap ref
```

### 2.3 What already exists (keep as the seed)

- `backendv2/app/domain/trading/model/` — `OHLC`, `OrderBook`, `AMTResult`, `Signal`, `Position`, `Portfolio` + enums. This is the best starting point: frozen value objects, Decimal, lifecycle invariants on Position.
- `backendv2/app/domain/trading/model/canonical_objects.py` — `TradingSignal`, `VWAPProfile` ("single source of truth" intent — good; unify the other `Signal`s onto it).
- `backendv2/app/runtime/pipeline/events.py` — rich typed event catalogue (Tick→…→FillEvent). This is the correct *event* backbone.

**Delete the parallel copies** in `backend/app/domain/trading/models/`, the second `Signal` in pipeline events, and the frontend `TradePosition` lifecycle fields (UI must receive a projection, not the aggregate).

---

## 3. Architecture Re-Design (High Level)

### 3.1 Target: Hexagonal / Clean Architecture

```text
┌─────────────────────────────── PRESENTATION (frontend) ───────────────────────────────┐
│  React views — PURE CONSUMER. No market math. No indicator math. No gap-fill.         │
│  Receives: versioned state deltas + typed events. Sends: commands + subscriptions.    │
└───────────────────────────────────────▲───────────────────────────────────────────────┘
                                        │  HTTP REST + WebSocket (versioned contracts)
┌─────────────────────────────── API / CONTRACT LAYER ──────────────────────────────────┐
│  FastAPI routers · WS gateway · Pydantic DTOs (generated from domain, not hand-kept)  │
│  AuthN/Z · rate limits · input validation · audit log                                  │
└───────────────────────────────────────▲───────────────────────────────────────────────┘
┌─────────────────────────────── APPLICATION LAYER ─────────────────────────────────────┐
│  Orchestration, use-cases: entry-coordinator, exit-engine, session-lifecycle,         │
│  signal-pipeline driver, LLM/RL workers, command bus                                   │
└───────────────────────────────────────▲───────────────────────────────────────────────┘
┌─────────────────────────────── DOMAIN LAYER (pure Python, zero I/O) ──────────────────┐
│  Candle · Indicators (incremental) · Signal · Order · Position · Risk · Session        │
│  AMT/fabio services · gate pipeline · exit rules                                       │
└───────────────────────────────────────▲───────────────────────────────────────────────┘
┌─────────────────────────────── INFRASTRUCTURE LAYER ──────────────────────────────────┐
│  Broker adapters (Dhan/Zerodha via IBrokerAdapter) · feeds (live/replay/historical)   │
│  storage (Postgres) · cache (Redis) · ML adapters · notifications · event bus          │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

### 3.2 What runs where (non-negotiable)

| Concern | Runs in | Rule |
|---|---|---|
| Candle aggregation, indicators, VWAP, volume profile | **Backend only** | Frontend must never compute these |
| Signal generation, gates, risk, order creation | **Backend only** | |
| Order routing, broker mapping, fills | **Backend broker adapters** | |
| Replay clock / time travel | **Backend runtime** (ReplayClock in domain runtime, not just broker layer) | Replay must drive the *same* pipeline as live |
| Rendering, user input, chart display | **Frontend only** | |
| State projection (what the UI sees) | **Backend** (projection service) | UI never merges raw ticks |

**Strictly forbidden in frontend:** VWAP/indicator math, candle synthesis, delta compression reconstruction, risk/safety derivation from raw fields, direct broker connectivity (`dataSource: 'DHAN'` must be removed).

### 3.3 Single Source of Truth rules

1. One `Candle` type, one `Signal` type, one `VWAP` implementation — **in the domain layer of the single surviving backend**.
2. Wire contracts are **generated** from domain objects (extend `scripts/generate_types.py` to emit TS + Python + OpenAPI from one schema), never hand-mirrored.
3. One replay engine, one live engine, sharing one `process_event` core.

---

## 4. Trading Pipeline Re-Architecture

### 4.1 Deterministic pipeline (target)

```text
Feed (live WS | replay clock | historical file)
   → Sequencer (monotonic sequence per symbol)
   → Normalizer (canonical Tick)
   → CandleBuilder (incremental; emits CandleClosed event)
   → IndicatorStage (incremental updates: VWAP, delta, profile, ATR…)
   → MarketStructure (AMT analysis on candle close)
   → Strategy / SignalStage (rule + LLM + RL, all async-consistent)
   → GateStage (entry gates, session phase, playbook)
   → RiskStage (limits, drawdown, kill-switch)
   → OrderStage (canonical OrderRequest)
   → Execution (broker adapter | paper broker | simulator)
   → StateUpdate (projection published to WS; event persisted to store)
```

### 4.2 Non-negotiable requirements

1. **`process(event, state)` is pure and deterministic** — given the same event sequence, all three runtimes (backtest/replay/live) produce identical outputs. Wall-clock time must never enter signal logic (only event timestamps).
2. **Replay = re-feed events through the SAME pipeline.** The ReplayClock is an *event source* (`brokersv2/replay/event_clock.py` already models this well) — it must be promoted into the trading runtime, not stay in the broker layer.
3. **No fork by mode.** Delete the "client-driven mode" in `gameloop.py` (frontend pushes ticks). There is exactly one way for events to enter the pipeline: through the feed/sequencer.
4. **Incremental indicators only** — `SymbolStateMixin` + per-symbol state already exist in `backendv2/app/runtime/pipeline/base.py` (TTL-capped state). Never recompute a profile from scratch per candle.
5. **Backpressure & ordering** — tick buffer + sequence gap detection (frontend already has a `tickBufferRef`; this belongs server-side). Out-of-order events are dropped or buffered by sequence, never applied blindly.
6. **Position/risk/order state lives server-side only.** The frontend receives projections.

### 4.3 Existing pipeline to build on

`backendv2/app/runtime/pipeline/` already has the right skeleton: `TickContext` (immutable accumulator), stage base class with lifecycle, `sequencer.py`, `normalizer.py`, `gates.py`, `risk.py`, `position.py`, `execution.py`, `persistence.py`. **This is the survivor** — the plan is to delete `backend/`'s `engine.py`/`trading_session.py` equivalents after parity tests pass.

---

## 5. Frontend Refactor Plan

### 5.1 Target state

- `useServerTradingSystem.ts` becomes a **thin transport hook**: connect → subscribe → dispatch state into a typed store (Zustand). All merge/gap-fill/derivation logic is deleted.
- Chart components become **pure projections** of `InstrumentState` (already partially true: chart managers are pure functions — keep that pattern).
- `dataSource: 'DHAN'` removed; frontend always talks to the backend API.
- Server must emit **complete, gap-free candle history** (the backend owns gap handling; the UI may *render* missing slots as empty, never as fabricated candles).

### 5.2 Concrete changes

| File | Change |
|---|---|
| `frontend/hooks/useServerTradingSystem.ts` | Delete `mergeCandleData`/forward-fill, `cumulativeDeltas`, `runtimeSafetyFromState` derivation → replace with store-backed projection + `tickBus` for chart-fast-path |
| `frontend/components/chart/VolumeSeriesManager.ts` | Delete `calculateVWAP` (use backend-provided `vwap`) |
| `frontend/components/chart/AMTLevelsOverlay.ts` | Delete `calculateVWAPColor` (it re-derives VWAP style from raw candles; style bands from backend `AMTAnalysis.vwapUpper/Lower*` instead) |
| `frontend/types.ts` | Remove `dataSource: 'DHAN'`; strip lifecycle fields from `TradePosition` (keep display projection) |
| `frontend/constants.ts` | Remove `'DHAN'` default |
| `frontend/stores/*` | Keep Zustand stores as the single client-side state container; add a `projection` layer that maps server deltas → typed state |

### 5.3 What the server must provide instead

- Versioned `InstrumentState` deltas (already exists) **plus** a `history` endpoint that returns gap-free candles with `source: EXCHANGE|SYNTHETIC` provenance.
- Replay mode = server-side time control: frontend sends `{replay: {symbol, speed, position}}` **commands**, never ticks.

---

## 6. Backend Refactor Plan

### 6.1 Survivor decision (the single most important architectural decision)

**Adopt `backendv2/` as the sole backend; delete `backend/` after parity is proven.** Evidence it's the right survivor:
- It is the layered/clean one (domain / application / infrastructure / runtime).
- It already has the typed pipeline event catalogue and immutable TickContext.
- Its domain model uses Decimal + frozen VOs.
- `backend/` is only "alive" because every start script points at it — an artifact of timing, not design.

**Adopt `brokersv2/` as the sole broker layer; delete `brokers/` after the Dhan adapter contract tests pass** (it already has `IBrokerAdapter`, OMS, risk gateway, replay infra). `brokers/` sync HTTP client is explicitly temporary.

### 6.2 Broker-agnostic OMS

- Port: `IBrokerAdapter` (place/cancel/query order, stream market data) — exists in `brokersv2/core/ports.py` and `backendv2/app/domain/broker/port.py`.
- `OrderManager`/`FillProcessor`/`Reconciliation` exist in `brokersv2/oms/` — keep, wire into the backend via the application layer.
- Dhan specifics (securityId, exchangeSegment, instrument mapping, auth) confined to `brokersv2/infrastructure/dhan_adapter/` — this is already the correct shape.

### 6.3 Unified engine

- One `TradingRuntime` that accepts `EventSource` = `LiveFeed | ReplaySource | HistoricalFile | Simulator`. Same pipeline core (§4).
- Lifecycle per trading day: `SessionOrchestrator` (backendv2 `runtime/orchestrator/session.py`) owns day rollover, warmup, profile reset, risk reset — with a single `SessionClock` for both live and replay.
- Paper broker (`backendv2/app/infrastructure/adapters/paper_broker.py`) becomes the fill simulator used by backtest/replay and by live dry-run — same code path as Dhan adapter behind the port.

### 6.4 Delete list (after parity gates pass)

- `backend/` entire tree (or archive to `archive/backend-legacy/` for one release)
- `brokers/` entire tree (Dhan facade lives on in brokersv2 adapters)
- Second `Signal`, second `Position` in pipeline events; second VWAP implementations; second gameloop; second schemas
- Deprecated shims: `brokersv2/broker_factory.py`, `brokersv2/websocket/manager.py`, `brokersv2/websocket/connection/manager.py`, `brokersv2/oms/order_machine.py`, duplicate retry managers
- TODO-stub test files (write real tests instead — see §8)

---

## 7. API & Contract Design

### 7.1 Principles

- **One schema authority.** Extend `scripts/generate_types.py` to generate:
  - `frontend/types_generated.ts` (already exists — make it the *only* frontend type source)
  - Python `schemas.py` (Pydantic, snake_case internally, camelCase aliases on the wire — backend convention)
  - OpenAPI spec (single source for routers)
- **Versioning:** prefix WS/event schemas with `v1` (`{"v":1,"type":"candle_closed",…}`). REST paths `/api/v1/…`. On breaking change: bump to v2, keep v1 adapter for one release.
- **Event envelope** (all streamed events):

```json
{ "v": 1, "seq": 81234, "ts": "2026-08-05T10:00:00.000Z",
  "type": "candle_closed", "symbol": "CRUDEOIL", "payload": {…} }
```

### 7.2 Canonical event catalogue

| Event | Payload (abridged) | Producer → Consumer |
|---|---|---|
| `tick` | symbol, price, volume, ts, bid/ask | Feed → backend |
| `candle_closed` | symbol, timeframe, OHLCV, delta, buy_vol, source | CandleBuilder → all |
| `signal` | symbol, direction, setup, conf, entry/sl/tp, reason | Strategy → gates/frontend |
| `order` | order_id, symbol, side, qty, type, price, status | OMS → broker / frontend |
| `fill` | order_id, qty, price, ts, commission | Broker → OMS → frontend |
| `position` | position_id, symbol, side, size, entry, pnl, status | Position → frontend |
| `risk_event` | kind, reason, limits snapshot | Risk → frontend |
| `state_delta` | versioned per-symbol projection delta | Backend → frontend (existing pattern, keep) |

### 7.3 Replay & live streamed identically

- Both modes emit the **same event envelope and the same projection deltas**. The only difference is the event *source* and a `mode: "live"|"replay"` + `replayPosition` field in the `state_delta` envelope.
- Frontend treats both identically: render event → update chart. No frontend branch on mode.

---

## 8. Test Strategy (Mandatory)

### 8.1 Pyramid

| Layer | Tooling | Coverage target |
|---|---|---|
| Unit — indicators/domain | pytest (backendv2), vitest (frontend pure fns) | Incremental indicator equivalence: `update(candle)` == recompute-from-scratch, over random bar sequences |
| Property-based | hypothesis | Candle invariants (H≥L, O,C within range, non-neg volume), Decimal precision, state-machine transitions (Order, Position, Cushion), no mutation after CLOSED |
| Replay-vs-live parity | pytest, dedicated harness | Feed the *same recorded event file* through live pipeline and replay pipeline; assert identical `state_delta` sequence. **This is the regression that prevents logic drift** |
| Broker adapter contract | pytest + recordings | Dhan adapter vs recorded golden responses: place/cancel/query/WS tick mapping; idempotency; partial fills; rejections |
| Simulation / E2E | pytest | Full pipeline: file → ticks → signals → gates → risk → order → paper fill → position → exit → PnL, end-to-end, deterministic |
| Frontend contract | vitest + `test_frontend_api_contract.py` (implement it!) | Frontend consumes generated types; server DTOs match snapshot |

### 8.2 Specific mandates

1. **Kill the TODO stubs** in `test_rl_model_lifecycle.py` and `test_frontend_api_contract.py` — replace with real assertions (they currently give false confidence of "green").
2. **Parity gate:** CI job runs `make parity` — legacy vs backendv2 signal/position outputs must match within tolerance on the recorded dataset before the legacy tree can be deleted.
3. **Determinism module** for replay: implement `brokersv2/replay/determinism.py` (currently commented-out TODO) and make replay tests depend on it.
4. **Regression guard:** a "golden tape" of one full trading day (ticks + all events) replayed in CI on every commit; any change that alters outputs fails the build.
5. **Frontend tests** already exist for chart managers (`VolumeSeriesManager.test.ts`, `AMTLevelsOverlay.test.ts`) — update them when `calculateVWAP`/`calculateVWAPColor` are deleted (they should assert projection behavior, not math).

---

## 9. Refactoring Roadmap

### Phase 1 — Safety (weeks 1–2) · *do not touch domain logic*
- **Change:** Add the golden-tape regression harness; implement the TODO-stubbed tests; add property tests for Position/Order state machines; wire a CI parity job (legacy vs backendv2).
- **Delete:** Nothing in live paths. Only delete TODO stubs' dead scaffolding.
- **Do NOT touch:** signal math, exits, risk gates, gameloop protocol.
- **Validation:** All suites green including new parity + golden tape. 🟢

### Phase 2 — Domain cleanup (weeks 3–5)
- **Change:** Collapse to ONE `Candle`, ONE `Signal` (canonical_objects), ONE VWAP tracker, ONE Position aggregate in `backendv2/app/domain/trading/model/`. Introduce typed timestamps + `source` on Candle.
- **Delete:** `backend/app/domain/trading/models/*`, second signals, 6 of the 7 VWAP implementations (keep `vwap_tracker.py`), duplicate state_bus.
- **Do NOT touch:** application handlers, websocket wire format (keep DTO layer as adapter).
- **Validation:** golden tape unchanged; parity still green. 🟢

### Phase 3 — Architecture realignment (weeks 6–9)
- **Change:** Make `backendv2` the booted app (update `start.sh`, `backend/start*.sh` → point at `backendv2/app/api/main.py`). Promote `brokersv2/replay` clocks into the trading runtime; add `ReplaySource` to the pipeline; delete gameloop client-driven mode.
- **Delete:** `backend/` (after parity gate), `brokers/` legacy, deprecated broker shims.
- **Do NOT touch:** broker adapter internals, LLM/RL handlers.
- **Validation:** Live + replay emit byte-identical event streams on golden tape; frontend works against new app.

### Phase 4 — Frontend/backend separation (weeks 10–12)
- **Change:** Frontend becomes pure consumer (delete VWAP math, gap-fill, delta derivation, DHAN datasource). Wire `types_generated.ts` as sole type source. Add replay *command* controls (speed/scrub) that call backend, not push ticks.
- **Delete:** `calculateVWAP`, `calculateVWAPColor`, `mergeCandleData`, `runtimeSafetyFromState`, DHAN dataSource.
- **Do NOT touch:** chart rendering primitives.
- **Validation:** Frontend tests green; zero indicator math in `frontend/` (grep gate). 🟢

### Phase 5 — Performance & observability (weeks 13+)
- **Change:** Profile pipeline hot path (allocation-free `process`, per-stage latency via existing `telemetry.py`), add cost tracking (exists), structured audit log of orders (exists in OMS — wire end-to-end), circuit breakers on broker calls (exist — keep), metrics endpoint hardening.
- **Delete:** dead analytics paths superseded by pipeline stage metrics.
- **Do NOT touch:** event semantics.
- **Validation:** p99 tick-processing latency budget met; ops dashboard shows live/replay parity health. 🟢

---

## 10. Final Deliverables

### 10.1 Architecture diagram (target, textual)

```text
[Frontend: pure consumer]  ⇄  [API/WS v1 contracts (generated)]
                                    │
                          [Application layer: coordinators, handlers]
                                    │
                     [Domain: Candle·Indicator·Signal·Order·Position·Risk·Session]
                     [AMT services · gates · exit rules]   ← single source of truth
                                    │
  [LiveFeed] [ReplaySource] [HistoricalFile] [Simulator]   ← EventSource (same pipeline)
                                    │
                     [Pipeline: seq→norm→candle→indicators→structure→signal→gates→risk→order]
                                    │
              [IBrokerAdapter: Dhan | Zerodha | Paper] → [Storage] [Cache] [ML] [Notify]
```

### 10.2 Component responsibilities

| Component | Responsibility |
|---|---|
| EventSource (Live/Replay/Hist/Sim) | Produce canonical events; replay clock controls timing only |
| Sequencer | Ordering, gap detection, dedup |
| CandleBuilder | Incremental aggregation, emits `candle_closed` |
| IndicatorStage | Incremental indicators; snapshot-able |
| Strategy/SignalStage | Rule + LLM + RL signal generation |
| GateStage | Entry gates, session phase, playbook |
| RiskStage | Limits, drawdown, kill-switch |
| OMS + BrokerAdapter | Order lifecycle, broker mapping |
| ProjectionService | Domain → versioned UI state deltas |
| Persistence | Event store, position/decision/tick repositories |

### 10.3 Anti-patterns found (summary)

1. **Parallel stacks** — two backends, two broker layers, near-identical files (130 shared names)
2. **Frontend = second backend** — VWAP math, gap-fill, delta derivation, direct broker datasource
3. **Copy-paste transport** — gameloop duplicated verbatim
4. **Multi-source-of-truth** — 7 VWAPs, 5 Candles, 3 Signals, hand-mirrored contracts
5. **Mode-forking** — replay in broker layer only; engine has no replay; client-driven WS mode
6. **TODO tests passing** — green suites that assert nothing
7. **Shared → broker dependency** — `shared/entities/models.py` imports broker types
8. **Deprecated shims left in tree** — stale placeholders pointing to their replacements

### 10.4 Before vs After

| Dimension | Before | After |
|---|---|---|
| Backends | `backend/` + `backendv2/` (130 dup files) | One backend (`backendv2`), legacy archived |
| Broker layers | `brokers/` + `brokersv2/` (sync temp + new) | One broker stack (`brokersv2`) behind `IBrokerAdapter` |
| VWAP | 7 implementations | 1 incremental tracker in domain |
| Candle | 5 types | 1 type + provenance `source` |
| Frontend | computes VWAP, fabricates candles, can hit DHAN directly | pure consumer of versioned projections |
| Replay | broker-only, no determinism, client pushes ticks | one engine, same pipeline, replay clock controls time only |
| Contracts | hand-mirrored TS/PY/OpenAPI | generated from one schema authority |
| Tests | TODO stubs + per-stack suites | golden-tape parity + property + contract + E2E, enforced in CI |

### 10.5 Non-negotiable coding rules (future development)

1. **One implementation per domain concept.** If you need VWAP/Candle/Signal anywhere, import the domain one. No local re-derivations.
2. **Frontend never computes market math.** UI renders what the server sends. No gap-fill, no VWAP, no delta accumulation.
3. **No mode forks.** Backtest/replay/live share `process(event, state)`. Replay controls time only.

> **Note on VWAP count:** the "≥ 7 implementations" figure lists 8 files because `AMTLevelsOverlay.calculateVWAPColor` is a style-derivation function rather than a pure VWAP computation; the other 7 are genuine implementations. The count is a conservative lower bound — `brokers/broker/dhan/domain/entities.py`, `brokersv2/domain/market/models.py` (`Candle.vwap`), and `brokersv2/marketdata/vwap_engine.py` add three more.
4. **Money in Decimal; time in one canonical type; every Candle carries `source`.**
5. **Contracts are generated, not mirrored.** Change domain → regenerate types; never hand-edit `types_generated.ts` vs `schemas.py` independently.
6. **No TODO tests.** A test that doesn't assert is deleted, not merged.
7. **Broker specifics live only in broker adapters.** `securityId`, `exchangeSegment`, Dhan enums never appear in domain or application code.
8. **Everything event-shaped.** Cross-process communication is typed events (`v`, `seq`, `ts`, `type`, `payload`) or versioned REST.
9. **No direct broker access from frontend, ever.**
10. **Parity is a CI gate.** Any change that breaks golden-tape replay-vs-live equality fails the build.

---

## Appendix: Concrete evidence map

| Claim | Evidence |
|---|---|
| Legacy is the booted backend | `start.sh:24`, `backend/start.sh:28`, `backend/start_mcx.sh:18` all run `uvicorn app.main:app` in `backend/` |
| backendv2 not booted | `ls backendv2/start*.sh` → none; only `backendv2/app/api/main.py` exists |
| Copy-porting | `grep -rl 'Ported from backend' backendv2/app` → 4+ files (`risk_manager.py`, `exit_engine.py`, `session_state_manager.py`, `tick_processor.py`) |
| Duplication scale | `comm -12` of `backend/app` vs `backendv2/app` file lists → **130 files**, 77 in domain |
| VWAP multiplicity | `code_search 'vwap|VWAP'` → 212 matches across `backend`, `backendv2`, `brokersv2`, `frontend` |
| Frontend logic leak | `VolumeSeriesManager.calculateVWAP`, `AMTLevelsOverlay.calculateVWAPColor`, `mergeCandleData` forward-fill in `useServerTradingSystem.ts`, `constants.ts: dataSource:'DHAN'` |
| Replay = broker-only | `brokersv2/replay/*` (event_clock, event_store, replay_engine, replay_scheduler, historical_replay); `backend/app/api/routers/gateway.py` reports `replay_infrastructure: False`; engine.py has no replay |
| TODO tests | `backendv2/tests/e2e/test_rl_model_lifecycle.py`, `backendv2/tests/integration/test_frontend_api_contract.py`, `brokersv2/tests/replay/test_replay_infrastructure.py:31` |
| Deprecated shims | `brokersv2/broker_factory.py`, `websocket/manager.py`, `websocket/connection/manager.py`, `oms/order_machine.py`, `resilience/policies/retry.py` |
| Shared→broker dep | `shared/entities/models.py:85` imports `brokers.broker.types` |
