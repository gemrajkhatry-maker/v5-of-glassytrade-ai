# Fabio AMT Decision Pipeline — Strategy Rules Mapped to Code

> Documents the 4-gate decision pipeline and VA-fade fallback.
> Every gate is mapped to its implementation, inputs, and pass/fail criteria.

## Overview

The Fabio AMT strategy uses a deterministic 4-gate pipeline to evaluate entries.
The LLM advisor **never gates an entry** — it provides narrative context only.

```
DecisionContext
      │
      ▼
  [Risk Halt?] ─── yes ──→ HALTED
      │ no
      ▼
  Gate 1: Session Phase
      │
      ▼
  Gate 2: Position / Cooldown
      │
      ▼
  Gate 3: Triple-A Edge
      │
      ▼
  Gate 4: Risk-Reward (Stop Cap)
      │
      ├── all pass → SignalBuilder → APPROVED (Triple-A / LVN_Sniper)
      │
      ├── Gate 1 or 2 failed → GATE_REJECTED (hard reject, no fade)
      │
      └── Gate 3 or 4 failed → VA-Fade Fallback
                                  ├── fade detected → VA_FADE (approved)
                                  └── no fade → NO_EDGE
```

**Source**: `quant/decision/decision_service.py` → `DecisionService.evaluate()`

---

## Gate 1: Session Phase

**File**: `quant/decision/gates/gate_session_phase.py` → `gate_session_phase(ctx)`

**Purpose**: Ensure the market is open, warmed up, in a tradeable session phase, and spread is acceptable.

### Checks (in order)

| # | Check | Fail Reason | Code |
|---|-------|-------------|------|
| 1 | `ctx.session_open == True` | "Session closed" | L56-57 |
| 2 | `ctx.warmup_complete == True` | "Warming up — insufficient bars" | L58-59 |
| 3 | Exchange clock: NSE 09:30–15:15 IST, MCX 09:15–23:15 IST | "NSE/MCX clock blackout: current {t} outside {window} IST" | L61-79 |
| 4 | Setup type vs session phase permission | "SESSION_PHASE: {type} blocked — trend continuation not permitted" or "mean reversion not permitted" | L81-101 |
| 5 | Spread ≤ max(2× tick, 0.1% of price, ₹0.40) | "Wide spread — slippage risk" | L103-115 |

### Session Phase Permissions

| Setup Type | Requires | Blocked When |
|-----------|----------|-------------|
| `TRIPLE_A`, `SECOND_DRIVE`, `LVN_SNIPER` (momentum) | `ctx.allow_trend == True` | Midday consolidation, reversion-only phases |
| `VA_FADE` (reversion) | `ctx.allow_reversion == True` | Trend-only phases |

---

## Gate 2: Position / Cooldown

**File**: `quant/decision/gates/gate_position_cooldown.py` → `gate_position_cooldown(ctx, allow_positioned)`

**Purpose**: Prevent duplicate entries and enforce post-trade cooldown.

### Checks

| # | Check | Fail Reason | Code |
|---|-------|-------------|------|
| 1 | `ctx.cooldown_remaining_sec == 0` | "In cooldown — {N}s remaining" | L19-24 |
| 2 | `ctx.position_open == False` (unless `allow_positioned`) | "Position already open" | L26-33 |

### Thesis-Flip Exception

When `allow_positioned=True` (evaluating an open position for invalidation):
- The position blocker is bypassed → "thesis-flip check"
- **Cooldown seconds still enforce** — a real post-trade cooldown always blocks

---

## Gate 3: Triple-A Edge

**File**: `quant/decision/gates_edge.py` → `gate_triple_a_edge(ctx)`

**Purpose**: Verify a valid Fabio setup exists — the institutional entry trigger.

### Phase A: Guards (veto checks before setup evaluation)

| Guard | Fail Condition | Code |
|-------|---------------|------|
| No bar | `ctx.bar is None` | L21-22 |
| Opposing stacked imbalance | Stacked imbalance direction opposes trade direction | L23-29 |
| Contested bubble zone | `ctx.contested_bubble_zone == True` | L30-31 |
| No direction | `ctx.agent_direction` not in {LONG, SHORT} | L32-33 |
| Dead market | `ctx.market_state == DEAD` | L34-36 |
| Anti-climax (LONG) | Price > `vwap_upper_2` (2σ extension) | L38-39 |
| Anti-climax (SHORT) | Price < `vwap_lower_2` (-2σ extension) | L40-41 |
| Drive exhausted | `drive_number >= 3` and `drive_entry_valid == False` | L42-43 |
| CVD conflict (LONG) | `cvd_slope < -0.3` (NSE) or `< -0.5` (MCX) | L44-49 |
| CVD conflict (SHORT) | `cvd_slope > 0.3` (NSE) or `> 0.5` (MCX) | L50-51 |

### Phase B: Setup Paths (evaluated in priority order)

| Path | Setup | Pass Condition | Code |
|------|-------|---------------|------|
| 1. Setup Evidence | Any complete setup | `setup_evidence.is_complete()` and direction matches | L57-62 |
| 2. Triple-A AGGRESSION | `triple_a_phase == "AGGRESSION"` | Phase is AGGRESSION, signal matches direction, trend allowed | L63-69 |
| 3. Second Drive | `drive_entry_valid == True` | Reclaim of rejected probe level | L70-71 |
| 4. LVN Sniper | `leg_lvn > 0`, price near LVN | Price within 2 ticks of LVN, absorption on correct side, CVD not opposing | L72-84 |
| 5. Initiative Breakout | `break_type == "INITIATIVE"` | Direction matches (UP→LONG, DOWN→SHORT), CVD not opposing, trend allowed | L85-95 |
| 6. Squeeze Retest | `squeeze_direction` matches | Price retests trapped level (within 3 ticks) or pullback confirmed, CVD not opposing | L97-110 |

