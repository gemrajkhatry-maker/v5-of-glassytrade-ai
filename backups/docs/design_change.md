# GlassyTrade AI — Full Build Plan
## MCX + NSE | Fabio AMT Methodology | Option Scalping

***

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────┐
│                    GLASSTRADE AI v3.0                       │
├─────────────────┬───────────────────────────────────────────┤
│   MCX MARKET    │           NSE MARKET                      │
│  NATURALGAS FUT │    NIFTY FUT / BANKNIFTY FUT              │
│  CRUDEOIL FUT   │    FINNIFTY FUT / MIDCPNIFTY FUT          │
│  GOLD FUT       │                                           │
├─────────────────┴───────────────────────────────────────────┤
│              FABIO AMT ENGINE (shared)                      │
│  Layer 1: Read UNDERLYING FUTURES → AMT Analysis           │
│  Layer 2: Execute OPTION CONTRACTS → Trade Management       │
└─────────────────────────────────────────────────────────────┘
```

***

## Phase 1 — Foundation Fix (Week 1–2) 🔴 CRITICAL

### 1A. Underlying Futures Feed — The Root Fix

Every AMT calculation must switch from option premium to underlying futures price.

**Instrument mapping config:**
```json
{
  "MCX": {
    "CRUDEOIL": {
      "underlying_symbol": "CRUDEOIL25APRFUT",
      "underlying_segment": "MCX_COMM",
      "options_segment": "MCX_COMM",
      "strike_step": 50,
      "lot_size": 100,
      "tick_size": 1.0,
      "session_start": "09:00",
      "session_end": "23:30",
      "ib_window_minutes": 30,
      "big_order_filter_lots": 30,
      "range_bar_size": 20,
      "dead_volume_pct": 5
    },
    "NATURALGAS": {
      "underlying_symbol": "NATURALGAS25APRFUT",
      "underlying_segment": "MCX_COMM",
      "strike_step": 5,
      "lot_size": 1250,
      "tick_size": 0.10,
      "session_start": "09:00",
      "session_end": "23:30",
      "ib_window_minutes": 30,
      "big_order_filter_lots": 20,
      "range_bar_size": 2,
      "dead_volume_pct": 5
    },
    "GOLD": {
      "underlying_symbol": "GOLD25APRFUT",
      "underlying_segment": "MCX_COMM",
      "strike_step": 100,
      "lot_size": 1,
      "tick_size": 1.0,
      "session_start": "09:00",
      "session_end": "23:30",
      "ib_window_minutes": 30,
      "big_order_filter_lots": 5,
      "range_bar_size": 100,
      "dead_volume_pct": 5
    }
  },
  "NSE": {
    "NIFTY": {
      "underlying_symbol": "NIFTY25APRFUT",
      "underlying_segment": "NSE_FNO",
      "options_segment": "NSE_FNO",
      "strike_step": 50,
      "lot_size": 75,
      "tick_size": 0.05,
      "session_start": "09:15",
      "session_end": "15:30",
      "ib_window_minutes": 30,
      "big_order_filter_lots": 50,
      "range_bar_size": 20,
      "dead_volume_pct": 5
    },
    "BANKNIFTY": {
      "underlying_symbol": "BANKNIFTY25APRFUT",
      "underlying_segment": "NSE_FNO",
      "strike_step": 100,
      "lot_size": 15,
      "tick_size": 0.05,
      "session_start": "09:15",
      "session_end": "15:30",
      "ib_window_minutes": 30,
      "big_order_filter_lots": 30,
      "range_bar_size": 50,
      "dead_volume_pct": 5
    },
    "FINNIFTY": {
      "underlying_symbol": "FINNIFTY25APRFUT",
      "underlying_segment": "NSE_FNO",
      "strike_step": 50,
      "lot_size": 40,
      "tick_size": 0.05,
      "session_start": "09:15",
      "session_end": "15:30",
      "ib_window_minutes": 30,
      "big_order_filter_lots": 20,
      "range_bar_size": 15,
      "dead_volume_pct": 5
    }
  }
}
```

### 1B. Dual Feed Subscription

```
DhanHQ WebSocket
├── Subscribe: CRUDEOIL FUT ticks   → AMT Engine (Layer 1)
├── Subscribe: CRUDEOIL Options LTP  → Execution Layer (Layer 2)
├── Subscribe: NIFTY FUT ticks      → AMT Engine (Layer 1)
└── Subscribe: NIFTY Options LTP    → Execution Layer (Layer 2)
```

### 1C. Session Boundary Engine

| Market | Session Start | Session End | IB Window | Prior VA Snapshot |
|---|---|---|---|---|
| MCX | 09:00 IST | 23:30 IST | 09:00–09:30 | Fires at 23:30 IST |
| NSE | 09:15 IST | 15:30 IST | 09:15–09:45 | Fires at 15:30 IST |

***

## Phase 2 — Fabio AMT Engine (Week 3–4) 🔴 CRITICAL

### 2A. Three-Step Model — Both Markets

```
STEP 1: MARKET STATE (from underlying futures)
├── BALANCED   → price inside VA → activate Model 2 (Mean Reversion)
└── IMBALANCED → price outside VA → activate Model 1 (Trend Follow)

