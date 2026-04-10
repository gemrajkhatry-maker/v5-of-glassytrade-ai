# AMT Live Trading System v2 — Phased Implementation Plan

> **Role**: TradingView-style architect + lead developers + QA team
> **Scope**: Greenfield backend + frontend in `appv2/` — **zero impact** on existing `backend/` or `frontend/`
> **Reuse**: Existing `brokers/` library (Dhan WebSocket, order execution, symbol mapping)
> **Target**: NIFTY / BANKNIFTY / CRUDEOIL options on NSE & MCX

---

## PHASE 1 — Project Scaffolding & Infrastructure
**Owner**: Lead Developer / DevOps | **Duration**: 1 day

### Tasks

| # | Task | Expectation | Acceptance Criteria |
|---|------|------------|---------------------|
| 1.1 | Create `appv2/backend/` directory structure | Hexagonal architecture: `domain/`, `infrastructure/`, `application/`, `api/`, `config/` | All directories exist with `__init__.py` |
| 1.2 | Create `appv2/frontend/` directory structure | React + Vite + TypeScript project, TailwindCSS configured | `npm run dev` starts without errors |
| 1.3 | `requirements.txt` for backend | Python 3.11+, FastAPI, websockets, numpy, dataclasses, pydantic, python-dotenv | `pip install -r requirements.txt` succeeds |
| 1.4 | `.env.example` template | DHAN_ACCESS_TOKEN, DHAN_CLIENT_ID, CAPITAL, EXCHANGE, SYMBOLS, RISK_* params | All required vars documented |
| 1.5 | `config/settings.py` | Pydantic BaseSettings, loads from env, validates on startup | Missing required var → clear error at startup |
| 1.6 | `config/constants.py` | AMT thresholds: LVN_THRESHOLD, HVN_THRESHOLD, VALUE_AREA_PCT, AGGRESSION_SIGMA_THRESHOLD, etc. | Matches Fabio Valentini spec values |
| 1.7 | Logging setup | Structured JSON logging, per-module loggers, log file rotation | Logs appear in `appv2/logs/` with correct format |
| 1.8 | Health check endpoint | `GET /api/health` returns `{status: "ok", version, uptime}` | Returns 200 with JSON |
| 1.9 | Broker library symlink / install | `brokers/` package importable from `appv2/backend` | `from broker.dhan.application.broker import DhanBroker` works |
| 1.10 | `pytest.ini` + test skeleton | `tests/` directory with `conftest.py`, one passing test | `pytest` runs and passes |

---

## PHASE 2 — Data Layer
**Owner**: Backend Developer | **Duration**: 2 days

### Tasks

| # | Task | Expectation | Acceptance Criteria |
|---|------|------------|---------------------|
| 2.1 | `domain/models/ohlc.py` | OHLC dataclass with delta, volume, time, symbol; float-based for speed | Immutable, hashable, serializable |
| 2.2 | `domain/models/tick.py` | Tick dataclass: LTP, LTQ, LTT, ATP, Volume, bid/ask depth | Matches Dhan rc=2/rc=4/rc=8 packet fields |
| 2.3 | `domain/services/candle_aggregator.py` | Tick→OHLCV incremental builder; handles partial candles, time boundaries | Given 60 ticks for 1-min bar → 1 correct OHLC |
| 2.4 | `domain/services/incremental_volume_profile.py` | Volume profile with per-candle `update()` — no full rebuild; CME buckets | After 100 candles, profile matches batch computation |
| 2.5 | `domain/services/vwap_calculator.py` | Session VWAP with sigma bands (+/-1σ, +/-2σ); auto-reset at session boundary | VWAP = Σ(typical_price × volume) / Σ(volume) |
| 2.6 | `domain/services/poc_calculator.py` | Point of Control with VWAP tie-break for multi-bin max volume | Identical POC as batch computation |
| 2.7 | `domain/services/value_area.py` | Value Area High/Low via CME two-row pairs method (70% of volume) | VAH/VAL match reference implementation |
| 2.8 | `infrastructure/dhan_feed.py` | Dhan WebSocket adapter; converts binary packets → domain Tick events | Reconnects on disconnect, replays subscriptions |
| 2.9 | `infrastructure/historical_fetcher.py` | Fetches 90-day intraday candles from Dhan REST; returns list[OHLC] | Handles rate limits, pagination, errors |
| 2.10 | `application/data_pipeline.py` | Event-driven pipeline: Tick → Candle → Profile → VWAP → emit AMTObservation | Each stage is independent, testable |
| 2.11 | Session boundary detection | New trading day → reset VWAP, VP, CVD, IB tracker | Detected from timestamp comparison |
| 2.12 | Multi-timeframe candles | Build 1-min, 5-min, 15-min candles simultaneously from same tick stream | All timeframes stay synchronized |

