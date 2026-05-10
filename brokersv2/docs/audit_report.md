# brokersv2 — Comprehensive Code-Level Audit Report

**Date:** 2026-05-10
**Scope:** Full codebase audit of brokersv2/ — 18 files read, 5 execution flows traced
**Methodology:** File-by-file reading, end-to-end flow tracing, invariant verification, money-impact scoring

---

## Cross-Reference Corrections (from second review)

The following findings from a parallel review were verified against the codebase. Items marked **[NEW]** were missed in the initial audit. Items marked **[CORRECTED]** were stated differently in the initial audit and are now refined.

### Newly discovered files (missed in initial audit)

| File | Role | Defects Found |
|------|------|---------------|
| `infrastructure/dhan_adapter/token_refresh_scheduler.py` | Background token refresh loop | **NOT wired into bootstrap.py**. Exists but never instantiated in production path. |
| `replay/historical_replay.py` | Historical candle replay engine | Passes `instrument=str` to `router.get_candles(instrument: CanonicalInstrument)`. Type mismatch -> runtime crash. |
| `marketdata/pipeline.py` | Stub pipeline (live/replay/simulation modes) | All 3 modes raise RuntimeError. Dead code in production path. |

### [NEW] IBrokerAdapter async/sync contract mismatch

`core/ports.py:26` defines `place_order` as **sync** (no `async def`):
```python
def place_order(self, order: Order) -> str:
```

But `DhanBrokerAdapter` at `adapter.py:113` implements it as **async def**:
```python
async def place_order(self, order: Order) -> str:
```

Callers are split:
- **OrderManager** (`order_manager.py:112`): calls WITHOUT await - matches protocol signature but implementation is async, so it gets a coroutine object, not a string.
- **KillSwitchEngine** (`kill_switch.py:277-280`): correctly awaits via `await asyncio.wait_for(broker_adapter.place_order(order), ...)`.
- **Gateway server** (`server.py:605`): correctly awaits via `await state.broker.place_order(order)`.

This is a **protocol-level defect**: the interface and implementation disagree on the async contract. Two of three call sites work correctly; one (OrderManager) silently fails.

**Root cause:** The protocol was written for a sync implementation, but the adapter was correctly made async. Neither was updated to match the other.

### [NEW] TokenRefreshScheduler exists but is NEVER wired into bootstrap

`TokenRefreshScheduler` (`token_refresh_scheduler.py`) is designed to:
1. Check token expiry every 5 minutes
2. Call `auth_provider.ensure_valid_token()`
3. Mutate `http_client._headers["access-token"]` directly

But **bootstrap.py never creates or starts a TokenRefreshScheduler**. The scheduler only exists as a module with tests. In the production gateway path:
- No `DhanAuthProvider` is created
- No `TokenRefreshScheduler` is created
- Token headers are set once at init and never refreshed

The CLI path (`DhanGateway.from_env()` via factory) DOES create auth_provider when TOTP credentials are present, but even there, no TokenRefreshScheduler is started.

### [NEW] HistoricalReplayEngine type mismatch

`historical_replay.py:96` passes `instrument=symbol` (a string like "RELIANCE") to `router.get_candles(instrument: CanonicalInstrument, ...)`. The router at `router.py:93` then accesses `instrument.symbol`, which will raise `AttributeError: 'str' object has no attribute 'symbol'`.

This means the replay engine **has never worked** for any symbol.

### [CORRECTED] Auth provider assessment

Initial audit stated: "auth_provider is stored but never used in _request - dead code."

**Refinement:** auth_provider IS used in the CLI/factory path (`factory.py:144-154`) for initial token generation via TOTP. However:
1. It is NOT used in the bootstrap/gateway path at all
2. TokenRefreshScheduler (which would update headers at runtime) is NOT wired in ANY path
3. Even when auth_provider IS created, the HTTP client's `_headers` are set once at init and the scheduler that would update them never runs

So the effective impact is: **token refresh infrastructure exists but is never activated in production**.

### [NEW] marketdata/pipeline.py is dead code

`MarketDataPipeline` at `pipeline.py` has all 3 streaming modes (`_stream_live`, `_stream_replay`, `_stream_simulation`) raising `RuntimeError`. The `get_quote` and `get_historical` methods return hardcoded fake data. This module is not imported by any production path but could confuse maintainers.

### [CORRECTED] KillSwitchEngine liquidation path