STEP 2: LOCATION (LVN on futures profile)
├── Model 1: Find LVN in direction of breakout above/below VA
│            Set alert zone at LVN ± (ATR × 0.1)
└── Model 2: Price at deep discount (near VAL) or premium (near VAH)
             Target = Prior POC (Fabio's primary mean reversion target)

STEP 3: AGGRESSION TRIGGER (futures footprint)
├── Price arrives at LVN zone
├── Big order filter fires: ≥ 30 lots (CRUDEOIL), ≥ 50 (NIFTY)
├── CVD session-cumulative confirms direction
├── Gate G7: Drive must be D2+ (no D1 entries)
└── SIGNAL GENERATED → pass to Option Execution Layer
```

### 2B. CVD Fix — Session Cumulative

```python
class SessionCVD:
    # Reset at session_start for each market
    # Accumulate: delta = ask_vol - bid_vol per tick
    # Slope: linear regression over last 20 bars
    # on top of session-cumulative series
    
    MCX_RESET  = "09:00 IST"
    NSE_RESET  = "09:15 IST"
```

### 2C. DEAD Market — Time-of-Day Adjusted

| Time Window | MCX Baseline | NSE Baseline |
|---|---|---|
| 09:00–12:00 | High activity | Opening range |
| 12:00–17:00 | Moderate | Mid-session |
| 17:00–21:00 | Peak MCX evening | Closed |
| 21:00–23:30 | Low MCX closing | Closed |

DEAD threshold compares against **same time-of-day 10-session rolling average** — not full session average.

***

## Phase 3 — Option Execution Layer (Week 5–6) 🟡 IMPORTANT

### 3A. Option Selection Logic

When AMT signal fires on CRUDEOIL FUT SHORT:
```
1. Signal: SHORT on CRUDEOIL FUT at ₹8,878
2. Select strike: nearest OTM PE below current price
   → 8850 PE (50-point below) ← MCX step = 50
3. Validate option:
   ├── OI > 50,000 contracts ✅
   ├── Bid-Ask spread < ₹1.50 ✅
   ├── IV < 40% (not overpriced) ✅
   └── Delta between -0.40 and -0.60 ✅
4. Entry: Market order or limit at LTP + ₹0.50 slippage buffer
```

### 3B. Stop Loss & Target Calculation

```
FUTURES level → convert to OPTION PREMIUM

Stop Loss:
  FUT stop = LVN level where aggression fired + buffer
  Option SL = current premium - (FUT_distance × |delta|)
  Example: FUT stop at 8,895 (+17 pts from entry 8,878)
           PE delta = -0.52
           Option SL = 640 - (17 × 0.52) = 640 - 8.8 = ₹631

Target:
  FUT target = Prior POC (₹8,699) — Fabio's primary target
  FUT distance = 8,878 - 8,699 = 179 points
  Option target = 640 + (179 × 0.52) = 640 + 93 = ₹733
  R:R = 93 / 8.8 = 10.6 : 1 ✅
```

### 3C. Trade Management Rules

```
POST-ENTRY MONITORING:
├── CVD continues BEARISH → HOLD position
├── CVD slope flattens (< -5 from -54) → ALERT: pressure easing
├── CVD reverses to BULLISH → MOVE TO BREAK EVEN
├── New big BUY ball appears at support → CONSIDER EXIT
├── Price reaches Prior POC → FULL EXIT (Fabio: 70% reversal prob)
└── Price reaches Prior VAL → PARTIAL EXIT (50%), trail rest
```

***

## Phase 4 — UI Layout (Week 7–8) 🟡 IMPORTANT

### Full Screen Layout

```
┌─────────────────────────────────────────────────────────────────────┐
│  GlassyTrade AI  │  MCX  ←→  NSE  │  Session: ACTIVE  │  23:15 IST │
├───────────────────────────────────────────────────────┬─────────────┤
│                                                       │   SCANNER   │
│  PANEL A: UNDERLYING FUTURES CHART (65%)             │   (15%)     │
│  ─────────────────────────────────────────────        ├─────────────┤
│  CRUDEOIL FUT  ₹8,878  │ Range Bars │ Footprint │ CVD │  CRUDEOIL   │
│                                                       │  IMBAL D2✅ │
│  VAH ━━━━━━━━ 8,920 ━━━━━━━━━━━━━━━━━━━━ (red)      │  NATURAL    │
│                                                       │  BAL  D1❌  │
│         🔴 52 lots                                    │  NIFTY      │
│  LVN ─ ─ ─ ─  8,905 ─ ─ ─ ─ ─ ─ ─ ─ (orange)      │  BAL  –     │
│                                                       │  BANKNIFTY  │
│  POC ━━━━━━━━ 8,878 ━━━━━━━━━━━━━━━━━━━━ (yellow)   │  IMBAL D2✅ │
│                         ← price                       ├─────────────┤
│  LVN ─ ─ ─ ─  8,850 ─ ─ ─ ─ ─ ─ ─ ─ (orange)      │  PANEL B    │
│                                                       │  EXECUTION  │
│         🟢 31 lots                                    │  (20%)      │
│  VAL ━━━━━━━━ 8,820 ━━━━━━━━━━━━━━━━━━━━ (green)    │             │
│                                                       │  📉 SHORT   │
│  Prior POC ─ ─ ─ 8,699 ─ ─ ─ ─ ─ ─ ─ ─ (purple)   │  8850 PE    │
│  Prior VAL ─ ─ ─ 8,640 ─ ─ ─ ─ ─ ─ ─ ─ (purple)   │  ₹640       │
│                                                       │  SL: ₹631   │
│  CVD ▁▂▃▄▃▂▃▄▅▆▇▆▅  Session: -2,450  BEARISH ▼     │  TGT: ₹733  │
│  IB ████████████████ 8,840–8,910 (30-min box)        │  R:R 10.6:1 │
│                                                       │             │
│  STATE: IMBALANCED │ LOCATION: AT LVN │ DRIVE: D2 ✅ │ [EXECUTE]   │
└───────────────────────────────────────────────────────┴─────────────┘
```

***

## Phase 5 — Model Intelligence (Week 9–10) 🟢 ENHANCEMENT

### 5A. Two-Model Logic per Market Condition

| Time | MCX Behavior | Model to Activate |
|---|---|---|
| 09:00–10:30 | Opening range, IB building | Wait — no trades |
| 10:30–17:00 | Directional session | Model 1 (Trend) |
| 17:00–21:00 | Peak volume evening | Model 1 + Model 2 |
| 21:00–23:30 | Winding down | Model 2 only (mean reversion) |
| 09:15–10:15 | NSE opening range | Wait — IB building |
| 10:15–12:30 | NSE directional | Model 1 (Trend) |
| 12:30–14:30 | NSE lunch chop | Model 2 (Mean Reversion) |
| 14:30–15:30 | NSE expiry/close | Model 1 if IMBALANCED |

### 5B. Prior POC Wired Into Probability Model

```
LightGBM Features to ADD:
├── prior_poc_distance_pct    (how far price is from Prior POC)
├── price_below_prior_poc     (boolean — mean reversion potential)
├── prior_va_width            (session range expectation)
├── price_vs_prior_vah        (above/below prior value area)
└── prior_poc_as_target       (target price for P(target) calc)
```

***

## Phase 6 — Risk & Order Management (Week 11–12) 🟢 ENHANCEMENT

### 6A. Kelly Sizing Per Market

```
Risk per trade:
  MCX CRUDEOIL:    0.25% of equity per lot (₹2,500 on ₹10L account)
  MCX NATURALGAS:  0.25% of equity per lot
  NSE NIFTY:       0.25% of equity per lot
  NSE BANKNIFTY:   0.25% of equity per lot

Max daily loss:
  MCX: 1.5% of equity (₹15,000) → auto-halt all MCX signals
  NSE: 1.0% of equity (₹10,000) → auto-halt all NSE signals
  Combined: 2.0% → system lockout until next session
```

### 6B. Session-Aware Order Gate

```
Order Gate checks (in sequence):
  G0: Is market session ACTIVE? (time-based per exchange)
  G1: Is underlying data feed LIVE? (heartbeat check)
  G2: Market state = IMBALANCED (Model 1) or AT VA EDGE (Model 2)?
  G3: Location confirmed at LVN?
  G4: Drive = D2 or higher?
  G5: Big order ball fired (≥ threshold lots)?
  G6: CVD confirming direction?
  G7: Daily loss limit NOT breached?
  G8: Option spread TIGHT (< ₹1.50 MCX, < ₹0.25 NSE)?
  
  ALL 8 GATES PASS → Signal confirmed → Execute
  ANY GATE FAILS  → Block trade, log reason
```

***

## Complete Build Timeline

| Phase | What | Duration | Priority |
|---|---|---|---|
| **1** | Dual feed: FUT + Options, instrument mapping, session boundary | Week 1–2 | 🔴 Must |
| **2** | AMT on underlying FUT, session CVD, DEAD fix | Week 3–4 | 🔴 Must |
| **3** | Option selection, delta-based SL/target, trade management | Week 5–6 | 🟡 High |
| **4** | Two-panel UI: FUT chart left, option execution right | Week 7–8 | 🟡 High |
| **5** | Two-model logic, Prior POC in ML features | Week 9–10 | 🟢 Medium |
| **6** | Kelly sizing, 8-gate order system, daily loss halt | Week 11–12 | 🟢 Medium |

***

## The One-Line Brief for Your Coding Agent

> **"Rebuild GlassyTrade AI as a two-layer system: Layer 1 subscribes to underlying FUTURES (CRUDEOIL FUT, NIFTY FUT) for all AMT analysis (profile, CVD, IB, LVN, aggression bubbles). Layer 2 uses the signal from Layer 1 to select, validate, and execute the corresponding OPTION contract (CE for LONG, PE for SHORT) via DhanHQ. Both MCX and NSE are supported via a market_config.json with per-instrument session times, lot sizes, strike steps, and range bar sizes."**