---

## PHASE 3 — Feature Engine
**Owner**: Backend Developer / Quant | **Duration**: 2 days

### Tasks

| # | Task | Expectation | Acceptance Criteria |
|---|------|------------|---------------------|
| 3.1 | `domain/services/cvd_tracker.py` | Cumulative Volume Delta with slope (40-bar window), sign persistence, divergence detection | CVD slope diverges from price → divergence flag |
| 3.2 | `domain/services/aggression_scorer.py` | PersistentAggressionScorer: 6-signal composite (footprint, CVD, big trades, absorption, OFI, confluence) | Score >= threshold → aggression confirmed |
| 3.3 | `domain/services/drive_tracker.py` | Drive numbering D1/D2/D3+ with rejection tracking; exhaustion detection | D1 suppressed, D3+ exhaustion flagged |
| 3.4 | `domain/services/profile_classifier.py` | Shape classification: D (bell), P (top-heavy), b (bottom-heavy), B (bimodal); POC migration tracking | Shape code computed from HVN/LVN positions |
| 3.5 | `domain/services/market_state_engine.py` | 4-state classifier: NO_TRADE, BALANCED, IMBALANCED, PROBING with zone sub-classification | State transitions logged with confidence |
| 3.6 | `domain/services/acceptance_rejection.py` | Acceptance: 2+ candles beyond VA + volume confirmation; Rejection: rejection wicks + volume drop | Returns ARResult with side, confidence, bar_count |
| 3.7 | `domain/services/break_detector.py` | Initial Balance break detection: initiative vs responsive break logic | Break direction + type classified |
| 3.8 | `domain/services/lvn_hvn_detector.py` | LVN (< 15% mean volume) + HVN (> 200% mean volume) with persistence filtering | LVN appears/disappears logic handled |
| 3.9 | `domain/services/session_context.py` | NSE 5-phase + MCX 4-phase session tracking; gap classification; opening type | Session phase returns allow_entry, allow_trend flags |
| 3.10 | `domain/services/initial_balance.py` | IB range (60-min for NSE, dynamic for MCX); IB break tracking with sticky state | IB high/low correct after window closes |
| 3.11 | `domain/services/displacement_detector.py` | Displacement = range > 1.5× ATR + volume > 1.5× average; leg profile builder | Displacement flag set correctly |
| 3.12 | `domain/services/orderflow_detectors.py` | Big trades, absorption, OFI, volume bubbles, footprint imbalance | Each detector independently testable |

---

## PHASE 4 — Strategy Engine
**Owner**: Backend Developer / Quant Lead | **Duration**: 2 days

### Tasks

