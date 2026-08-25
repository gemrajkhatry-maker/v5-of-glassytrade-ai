# Principal Re-Architecture — GlassyTrade AI

**Date:** 2026-08-24  
**Role:** Principal Trading Systems Architect  
**Status:** Analysis only. No production code changed by this document.  
**Companion:** today’s production-rework audit (`docs/audit/PRODUCTION_REWORK_AUDIT_2026-08-24.md`).

**Verdict: not production-ready for live capital.**  
The decision kernel is a real engine. The money path is not.

---

## 1. System Intent

Trade Indian index and commodity options (NSE / MCX, later BSE) with a single Auction Market Theory (AMT) scalping playbook:

1. Ingest exchange ticks (Dhan today).
2. Aggregate to bars; maintain incremental volume profile, VWAP, CVD, IB, drives, NPOC.
3. On bar close, evaluate session + Triple-A / LVN / VA-fade gates.
4. Size under session + portfolio risk.
5. Place, manage, and exit orders through a broker-agnostic OMS.
6. Persist every fill so restart, replay, and nightly audit reconstruct the same book.
7. Project state to a read-only UI. The UI never decides, never sizes, never clocks the market.

**Intended modes (one engine, three clocks):**

| Mode | Clock | Fill model | Persistence |
|---|---|---|---|
| Backtest | recorded ticks | simulated, same OMS port | journal |
| Replay | recorded ticks / journal | simulated, same OMS port | journal |
| Paper | live ticks | simulated, same OMS port | journal + storage |
| Live | live ticks | **exchange**, same OMS port | journal + storage + broker reconcile |

**Actual:** backtest, replay, paper, and `GLASSYTRADE_ENV=live` all fill inside `PaperOMS`. `IBroker.execute_order` has no production caller. Storage `save_open_position` / `save_trade` have no production writer from the engine.

---

## 2. Current Architecture Map

```
┌─────────────────────────────────────────────────────────────────────────┐
│ FRONTEND (React / Zustand chrome / Lightweight Charts)                  │
│  Viewer + parallel scoring (3A ENTER, IB targets, client PnL, VWAP)     │
│  No replay UI. No order send. Forming-bar merge is client-owned.        │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ WS /api/trading/ws/gameloop (delta)
                                │ REST history, journal, config
┌───────────────────────────────▼─────────────────────────────────────────┐
│ BACKEND FastAPI SHELL                                                    │
│  DI composition root · gameloop projector · REST · SIGTERM halt          │
│  DhanMarketDataAdapter (USED)  DhanBrokerAdapter (CONSTRUCTED, UNUSED)   │
│  SQLite IStorage (ports exist; engine never writes positions)            │
│  AnalysisService — a SECOND AMTAnalyzer, not the live engine             │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │ QuantCoordinator.start()
┌───────────────────────────────▼─────────────────────────────────────────┐
│ QUANT (the brain — quant.* only)                                         │
│  Coordinator: scan → spawn 1 QuantEngine thread / symbol                 │
│  Engine: Tick → BarAggregator → AMTEngine → DecisionService              │
│          → SessionRisk → PaperOMS → PositionManager → EventBus           │
│  Projector → camelCase WS snapshot                                       │
│  Journal JSONL (fsync) — the only durable trade record on the hot path   │
└───────────────────────────────┬─────────────────────────────────────────┘
                                │
        ┌───────────────────────┼────────────────────────┐
        ▼                       ▼                        ▼
  quant/brokers/          brokers/ (Dhan hexagon)    shared/entities
  Tick + LiveGateway      IBrokerPort + DhanBroker   Instrument.security_id
  (USED by engine)        (USED for market data;     (Dhan id on "canonical")
                           UNUSED for orders)
```

**Three universes that never meet:**

| Universe | Types | Who uses it |
|---|---|---|
| Engine book | `signal_builder.Signal` (LONG/SHORT, float `entry/sl/tp`), `execution.order.Position` | QuantEngine, PaperOMS, projector |
| Port book | `contracts.entities.Signal` (BUY/SELL, Decimal `price/stop_loss`), `contracts.entities.Position`, `Portfolio` | IBroker adapters, unit tests |
| Broker book | `shared.entities.models.Order/Position/Tick`, `DhanInstrument` | Dhan hexagon |