Initial audit did not examine the liquidation path in detail.

`kill_switch.py:277-280` correctly awaits `broker_adapter.place_order(order)`. This call site works because it treats `place_order` as async (matching the actual implementation, not the protocol). The liquidation path is correctly async-end-to-end.

However, the broader issue remains: the protocol/interface says sync, so other callers (OrderManager) treat it as sync. The correct fix is to make the protocol match the implementation (all I/O methods should be async).

### [NEW] Revised defect count

After cross-reference, the total defect count is now **27** (was 23):
- **5 CRITICAL** (was 3): added IBrokerAdapter contract mismatch and TokenRefreshScheduler not wired
- **12 HIGH** (unchanged)
- **10 MEDIUM** (was 8): added HistoricalReplayEngine type mismatch and pipeline.py dead code

---

## Executive Summary

The brokersv2 codebase has a sound architectural shape (domain-led, ports/adapters, async-first) but contains **5 critical defects** that would prevent reliable order execution in a live environment, and **12 high-severity defects** that would cause silent data degradation, stream loss, or reliability collapse under real-time conditions.

**Critical defects:**
1. `order_manager.py:112` — `place_order` not awaited (returns coroutine, never executes)
2. `client.py:113-118` — HTTP headers frozen at init, token refresh has zero effect
3. `bootstrap.py` — No DhanAuthProvider or TokenRefreshScheduler wired in gateway path
4. `core/ports.py:26` vs `adapter.py:113` — IBrokerAdapter protocol says sync, implementation says async. Callers split.
5. `replay/historical_replay.py:96` — Passes string as instrument to router expecting CanonicalInstrument. Replay never worked.

**Money-loss vector:** Orders silently fail to execute while the system believes they were submitted. Under real-time load, WS streams die after 5 reconnects with no recovery. Historical fallback switches without provenance, causing strategy signal drift. Token refresh infrastructure exists but is never activated. The replay engine has never worked. The IBrokerAdapter protocol and implementation disagree on async contract.

---

## 1. System Intent (code-verified contract)

**Declared intent from code:**
- DhanHQ broker adapter implementing `IBrokerAdapter` port
- Canonical domain models (Order, Tick, Quote, Candle, CanonicalInstrument)
- Safety gates: lot-size, freeze-quantity, market-hours, risk checks, circuit breaker, rate limiter, margin checker
- Live streaming via DhanFeed WebSocket with reconnect
- Historical data with Dhan primary + OpenChart fallback
- Token lifecycle management with TOTP-based auth

**Contract gap:** The code attempts to guarantee these invariants but only partially enforces them. Three critical bugs (detailed below) break the core order execution contract entirely.

---

## 2. Architecture Map (code-level)

```
Entry Points:
  gateway/server.py     — FastAPI REST/WS endpoints (thin)
  cli/main.py           — CLI commands
  broker_factory        — Legacy (deprecated, still reachable)

Composition Root:
  app/bootstrap.py      — Wires all services

Domain Boundary:
  domain/order/models.py     — Order, OrderStatus
  domain/market/models.py    — Tick, Quote, Candle
  domain/instrument/models.py     — CanonicalInstrument
  domain/instrument/master_loader.py — MasterDataLoader
  domain/instrument/registry.py    — InstrumentRegistry
  domain/market/hours.py    — MarketHoursGate, holiday calendar
  domain/market/events.py   — DepthEvent, DepthLevel

Ports:
  core/ports.py       — IBrokerAdapter, IInstrumentMapper, ISubscriptionManager

Adapter Layer:
  infrastructure/dhan_adapter/adapter.py   — DhanBrokerAdapter (IBrokerAdapter impl)
  infrastructure/dhan_adapter/client.py    — DhanHttpClient (REST transport)
  infrastructure/dhan_adapter/websocket.py — DhanWebSocketManager (WS streaming)
  infrastructure/dhan_adapter/auth_provider.py — DhanAuthProvider (token lifecycle)
  infrastructure/dhan_adapter/mapper.py    — InstrumentMapper (symbology)

Data Services:
  marketdata/service.py       — MarketDataService (unified entry)
  marketdata/depth_processor.py — DepthProcessor (order book reconstruction)
  providers/router.py         — HistoricalDataRouter (primary + fallback)
  providers/dhan_provider.py  — DhanHistoricalProvider (primary)
  providers/opencart_provider.py — OpenChartHistoricalProvider (fallback)

OMS / Risk:
  oms/order_manager.py     — OrderManager (orchestration)
  oms/order_machine.py     — OrderStateMachine (DEPRECATED)
  oms/margin_checker.py    — MarginChecker (pre-trade margin)
  oms/position_reconciler.py — PositionReconciler (startup sync)
  risk/gateway.py          — RiskGateway (position/exposure/kill-switch)
  risk/kill_switch.py      — KillSwitchEngine (emergency shutdown)

Resilience:
  core/resilience.py            — CircuitBreaker
  resilience/policies/retry.py  — RetryPolicy, RetryManager
  resilience/policies/rate_limit.py — BrokerRateLimiter, ProviderRateLimiter

Events:
  events/bus.py  — EventBus (async pub/sub with backpressure)
  core/events.py — Event base types (OrderEvent, FillEvent, RiskEvent)
```