| # | Task | Expectation | Acceptance Criteria |
|---|------|------------|---------------------|
| 4.1 | `domain/services/auction_state_machine.py` | State machine: states = {NO_TRADE, BALANCED, IMBALANCED, PROBING}; transitions with guards; hysteresis | State diagram fully documented; no illegal transitions |
| 4.2 | `domain/services/signal_generator.py` | Produces Signal objects: direction, entry_price, SL, TP, confidence, setup_type | SL/TP derived from aggressive prints, not fixed |
| 4.3 | `domain/services/gate_pipeline.py` | 12-gate pipeline: 5 hard gates (fail-fast) + 7 soft gates (quorum ≥ 3/4) | Gate failure returns specific rejection reason |
| 4.4 | `domain/services/three_align_gate.py` | Three-align: timeframe alignment (5m + 15m + 1h), POC shift direction, VA migration | Returns (passed, confirmation_strength, is_second_drive) |
| 4.5 | `domain/services/entry_zones.py` | Entry zone identification: pullback to VA edge, LVN retest, POC bounce | Entry zone = price level ± tolerance |
| 4.6 | `domain/services/exit_engine.py` | Stateless exit logic: SL hit, TP hit, trailing stop, time stop, scratch | Given current price + trade state → exit decision |
| 4.7 | `domain/services/trail_engine.py` | ATR trailing, VWAP trailing, CVD breakeven trigger | Trail price updates correctly each candle |
| 4.8 | `domain/services/scale_manager.py` | Scale-in management: 40/30/30 position sizing across 3 entries | Each scale has independent SL/TP |
| 4.9 | `application/strategy_orchestrator.py` | Wires AMT analysis → state machine → gates → signal → exit; per-symbol | End-to-end test: tick in → signal out |
| 4.10 | `domain/services/mtf_analyzer.py` | Multi-timeframe alignment: daily bias + hourly trend + 5-min entry | Alignment score 0-3 (3 = all aligned) |

---

## PHASE 5 — Execution Engine
**Owner**: Backend Developer | **Duration**: 2 days

### Tasks

| # | Task | Expectation | Acceptance Criteria |
|---|------|------------|---------------------|
| 5.1 | `infrastructure/dhan_executor.py` | DhanBroker adapter for live order placement; wraps `brokers/broker/dhan/` | `place_order()` returns order_id or raises |
| 5.2 | Order type support | Market, Limit, SL, SL-M, Bracket orders | Each type tested with paper broker first |
| 5.3 | `domain/services/order_router.py` | Routes orders to correct exchange (NSE_FNO, MCX_COMM, MCX_FNO); handles symbol format | Correct security_id for each symbol |
| 5.4 | `domain/services/slippage_tracker.py` | Tracks expected vs actual fill price; alerts on > threshold | Slippage logged per trade |
| 5.5 | `domain/services/order_retry.py` | Retry logic for network failures; exponential backoff; max 3 attempts | Failed order retried correctly |
| 5.6 | `domain/services/position_reconciliation.py` | Compares internal positions vs broker positions every 30s; alerts on mismatch | Mismatch → alert + auto-correct option |
| 5.7 | `domain/services/paper_executor.py` | Paper trading adapter with configurable slippage + commission | Used for testing before live |
| 5.8 | Real-money safety switch | `LIVE_TRADING=false` env var → all orders go to paper | Paper mode confirmed at startup |
| 5.9 | Order acknowledgment flow | Place → Ack → Fill/Reject → Update internal state | State machine for order lifecycle |

---

## PHASE 6 — Risk Engine
**Owner**: Backend Developer / Risk Lead | **Duration**: 1 day

### Tasks

| # | Task | Expectation | Acceptance Criteria |
|---|------|------------|---------------------|
| 6.1 | `domain/services/position_sizer.py` | Position size = (risk_per_trade × capital) / (entry - SL); max 2% capital per trade | Size respects lot size rounding |
| 6.2 | `domain/services/daily_loss_tracker.py` | Tracks cumulative daily P&L; halts trading at max_loss (e.g., 3% capital) | Trading halted, alert sent |
| 6.3 | `domain/services/circuit_breaker.py` | Per-symbol circuit breaker: 3 consecutive losses → 30-min cooldown | Cooldown enforced, logged |
| 6.4 | `domain/services/consecutive_loss_tracker.py` | Max 5 consecutive losses → full day halt | Day halt enforced |
| 6.5 | `domain/services/exposure_monitor.py` | Max open positions per symbol; max total exposure across all symbols | New trade blocked if limits exceeded |
| 6.6 | `domain/services/volatility_adjuster.py` | ATR-based position sizing: high ATR → smaller size, low ATR → normal size | Size adjusted inversely to ATR |
| 6.7 | `application/risk_orchestrator.py` | Wires all risk checks: pre-trade check, post-trade update, daily reset | All checks run in order, any fail → block |