`QuantCoordinator.broker` is assigned and never read.

---

## 3. End-to-End Execution Flow (one bar)

Walk-through assuming live CRUDEOIL futures ticks, IST session open, engine warmed (>15 bars).

| Step | Code | State change | Silent-failure if… |
|---|---|---|---|
| 1 | Dhan WS FULL packet | raw broker bytes | feed drop |
| 2 | `multiplexed_feed._normalize_dhan_packet` | `quant.brokers.gateway.Tick` with exchange LTT | LTT missing → arrival stamp (host TZ) |
| 3 | `LiveGateway.next_tick` | per-symbol queue | queue overflow / symbol mismatch |
| 4 | `BarAggregator.add_tick` | forming bar; on boundary emit closed `Bar` | clock jump / duplicate timestamps |
| 5 | `AMTEngine.on_tick` + `analyze` on close | incremental VP, CVD, IB, drives, DTO | seed thread lost the race → cold profile |
| 6 | `QuantEngine._decide` | halt? cooldown? warmup? | cooldown returns with **no** `DecisionProduced` (stale ENTER on WS) |
| 7 | `DecisionContextBuilder.build` | session + AMT + position flags | `ist_dt` None on synthetic times → gates skipped |
| 8 | `AmtScalpingStrategy.should_enter` → `DecisionService.evaluate` | gates 1–4 or VA-fade | DEAD mapped away on **exits** (see below) |
| 9 | `SignalBuilder.build` | engine `Signal` | thin stop discarded silently (`None`) |
| 10 | `SessionRisk.position_size` + `PortfolioRiskAuthority.can_accept` | qty or refuse | lot-size lookup fail → 1.0 |
| 11 | `PaperOMS.submit` | in-memory `Position` | **no broker call even in live env** |
| 12 | `EventBus` → journal + projector | JSONL + WS snapshot | journal fail swallowed (no audit trail) |
| 13 | later: `PositionManager.manage_exit` | whole-position `PaperOMS.close` | `close_partial` never called; DEAD→BALANCED |

**Expected:** step 11 hits `IBroker.execute_order` in live, `PaperOMS` in paper/replay, same `Position` type, storage write, broker ack.  
**Actual:** step 11 is always paper. Live mode is a label on the process, not a fill model.

Replay uses the same `_run_inner` with `SyntheticGateway`. Parity holds for **decisions given identical ticks and parseable timestamps**. It does not hold for fills, costs, session gates on `t0..tN` labels, history seeding, or broker state.

---

## 4. Invariant Checklist

| Invariant | Required | Enforced today |
|---|---|---|
| One Signal type across engine and broker | yes | **no** — two Signals, no mapper on hot path |
| One Position type restored on restart | yes | **no** — engine position is RAM; storage unused |
| Live fill == paper fill semantics except venue | yes | **no** — live never leaves process |
| Replay(ticks) == live(ticks) for decisions | yes, given parseable time | **partial** — synthetic times skip session gates |
| Indicators incremental, not full recompute | yes | **mostly** — AMTAnalyzer is incremental; REST `/analysis/amt` rebuilds a fresh analyzer |
| Frontend cannot produce ENTER | yes | **no** — `computeThreeA` emits ENTER independently |
| Kill switch flattens exposure | yes for live | **no** — halt blocks new entries only; no broker flatten |
| Daily loss / 3-stop cutoff cannot be bypassed | yes | **session risk yes**; default `max_trades_per_session=50` (spec ~6) |
| Unknown symbol cannot silently become MCX | yes | **patched for SENSEX/BANKEX**; pattern (enum tables + fallback) remains |
| Journal is the audit of record | yes | **yes if disk works**; fail-open if disk full |
| Spec §13.3 50/25/25 runner | yes | **no production caller of `close_partial`** |
| Delta is aggressor-true | for Triple-A fidelity | **no** — uptick proxy; epistemic, not a unit-test bug |

Any invariant marked **no** is a live-trading blocker or a documented deviation. Do not treat a green pytest run as coverage of these.

---

## 5. Failure and Risk Points (real money)

Answer only what the mandate asked.

### What can go wrong silently

