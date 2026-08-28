# GlassyTrade AI — Principal Architecture Review & Re-Architecture Plan

**Date:** 2026-08-28
**Role:** Principal Trading Systems Architect & Senior Code Reviewer
**Scope:** Full system — backend (`quant/`, `backend/app/`, `brokers/`), frontend (`frontend/`), shared domain, contracts, tests.
**Method:** 5-agent parallel audit (domain+pipeline, frontend, contracts+parity, OMS+brokers+risk, test strategy). All findings cite `file:line`.
**Treatment:** REAL-MONEY trading system. Correctness > cleverness, determinism > convenience, deletion > refactoring.

---

## 0. Executive Summary

**Verdict:** The system has a genuinely broker-agnostic *core* (no Dhan imports inside `quant/`; clean `IOMS`/`IBroker`/`IMarketData` seams; Dhan WS parsing isolated to one normalizer) and a strong deterministic-replay test culture. **But the execution layer is a synchronous signal-to-order bridge, not an OMS**, the domain model is duplicated 2–3× per concept, the frontend re-implements trading logic, and the wire contracts are unversioned and already observably drifted. Most dangerously, **several live-path defects violate trading correctness today** and must be fixed before any re-architecture.

### The 7 real-money correctness violations (fix FIRST — Phase 1)

| # | Sev | Defect | Where |
|---|-----|--------|-------|
| C1 | CRIT | **Live order quantity is discarded and re-sized against a frozen phantom portfolio.** Engine sizes via `SessionRisk.position_size`, but `LiveOMS`/`broker_mapper` drop the qty; `DhanBrokerAdapter._resolve_quantity` re-sizes from a fresh `Portfolio` frozen at `INITIAL_CAPITAL=₹10L`, risk% clamps to 0.25–0.5%, and option `lot_size` is never set → **non-lot-multiple option orders** → exchange rejection / mis-sized fills. Portfolio-risk reservation uses the *engine* qty, so the aggregate ceiling tracks numbers unrelated to real exposure. | `live_oms.py:57-65`, `broker_mapper.py:27-38`, `dhan_broker_adapter.py:483-547` |
| C2 | CRIT | **`risk_per_trade_pct` from `live.yaml` (0.002) is never propagated through DI; engines default to 0.95.** Live risk-per-trade is effectively 95%, not 0.2%. | `live.yaml:17`, `composition_root.py:134-146`, `multi_engine.py:883` |
| C3 | CRIT | **Any broker rejection/timeout kills the engine thread and leaks the risk reservation.** No try/except around `oms.submit`; `RuntimeError` propagates → `_crashed` → symbol dead for the day; `register_open` reservation never released. | `runtime.py:895`, `live_oms.py:67-71` |
| C4 | CRIT | **Orphaned/desynced positions on poll timeout or partial fill.** No intraday reconciliation; a partial fill that ends CANCELLED returns `None` → exchange holds a position the engine never records. | `dhan_broker_adapter.py:165-185`, no reconcile loop |
| C5 | HIGH | **Double-close / accidental position flip on SIGTERM.** `emergency_halt(force_close=True)` bypasses `_close_lock` and sends a second opposing MARKET order; if the first close filled, the second opens a fresh opposite intraday position. Also bypasses pyramids. | `multi_engine.py:558-583` |
| C6 | HIGH | **Short-position reconciliation bug blocks live restarts.** Broker reports `size=abs(qty)` (always +) vs DB signed size → any open SHORT at restart = guaranteed "discrepancy" → strict mode refuses to boot. | `multi_engine.py:1032-1037`, `dhan_broker_adapter.py:398-401`, `order.py:41` |
| C7 | HIGH | **Unprotected MARKET orders; entry price ignored; no slippage collar.** Entries default MARKET, closes hardcoded MARKET; signal `entry` sent as `price` on a MARKET order (ignored). Unbounded slippage on thin options. | `dhan_broker_adapter.py:283,460-469` |

Supporting structural defects: order dedup is a **no-op** (fresh `uuid4` per mapping defeats `_executing_signal_ids` + Dhan `correlationId`); **no durable order state** (no orders table); **two `DhanBroker` instances** in one process (two blind rate-limiters = 2× effective API rate); portfolio "ceiling" is **95% of capital** and non-persistent (`portfolio_risk.py:28-29`).

### The 3 biggest structural problems
1. **No single source of truth anywhere.** 3 candle types, 2 signal models, 3 position models, 2 order models, 2 tick models, 6 PnL sites, 3 sizing impls, 4 lot-snap sites, 3 VWAPs, 5 session/time parsers. Contracts defined 3× (backend DTO + WS adapter + hand-maintained `frontend/types.ts`) with ~20-field drift.
2. **Layer inversion / god classes.** `contracts → execution → decision → contracts` import cycle. God classes: `runtime.py` 1218 LOC, `multi_engine.py` 1066, `analyzer.py` 1052, `position_manager.py` 582, `aggregates.py` 579, plus 616 LOC of dead `exit_rules.py`.
3. **Frontend is a co-strategy.** It re-derives trading verdicts, breakout/retest detectors, 3-A gate scoring, PnL/R-multiple math, session phases (with NSE times hardcoded onto MCX symbols), and a client-side mid-price LTP — all of which can silently disagree with the engine.