**Dependency direction assessment:** Core logic depends on ports (correct). DhanHQ consumed only in adapter layer (correct). Hidden coupling exists where bootstrap creates independent instances of shared dependencies (MarketHoursGate, InstrumentMapper).

---

## 3. End-to-End Flow Traces

### A. Order Flow: gateway → risk → OMS → adapter → client → Dhan

```
1. POST /orders (server.py:557-619)
   - Creates OrderRequest → validates market hours via NEW MarketHoursGate instance
   - Constructs Order, calls state.broker.place_order(order)  [AWAITED at gateway level]

2. DhanBrokerAdapter.place_order (adapter.py:113-141)
   - dry_run check
   - circuit breaker context
   - calls self._client.place_order(order, mapper)  [AWAITED]

3. DhanHttpClient.place_order (client.py:247-303)
   - mapper lookup (hard-fail if missing)
   - MarketHoursGate.check()  [SECOND instance, may differ from gateway]
   - validate_lot_size, validate_freeze_quantity
   - MarginChecker.check(order)  [if wired]
   - Builds Dhan payload, calls self._request("POST", "/orders")

4. DhanHttpClient._request (client.py:132-164)
   - Rate limiter wait
   - Uses self._headers (FROZEN at __init__, NEVER refreshed)
   - aiohttp request to Dhan API
   - Returns JSON
```

**Defects in this flow:**

| # | Location | Defect | Impact |
|---|----------|--------|--------|
| A1 | `order_manager.py:112` | `self._broker.place_order(order)` NOT awaited | Returns coroutine object. `order.broker_order_id` becomes `<coroutine object...>`. Order NEVER reaches broker. |
| A2 | `order_manager.py:142` | `self._broker.cancel_order(...)` NOT awaited | Same bug. Cancel never executes. |
| A3 | `client.py:113-118` | `_headers` captured at init, never refreshed | After token expiry/renewal, ALL REST calls use stale token. 401 cascade. |
| A4 | `client.py:109, 132-164` | `_auth_provider` stored but NEVER called in `_request` | Token refresh mechanism has ZERO effect on live traffic. |
| A5 | `server.py:569`, `client.py:107` | TWO independent MarketHoursGate instances | Drift risk if holiday config differs between them. |
| A6 | `order_manager.py:112-118` | No idempotency key on order submission | Network retry = duplicate order risk. |
| A7 | `order_manager.py:117-118` | Status set to VALIDATED→SENT before broker confirms | Internal state lies about actual broker state. |
| A8 | `order_manager.py:93` | `await self._risk.check_order(order)` is async but RiskGateway.check_order is async only for event publishing, actual checks are sync | Unnecessary async deferral, but not a bug. |
| A9 | `client.py:263-264` | Market hours check uses `getattr(order, "after_market_order", False)` | If Order model doesn't have this attr, defaults to False. AMO orders may be rejected. |

### B. Market Data Flow: WS → parser → depth → service → providers