1. **Operator believes LIVE; exchange sees nothing.** `GLASSYTRADE_ENV=live` still `PaperOMS.submit`. UI will show positions. Broker book empty. Inverse after a naive wire: engine Signal (`entry`, LONG) vs IBroker Signal (`price`, BUY) — first live order is an untested type mismatch.
2. **Restart orphans exposure.** Nothing writes `save_open_position`. Reconciliation counts and deletes; it does not rebuild `QuantEngine._position`. Live-boot mismatch vs broker is comparing empty DB to a real book.
3. **UI ENTER while engine FLAT.** `frontend/utils/threeA.ts` is a second Triple-A with its own thresholds. Scanner can show ENTER. Engine did not approve.
4. **Client mark-to-market when `pnl === 0`.** Sidebar computes `(ltp - entry) * size`. Options multiplier, lots, fees ignored. A zero from OMS is treated as “missing.”
5. **RAF queue drops AMT/decision frames.** Ticks still paint. Intelligence is stale with no sequence number.
6. **Journal append failure is isolated.** Trading continues with no audit trail (`D-OBS-12`).
7. **Cooldown skip emits no decision event.** Projector can keep a previous ENTER.
8. **DEAD market never reaches ExitEngine.** `PositionManager` maps non-IMBALANCED → BALANCED. Volume-collapse veto can fail to force-exit.
9. **Lot/tick lookup exceptions → 1.0 / 0.05.** Wrong size, not a crash.
10. **REST `/analysis/amt` is a different analyzer instance** than the live engine. Two POCs for one symbol.

### What will break under real-time conditions

- History seed daemon vs first live bars: `if self._amt_candles: return` can skip seed → decisions on a cold profile.
- Depth + bar-close + `switch_symbol` interleaving: lifecycle locks exist; no stress test of the schedule.
- WS subscribe race (80ms debounce + StrictMode remount) can miss `server_mode` / history warm.
- Dhan has no aggressor flag. Block-at-touch regimes mislabel delta → Triple-A, absorption, CVD all shift together.
- Option engine with empty option profile can skip translation (`None`) rather than halt — silent no-trade, not a loud fail.

### Unsafe assumptions

- “`QUANT_EXECUTION_MODE` routes to the broker” — flag describes deleted `EntryCoordinator`. Coordinator always starts; OMS is always paper.
- “Frontend is a pure renderer” — header of `useServerTradingSystem.ts`. False for 3A, IB targets, VWAP events, candle merge, PnL fallback.
- “`agentDecision.timing` gates the UI” — adapter sends `""`.
- “Auction arrives on the snapshot” — removed from `WS_SNAPSHOT_KEYS`; freeze card stays empty.
- “MCX is a safe default for unknown roots” — this is the MIDCPNIFTY class.
- “`SessionRisk._today()` is session time” — it is wall-clock IST.
- “Goldens specify the strategy” — they characterize current behavior, including VAH-clamp warnings.

### Where behavior is implicit

- Fill model (SL/TP exact at level vs close) lives in tests after the fact, not in an OMS contract.
- Session-gate skip on unparseable time is a replay convenience encoded in `ist_dt` returning `None`.
- `TradingStrategy.should_exit` is a no-op; `PositionManager` is the real exit owner. Protocol lies.
- `strategy.py` TYPE_CHECKING-imports deleted `quant.auction_state`.
- Feature flags loaded into `SystemConfig.flags` and never read by `quant/`.
- Four symbol-classification tables (scanner, selector, registry, ExchangeConfig).

---

## 6. Audit findings (Tasks 1)

### Duplicate logic