---

## TASK 1 — System Audit & Gap Analysis

### 1.1 Live pipeline trace (as-is)
```
Dhan WS packet
 → MultiplexedMarketFeed._producer/_normalize_dhan_packet/_route   multiplexed_feed.py:289/430/417
 → LiveGateway.next_tick                                            live_gateway.py:20
 → QuantEngine._run_inner (stamps wall-clock time.time())           runtime.py:452/507
 → BarAggregator.add_tick → closed Bar                              aggregator.py:19  bars.py:11
 → AMTEngine.on_tick / .analyze → AMTAnalyzer.analyze → AMTResult   amt_engine.py:121/332  analyzer.py:239/355
 → amt_result_to_dto (untyped dict)                                 amt/dto.py:18
 → DecisionContextBuilder.build → DecisionContext (~60 fields)      context_builder.py:90  context.py:11
 → DecisionService.evaluate → GatePipeline.evaluate (4 gates)       decision_service.py:52  pipeline.py:20
     gates: session_phase / position_cooldown / triple_a_edge / rr  gates_session_position.py:11  gates_edge.py:114  gates_rr.py:12
 → SignalBuilder.build_or_reason → engine Signal                    signal_builder.py:61/49
 → SessionRisk.position_size + clamp_quantity                       risk.py:242  signal_builder.py:35
 → PortfolioRiskAuthority.can_accept/register_open                  portfolio_risk.py:54/38  runtime.py:880/887
 → IOMS.submit (PaperOMS | LiveOMS)                                 ports.py:25  oms.py:6  live_oms.py:57
 → to_broker_signal (QTY DROPPED) → broker Signal                   broker_mapper.py:27  entities.py:31
 → DhanBrokerAdapter.execute_order (_resolve_quantity RE-SIZES)     dhan_broker_adapter.py:106/483
 → DhanBroker.place_order → REST poll for terminal status (0.5s×30s) dhan_broker_adapter.py:549
 → Position (from broker fill) → PositionOpened event               runtime.py:899  events.py:138
 → StateProjector.on_event → ViewState                              state.py:185
 → exits: PositionManager.manage_exit/_tick_exit → ExitEngine       position_manager.py:113/282  exits.py:33
 → QuantCoordinator.snapshot → view_state_to_ws → gameloop WS       multi_engine.py:482  ws_adapter.py:17  gameloop.py:75
 → EOD: _eod_watchdog_loop → eod_square_off → force_close_position  multi_engine.py:632/600  runtime.py:1019
```

### 1.2 Duplicate logic (ranked)
1. **Exit logic, two parallel engines** — live `exit_checks.py:14/26/91/155` vs ~dead `exit_rules.py:84/120/207/348/456` (616 LOC).
2. **Position sizing, three impls** — `SessionRisk.position_size` (truth), dead `SignalBuilder.size` (`signal_builder.py:206`), live `DhanBrokerAdapter._resolve_quantity` (+ `Portfolio.open_position`). **These disagree in live = C1.**
3. **Lot snapping, four sites** — `oms.py`, `live_oms.py:297`, `aggregates.py`, `dhan_broker_adapter.py:483`.
4. **Candle, three types** — `Bar` (`bars.py:11`, float), `OHLC` (`value_objects.py:19`, Decimal), `FloatOHLC` (`:82`, float).
5. **Signal, two incompatible models** — engine (`signal_builder.py:49`, frozen float LONG/SHORT) vs broker (`entities.py:31`, mutable Decimal BUY/SELL + uuid).
6. **Position, three models** — `execution/order.py:14`, `contracts/entities.py:86`, `shared/entities/models.py:292`.
7. **Order, two** — `execution/order.py:8` vs `shared/entities/models.py:134`.
8. **Tick, two** — `brokers/gateway.py:10` vs `shared/entities/models.py:121`.
9. **PnL, six sites** — `oms.py`, `live_oms.py`, `aggregates.py`, `state.py`, `context_builder.py`, `entities.py`.
10. **VWAP, three** — `aggregator.py`, `amt/profile/vwap.py`, `contracts/market_data_utils.py`.
11. **Session/time parsing, five sites** — `session_gates.py`, `amt/session/context.py`, `state.py`, `aggregator.py`, `contracts/timezones.py`.
12. Market structure ×2, displacement ×2, startup reconciliation ×2, contract scanning ×2.
13. **Frontend duplicates of backend logic** — see 1.4.