---

## PHASE 7 — Options Trading Adaptation
**Owner**: Backend Developer / Options Quant | **Duration**: 2 days

### Tasks

| # | Task | Expectation | Acceptance Criteria |
|---|------|------------|---------------------|
| 7.1 | `domain/services/blackscholes.py` | Black-Scholes computation: delta, gamma, theta, vega, IV | Matches reference values within 0.001 |
| 7.2 | `domain/services/strike_selector.py` | Strike selection: ATM for gamma (scalping), ITM for directional; liquidity filter | Returns best strike given underlying price |
| 7.3 | `domain/services/expiry_manager.py` | Expiry awareness: weekly (Thursday), monthly; gamma-trap avoidance on expiry day after 14:30 | No new entries in gamma-trap zone |
| 7.4 | `domain/services/liquidity_filter.py` | Filters contracts by: min OI, min volume, bid-ask spread < threshold | Illiquid contracts excluded |
| 7.5 | `domain/services/theta_decay.py` | Theta cost analysis: theta × hours_to_expiry < 20% of expected profit | Trade rejected if theta cost too high |
| 7.6 | `domain/services/option_chain_fetcher.py` | Fetches option chain from Dhan API; parses strikes, OI, IV, greeks | Returns structured OptionChain object |
| 7.7 | `domain/services/underlying_router.py` | Routes AMT analysis to underlying futures (NIFTY futures for NIFTY options, CRUDEOIL futures for CRUDEOIL options) | AMT always runs on underlying, not premium |
| 7.8 | `domain/services/iv_rank.py` | IV rank and percentile tracking (30-day window); IV crush detection | IV rank computed and stored |
| 7.9 | CE/PE selection logic | Given signal direction, select CE for LONG, PE for SHORT; validate liquidity | Correct option type selected |
| 7.10 | Premium decay handling | Session-only VP for options (theta distorts multi-day VP) | VP built from today's candles only for options |

---

## PHASE 8 — State Management & Recovery
**Owner**: Backend Developer | **Duration**: 1 day

### Tasks

| # | Task | Expectation | Acceptance Criteria |
|---|------|------------|---------------------|
| 8.1 | `domain/services/session_state.py` | Per-symbol state: candles, order book, portfolio, pending signal, executed IDs | State is serializable to JSON |
| 8.2 | `infrastructure/sqlite_storage.py` | Async SQLite storage: trades, signals, candles, KV store | Writes via background thread, no blocking |
| 8.3 | `domain/services/crash_recovery.py` | On startup: load last state from KV store; reconcile positions with broker | System resumes from last known state |
| 8.4 | `domain/services/trade_lifecycle.py` | Trade lifecycle: Signal → Order Placed → Filled → Open → Exit → Closed | Each transition logged and persisted |
| 8.5 | `domain/services/trade_journal.py` | JSONL journal: every trade, every signal, every gate rejection | Logs to `appv2/logs/trade_journal.jsonl` |
| 8.6 | Signal TTL | Signals expire after 600 seconds; stale signals discarded | Old signals not executed |
| 8.7 | Multi-symbol state | Each symbol has independent state; no cross-contamination | NIFTY and CRUDEOIL states isolated |

---

## PHASE 9 — Frontend v2 (React Dashboard)
**Owner**: Frontend Developer | **Duration**: 3 days

### Tasks