| Concern | Live path | Twin | Action |
|---|---|---|---|
| Signal | `decision/signal_builder.py` | `contracts/entities.py` | one type + adapter mapper at broker edge only |
| Position / Order | `execution/order.py` | contracts + `shared.entities` | engine type is SoT; broker DTO at adapter |
| OMS | `PaperOMS` | DhanBrokerAdapter, PaperBrokerAdapter, deprecated `brokers/.../paper` | one port, two impls |
| AMT | engine `AMTAnalyzer` | `AnalysisService` fresh instance; `OrderFlowService` (tests) | kill REST twin or point it at engine |
| Session | `get_session_info` | unused `SessionContextFactory`; `session_gates` second layer | one function |
| MarketState | quant `{BALANCED, IMBALANCED, DEAD}` | shared `{… INITIATIVE, BALANCE, UNKNOWN}` | delete shared enum |
| Tick | `quant.brokers.gateway.Tick` | `shared.entities.Tick` | keep quant Tick; convert at feed |
| 3A | `gates_edge.py` | `frontend/utils/threeA.ts` | delete UI scorer |
| Session hours | `context.py` | `frontend/utils/profileInfo.ts` | stream phase; delete UI calendar |
| Portfolio defaults | `state.py` / `ws_adapter.py` / frontend empty state | ₹1M × 3 | one constant in contract |

### Dead / unused

Delete or quarantine (do not “refactor”):

- `IBroker.execute_order` **as currently unused** — keep the port, wire it, or stop constructing adapters
- `QuantCoordinator.broker` unread field
- `SessionContextFactory` (tests only)
- `OrderFlowService` if analyzer keeps inlined detectors — pick one
- `PaperOMS.close_partial` unused **or** wire §13.3
- `quant/contracts/aggregates.Portfolio.process_tick` (second exit engine)
- `brokers/broker/paper/broker.py` (DEPRECATED)
- `quant/advisory/`, `ports/llm_inference.py`, `compression_box.py`, `range_bars.py`, `amt/market/vwap_bands.py` (KNOWN_DEAD)
- `backend/app/domain/models/` empty package
- Feature flags: `quant_execution_mode`, `true_delta_lee_ready`, `print_level_trigger`, `parallel_symbol_sessions`, `walk_forward_validation`
- Frontend: `DecisionHistoryPanel`, `ModelIoFooter`, `showControls` icon, fabricated genAI placeholder, ENTER_NOW scanner filter
- Stale comments: `AuctionCoordinator`, `GREENFIELD_ENGINE`, `EntryCoordinator`

### SOLID / SoC / SSOT violations

- **SRP:** `AMTAnalyzer` (~1500 lines) and `QuantEngine` still own too many stages. Partial extractions (`AMTEngine`, `PositionManager`, `OrderFlowService`) left twins.
- **OCP:** new venue = edit four classification lists. No InstrumentRegistry.
- **LSP:** `TradingStrategy.should_exit` does not actually exit.
- **ISP:** `brokers.ports.IBrokerPort` is a mega-port (orders + history + streaming + options).
- **DIP:** composition root is real; engine then ignores `IBroker`. `SessionContextFactory` is DIP theater.
- **Frontend in domain:** camelCase DTOs in `quant/amt/dto.py` because the UI contract leaked inward.
- **Broker in domain:** `Instrument.security_id` is a Dhan id on a shared entity.

### Live vs replay divergence

Shared: `QuantEngine._run_inner`.  
Divergent: gateway, history seed, `ist_dt` skip, costs, OMS venue (both paper today), `SessionRisk._today()` wall clock.

There is **no replay product UI**. Replay is a test property. Frontend “replay” in the original brief does not exist; do not design a UI time-machine until the engine clock is explicit.

---

## 7. Domain model re-design (Task 2)

Rules: no UI fields, no broker fields, same objects in backtest / replay / paper / live.

```
InstrumentId    = { root, expiry?, strike?, right?, venue }
                venue is an enum (NSE, MCX, BSE), never a broker name.

Bar             = { instrument, timeframe, open_time (epoch ns, exchange),
                    o, h, l, c, volume, delta, tick_count, is_closed }
                Tick is Bar with timeframe=0. No Candle class.

IndicatorState  = opaque, incremental, (state, bar) -> state
                AMTResult is a *read model* of indicator+session, not a WS DTO.

Signal          = { signal_id, instrument, side: LONG|SHORT, thesis,
                    entry, sl, tp, rr, qty_hint?, model, bar_time }
                Money fields: Decimal at OMS boundary; float allowed inside AMT.

Order           = { order_id, signal_id, instrument, side, qty, type,
                    limit?, status, venue_order_id? }
                venue_order_id only on the adapter DTO, not the domain Order
                until filled — or store in Order.execution: ExecutionRef (infra).

Fill            = { fill_id, order_id, qty, price, time, liquidity, fees }

Position        = { position_id, instrument, signed_qty, avg_entry,
                    sl, tp, opened_at, pyramids[], realized, status }
                Partial close = new Fill + qty mutation; same position_id.

RiskParameters  = { max_daily_loss_pct, max_consecutive_losses,
                    max_trades, risk_per_trade_pct, cushion_table,
                    flatten_on_halt: bool }

Session         = { venue, trading_day (exchange calendar), phase,
                    allow_entry, force_exit, prior_profile, seconds_to_close }
                Clock: exchange event time converted to venue TZ. Never datetime.now().
```