```
1. WS /ws/ticks (server.py:851-896)
   - Accepts WebSocket, receives symbols list
   - Creates CanonicalInstrument.from_symbol()  [may fail if not in registry]
   - Calls state.broker.stream_ticks(instruments)  [async iterator]

2. DhanBrokerAdapter.stream_ticks (adapter.py:208-268)
   - Validates <=100 instruments
   - Manages WS lifecycle with reconnect loop
   - On exception: recreates DhanWebSocketManager entirely

3. DhanWebSocketManager (websocket.py)
   - start(): Creates DhanFeed client, connect(), starts _receive_loop + _heartbeat_monitor
   - subscribe(): Batches instruments, calls mapper, forwards to DhanFeed.subscribe
   - _receive_loop(): Calls DhanFeed.receive(), dispatches to _handle_tick / _handle_depth
   - _handle_tick: Puts to _tick_queue (maxsize=10000, drops if full)
   - _parse_tick: Creates Tick with datetime.now() (not broker timestamp)

4. MarketDataService.start_live_stream (service.py:155-181)
   - Starts WS, subscribes, yields ticks from stream_ticks()

5. Historical path: service.py:91-112 → router.py:73-135 → dhan_provider.py:87-151
   - Router tries primary with 10s timeout
   - On failure, tries fallback OpenChart with 15s timeout
   - No provenance tagging on returned candles
```

**Defects in this flow:**

| # | Location | Defect | Impact |
|---|----------|--------|--------|
| B1 | `websocket.py:262-263` | Tick queue full → drops with only a log warning | No metric, no event, no backpressure signal. Strategy acts on stale data. |
| B2 | `websocket.py:391-394` | Max 5 reconnects → `self._running = False` | Permanent stream death after 5 failures. No recovery path. |
| B3 | `websocket.py:291` | Tick timestamp = `datetime.now()`, not broker timestamp | Timestamp drift affects time-sensitive strategies. |
| B4 | `adapter.py:262` | WS manager recreated on every reconnect loop | Old manager's background tasks may still run. Race condition. |
| B5 | `websocket.py:428-430` | Resubscribe after reconnect uses `_subscriptions.values()` | If InstrumentMapper changed between disconnect/reconnect, wrong instruments. |
| B6 | `websocket.py:284-286` | Unknown security_id → silently returns None | Drops ticks from unmapped instruments with no alert. |
| B7 | `router.py:128-131` | Fallback succeeds without provenance tag | Strategy cannot distinguish primary vs fallback data quality. |
| B8 | `service.py:168-176` | `start_live_stream` starts WS but has no error handling | If WS fails to start, caller gets unhandled exception. |
| B9 | `depth_processor.py:220-226` | Stale threshold check raises exception | May be too aggressive for bursty markets; could reject valid updates. |

### C. Auth/Token Lifecycle

```
1. DhanAuthProvider.__init__ (auth_provider.py:59-82)
   - Stores client_id, optional http_client, env_file path
   - Token state: None

2. generate_token (auth_provider.py:101-152)
   - Checks cooldown (2 min)
   - Generates TOTP code
   - Calls dhanhq.auth.DhanLogin.generate_token
   - Stores token with 24h expiry
   - Persists to .env file (NO FILE LOCKING)

3. renew_token (auth_provider.py:154-191)
   - Calls dhanhq.auth.DhanLogin.renew_token
   - Updates token with 24h expiry
   - Persists to .env

4. ensure_valid_token (auth_provider.py:193-238)
   - If no token: tries to load from .env
   - If expired: regenerates via TOTP (if credentials available)
   - If near expiry (1hr): renews
   - Returns valid token

5. CONSUMPTION: DhanHttpClient.__init__ (client.py:97-118)
   - If auth_provider: reads auth_provider._access_token directly
   - Sets self._headers ONCE at init
   - _request NEVER calls auth_provider.ensure_valid_token()
```

**Defects in this flow:**

| # | Location | Defect | Impact |
|---|----------|--------|--------|
| C1 | `client.py:113-118` | Token read once at init, never refreshed | All REST calls fail after token expiry/renewal. |
| C2 | `client.py:109` | `_auth_provider` stored but unused in `_request` | Entire auth refresh mechanism is dead code for REST calls. |
| C3 | `auth_provider.py:291-325` | .env persistence with no file locking | Multi-process race: parallel workers can corrupt/overwrite token. |
| C4 | `auth_provider.py:92-99` | `set_current_token` default expiry = 24h hard assumption | May not match Dhan's actual token TTL. Silent expiry mismatch. |
| C5 | `auth_provider.py:210-213` | Loads token from .env but assumes 24h expiry | Token could already be expired on load. No validation call. |
| C6 | `auth_provider.py:116` | `_check_generation_cooldown` is sync, not async | Cooldown enforcement may be racy across processes. |

### D. Resilience Layer