| # | Task | Expectation | Acceptance Criteria |
|---|------|------------|---------------------|
| 9.1 | Project scaffold | React 18 + Vite + TypeScript + TailwindCSS | `npm run dev` starts on port 5174 |
| 9.2 | WebSocket connection | Connects to `ws://backend:8000/api/v2/ws` | Real-time data streaming |
| 9.3 | Dashboard layout | Header (P&L, status), sidebar (symbols), main (chart + signals) | Responsive, clean layout |
| 9.4 | Volume Profile chart | Canvas-based VP overlay on price chart; VAH/VAL/POC/LVN/HVN lines | Matches backend computation |
| 9.5 | VWAP bands chart | VWAP + 1σ/2σ bands overlay | Bands update in real-time |
| 9.6 | Signal panel | Active signals, rejected gates, execution status | Real-time updates |
| 9.7 | Position panel | Open positions, P&L, SL, TP, trail price | Updates on every tick |
| 9.8 | CVD chart | CVD line + slope indicator; divergence alerts | Matches backend CVD |
| 9.9 | Risk panel | Daily P&L, max drawdown, consecutive losses, circuit breaker status | Color-coded (green/yellow/red) |
| 9.10 | Settings page | Enable/disable live trading, adjust risk params, symbol selection | Changes applied without restart |
| 9.11 | Trade journal view | Historical trades table with filtering, sorting, export | CSV export works |
| 9.12 | Mobile responsive | Dashboard usable on tablet | Touch-friendly, no horizontal scroll |

---

## PHASE 10 — Testing, QA & Deployment
**Owner**: QA Lead + DevOps | **Duration**: 2 days

### Tasks

| # | Task | Expectation | Acceptance Criteria |
|---|------|------------|---------------------|
| 10.1 | Unit tests (backend) | 80%+ coverage on domain services; each detector independently tested | `pytest --cov=domain --cov-fail-under=80` passes |
| 10.2 | Integration tests | Dhan adapter → paper broker → full pipeline | End-to-end signal generation from live tick |
| 10.3 | Candle-by-c replay test | Replay historical day candle-by-candle; verify no lookahead bias | Signals match expected output |
| 10.4 | Tick-level SL test | Replay tick data; verify SL triggers at exact price level | SL fill price = trigger price ± slippage |
| 10.5 | Edge case: gap open | Simulate gap open above VAH; verify PROBING state | State transition correct |
| 10.6 | Edge case: low liquidity | Simulate thin order book; verify gate rejection | Trade blocked |
| 10.7 | Edge case: broker API failure | Simulate Dhan API 500; verify retry + alert | Retry attempted, alert sent |
| 10.8 | Edge case: network disconnect | Simulate WebSocket disconnect; verify reconnect + state recovery | Reconnect within 5s, no data loss |
| 10.9 | Edge case: market open volatility | First 15 min candles; verify NO_TRADE phase enforced | No entries during Phase 1 |
| 10.10 | Deployment script | `start.sh` launches backend + frontend; `.env` loaded; health check passes | One-command start |
| 10.11 | Docker support (optional) | `docker-compose.yml` with backend + frontend | `docker compose up` works |
| 10.12 | Runbook | Document: how to start, stop, monitor, recover from crash | QA team validates |

---

## AMT Strategy Formalization (Fabio Valentini Spec)

### 1. Auction Phases

| Phase | Condition | Machine Rule |
|-------|-----------|-------------|
| **Balance** | Price inside VAH-VAL, ≥70% candles inside VA, balance_ratio > 0.30 | State = BALANCED; mean-reversion strategy active |
| **Imbalance** | Price outside VA + displacement candle + acceptance (2+ candles beyond VA) | State = IMBALANCED; trend-following strategy active |
| **Probing** | Price outside VA without displacement OR at VA edge with displacement but no acceptance | State = PROBING; wait for confirmation |
| **No-Trade** | Price within ±POC_NO_TRADE_TICKS of POC | State = NO_TRADE; no signals generated |

### 2. Value Area Computation

```
1. Build volume profile: price bins (bucket_size = tick_size × 4)
2. Find POC = bin with max volume (VWAP tie-break for ties)
3. CME Two-Row Pairs Method:
   - Start at POC
   - Add pairs of bins above and below POC
   - Choose pair with higher combined volume
   - Continue until accumulated volume ≥ 70% of total
   - VAH = upper boundary, VAL = lower boundary
```

### 3. VWAP Computation

```
Session VWAP = Σ(typical_price × volume) / Σ(volume)
  where typical_price = (high + low + close) / 3
  Reset at session boundary (new trading day)

Sigma Bands:
  variance = Σ((typical_price - VWAP)² × volume) / Σ(volume)
  σ = √variance
  Upper 1σ = VWAP + σ, Lower 1σ = VWAP - σ
  Upper 2σ = VWAP + 2σ, Lower 2σ = VWAP - 2σ
```