**Forbidden on these types:** `security_id`, camelCase, `agentDecision`, color, chart coordinates, Dhan product codes.

**Mapping:** adapter translates Dhan packet → Tick/Bar; adapter translates Order → Dhan place_order; `view_state_to_ws` is the *only* camelCase boundary.

---

## 8. Architecture re-design (Task 3)

Hexagonal. Domain in the center. One composition root.

```
                    ┌──────── Presentation ────────┐
                    │  React: projection only      │
                    │  generated types from WS     │
                    └──────────────▲───────────────┘
                                   │ WS/REST (versioned)
                    ┌──────── Infrastructure ──────┐
                    │ FastAPI, SQLite, Journal     │
                    │ Dhan feed adapter            │
                    │ Dhan order adapter           │
                    │ Paper adapter                │
                    └──────────────▲───────────────┘
                                   │ ports
                    ┌──────── Execution ───────────┐
                    │ OMS (paper | live)           │
                    │ SessionRisk, PortfolioRisk   │
                    │ Reconciliation               │
                    └──────────────▲───────────────┘
                                   │ SignalApproved / ExitDecision
                    ┌──────── Strategy ────────────┐
                    │ TradingStrategy (AMT)        │
                    │ GatePipeline, SignalBuilder  │
                    └──────────────▲───────────────┘
                                   │ DecisionContext
                    ┌──────── Domain ──────────────┐
                    │ Bar, Signal, Position, Fill  │
                    │ Session, RiskParameters      │
                    │ AMT kernel (incremental)     │
                    └──────────────▲───────────────┘
                                   │ Tick/Bar
                    ┌──────── Data ────────────────┐
                    │ Normalizer, aggregator       │
                    │ InstrumentRegistry           │
                    └──────────────────────────────┘
```

| Layer | Runs where | Forbidden |
|---|---|---|
| Presentation | browser | any ENTER/SKIP, PnL, IB target, session hours, indicator math |
| Infrastructure | backend process | strategy rules, sizing |
| Execution | backend | UI shapes, Dhan field names (adapters only) |
| Strategy | backend `quant/` | broker ids, HTTP, React |
| Domain | `quant/contracts` + `quant/amt` + `quant/execution/order` | camelCase, `security_id` |
| Data | `quant/brokers`, adapters | decision |

**Shared:** domain types + AMT kernel + OMS port. Shared via Python package, not a JS port of indicators.

**Frontend strictly forbidden:** Triple-A, SL/TP, sizing, session phase, expiry, PnL, IB extensions, VWAP slope-as-signal.

---

## 9. Trading pipeline (Task 4)

Deterministic, event-driven, candle-by-candle:

```
TickIn
  → Normalize(exchange time)
  → Aggregate(timeframe)          # incremental
  → OnTick(footprint, CVD)        # incremental
  → OnBarClose
       → Indicators.update(bar)   # incremental; never replay full history
       → Session.update(bar.time) # exchange clock
       → if position: Exits.eval  # includes DEAD, spread blowout, time, SL/TP/partials
       → else: Strategy.should_enter
       → Risk.authorize
       → OMS.submit | OMS.reduce | OMS.close
       → Persist(event)
       → Project(ws)
```

Replay control is a **gateway that emits historical ticks at a chosen rate**. It does not call `analyze()` itself. Time travel = seek journal offset + reset indicator state from snapshot, then replay forward. No forked “replay engine.”

**Clock law:** every gate uses `bar.open_time` in venue TZ. `datetime.now()` is allowed only for process liveness (WS heartbeat), never for phase, expiry, or `_today()`.

---

## 10. Frontend refactor plan (Task 5)