### 1.3 Dead code (ranked)
1. `quant/execution/exit_rules.py` — 616 LOC, mostly dead (only `classify_exit:496`, `get_session_time_stop:557` live).
2. `quant/contracts/constants.py` — ~30 unread constants (`CVD_SLOPE_HARD_BLOCK:68`, `SIGNAL_TTL_SECONDS:126`, `RISK_PER_TRADE_PCT:133`, `MAX_DAILY_LOSS_PCT:134`, `ATR_TRAIL_ACTIVATION_R:205`, …).
3. `SignalBuilder.size()` (`signal_builder.py:206`) — never called.
4. `runtime.py` dead imports/constants — `MarketState:12`, `random:16`, `ThreadPoolExecutor:21`, `empty_amt_dto:26`, `_DETERMINISTIC_CONVICTION:75` (shadow of live one at `context_builder.py:24`), `_WARMUP_BARS:84`.
5. `events.py:86 DepthUpdated` — defined/projected, never emitted.
6. `quant/strategy.py` — dead seam (`on_bar():24` never called; imports nonexistent `quant.auction_state:8`). Real strategy is `strategies/amt_scalping.py:46` + gates.
7. `analyzer.py:965 compute_observation()` + `amt/models/observation.py` — RL leftovers.
8. `amt/session/one_min_bar.py:36 OneMinBarEngine` — zero refs.
9. `risk.py:301 pyramid_position_size`, `:316 rupee_risk_for_quantity` — test-only.
10. `decision/context.py` dead fields — `state:13`, `consecutive_losses:30`, `agent_probability:33` (set, consumed by no gate), `balance_ratio:41`, `equity:70`, `risk_per_trade_pct:71`.
11. AI VOs — `ModelWeights:370`, `FactorBreakdown:381`, `AIAnalysisResult:392`, `AICommandResponse` (0 usages).
12. **Frontend dead:** `ProfileOverlayInfo.tsx` (never mounted), `llmHistory` (built, never rendered), `auction`/`overseer`/`history_loaded` handlers (backend never sends), `types.ts` phantom fields (`aiAnalysis`, `modelWeights`, `predictions`, …).
13. **Backend dead:** `TradeJournal` (`trade_journal.py`) has **no production writer** — `/api/journal*` serves an empty store live; real persistence is SQLite + quant JSONL. `PaperBrokerAdapter.execute_order` never called in paper mode. `IBroker.cancel_order` has zero callers.

### 1.4 SOLID / SoC / SSoT violations (top 10)
1. **Layer inversion contracts→execution:** `contracts/entities.py:22` imports `execution.exit_rules`.
2. **Layer inversion execution→decision:** `execution/order.py:4` imports `decision.signal_builder.Signal`.
3. **decision→contracts.aggregates cycle:** `decision/context.py:5` imports `INITIAL_CAPITAL` → forms `decision→contracts→execution→decision` package cycle.
4. **God class `QuantEngine`** (`runtime.py:88`, 1218 LOC) — feed loop + aggregation + AMT orchestration + decision dispatch + exits + events + storage + EOD.
5. **God class `QuantCoordinator`** (`multi_engine.py:201`, 1066 LOC) — scan + spawn + reconcile + EOD watchdog + halt + snapshot.
6. **God class `AMTAnalyzer`** (`analyzer.py:239`, 1052 LOC) — one `analyze()` recomputing derived analytics per bar.
7. **God class `PositionManager`** (`position_manager.py:30`, 582 LOC) — tick exits + bar exits + trailing + pyramids + time stops.
8. **Coordinator reaches into engine privates** — `multi_engine.py:529-583` reads/writes `eng._risk/_position/_oms`; `:901-902` `engine._oms = live_oms`.
9. **God aggregate `Portfolio`** (`aggregates.py:68`, 579-LOC file) — state + sizing + slippage + commissions + stats; duplicates `SessionRisk`.
10. **Sizing scattered across 3 layers** (SRP/OCP broken, real-money) — see C1.

### 1.5 Frontend implements backend logic (ranked)
1. **Trading verdict ("Rule Checklist")** — `DiagnosticsPanel.tsx:210-229` (`RESPONSIVE FADE ACTIVE` / `ENTER_NOW` / `MONITOR`), incl. VA-edge proximity test duplicated at `:258`.
2. **Failed-breakout detection + IB classification** — `InitialBalanceCard.tsx:98-129` (MRL-009), IB NARROW/WIDE bands `:39-66`.
3. **Order-flow conflict/divergence + option-flow interpretation** — `OrderFlowCard.tsx:82-123` (bull/bear votes, CVD-vs-IB divergence, CE/PE→underlying inference).
4. **IB-break retest zone from raw candles, TWO impls** — `ChartScene.tsx:608-688` + `ExecutionMarkersManager.ts:99-131`. Backend already detects the break (`dto.py:112-114`); FE re-detects *when*, twice.
5. **Hardcoded session-phase logic** — `ChartScene.tsx:511-606` (NSE 9:15/10:15/12:00-14:00/14:45-15:30) painted for **every** symbol incl. MCX (which is 09:00–23:30). Contradicts backend `amt/session/context.py:666-696`.
6. **Triple-A gate re-scoring** — `utils/threeA.ts:29-50` re-derives the 3 gates with local thresholds; can drift from `quant/decision/`.
7. **PnL/risk math fallbacks** — open PnL `AIAnalysisPanel.tsx:55-63` + `MarketSidebar.tsx:49-53`; session PnL/equity `EquityPanel.tsx:17-27`; R-multiple `TradePlanCard.tsx:24-26`. Backend already computes these (`state.py:301-309`).
8. **Client-derived LTP (mid-price)** — `AIAnalysisPanel.tsx:45-53` `(bestBid+bestAsk)/2`, though backend streams canonical `ltp` that is never passed to the panel.
9. VA-expansion re-derivation `VaFreezeCard.tsx:10-17`; VWAP slope indicator `AMTLevelsOverlay.ts:40-63`; VWAP-event detection `DiagnosticsPanel.tsx:114-208`; misc display analytics (delta volume coloring, % change, POC confluence, swing-delta labels, exit-reason relabeling).