```
CircuitBreaker (core/resilience.py):
  - Thread-safe (RLock), 3-state machine (CLOSED→OPEN→HALF_OPEN)
  - Context manager API: `with cb:`
  - failure_threshold=5, recovery_timeout=60s
  - Used by: adapter (order/quote/historical), gateway (option chain)
  - Bug: _total_requests incremented on exit even for rejected requests (line 111)

RetryManager (resilience/policies/retry.py):
  - Factory pattern: execute(lambda: coro()) — correct async retry
  - Exponential backoff with jitter
  - Circuit breaker integration (optional)
  - Used by: DhanHistoricalProvider

BrokerRateLimiter (resilience/policies/rate_limit.py):
  - Multi-bucket token bucket (orders: 10/s, quotes: 1/s, historical: 5/s)
  - Sync with async_wait_for_token wrapper
  - Orders bucket burst = 10 (correct for Dhan v2 post-March-2026)

KillSwitchEngine (risk/kill_switch.py):
  - Two-state: INACTIVE/ACTIVE
  - Auto-activates on daily_loss, position_size, order_rate breaches
  - 90% warning threshold
  - liquidate_all_positions(): market orders for INTRADAY positions
  - Bug: _order_count never resets daily (line 170) — cumulative, not rate
```

**Defects in resilience:**

| # | Location | Defect | Impact |
|---|----------|--------|--------|
| D1 | `resilience.py:111` | `_total_requests` incremented even for rejected (CircuitBreakerOpenError) requests | Metrics overcount actual requests. |
| D2 | `kill_switch.py:170` | `_order_count` is cumulative, not time-windowed | Kill switch triggers after N total orders ever, not per-period. |
| D3 | `retry.py:173` | `pol.circuit_breaker.allow_request()` — CircuitBreaker uses context manager, not allow_request() | If CB passed here, it will raise AttributeError (no such method). |
| D4 | `rate_limit.py:244` | Orders bucket = 10 capacity / 10 req/s | No burst tolerance at market open. All 10 consumed instantly. |
| D5 | `resilience/policies/retry.py:269-272` | `execute_with_retry_operation` accepts bare coroutine | Pre-created coroutine can only run once. Retries are a lie. |

---

## 4. Invariant Checklist (code-level pass/fail)

| # | Invariant | Status | Evidence |
|---|-----------|--------|----------|
| I1 | Instrument mapping exists before every market/order op | PARTIAL | client.py:259 raises ValueError. websocket.py:284 silently returns None. |
| I2 | Single market session policy for all entry points | FAIL | MarketHoursGate created per-call at server.py:569, per-client at client.py:107. No shared instance. |
| I3 | Token freshness for every REST request | FAIL | Headers frozen at init (client.py:113). auth_provider never called in _request. |
| I4 | Deterministic domain transform (live/replay/backtest parity) | FAIL | No shared codec. Replay not implemented in brokersv2. |
| I5 | Order idempotency on retry | FAIL | No idempotency key anywhere in order path. |
| I6 | Observability on failures (queue drops, fallbacks, reconnects) | PARTIAL | Logging exists. No structured metrics for queue drops, fallback provenance, or reconnect outcomes. |
| I7 | Single InstrumentMapper instance shared across services | FAIL | bootstrap.py:124 creates new InstrumentMapper per adapter. |
| I8 | Source provenance on all market data outputs | FAIL | No provider_id, fetched_at, or quality_flags on Candle/Quote/Tick. |
| I9 | Kill switch deactivates orders immediately | PARTIAL | KillSwitchEngine.check_order_allowed() raises. But RiskGateway doesn't wire to KillSwitchEngine. |
| I10 | Position book accurately reflects broker state | PARTIAL | PositionReconciler seeds at startup. No continuous reconciliation. |

---

## 5. Money-Loss Impact Scorecard

### CRITICAL — silently loses money or prevents execution

| # | Defect | Location | Severity | Scenario |
|---|--------|----------|----------|----------|
| 1 | **place_order not awaited** | `order_manager.py:112` | CRITICAL | OrderManager returns coroutine as broker_order_id. Order NEVER sent to broker. Strategy thinks order placed. No fill, no reject. Silent execution failure. |
| 2 | **Token headers never refreshed** | `client.py:113-118` | CRITICAL | After token expiry (or renewal), ALL REST calls use stale access-token. 401 on orders, quotes, historical, positions. Cascading failures across entire platform. |
| 3 | **auth_provider dead code** | `client.py:109` + `_request:132-164` | CRITICAL | Token refresh mechanism exists but is never invoked in the request path. Even if ensure_valid_token() is called externally, the HTTP client ignores the new token. |
| 4 | **No order idempotency** | `client.py:247-303`, `order_manager.py:112` | CRITICAL | If network fails between POST and response, retry creates duplicate order. No dedup key, no client-side order ID. Potential double fills. |