The frontend is already close to a viewer. The damage is **parallel conclusions**.

1. Generate `frontend/types.ts` from `quant/ws_contract.py` (or fail CI on drift). Restore the deleted generator.
2. Delete `computeThreeA` ENTER/MONITOR/SKIP. Stream `quantDecision` only. Scanner sorts by engine approval, not a client score.
3. Delete IB 1.5×/2.0× targets from `InitialBalanceCard` unless the engine emits them on the signal.
4. Delete client PnL fallback. Render `position.pnl` including `0`.
5. Delete `profileInfo.ts` session hours. Render `amt.session` / `riskState`.
6. Delete fabricated genAI object. Empty state is empty.
7. Drop unused types: `auction`, `genAIAnalysis`, `overseer*` **or** put them back on `WS_SNAPSHOT_KEYS`. Do not leave zombies.
8. Sequence numbers on WS frames; show “analytics stale” when RAF drops.
9. Chart: forming bar from server tick only; do not own a second OHLC store beyond display buffer.
10. Replay UI (later): transport of `{mode: replay, t}` to backend clock. Zero strategy code.

Zustand stays chrome-only. Trading state stays the WS hook, but the hook must not interpret.

---

## 11. Backend refactor plan (Task 6)

**OMS (one port):**

```python
class IOMS(Protocol):
    def submit(self, signal: Signal, qty: Decimal) -> Position: ...
    def close(self, position_id, price, time, reason) -> Fill: ...
    def close_partial(self, position_id, fraction, price, time, reason) -> Fill: ...
```

- `PaperOMS` — replay / backtest / paper (costs applied here, not in a second PaperBroker).
- `LiveOMS` — maps domain Signal → adapter `execute_order`; polls to terminal; cancel-on-timeout already in Dhan adapter.
- Coordinator injects the impl from env. Engine never constructs `PaperOMS()` itself.

**Broker adapters:** Dhan stays in `brokers/`. Backend adapter is a thin `IOMS` + `IMarketData`. Delete deprecated `brokers/broker/paper`. Delete `IBrokerPort` mega-interface or split it (market vs orders).

**Simulation:** PaperOMS + SyntheticGateway **is** the simulator. Do not add a second backtester.

**Lifecycle per trading day:**

1. Load InstrumentRegistry (unknown root = boot fail).
2. Reconcile: broker positions vs storage vs journal. Mismatch → **refuse live** (already intended) but with real counts.
3. Restore engine `Position` + `SessionRisk` + exit state from storage, or flag manual.
4. Seed AMT from history **before** subscribing live (join the seed thread; delete the race).
5. Run.
6. Session force-exit; persist; halt entries; optional flatten if `flatten_on_halt`.

**Kill switch:** `emergency_halt` must mean: stop entries **and** (if live) market-close all via OMS. Halt-entries-only is acceptable only as an explicit, operator-visible policy — not as a SIGTERM handler.

---

## 12. API and contract design (Task 7)

**Envelope (versioned):**

```
WSFrame = {
  v: 1,
  seq: int,
  type: "snapshot" | "delta" | "tick" | "control",
  symbol: str,
  payload: ...
}
```

Bump `v` on breaking field rename. Additive fields allowed in v1.

**Events (domain → projector):** `BarClosed`, `AmtUpdated`, `DecisionProduced`, `SignalApproved`, `OrderSubmitted`, `FillReceived`, `PositionOpened`, `PositionReduced`, `PositionClosed`, `RiskUpdated`, `HaltChanged`.

**Identity:** every Signal/Order/Fill/Position has an id. Journal, storage, WS, UI use the same ids.

**Replay vs live stream:** same `WSFrame`. Control message `server_mode: live|paper|replay` is metadata. Payload schema identical. Replay does not invent a second socket.

**REST:** config, history warmup, journal query, health (include journal consecutive-fail counter). `/analysis/amt` either proxies the **live engine DTO** or is deleted (duplicate analyzer is a lie).

**Versioning:** `v` in frame + OpenAPI for REST. CI: Python `WS_SNAPSHOT_KEYS` hashed against generated TS.

---

## 13. Test strategy (Task 8)