**Not found client-side (good):** no candle aggregation, no POC/VAH/VAL computation, no order sizing, no VWAP/σ-band math.

### 1.6 Live vs replay divergence
- **There is no replay mode in the frontend.** Replay is an **offline engine-determinism harness** over the JSONL journal (`tests/quant/certification/journal_replay.py`, `journal_ticks.py`, `replay_journal.py`). It runs the journal's *bars* through **two fresh engines** and compares them **to each other** — never to the decisions recorded live.
- **Live-vs-replay parity is explicitly unproven and self-documented as such:** `journal_ticks.py:5-8` — *"replay x2 determinism is exact, live-vs-replay parity needs tick-grade journals."* Raw ticks and depth are never journaled, so VWAP/depth-dependent gates (OBI, gate-3 aggression) cannot be parity-checked.
- Replay engines are built **without the LLM advisor** (F4 rule), so `agentDecision` is excluded from replay determinism by construction.
- Replay appends a synthetic zero-volume tick to close the final forming bar (`journal_replay.py:33-43`) — a structural live/replay asymmetry.
- The frontend fixture "replay" (`runtime_audit/transport/build_fixture.py`) feeds **handwritten phantom AMT dicts** (`vah`, `val`, `cvd` — keys the real mapper never emits) and pair-array depth, so frontend tests pin a fabricated contract.

---

## TASK 2 — Domain Model Re-Design

**Principles:** one concept = one type; immutable value objects; IDs assigned deterministically at boundaries (never `uuid4()` in a constructor); Decimal for money at the domain edge, float only in the hot indicator path with conversion at exactly one boundary; **no UI fields, no broker fields** in domain objects. Same model usable in backtest, replay, and live.

```
domain/
  candles.py     Bar, Tick                       (one candle type; delete OHLC + FloatOHLC)
  indicators.py  IndicatorState protocol          (stateful, incremental update())
  signals.py     Signal                           (one model; broker mapping is a separate ACL)
  orders.py      Order, OrderStatus, Fill         (order state machine; durable)
  positions.py   Position, AddOn                  (one model; signed qty)
  trades.py      Trade                            (closed round-trip)
  risk.py        RiskParams, RiskState            (immutable params value object)
  session.py     TradingDay, SessionPhase         (deterministic from config + bar ts)
  events.py      DomainEvent hierarchy            (deterministic correlation ids)
  amt.py         AMTResult                        (no UI fields)
```

| Object | Canonical shape | Rules |
|---|---|---|
| `Bar` | `symbol, interval_sec, ts (epoch UTC int), o,h,l,c,v, delta, cvd, is_closed` | One type. `ts` is an int epoch, not a polymorphic str. Delete `OHLC`/`FloatOHLC`. |
| `Tick` | `symbol, ts, price, size, side, bid, ask` | One type (delete `shared` twin). |
| `IndicatorState` | `update(bar|tick) -> None` + read-only accessors | Incremental only; **no recompute-from-scratch**. Fixes the skipped incremental-profile bug. |
| `Signal` | `id (deterministic seq/hash), symbol, side (BUY/SELL canonical), intent (entry/exit/pyramid), price, stop, target, qty, lot_size, rr, setup, model_label, created_ts, ttl` | One model. `qty` and `lot_size` are **mandatory and carried through to execution** (fixes C1). Broker enums live in the adapter ACL, not here. |
| `Order` | `id, signal_id, symbol, side, qty, order_type, limit_price, status, filled_qty, avg_fill_price, broker_order_id, submitted_ts, terminal_ts` | Real state machine `CREATED→SUBMITTED→ACKED→PARTIAL→FILLED/CANCELLED/REJECTED`. **Durable (orders table).** |
| `Fill` | `order_id, qty, price, ts, fees` | Immutable. |
| `Position` | `id, symbol, side, qty (signed), entry_price, stop, targets[], opened_ts, entry_bar_index, realized_pnl, add_ons[]` | One model. Signed qty (fixes C6). No cushion/scale UI/strategy fields. |
| `Trade` | `position_id, entry_fill, exit_fill, pnl, r_multiple, setup, exit_reason` | Closed round-trip record. |
| `RiskParams` | `risk_per_trade_pct, max_daily_loss_pct, max_consecutive_losses, max_trades_per_session, max_positions, max_portfolio_risk_pct, sizing_tiers` | Immutable value object, loaded once, injected. **Not scattered across ctors/config/constants.** |
| `TradingDay` / `SessionPhase` | `trading_date (not wall-clock), market (NSE/MCX), phases{open,warmup_end,eod_squareoff,close}` | Deterministic from config + bar ts. **Never `datetime.now()`.** |
| `AMTResult` | (as-is minus UI fields) | Remove `vwap_deviation_sigmas`-style "frontend shows N/A" fields and option-labelling; those are presentation. |