### HIGH — breaks under real-time load or causes silent data degradation

| # | Defect | Location | Severity | Scenario |
|---|--------|----------|----------|----------|
| 5 | **cancel_order not awaited** | `order_manager.py:142` | HIGH | Same as #1. Cancel never reaches broker. Stale orders remain active. |
| 6 | **WS permanent death after 5 reconnects** | `websocket.py:391-394` | HIGH | Flaky network → 5 failures → stream dies. No recovery. Strategy loses live feed without explicit failure signal. |
| 7 | **Tick queue overflow silently drops** | `websocket.py:262-263` | HIGH | High-frequency tick burst → queue full → drops ticks. No metric. Strategy sees stale/incomplete book. |
| 8 | **Two MarketHoursGate instances** | `server.py:569` + `client.py:107` | HIGH | Gateway check passes but client check fails (or vice versa). Inconsistent order acceptance/rejection. |
| 9 | **Historical fallback without provenance** | `router.py:128-131` | HIGH | Strategy receives OpenChart data indistinguishable from Dhan data. Different timestamps, precision, coverage. Signal drift. |
| 10 | **Hardcoded NSE session times for all segments** | `client.py:406-407` | HIGH | MCX intradal data uses 09:15-15:30 (NSE hours) instead of MCX hours. Wrong data range or empty results. |
| 11 | **WS manager recreated during reconnect** | `adapter.py:255-265` | HIGH | Old manager background tasks still running. Duplicate receive loops, double-subscriptions, or lost state. |
| 12 | **KillSwitch _order_count is cumulative** | `kill_switch.py:170` | HIGH | Kill switch fires after 100 total orders (ever), not per-day. Blocks all trading after arbitrary threshold. |

### MEDIUM — degrades reliability or creates operational risk

| # | Defect | Location | Severity | Scenario |
|---|--------|----------|----------|----------|
| 13 | **Broker timestamp not used in tick parsing** | `websocket.py:291` | MEDIUM | Tick uses local datetime.now(). Clock drift affects time-sensitive strategies and backtest parity. |
| 14 | **OrderEvent published with hardcoded empty fields** | `order_manager.py:222-228` | MEDIUM | Event consumers get symbol="", side="BUY", quantity=0. Useless for downstream processing. |
| 15 | **MarginChecker wired via private attr** | `bootstrap.py:138` | MEDIUM | `adapter.client._margin_checker = MarginChecker(...)`. Fragile coupling. Breaks on refactoring. |
| 16 | **Independent InstrumentMapper per adapter** | `bootstrap.py:124` | MEDIUM | Each adapter has its own mapper. Mappings not shared. Registry may be stale in one service. |
| 17 | **.env token persistence without file locking** | `auth_provider.py:291-325` | MEDIUM | Multi-process race: two workers generate token simultaneously. One overwrites the other. Intermittent auth failures. |
| 18 | **RetryManager accepts bare coroutine** | `retry.py:269-272` | MEDIUM | Pre-created coroutine passed to execute_with_retry_operation can only run once. Subsequent retries silently skip. |
| 19 | **Order status set before broker confirmation** | `order_manager.py:117-118` | MEDIUM | Internal state shows SENT before broker ack. Misleading state if broker rejects later. |
| 20 | **Option chain parser uses .get() with no validation** | `adapter.py:413-462` | MEDIUM | Malformed Dhan response → silent field defaults. Wrong strikes, prices, or Greeks. |
| 21 | **CircuitBreaker counts rejected requests** | `resilience.py:111` | MEDIUM | _total_requests includes requests rejected due to open circuit. Metrics are inflated. |
| 22 | **RiskGateway.check_order only checks 2 rules** | `risk/gateway.py:419-459` | MEDIUM | Only checks position_size and duplicate_order_id. No exposure, kill-switch, or daily-loss checks in async path. |
| 23 | **modify_order not awaited in OrderManager** | N/A — not in OrderManager yet | MEDIUM | OrderManager has no modify_order method. Gateway calls broker directly (server.py:638). Inconsistent pattern. |

