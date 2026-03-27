# GlassyTrade AI — Complete System Documentation

> Generated: 2026-03-27 | Version: 2.0 | 1080 tests passing

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Architecture Layers](#2-architecture-layers)
3. [AMT Strategy — How It Works](#3-amt-strategy--how-it-works)
4. [Volume Profile Computation](#4-volume-profile-computation)
5. [Gate Pipeline — Complete Sequence](#5-gate-pipeline--complete-sequence)
6. [Entry Signal Construction](#6-entry-signal-construction)
7. [Risk Management](#7-risk-management)
8. [Scalping Layer](#8-scaling-layer)
9. [Data Flow & Event Architecture](#9-data-flow--event-architecture)
10. [Configuration System](#10-configuration-system)

---

## 1. System Overview

GlassyTrade AI is an automated options trading system built on **Fabio Valentini's Auction Market Theory (AMT)** methodology. It processes real-time tick data, builds volume profiles, classifies market states, scores aggression, and generates trade signals with strict gate-based risk controls.

### Core Design Principles

- **Domain-Driven Design** — all business logic in `domain/` layer, no infrastructure imports
- **Port/Adapter** — broker, storage, LLM are all swappable via abstract ports
- **Feature Flags** — 18 flags control every new feature (YAML-configurable)
- **Gate-based Risk** — 12+ gates must pass before any trade executes
- **Paper-First** — realistic cost model (STT, brokerage, GST, SEBI) before live

### Technology Stack

| Component | Technology |
|-----------|-----------|
| Backend | Python 3.14, FastAPI, uvicorn |
| Frontend | React 18, TypeScript, Vite, Lightweight Charts |
| Database | SQLite (WAL mode) |
| ML | LightGBM (via mlx) |
| LLM | OpenRouter (Grok 4.1 Fast) |
| Broker | DhanHQ (WebSocket + REST) |

---

## 2. Architecture Layers

```
┌─────────────────────────────────────────────────────┐
│  API Layer (FastAPI)                                │
│  routers/, websocket/, dependencies.py               │
├─────────────────────────────────────────────────────┤
│  Application Layer                                  │
│  trading_session.py, engine.py, exit_coordinator.py │
│  entry_coordinator.py, signal_bus.py                │
├─────────────────────────────────────────────────────┤
│  Domain Layer (pure business logic)                 │
│  fabio_ai/services/ — AMT, gates, aggression, LLM   │
│  services/ — volume_profile, lvn, tick, cvd, risk   │
│  trading/models/ — entities, aggregates, events     │
│  ports/ — abstract interfaces for all external deps │
├─────────────────────────────────────────────────────┤
│  Infrastructure Layer                               │
│  adapters/ — dhan, paper_broker, mlx_inference      │
│  storage/ — database.py (SQLite)                    │
│  serialization/ — schemas.py (DTO conversion)       │
└─────────────────────────────────────────────────────┘
```

**Rule**: Domain layer NEVER imports from infrastructure or application. All external dependencies injected via constructor.

---

## 3. AMT Strategy — How It Works

### The Core Concept

Auction Market Theory views markets as auctions where price discovers value. The system:
1. Builds a **Volume Profile** (histogram of volume at each price level)
2. Finds **POC** (Point of Control — highest volume price)
3. Computes **Value Area** (70% of volume around POC)
4. Classifies **Market State** (NO_TRADE / BALANCED / IMBALANCED / PROBING)
5. Scores **Aggression** (multi-signal additive: footprint, CVD, big trade, absorption, OFI, confluence, bubble)
6. Generates **Signals** via 3 playbooks

### Market State Classification

```
Price position relative to Value Area:

  NO_TRADE    — price within 2 ticks of POC (dead zone, no edge)
  BALANCED    — price inside VAH ↔ VAL (mean reversion territory)
  IMBALANCED  — price outside VAH or VAL (trend territory)
  PROBING     — price attempting to break VAH/VAL (needs confirmation)
```

### The 3 Playbooks

| Playbook | Market State | Entry Logic | SL/TP |
|----------|-------------|-------------|-------|
| **A. Trend Continuation** | IMBALANCED | Aggression at LVN inside VA | TP = VAH + 1×range, SL = POC |
| **B. Mean Reversion** | BALANCED | Failed breakout reclaim | TP = POC, SL = VAH/VAL |
| **C. Probing Breakout** | PROBING | Acceptance/rejection at VAH/VAL with VWAP | TP = measured move, SL = level |

### Aggression Scoring (7 signals, max 4.5)

| Signal | Condition | Points |
|--------|-----------|--------|
| **Footprint** | ≥2 aggressive prints AND |norm_delta| > 0.30 | +1.0 |
| **CVD** | Slope confirms direction OR divergence detected | +1.0 |
| **Big Trade** | Cluster of large prints detected | +1.0 |
| **Absorption** | Range < ATR×0.3 AND volume > avg×2 | +0.5 |
| **OFI** | |Order Flow Imbalance| > 0.10 | +0.5 |
| **Confluence** | LVN within 3 ticks of VAH/VAL/POC | +0.5 |
| **Bubble** | Volume bubble near entry price | +0.5 |

**Persistence Filter**: Aggression must score ≥ 2.0 for 3 consecutive bars before trade confirmation. Pyramid (size increase) requires ≥ 3.0 for 3 bars.

---

## 4. Volume Profile Computation

### Bucket Formula

```
bucket_idx = floor((price - price_min) / bucket_size)

Where:
  price_min = min(low) - 1% buffer
  price_max = max(high) + 1% buffer
  bucket_size = (price_max - price_min) / num_buckets (default 200)
```

### Volume Distribution

Each candle's volume is distributed uniformly across its [low, high] range:

```
start_bucket = floor((candle.low - price_min) / step)
end_bucket = floor((candle.high - price_min) / step)
vol_per_bucket = candle.volume / (end_bucket - start_bucket + 1)

Buy ratio inference:
  IF taker_buy_volume > 0: buy_ratio = taker_buy_volume / volume
  ELIF delta != 0: buy_ratio = 0.5 + delta/(2×volume), clamped [0,1]
  ELSE: close > midpoint → 0.6, close < midpoint → 0.4, else → 0.5
```

### POC Computation

```
max_vol = max(p.volume for p in profile)
poc_candidates = [i for i, p in enumerate(profile) if p.volume == max_vol]

Tie-break: if multiple buckets share max volume, pick one closest to session VWAP.
poc = profile[poc_index].price
```

### Value Area — CME Two-Row Pairs Method

```
target_volume = total_volume × 0.70
current_volume = poc_volume
up_idx = down_idx = poc_index

WHILE current_volume < target_volume:
    up_pair = histogram[up_idx+1] + histogram[up_idx+2]     # next 2 rows above
    down_pair = histogram[down_idx-1] + histogram[down_idx-2] # next 2 rows below

    IF can_go_up AND (NOT can_go_down OR up_pair >= down_pair):
        expand up 1-2 rows, add volume
    ELIF can_go_down:
        expand down 1-2 rows, add volume
    ELSE:
        break (hit boundaries)

VAH = profile[up_idx].price + step/2   # upper edge of top VA bin
VAL = profile[down_idx].price - step/2 # lower edge of bottom VA bin
```

### LVN Detection

```
1. Smooth histogram: centered simple moving average (window=3)
2. LVN candidate = bucket i where ALL:
   - H_smooth[i] < 0.15 × mean(H_smooth)
   - H_smooth[i] < H_smooth[i-1]   (local minimum — lower than neighbor)
   - H_smooth[i] < H_smooth[i+1]   (local minimum — lower than neighbor)
3. Strength score: 1 - (H_smooth[i] / mean(H_smooth))  — range [0,1]
4. Persistence filter: must appear in 3 consecutive bars
5. Removal: H_smooth[i] > 0.30 × mean(H_smooth) → LVN filled in
```

---

## 5. Gate Pipeline — Complete Sequence

The gate pipeline has 12 sequential gates. First FAIL stops evaluation.

| Gate | Name | Condition | Fail Reason |
|------|------|-----------|-------------|
| **0** | Session Time | `candle_count ≥ 1` AND `candle_count × 5 ≥ warm_up_minutes` | BLOCKED |
| **1** | Data Quality | `tick_age_seconds ≤ 30` | STALE |
| **2** | Session Risk | `is_risk_halted == False` | SESSION_STOPPED |
| **3** | NO_TRADE | `market_state != NO_TRADE` | FLAT |
| **4** | PROBING | `market_state != PROBING` OR `aggression ≥ threshold` | FLAT |
| **5** | Key Level | `nearest_level > 0` | WAIT |
| **6** | Entry Zone | `distance_to_level ≤ max_distance_ticks` | ALERT |
| **7** | Drive Check | `drive_number == 2` OR `(drive ≥ 3 AND drive_valid)` | FLAT |
| **8** | Aggression | `aggression_score ≥ min_aggression` | WAIT |
| **9** | Cushion | `cushion_ticks ≤ max_cushion` | INVALID |
| **10** | R:R Ratio | `r:r ≥ min_rr_ratio` | SKIP |
| **11** | Position Sizing | `position_size_ok == True` | BLOCKED |
| **12** | EIA Window | `eia_window_active == False` | SUPPRESSED |

**All 12 pass** → `GateResult(passed=True, reason=TRADE)`

### Additional SHORT Gates (S1-S5)

Only evaluated when direction is SHORT:

| Gate | Name | Condition |
|------|------|-----------|
| **S1** | Direction Allowed | `short_signals_enabled == True` |
| **S2** | Market State | IMBALANCED + DOWN displacement OR BALANCED + failed breakout |
| **S3** | ML Probability | P ≥ threshold for playbook (higher than LONG: 0.58 vs 0.55) |
| **S4** | Aggression | ask_volume > bid_volume AND cvd_slope < 0 AND delta < 0 |
| **S5** | Contract Type | Must select PE (not CE) |

---

## 6. Entry Signal Construction

### SL/TP Rules per Playbook

**Mean Reversion (BALANCED):**
```
TP = POC
SL = aggressive_print_level OR VAL - buffer (for LONG)
Max SL distance: min(va_width × 0.5, price × 0.02)
Allow trail: False
```

**Trend Continuation (IMBALANCED):**
```
TP = VAH + (VAH - POC) for LONG, VAL - (POC - VAL) for SHORT
SL = aggressive_print_level OR POC - buffer (for LONG)
Max SL distance: min(va_width × 0.75, price × 0.03)
Allow trail: True
```

**Minimum SL Floor:**
```
atr_val = ATR(14) or price × 0.015
min_sl_dist = max(price × 0.015, atr_val)
```

**Tick Rounding:**
- LONG: SL rounded DOWN, TP rounded UP
- SHORT: SL rounded UP, TP rounded DOWN

**Size Multiplier:**
```
confidence_multiplier: High=1.0, Medium=0.75, Low=0.5
lvn_multiplier: 1.25 if LVN play direction matches trade
Final = confidence × lvn
```

---

## 7. Risk Management

### Risk Tier Engine (A/B/C model)

```
SESSION START → tier=C (0.15% of capital risk per trade)
daily_pnl_r ≥ +1R → tier=B (0.25% risk)
daily_pnl_r ≥ +3R + premium setup → tier=A (0.45% risk)
3 consecutive losses → tier=HALT (0% risk — circuit breaker)
DAILY RESET → tier=C
```

**Tier A Premium Setup** (ALL required):
- aggression_score ≥ 3.5
- lvn_strength ≥ 0.85
- cvd_divergence = true
- is_second_drive = true
- ml_probability ≥ 0.65

### Portfolio Coordinator Rules

| Rule | Limit |
|------|-------|
| MAX_POSITIONS | 5 simultaneous |
| PORTFOLIO_NOTIONAL | 60% of capital |
| SYMBOL_NOTIONAL | 20% of capital per underlying |
| DAILY_LOSS | 2% of capital |
| CORRELATION_GUARD | NIFTY/BANKNIFTY same-direction blocked |

### Scalp Exit Rules (S-EXIT-1 to S-EXIT-6)

| Rule | Trigger | Action |
|------|---------|--------|
| S-EXIT-1 | Price hits hard stop | FULL_EXIT |
| S-EXIT-2 | Unrealized ≥ 1.0R | TRAIL_TO_BREAKEVEN |
| S-EXIT-3 | 1-min CVD flips against position | FULL_EXIT |
| S-EXIT-4 | Opposing absorption detected | FULL_EXIT |
| S-EXIT-5 | Unrealized ≥ 1.5R | PARTIAL_EXIT (50%), trail rest |
| S-EXIT-6 | 12 bars elapsed (60 min) | FULL_EXIT (time stop) |

---

## 8. Scalping Layer

### 15-Sec Trigger (3 conditions, ALL required)

1. **Large Print**: volume ≥ 3× rolling EMA(20)
2. **No Opposing Absorption**: no opposing large print within 3 ticks
3. **CVD Flip**: 15-sec CVD crosses zero

### Scalp Gate Pipeline (6 gates)

| Gate | Check |
|------|-------|
| G1 | Session timing (prime windows only) |
| G2 | MTF alignment (5-min bias + 1-min aggression + 15-sec trigger) |
| G3 | Level proximity (within 5 ticks of structural level) |
| G4 | Risk tier active (not HALT) |
| G5 | Portfolio headroom (< max positions) |
| G6 | No double exposure (NSE: no scalp on symbol with existing position) |

### IB Breakout Scalp

**Setup A — Continuation:**
- Price closes above IB_HIGH with volume confirmation
- Wait for retest within 3 bars
- Entry at IB_HIGH retest, SL 1 tick below, TP = IB_HIGH + 1× IB_WIDTH

**Setup B — Failed Breakout:**
- Price breaks above IB_HIGH then closes back inside within 1-2 bars
- Opposing aggression at breakout high
- Entry at IB_MID breach, SL above failed high, TP = IB_LOW

---

## 9. Data Flow & Event Architecture

### Tick Processing Flow

```
WebSocket tick from Dhan
  → engine.process_tick(symbol, tick, order_book)
    → trading_session.process_tick(symbol, tick, order_book)
      → AMTHandler.analyze(data, order_book, prior_poc/vah/val)
        → Volume profile construction (incremental)
        → POC/VAH/VAL computation (CME Two-Row Pairs)
        → LVN/HVN detection
        → Aggressive prints detection
        → Market state classification
        → Aggression scoring (7 signals)
        → Session VWAP computation
        → Signal generation (3 playbooks)
      → IB engine update
      → 1-min bar engine update
      → Pre-candle advisory (T-60s)
      → Agent pipeline (probability engine)
      → check_exits() for existing positions
      → Entry decision (agent_decision, P ≥ 0.55)
      → Gate Pipeline (12 gates)
      → SHORT gates (S1-S5)
      → build_entry_signal()
      → execute_signal() via EntryCoordinator
      → latency_tracker.record()
```

### Data Storage

| Table | Purpose |
|-------|---------|
| `ticks` | Historical OHLCV candles |
| `trades` | Closed trades with llm_analysis JSON |
| `llm_decisions` | LLM entry decisions |
| `performance_snapshots` | Session equity tracking |
| `session_profiles` | Daily market profiles |
| `open_positions` | Active positions |
| `position_events` | Position lifecycle events |
| `fine_tuning_features` | ML training feature vectors |
| `kv_store` | Key-value store for state persistence |

---

## 10. Configuration System

### YAML Hierarchy (merge sequence)

```
1. config/base.yaml        — default values for all symbols
2. config/environments/{env}.yaml — environment overrides (development/paper/live)
3. config/strategies/*.yaml — strategy overrides
4. Environment variables    — secrets only (DHAN_API_KEY, OPENROUTER_API_KEY, etc.)
5. SystemConfig model       — typed frozen dataclass (source of truth)
6. ConfigValidator          — RULE-1 through RULE-12
7. Startup summary          — logs active config on boot
```

### Feature Flags (18 total)

| Flag | Default | Purpose |
|------|---------|---------|
| `true_delta_lee_ready` | False | Lee-Ready delta vs Gaussian proxy |
| `realistic_cost_model` | False | Full NSE cost model in PaperBroker |
| `parallel_symbol_sessions` | False | Multi-symbol concurrent execution |
| `duckdb_storage` | False | SQLite → DuckDB |
| `short_signals_enabled` | False | PE/SHORT gate logic |
| `risk_tier_engine` | False | A/B/C dynamic risk tiers |
| `initial_balance_engine` | False | IB High/Low/Mid tracking |
| `correlation_guard` | True | NIFTY+BANKNIFTY same-direction block |
| `iv_vix_features` | False | VIX, IV Rank, PCR features |
| `walk_forward_validation` | False | WF-validated models required |
| `shap_feature_pruning` | False | Prune low-importance features |
| `llm_entry_gate` | False | HARDCODED FALSE — never enabled |
| `llm_pre_candle_advisory` | True | Pre-candle advisory (T-60s) |
| `llm_overseer` | True | Position monitoring |
| `llm_post_trade` | True | Post-trade analysis |
| `scalp_engine_enabled` | False | 1-min/15-sec MTF stack |
| `ib_breakout_scalp` | False | IB breakout setups |
| `print_level_trigger` | False | 15-sec tick-level aggression |

### Constants Migration

All 60+ constants loaded from `config/base.yaml` → `globals:` section at import time. Source of truth is YAML, not Python code.

---

## Appendix: File Structure

```
backend/
├── app/
│   ├── api/
│   │   ├── routers/          # REST endpoints (ai, market, metrics, health)
│   │   ├── websocket/        # WebSocket (gameloop)
│   │   └── dependencies.py   # ServiceGraph (dependency injection)
│   ├── application/
│   │   ├── handlers/         # LLM handlers (entry, overseer, pre_candle, post_trade)
│   │   ├── services/         # trading_session, engine, coordinators
│   │   └── candle_aggregator.py
│   ├── domain/
│   │   ├── fabio_ai/services/ # AMT analyzer, gate pipeline, aggression, prompt builder
│   │   ├── services/         # 27 extracted services (volume_profile, lvn, tick, cvd, risk, etc.)
│   │   ├── trading/models/   # entities, aggregates, value_objects, events
│   │   ├── ports/            # abstract interfaces (broker, storage, llm, probability)
│   │   └── constants.py      # YAML-backed constants
│   ├── infrastructure/
│   │   ├── adapters/         # dhan, paper_broker, mlx_inference
│   │   ├── storage/          # database.py (SQLite)
│   │   └── serialization/    # schemas.py (DTO conversion)
│   └── config.py             # Settings (pydantic BaseSettings)
├── config/
│   ├── base.yaml             # default config for all symbols
│   ├── environments/         # development.yaml, paper.yaml, live.yaml
│   └── feature_flags.yaml    # all 18 feature flags
├── config_models/
│   ├── __init__.py           # SystemConfig, ExchangeConfig, SymbolConfig (frozen dataclasses)
│   ├── loader.py             # ConfigLoader (7-step merge)
│   └── validator.py          # ConfigValidator (RULE-1-12)
└── tests/unit/
    ├── domain/               # 64 test files
    ├── application/          # 1 test file
    └── infrastructure/       # 1 test file
```