**Deletions implied:** `OHLC`, `FloatOHLC`, broker `Signal`/`Position` as domain types (move to adapter ACL), `shared/entities/models.py` duplicates, `ModelWeights`/`FactorBreakdown`/`AIAnalysisResult`/`AICommandResponse`, dead `context.py` fields.

---

## TASK 3 — Architecture Re-Design (Hexagonal / Ports & Adapters)

```
                        ┌───────────────────────────────┐
                        │        PRESENTATION           │
                        │  FastAPI REST/WS (thin)       │
                        │  Frontend (pure consumer)     │
                        └───────────────┬───────────────┘
                                        │ versioned DTOs (generated)
                        ┌───────────────▼───────────────┐
                        │     APPLICATION / ENGINE      │
                        │  TradingEngine (event loop)   │  ← same for backtest/replay/live
                        │  SessionLifecycle, Coordinator│
                        └───────┬───────────────┬───────┘
                                │               │
                ┌───────────────▼──┐        ┌───▼────────────────┐
                │     STRATEGY     │        │     EXECUTION      │
                │ IndicatorEngine  │        │ RiskGate (choke)   │
                │ AMTAnalyzer      │        │ OMS (state machine)│
                │ GatePipeline     │        │ PositionManager    │
                │ SignalBuilder    │        └───┬────────────────┘
                └───────┬──────────┘            │ ports
                        │               ┌───────▼────────────────┐
                ┌───────▼───────────────┴────────────────────────┐
                │                  DOMAIN (pure)                  │
                │  Bar/Tick/Signal/Order/Position/Trade/Risk/    │
                │  Session/AMTResult/DomainEvents                 │
                └─────────────────────────────────────────────────┘
                        ▲ implemented by
                ┌───────┴────────────────────────────────────────┐
                │              INFRASTRUCTURE (adapters)         │
                │  DhanBrokerAdapter, MarketFeed, Persistence,   │
                │  Clock, WS transport, (future Zerodha)         │
                └────────────────────────────────────────────────┘
```

**Dependency rule:** arrows point inward. Domain imports nothing. Strategy imports Domain. Engine imports Domain+Strategy. Infra implements Domain ports. Presentation imports Application. **The `contracts→execution→decision` cycle is deleted.**

| Layer | Runs where | Responsibility | Forbidden |
|---|---|---|---|
| Domain | backend | Pure entities/VOs/events, risk policy, order/position state machines | I/O, framework, broker, UI |
| Strategy | backend | Incremental indicators, AMT, gates, signal build | I/O, broker, wall-clock |
| Engine (Application) | backend | Event loop, orchestration, session lifecycle, coordinator | broker details, UI |
| Execution | backend | RiskGate choke point, OMS, position mgmt | strategy logic |
| Infrastructure | backend | Broker adapters, feeds, persistence, clock, WS transport | strategy decisions |
| Presentation | FastAPI = backend; UI = frontend | Thin REST/WS; render-only UI | **any trading logic in UI** |

**What is shared FE↔BE:** *nothing executable.* The only shared artifact is a **generated contract** (TypeScript types emitted from the backend Pydantic schema). Logic is never shared.

**Strictly forbidden in frontend:** indicator math, PnL/R-multiple calc, signal/decision/verdict logic, risk math, session-phase logic, order sizing, breakout/retest re-detection, client-derived prices. If the UI needs it, the backend sends it as a typed field.

---

## TASK 4 — Trading Pipeline Re-Architecture (deterministic)

```
MarketEventStream (ticks)                 ← injected: Live=Dhan feed | Replay/Backtest=journal feed
  → BarAggregator        (incremental)
  → IndicatorEngine      (incremental, stateful update())
  → AMTAnalyzer          (→ AMTResult)
  → DecisionContextBuilder
  → GatePipeline         (4 gates, pure functions)
  → SignalBuilder        (→ Signal with qty + lot_size)
  → RiskGate             (SINGLE choke point: halt/budget/portfolio/sizing/lot)
  → OMS                  (order state machine, durable)
  → BrokerAdapter        (ACL translate + execute exact qty)
  → FillFeed             (async WS order updates, not REST polling)
  → PositionManager / StateProjector (event-sourced fold)
```