If no path fires → "No Triple-A edge: no valid setup"

---

## Gate 4: Risk-Reward (Stop Cap)

**File**: `quant/decision/gates_rr.py` → `gate_risk_reward(ctx)`

**Purpose**: Ensure the structural stop is within acceptable distance. This gate is the **stop-width authority only**. SignalBuilder enforces the actual R:R ≥ 1.5.

### Checks

| # | Check | Fail Condition | Code |
|---|-------|---------------|------|
| 1 | Valid bar and direction | `ctx.bar is None` or direction not in {LONG, SHORT} | L19-23 |
| 2 | Stop within cap | `risk > scaled_cap_ticks × tick` where `scaled_cap_ticks = max(200, (entry × 0.75%) / tick)` | L28-35 |

### Constants

- `MIN_RR = 1.5` — enforced by SignalBuilder, not this gate
- `MAX_STOP_DISTANCE_TICKS = 200` — default cap, scaled up for high-priced instruments

---

## Model Router (Fabio two models)

**File**: `quant/decision/model_router.py` — the ONE place that maps auction state to model.

- `IMBALANCED → TREND`; `BALANCED → MEAN_REVERSION`.
- A *complete* `SetupEvidence` snapshot or a certified `INITIATIVE` break overrides
  a lagging VA label (`select_model(ctx)`).
- `DecisionService.evaluate()` enforces it once: a Gate-3 approval whose
  `GateResult.setup_key` belongs to the other model is blocked, and the VA-fade
  fallback runs only when `allows("VA_FADE", active_model)`.

## VA-Fade / MEAN_REVERSION path

**File**: `quant/decision/va_fade.py` → `detect_va_fade()` (called from `DecisionService.evaluate()`)

**Purpose**: The balance-returning reversion trade (Fabio Model 2): price probes
beyond the VA, fails to hold, and closes back INSIDE the VA — a failed auction.
Price still outside the VA is a trend, not a fade, and yields no signal.

### Conditions

1. Market is NOT dead (`market_state != DEAD`) and `allows("VA_FADE", active_model)`
2. A probe beyond the VA edge was rejected: `session_extreme_low < VAL` /
   `session_extreme_high > VAH`, or a complete `VA_FADE` evidence packet
3. Price CLOSES back inside the value area (`val <= close <= vah`)
4. Direction agrees with order flow (CVD sign, or a VARS reclaim)
5. Fade direction matches `agent_direction` (or `agent_direction` is None)
6. Minimum stop distance met (`is_min_stop_met(entry, sl)`)

### Output

- Approved with `reason="VA_FADE"`, `model_label="VA_Fade"`, stop beyond the full
  probe extreme, and **target = POC** (100% exit at balance).

---

## Decision Outcomes

| Reason | Approved | Meaning |
|--------|----------|---------|
| `Triple-A` | Yes | Gate 3 path: Triple-A AGGRESSION / Second Drive / LVN Sniper / Initiative Breakout / Squeeze Retest |
| `LVN_Sniper` | Yes | Gate 3 path: LVN Sniper specifically |
| `VA_FADE` | Yes | VA-fade fallback after Gate 3/4 rejection |
| `HALTED` | No | Session risk halted trading |
| `GATE_REJECTED` | No | Gate 1 or 2 failed (hard reject — no fade allowed) |
| `NO_EDGE` | No | No valid setup found, or VA fade not available |

---

## DecisionContext Key Fields

**File**: `quant/decision/context.py` → `DecisionContext`

| Field | Source | Used By |
|-------|--------|---------|
| `session_open` | Session gates | Gate 1 |
| `warmup_complete` | Engine (≥15 bars) | Gate 1 |
| `allow_trend` / `allow_reversion` | Session phase table | Gate 1, Gate 3 |
| `position_open` | Engine state | Gate 2 |
| `cooldown_remaining_sec` | SessionRisk | Gate 2 |
| `agent_direction` | AMT analyzer / context builder | Gate 3, Gate 4 |
| `market_state` | AMT analyzer | Gate 3 (DEAD veto) |
| `setup_evidence` | Setup state detector | Gate 3 Path 1 |
| `triple_a_phase` / `triple_a_signal` | Triple-A machine | Gate 3 Path 2 |
| `drive_entry_valid` / `drive_number` | AMT analyzer | Gate 3 Path 3 |
| `leg_lvn` | AMT DTO (impulse leg profile) | Gate 3 Path 4 |
| `break_direction` / `break_type` | AMT analyzer | Gate 3 Path 5 |
| `squeeze_direction` / `squeeze_trapped_level` | Regime detector via AMT DTO | Gate 3 Path 6 |
| `cvd_slope` | CVD tracker | Gate 3 guards |
| `obi` | Live depth snapshot | Gate 3 (A3 aggression) |
| `poc` / `vah` / `val` | AMT analyzer (session VA) | Gate 4, VA-fade |
| `vwap_upper_2` / `vwap_lower_2` | Session VWAP | Gate 3 anti-climax |
| `bid` / `ask` | Live depth | Gate 1 spread check |