| Layer | What | Notes |
|---|---|---|
| Unit | indicators incremental (VP, CVD, IB); SignalBuilder stops; SessionRisk cushion | real functions, synthetic **bars** (not mocked AMT) |
| Property | ∀ signals: rr≥min, sl on the correct side, qty lot-snapped; ∀ closes: pop_trail | hypothesis / parametrize |
| Parity | same tick tape through engine with PaperOMS vs recorded journal | **require parseable timestamps** — ban `t0` in new goldens |
| Adapter contract | Dhan adapter: duplicate signal_id, freeze cap, poll-to-terminal (already) | add: Signal mapper engine→port |
| E2E sim | SyntheticGateway → fills → journal → replay() byte-equal events | existing golden path, keep |
| Live-shadow | paper process on live ticks, compare would-be orders to Dhan book **without sending** until OMS wired | new |
| Spec invariants | `tests/quant/test_spec_invariants.py` from § matrix (seed: `test_audit_regressions.py`) | include §13.3 once wired |
| UI contract | generated types compile; no `computeThreeA` ENTER | vitest |
| Forbidden | mocks of OMS/AMT in tests that claim to test the engine | use real PaperOMS + real analyzer |

Replay-vs-live parity test **must fail today** if it includes session gates and synthetic `t*` times — that failure is the point. Fix the clock, do not skip gates.

---

## 14. Refactoring roadmap (Task 9)

### Phase 1 — Safety (do not add features)

**Change:** halt API already added; add `flatten_all` policy decision + journal health on `/health`; seed-thread join; emit `DecisionProduced` on cooldown/halt; stop mapping DEAD→BALANCED on exits; refuse live boot if `execute_order` unwired **or** label process `paper` regardless of env; log loud if env=live and OMS is paper.

**Delete:** nothing large.

**Do not touch:** AMT math, gate thresholds, frontend visuals.

**Validate:** existing 1075 tests stay green; new tests: live-env-cannot-silently-paper (or explicit banner), DEAD forces exit, cooldown clears ENTER, seed completes before first decide.

### Phase 2 — Domain cleanup

**Change:** one Signal, one Position, mapper only in Dhan adapter; InstrumentRegistry as single classification table; `SessionRisk` defaults from config (max trades 6); unify NSE close 15:30 vs last-entry 15:15; expiry from contract not weekday.

**Delete:** unused Signal import in analyzer; shared MarketState; SessionContextFactory if still unused; KNOWN_DEAD modules listed in §6; stale flags.

**Do not touch:** gate order, Triple-A constants (calibrate later against tape, not tests).

**Validate:** mapper round-trip test; unknown root boot-fails; SENSEX/BANKEX/MIDCPNIFTY never MCX.

### Phase 3 — Architecture realignment

**Change:** engine takes `IOMS`; coordinator passes paper vs live impl; storage subscriber on PositionOpened/Closed/Fill; reconciliation restores or refuses; wire `close_partial` for §13.3 **or** amend spec (do not leave both).

**Delete:** unread `coordinator.broker` if replaced by OMS; second Portfolio exit engine; REST duplicate analyzer.

**Do not touch:** frontend cards except contract fields.

**Validate:** process kill → restart restores position in paper; live paper-shadow still no real order until explicitly enabled; three-fill winner test if §13.3 kept.

### Phase 4 — Frontend / backend separation

**Change:** generate types; delete client 3A/PnL/IB/session hours; sequence WS; empty states honest.

**Delete:** zombie components and unused WS fields.

**Do not touch:** chart library, layout chrome.

**Validate:** vitest: no ENTER without `quantDecision.approved`; pnl=0 displays 0; CI contract hash.

### Phase 5 — Performance and observability

**Change:** journal fail counter → read-only degrade policy; structured order audit; latency of tick→decide; calibration replay on recorded Dhan days (absorption 0.30/2.0 vs spec 0.50/1.50).

**Delete:** leftover LLM prompt code if still present.

**Do not touch:** hot-path locks without a race repro.

**Validate:** disk-full drill; one full-day replay vs live journal equality.

---

## 15. Before vs after