### 4. Liquidity Zones

```
LVN (Low Volume Node): bin volume < 15% of mean profile volume, persistence ≥ 3 bars
HVN (High Volume Node): bin volume > 200% of mean profile volume, persistence ≥ 3 bars
```

### 5. Aggression Score (Composite)

```
Signals:
  1. Footprint Confirmed: aggressive prints + strong delta (>0.30)
  2. CVD Confirmed: slope aligned with direction
  3. Big Trade: volume > 2× average candle volume
  4. Absorption: large range + large volume + small close-open body
  5. OFI Aligned: order flow imbalance > 0.10 or < -0.10
  6. Confluence Bonus: LVN near key level (VAH/VAL/POC) within 3 ticks
  7. Volume Bubble: detected near key level

Score = weighted sum of signals (weights: 0.25, 0.25, 0.15, 0.15, 0.10, 0.05, 0.05)
Confirmed if: score >= threshold (2.5σ equivalent) AND persistence >= 2 bars
```

### 6. Entry Gate Pipeline

```
Hard Gates (fail-fast, any failure = reject):
  1. Session warm-up (Phase 1 = reject)
  2. Data quality (≥ 5 candles required)
  3. Risk halt (circuit breaker, daily loss limit)
  4. NO_TRADE state
  5. PROBING without aggression
  6. Key level proximity (within 3 ticks of opposing level)
  7. Drive validation (D1 suppressed, D3+ exhausted)
  8. Position sizing (within limits)
  9. EIA release window (15 min around announcements)
  10. Signal age (< 10 minutes)
  11. Profile shape (P-shape blocks LONG, b-shape blocks SHORT)
  12. CVD hard gate (extreme opposing slope)

Soft Gates (quorum: ≥ 3 of 4 must pass):
  1. Price at entry zone (within 3 ticks)
  2. Aggression score >= 2.0
  3. Cushion to opposing level <= 10 ticks
  4. R:R >= 1.5
```

### 7. Options-Specific Rules

```
Strike Selection:
  - Scalping: ATM (max gamma)
  - Directional: ITM (delta 0.60-0.75)
  - Avoid: OTM (low delta, high theta decay)

Expiry:
  - Allow 1-DTE for max gamma
  - Gamma-trap avoidance: no entries after 14:30 on expiry day
  - Skip to next week expiry if in gamma-trap zone

Liquidity:
  - Min OI: 50,000 contracts (NIFTY), 10,000 (BANKNIFTY), 5,000 (CRUDEOIL)
  - Min volume: 1,000 contracts in last 5 min
  - Max bid-ask spread: 0.5% of premium

Theta:
  - Theta cost = abs(theta) × hours_to_expiry
  - Reject if theta_cost > 20% of expected profit
```

---

## Directory Structure (appv2)