**Requirements met:**
- **Candle-by-candle, event-driven.** The engine consumes an abstract `MarketEventStream`; every stage is a pure/incremental transform emitting domain events.
- **Replay and live share 100% of logic.** The ONLY things injected differently per mode are: the feed (Dhan vs journal), the OMS (LiveOMS vs PaperOMS/sim), and the Clock. Strategy, indicators, gates, risk are identical instances.
- **Time control does not fork logic.** A `Clock` port is injected. **Decision logic reads time ONLY from the bar/tick timestamp, never from the clock.** The clock is used only for non-decision stamping/ops. Replay drives the clock from the journal; this is the single rule that makes replay==live.
- **No recompute from scratch.** All indicators are `update()` objects. (Fixes the skipped `TestIncrementalProfile` bug; `AMTAnalyzer.analyze` must stop recomputing derived analytics per bar.)

**Determinism fixes required:** remove `datetime.now()` from the decision path (`risk.py:16-17` keys daily risk by wall-clock date → key by trading_date; `amt/session/context.py` nine `datetime.now` fallbacks → require caller-supplied ts); remove `random.uniform` from seeding (`amt_engine.py:64,228`); replace `uuid4()` in domain constructors with deterministic ids (`order.py:22`, `entities.py:47/96`, `events.py:45`).

---

## TASK 5 — Frontend Refactor Plan (pure consumer)

1. **Delete all leaked logic** (1.5 items 1–9). Each either becomes a backend-computed snapshot field or is deleted:
   - Verdict, failed-breakout, retest-zone, 3-A score, VA-expansion, VWAP events → backend fields (or dropped).
   - PnL/R-multiple/session-equity fallbacks → always read backend values; delete client math.
   - Client mid-price LTP → use backend `ltp` (wire it into the panel).
   - Session-phase shading → backend sends typed phase overlays per market (fixes NSE-times-on-MCX).
2. **Single source of truth.** One WS-driven store. Delete the duplicate `ChartScene` `scopedData` cache; one candle cache.
3. **Chart = projection.** Render backend series + backend-computed typed overlays (retest zone, markers, phases). No client derivation.
4. **Generated types.** Replace hand-maintained `types.ts` with codegen from the backend schema (kills the drift in 1.6/7.x).
5. **Replay controls only control time.** UI sends `{replay:{command,speed,position}}`; backend replays through the SAME engine and streams **identical** snapshots. UI renders; it never re-derives.
6. **Delete dead surface:** `ProfileOverlayInfo`, `llmHistory`, `auction`/`overseer`/`history_loaded` handlers, phantom `types.ts` fields. Fix the 8090-vs-9090 port mismatch.

---

## TASK 6 — Backend Refactor Plan

1. **Broker-agnostic OMS** with a real order state machine + **durable orders table** + **async fill feed** (Dhan WS order updates; retire the 0.5s×30s REST poll).
2. **Single RiskGate choke point** before ANY order submission (live AND paper). **Move sizing OUT of the adapter**; the adapter only translates and executes the exact qty/lot it is given (fixes C1). Wire `risk_per_trade_pct` through DI (fixes C2).
3. **Adapter pattern, one port.** Merge `IBroker` + `IBrokerPort` into one `BrokerPort`. **One `DhanBroker` singleton** (fixes two instances / two blind rate-limiters). Future Zerodha implements the same port + the shared contract suite.
4. **OMS failures non-fatal.** try/except around OMS calls; unwind risk reservation on failure; don't kill the engine (fixes C3). `emergency_halt` under `_close_lock`, pyramid-aware (fixes C5). Signed reconciliation (fixes C6). Limit-price collars instead of naked MARKET (fixes C7).
5. **Deterministic simulation engine.** PaperOMS with realistic slippage/fees (reuse the dead `PaperBrokerAdapter` cost model so paper P&L represents live).
6. **Unified backtest/replay/live engine** (Task 4) — inject feed/OMS/clock.
7. **Per-day lifecycle.** Explicit `SessionLifecycle`: open → warmup → trade → eod-squareoff → close → persist → reconcile, driven by the trading-day clock, not wall-clock. Add an **intraday reconciliation loop** (fixes C4).
8. **Real portfolio ceiling** (not 95%) and persist it.

---

## TASK 7 — API & Contract Design

1. **One canonical schema module** (Pydantic) = single source of truth for every wire object.
2. **Generate TypeScript** from it (codegen). Delete hand-maintained `types.ts`.
3. **Version every envelope.** Add `v` field. Additive = minor bump; breaking = major. Delta frames carry the version (today a key rename is indistinguishable from "no change" under delta compression).
4. **Event schemas (versioned):** `Candle, Signal, Order, Fill, Trade, Position, PnL, RiskState, Decision`.
5. **One serialization boundary** per channel. Delete the duplicated envelope producer (`ws_contract.py:to_dict` vs `ws_adapter.py:view_state_to_ws`) and the ~10 ad-hoc dict-builders; stop post-serialization mutation (`runtime.py:638-677` injecting `barInterval`/overrides).
6. **Replay and live stream IDENTICAL snapshots/events.** Replay = engine fed recorded data; same wire format. Add a replay transport endpoint.
7. **Fix the drifted contracts now:**
   - `agentDecision` — 3 incompatible definitions (`ws_contract.py:41-50` vs `llm/narrative.py:64-72` vs `frontend/types.ts:40-48`). Pick the real emitted shape; delete the fiction dataclass; update FE.
   - AMT DTO — defined 3× with ~20-field drift (`amt/dto.py` 77 keys vs `schemas.py:AMTAnalysisDTO` 53 vs `types.ts:AMTAnalysis` 64). One definition.
   - Depth — object vs pair-array conflict. Pick objects (live feed shape); fix the pair-array tests/fixtures.
   - Remove or wire the dead `auction`/`overseer` surface. Fix `RiskState`/`TradePosition` drift. Retire the orphaned `TradeJournal` or wire it as the real writer.