| | Before | After |
|---|---|---|
| Decision | QuantEngine (good) | unchanged owner |
| Fill | always PaperOMS | IOMS: paper or live |
| Position SoT | RAM | RAM + storage + journal, restored |
| Signal | two incompatible types | one domain type |
| Symbol class | four lists + MCX fallback | one registry, boot fail |
| UI | parallel ENTER | projection of `quantDecision` |
| Replay | engine yes, UI no, gates skipped on `t*` | same engine, parseable time, optional UI clock |
| Kill switch | halt entries | halt + flatten policy |
| REST AMT | second analyzer | live DTO or gone |
| Flags | describe deleted coordinators | deleted or wired |

---

## 16. Non-negotiable coding rules

1. **No second brain.** Indicators, gates, PnL, session, sizing exist in `quant/` once.
2. **No silent defaults** on symbol class, lot, tick, or live routing. Log + metric + fail-closed for live.
3. **`datetime.now()` is not market time.**
4. **Adapters own broker vocabulary.** Domain never sees `securityId`, `DH-3001`, product bits.
5. **Projector owns camelCase.** Domain stays snake_case / typed.
6. **Every SignalApproved has an OMS call or an explicit reject event.**
7. **Every PositionOpened has a storage write.** Restart without restore is a P0.
8. **Tests that encode `t0` must not exercise session gates.** New goldens use exchange timestamps.
9. **Do not mock the engine’s collaborators to prove the engine.** Use PaperOMS + real AMT + synthetic ticks.
10. **If a flag is unread, delete it in the same PR that notices.**
11. **Frontend may not emit ENTER, SL, TP, or targets.**
12. **Partial close and flatten are product rules, not TODOs in constructors.**

---

## 17. Ponytail (complexity) — ranked cuts

- `delete:` unused IBroker on engine path until wired. Replacement: inject IOMS. [`quant/runtime.py`, `multi_engine.py`]
- `delete:` REST AnalysisService AMT twin. Replacement: engine snapshot. [`analysis_service.py`]
- `delete:` `frontend/utils/threeA.ts` ENTER. Replacement: `quantDecision`. 
- `delete:` KNOWN_DEAD modules (`llm_inference`, `compression_box`, `range_bars`, `vwap_bands`, deprecated paper broker, empty advisory). Replacement: nothing.
- `delete:` feature flags with no readers. Replacement: nothing.
- `delete:` `SessionContextFactory`. Replacement: `get_session_info`.
- `yagni:` `TradingStrategy.should_exit` while PositionManager owns exits. Replacement: remove method or actually delegate.
- `yagni:` `contracts.entities.Signal` parallel to engine Signal. Replacement: one type.
- `shrink:` four classification tables → InstrumentRegistry.

net: large negative line count after Phase 2–4; zero new frameworks.

---

## 18. Fabio / strategy fidelity (do not confuse with architecture)

Architecture bones (event bus, incremental VP, session table, RR gate) are the right shape. Strategy gaps that change expectancy if you go live on the *documented* playbook:

- §13.3 tiered TP not wired (`close_partial`)
- footprint stacked imbalances detected, not in gates (historical Fabio gap)
- absorption constants 0.30/2.0 vs spec 0.50/1.50 — tests pass both
- delta is inferred

Do **not** implement new Fabio features until Phase 1–3 close the money path. A better signal into a disconnected OMS is still not live trading.

---

## 19. Recommended approach (vs alternatives)

1. **Incremental hexagonal realignment (recommended).** Keep QuantEngine. Replace its constructed PaperOMS with an injected port. Unify types. Delete twins. Wire storage. Then UI. Lowest risk for a running paper system.
2. **Big-bang rewrite of `quant/`.** Rejected. 1075 tests and golden traces are the only determinism you have.
3. **Strangler `quant.core` package beside `quant/`.** Rejected. You already strangler’d AuctionCoordinator → AMT and left comments. A third brain would repeat 2026-08-06.

---

## 20. Implementation gate

This document is the design. No implementation until you pick:

- **Phase 1 first** (safety: live-cannot-silently-paper, DEAD exits, seed join, journal health), or
- **OMS wire first** (Phase 3 money path), which is higher leverage but unsafe without Phase 1 labels.

Default recommendation: Phase 1 then 3 (OMS + persistence), then 2 (registry) in the same sequence as risk-to-capital, then 4 (UI honesty), then 5.