```
appv2/
├── backend/
│   ├── appv2/
│   │   ├── __init__.py
│   │   ├── main.py                    # FastAPI entrypoint
│   │   ├── config/
│   │   │   ├── __init__.py
│   │   │   ├── settings.py            # Pydantic settings from env
│   │   │   └── constants.py           # AMT thresholds
│   │   ├── domain/
│   │   │   ├── models/
│   │   │   │   ├── ohlc.py
│   │   │   │   ├── tick.py
│   │   │   │   ├── signal.py
│   │   │   │   ├── trade.py
│   │   │   │   └── option.py
│   │   │   ├── services/
│   │   │   │   ├── candle_aggregator.py
│   │   │   │   ├── incremental_volume_profile.py
│   │   │   │   ├── vwap_calculator.py
│   │   │   │   ├── poc_calculator.py
│   │   │   │   ├── value_area.py
│   │   │   │   ├── cvd_tracker.py
│   │   │   │   ├── aggression_scorer.py
│   │   │   │   ├── drive_tracker.py
│   │   │   │   ├── profile_classifier.py
│   │   │   │   ├── market_state_engine.py
│   │   │   │   ├── acceptance_rejection.py
│   │   │   │   ├── break_detector.py
│   │   │   │   ├── lvn_hvn_detector.py
│   │   │   │   ├── session_context.py
│   │   │   │   ├── initial_balance.py
│   │   │   │   ├── displacement_detector.py
│   │   │   │   ├── orderflow_detectors.py
│   │   │   │   ├── auction_state_machine.py
│   │   │   │   ├── signal_generator.py
│   │   │   │   ├── gate_pipeline.py
│   │   │   │   ├── three_align_gate.py
│   │   │   │   ├── entry_zones.py
│   │   │   │   ├── exit_engine.py
│   │   │   │   ├── trail_engine.py
│   │   │   │   ├── scale_manager.py
│   │   │   │   ├── mtf_analyzer.py
│   │   │   │   ├── position_sizer.py
│   │   │   │   ├── daily_loss_tracker.py
│   │   │   │   ├── circuit_breaker.py
│   │   │   │   ├── blackscholes.py
│   │   │   │   ├── strike_selector.py
│   │   │   │   ├── expiry_manager.py
│   │   │   │   ├── liquidity_filter.py
│   │   │   │   ├── theta_decay.py
│   │   │   │   ├── iv_rank.py
│   │   │   │   └── underlying_router.py
│   │   │   ├── enums/
│   │   │   │   ├── market_state.py
│   │   │   │   ├── signal_type.py
│   │   │   │   └── session_phase.py
│   │   │   └── ports/
│   │   │       ├── market_data.py
│   │   │       ├── broker.py
│   │   │       └── storage.py
│   │   ├── infrastructure/
│   │   │   ├── dhan_feed.py
│   │   │   ├── dhan_executor.py
│   │   │   ├── historical_fetcher.py
│   │   │   ├── sqlite_storage.py
│   │   │   └── paper_executor.py
│   │   ├── application/
│   │   │   ├── data_pipeline.py
│   │   │   ├── strategy_orchestrator.py
│   │   │   ├── risk_orchestrator.py
│   │   │   ├── session_state.py
│   │   │   └── trade_lifecycle.py
│   │   └── api/
│   │       ├── routes/
│   │       │   ├── health.py
│   │       │   ├── market.py
│   │       │   ├── signals.py
│   │       │   ├── positions.py
│   │       │   └── ws.py
│   │       └── websocket.py
│   ├── tests/
│   │   ├── conftest.py
│   │   ├── test_candle_aggregator.py
│   │   ├── test_volume_profile.py
│   │   ├── test_vwap.py
│   │   ├── test_market_state.py
│   │   ├── test_gate_pipeline.py
│   │   └── test_blackscholes.py
│   ├── requirements.txt
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── App.tsx
│   │   ├── main.tsx
│   │   ├── components/
│   │   │   ├── Dashboard.tsx
│   │   │   ├── VolumeProfileChart.tsx
│   │   │   ├── VWAPChart.tsx
│   │   │   ├── SignalPanel.tsx
│   │   │   ├── PositionPanel.tsx
│   │   │   ├── CVDChart.tsx
│   │   │   ├── RiskPanel.tsx
│   │   │   └── Settings.tsx
│   │   ├── hooks/
│   │   │   └── useWebSocket.ts
│   │   ├── types/
│   │   │   └── index.ts
│   │   └── styles/
│   │       └── globals.css
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── tailwind.config.js
│   └── index.html
├── logs/
├── .env.example
├── start.sh
└── IMPLEMENTATION_PLAN.md  ← this file
```

---

## Execution Order

1. **Phase 1** → Scaffolding (1 day)
2. **Phase 2 + 3** → Data + Features (3 days, parallel possible)
3. **Phase 4** → Strategy (2 days, depends on Phase 3)
4. **Phase 5 + 6** → Execution + Risk (2 days, parallel)
5. **Phase 7** → Options (2 days, depends on Phase 4)
6. **Phase 8** → State Management (1 day)
7. **Phase 9** → Frontend (3 days, starts after Phase 2 API ready)
8. **Phase 10** → QA + Deploy (2 days)

**Total: ~14-16 working days**