---

## TASK 8 — Test Strategy (mandatory)

~2,770 cases today (tests/ 1278, backend/tests 792, brokers 469, frontend ~231). Strong unit + golden-determinism; weak parity/contract/property.

| Type | Status | Action |
|---|---|---|
| Unit (indicators, gates, risk, order SM) | Present, strong | Keep; add order-state-machine + RiskGate units |
| Property-based | **Token (2 tests)** | Expand via hypothesis: sizing, risk math, order lifecycle, bar-aggregation invariants |
| **Replay-vs-live parity** | **MISSING (critical)** | Record **tick-grade journals** (raw ticks + depth) in live; replay through the engine; assert decision-for-decision equality vs the live record. This is the documented upgrade path (`journal_ticks.py:5-8`). |
| Broker adapter contract | **Partial** | Shared parameterized conformance suite run against every impl + paper sim; extract `MockBroker` into a shared fixture |
| E2E simulation (candle→order) | Present, strong | Keep + extend to cover C1–C7 regressions |
| Regression/golden | Present, strong | Keep; add golden WS snapshot for the FULL AMT payload (today only `{"poc":100.2}`) |

**Must un-skip (5 groups hiding real bugs):** incremental-profile divergence (`test_amt_analyzer.py::TestIncrementalProfile`), option-scanner service (10 tests), MarketState PROBING-vs-BALANCED mismatch (`test_raci_bindings.py`), scanner exchange passthrough (`test_scanner.py::test_scanner_passes_exchange_string`), parquet-gated feature-skew guard (skipped everywhere incl. CI). **Fix or delete — a green suite that floors 172 known failures overstates correctness.**

**Determinism hygiene:** add freezegun/controlled clock; remove `datetime.now()` from decision path; remove `time.sleep` from concurrency tests. **CI:** add broker tests + frontend tests + e2e (currently excluded); fix the py3.11/3.12-vs-3.13 matrix (deployed interpreter is least-tested).

---

## TASK 9 — Refactoring Roadmap

> Rule: each phase leaves the suite green and golden traces byte-identical unless the phase explicitly changes behavior (Phase 1 changes behavior on purpose — it fixes money bugs).

### Phase 1 — Safety (fix real-money bugs; no re-architecture)
- **Change:** C1 pass engine qty+lot through, delete adapter re-sizing; C2 wire `risk_per_trade_pct`; C3 try/except OMS + unwind reservation; C5 `emergency_halt` under `_close_lock`; C6 signed reconciliation; C7 limit collars; add durable orders table + order state machine; async fill feed; single `DhanBroker` singleton.
- **Delete:** the second sizing path in the adapter; the duplicate startup-reconciliation semantics (pick one).
- **Do NOT touch:** strategy logic, AMT, gates, frontend.
- **Validation:** new regression tests per C#; full suite green; paper e2e; live canary with tiny size.

### Phase 2 — Domain cleanup
- **Change:** unify candle/signal/position/order/tick to one type each; extract `RiskParams` VO; break the `contracts→execution→decision` cycle; deterministic ids.
- **Delete:** `exit_rules.py` (616 LOC), dead constants, `SignalBuilder.size`, `DepthUpdated`, AI VOs, dead `context.py` fields, `strategy.py` dead seam, `shared/entities` duplicates.
- **Do NOT touch:** pipeline behavior, OMS (from Phase 1).
- **Validation:** suite green; golden event traces byte-identical (proves no behavior change).

### Phase 3 — Architecture realignment
- **Change:** establish hexagonal boundaries; pull strategy out of engine; introduce `Clock` port (decision reads time only from bars); single RiskGate choke point; unified backtest/replay/live engine (inject feed/OMS/clock); real portfolio ceiling + persistence.
- **Delete:** god-class responsibilities split (engine/coordinator/analyzer/position-manager); `Portfolio` sizing/slippage duplication.
- **Do NOT touch:** wire contracts yet (Phase 4), frontend.
- **Validation:** replay-x2 determinism still exact; **new replay-vs-live parity test passes on a recorded tape**.