---

## 6. Proposed Correct Architecture

### Immediate fixes (block production release)

1. **Await broker calls in OrderManager:**
   ```python
   # order_manager.py:112
   broker_order_id = await self._broker.place_order(order)
   # order_manager.py:142
   success = await self._broker.cancel_order(order.broker_order_id)
   ```

2. **Wire auth_provider into _request:**
   ```python
   # client.py:_request method, before making the HTTP call
   if self._auth_provider:
       token = await self._auth_provider.ensure_valid_token()
       self._headers["access-token"] = token
   ```

3. **Add idempotency key to order payload:**
   ```python
   # client.py:place_order
   payload["correlationId"] = str(order.order_id)  # already exists but ensure it's unique
   # Add dedup store in OrderManager
   ```

4. **Share MarketHoursGate instance:**
   Inject single instance from bootstrap into both gateway and HTTP client.

### Short-term hardening (1-2 weeks)

5. Replace WS hard death (5 reconnects) with circuit-breaker-governed reconnect
6. Emit metrics/events on: queue full, reconnect outcome, fallback activation, mapping miss
7. Add provenance fields (`source`, `fetched_at`, `is_fallback`) to Candle/Quote/Tick
8. Use broker timestamp in tick parsing (not datetime.now())
9. Fix KillSwitch._order_count to use time-windowed counter (per day)
10. Fix RetryManager.circuit_breaker integration (use context manager, not allow_request())

### Architectural (next quarter)

11. Single InstrumentMapper instance shared via DI from bootstrap
12. Unified codec path for live/replay/backtest transforms
13. Explicit BrokerExecutionContract with per-operation timeout/retry/idempotency policy
14. Legacy broker_factory behind explicit compatibility flag only
15. End-to-end parity test harness with recorded sessions

---

## 7. Files Reviewed

| File | Lines | Status |
|------|-------|--------|
| infrastructure/dhan_adapter/adapter.py | 536 | 3 defects |
| infrastructure/dhan_adapter/websocket.py | 550 | 6 defects |
| infrastructure/dhan_adapter/client.py | 561 | 4 defects |
| infrastructure/dhan_adapter/auth_provider.py | 343 | 4 defects |
| infrastructure/dhan_adapter/mapper.py | 224 | 1 defect |
| app/bootstrap.py | 339 | 3 defects |
| oms/order_manager.py | 269 | 4 defects |
| oms/margin_checker.py | 154 | 0 defects (well-structured) |
| oms/order_machine.py | 259 | Deprecated, not in use |
| oms/position_reconciler.py | 171 | 0 defects |
| risk/gateway.py | 460 | 2 defects |
| risk/kill_switch.py | 340 | 2 defects |
| gateway/server.py | 1032 | 2 defects |
| marketdata/service.py | 342 | 1 defect |
| marketdata/depth_processor.py | 301 | 0 defects |
| providers/router.py | 295 | 1 defect |
| providers/dhan_provider.py | 291 | 0 defects |
| providers/opencart_provider.py | 310 | 0 defects |
| resilience/policies/retry.py | 366 | 2 defects |
| resilience/policies/rate_limit.py | 415 | 1 defect |
| core/resilience.py | 190 | 1 defect |
| events/bus.py | 238 | 0 defects |
| domain/market/hours.py | 217 | 0 defects (well-structured) |
| domain/instrument/master_loader.py | 626 | 0 defects |
| domain/instrument/registry.py | (via master_loader) | OK |

| infrastructure/dhan_adapter/token_refresh_scheduler.py | 134 | 1 defect (not wired) |
| replay/historical_replay.py | 194 | 1 defect (type mismatch) |
| marketdata/pipeline.py | 140 | 1 defect (dead code) |

**Total:** 28 files, ~9,000 lines reviewed.

---

## 8. Verdict

**Production readiness: NOT READY**

The 5 critical defects (unawaited broker calls, stale token headers, dead auth/scheduler path, async/sync protocol mismatch, replay type error) mean the platform cannot reliably execute orders, maintain sessions, or replay historical data in a live environment. These are not edge cases — they are the primary execution path.

The codebase has good architectural foundations (domain models, ports/adapters, async-first, resilience patterns). The defects are concentrated at the integration boundaries where components connect, not in the domain logic itself.

**Fix the 5 critical items first.** The remaining 22 high/medium defects can be addressed in order of money-loss impact.