### Phase 4 — Frontend/backend separation
- **Change:** codegen TS types from backend schema; move needed computations to backend snapshot fields; single store; replay transport (backend replays, streams identical snapshots).
- **Delete:** all leaked frontend logic (Task 5 list); duplicate candle cache; dead FE surface; hand-maintained `types.ts`.
- **Do NOT touch:** backend domain/engine (Phases 2–3).
- **Validation:** frontend tests green against a REAL fixture (not phantom); a grep/lint gate proves no trading logic in FE; replay and live snapshots diff-identical.

### Phase 5 — Performance & observability
- **Change:** incremental indicators everywhere (fix incremental profile); tick-grade journaling; structured metrics (order lifecycle, risk-gate decisions, reconciliation, latency); intraday reconciliation loop.
- **Delete:** remaining dead code surfaced by the above.
- **Validation:** parity test on a live-recorded tape; dashboards for order/risk/reconcile health.

---

## TASK 10 — Final Deliverables

### Component responsibilities (target)
| Component | Responsibility | Must NOT |
|---|---|---|
| Domain | Pure VOs/entities/events, risk policy, order/position state machines | I/O, broker, UI |
| IndicatorEngine | Incremental indicator state | recompute from scratch, I/O |
| AMTAnalyzer | Produce `AMTResult` from indicator state | UI fields, wall-clock |
| GatePipeline | Pure 4-gate decision | I/O, sizing |
| RiskGate | Single pre-submission choke: halt/budget/portfolio/size/lot | be bypassed |
| OMS | Order state machine, durable orders, fill reconciliation | size orders, strategy |
| BrokerAdapter | ACL translate + execute exact qty | re-size, risk decisions |
| Engine | Event loop, session lifecycle | broker details |
| FastAPI | Thin REST/WS, versioned DTOs | logic |
| Frontend | Render-only projection | any trading logic |

### Anti-patterns found
1. Duplicated domain models (2–3× per concept). 2. Layer-inversion import cycle. 3. God classes (1000+ LOC). 4. Scattered sizing/risk (no choke point). 5. Frontend as co-strategy. 6. Hand-maintained cross-language contracts (drift). 7. Unversioned wire envelopes. 8. Synchronous REST-poll "fills" instead of an event feed. 9. No durable order state. 10. Wall-clock in decision path. 11. `uuid4()` in domain constructors. 12. Dead parallel subsystems (`exit_rules.py`, `TradeJournal`, `PaperBrokerAdapter` order path). 13. Skipped tests flooring known failures. 14. Two broker instances / two rate-limiters.

### Before vs After
| Dimension | Before | After |
|---|---|---|
| Candle types | 3 (`Bar`/`OHLC`/`FloatOHLC`) | 1 (`Bar`) |
| Signal/Position/Order models | 2/3/2 | 1/1/1 (+ durable Order SM) |
| Sizing impls | 3 (disagree in live) | 1 (RiskGate) |
| PnL sites | 6 | 1 |
| Layer deps | `contracts→execution→decision` cycle | Strict inward (hexagonal) |
| Risk enforcement | Scattered in engine `_decide` | Single RiskGate choke point |
| Fills | Sync REST poll 0.5s×30s | Async WS fill feed + reconciliation |
| Order durability | None | Orders table + state machine |
| FE trading logic | Verdicts, detectors, PnL, phases | None (render-only) |
| Contracts | 3× hand-maintained, unversioned, drifted | 1 schema, codegen, versioned |
| Replay vs live | Offline x2-determinism only; parity unproven | Same engine; tick-grade parity test |
| Time in decisions | `datetime.now()` fallbacks | Bar/tick ts only; injected Clock |

### Non-negotiable coding rules (future development)
1. **One concept = one type.** Never add a second `Position`/`Signal`/`Bar`. Translate at boundaries via an ACL.
2. **Domain imports nothing.** No I/O, framework, broker, or UI in `domain/`.
3. **No trading logic in the frontend. Ever.** If the UI needs a value, the backend sends it.
4. **Decision logic reads time only from bar/tick timestamps.** No `datetime.now()`/`time.time()` in the decision path. Clock is injected.
5. **All risk passes through the single RiskGate** before any order. No adapter re-sizing.
6. **Orders are durable and state-machined.** No fire-and-forget submissions; every order reconciles.
7. **The engine-sized quantity is the quantity that executes.** Carried end-to-end with lot size.
8. **Contracts are versioned and generated.** The wire schema is defined once; TS is codegen'd. Breaking change = major bump.
9. **Indicators are incremental.** No recompute-from-scratch per candle.
10. **No `uuid4()`/`random` in domain objects or decision logic.** Deterministic ids.
11. **Replay and live share 100% of logic.** Only feed/OMS/clock differ by injection.
12. **Prefer deletion over refactoring.** Dead code is deleted, not commented.
13. **Never skip a failing test.** Fix it or delete it. A green suite must mean correct.
14. **Broker failures are non-fatal to the engine** and always unwind risk reservations.

---

## Sequencing note
Do **Phase 1 first and in isolation** — it fixes active real-money defects (C1–C7) with no re-architecture risk. Phases 2–5 are the clean-up/re-architecture and can proceed incrementally, each gated on a green suite + unchanged golden traces (except where a phase intentionally changes behavior).
