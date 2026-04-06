<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# continue

Here is the full continuation, covering the remaining critical systems — LLM architecture, options layer, learning loop, RL environment, and the complete implementation sprint plan.

***

## 🔴 P0 Continued — Critical AMT Methodology Failures


***

### 21. `Drive Tracker` / `Drive Decay` Not Wired to Gate Pipeline

**Files**: `drive_tracker.py`, `drive_decay.py` (Section 31.6)[^1]

Both services exist but their output doesn't appear anywhere in the `EntryGateCoordinator` 7-gate list or the 12-gate pipeline. In Fabio's methodology, **Drive Tracking** is fundamental: you need to know if the current directional move is a fresh drive (high-conviction entry opportunity) or a decaying drive nearing exhaustion (avoid entering; look for a reversal). Entering on a drive in late-decay is one of the most common mistakes in AMT trading — you buy the top of an exhausting move thinking it's momentum.

**What's Missing**:

- `DriveTrackerPort` should feed `drive_state: FRESH | MATURING | DECAYING | EXHAUSTED` into `AMTResult`
- `Gate-14` (Drive State Gate): block `MOMENTUM` and `AAA` setups when drive state is `DECAYING` or `EXHAUSTED`
- `MEAN_REVERSION` and `FAILED_AUCTION` setups should be **preferred** when drive is `EXHAUSTED`
- `drive_decay.py` output should also override the Overseer's ADD decision — no pyramid add during a decaying drive

**Fix**:

```python
# In entry_gate.py - add Drive Gate:
if setup.type in [SetupType.MOMENTUM, SetupType.AAA]:
    drive_state = amt_result.drive_state  # Add to AMTResult
    if drive_state in [DriveState.DECAYING, DriveState.EXHAUSTED]:
        return GateResult.BLOCKED, "GATE_DRIVE_DECAY: momentum entry on exhausted drive"
```


***

### 22. `Absorption Validator` Is Isolated — Not Used as Primary Entry Trigger

**File**: `backend/app/domain/fabio_ai/services/absorption_validator.py`[^1]

`absorption_validator.py` exists as a standalone service under "Entry \& Gate Services" but in Fabio's playbook, **absorption** at a structural level (HVN, POC, VAL/VAH) is **the primary confirmation signal** before an AAA or Failed Auction entry — not a secondary filter. Absorption means smart money is quietly accumulating/distributing without moving price: footprint shows high volume at a price level with near-zero delta (buyers and sellers balanced at that price). When price suddenly leaves that level with directional aggression after absorption, that is the highest-probability entry trigger Fabio teaches.

**Current Problem**: The footprint already detects `Absorption (high volume without price movement)` in `TickFootprintAccumulator`, but this signal is generated for visualization only via `FootprintDTO`. It is not converted into a domain event or gate decision. `absorption_validator.py` is called nowhere in the main `_on_tick()` pipeline.[^1]

**Fix**:

- `FootprintAnalyzer` should emit `AbsorptionEvent(price, direction_of_departure, volume_absorbed, candle_time)` when absorption fingerprint is detected
- Subscribe this event in `SessionRiskCoordinator` and set `session_state.absorption_context = event`
- In `AAA precondition engine` (`aaa_precondition_engine.py`): require `absorption_context` at the entry LVN within the last 3 candles
- In `LLM prompt builder` (`prompt_builder.py`): include `absorption_context` in the prompt context so the LLM can reference it in its thesis

***

## 🟠 P1 Continued — High Priority Issues


***

### 23. LLM System Prompt Does Not Encode Fabio's Full Playbook

**File**: `backend/app/domain/fabio_ai/services/prompt_builder.py` and `prompt_engineering_service.py`[^1]

The LLM receives a "Fabio playbook instructions" system prompt, but the actual content of this prompt is not documented in the architecture guide. Based on the system structure, there are critical Fabio rules that must be explicitly encoded in the prompt or the LLM will generate plausible-sounding but non-Fabio trades:

**Rules the prompt MUST include and enforce via JSON schema validation**:

```
RULE-P1: "Only enter at structural locations (LVN, VAH, VAL, POC boundaries). 
          Never enter in the middle of the Value Area."
RULE-P2: "Stop loss must be placed at the structural invalidation level — 
          the level that, if breached, proves the thesis wrong."
RULE-P3: "Minimum R:R is 1.5:1. Do not generate any signal with R:R < 1.5."
          [NOTE: Config validator warns at R:R < 1.5 as Fabio's floor]
RULE-P4: "If CVD slope contradicts the direction, return FLAT. Never fight order flow."
RULE-P5: "Identify the Setup Type explicitly: AAA, MOMENTUM, MEAN_REVERSION, or 
          FAILED_AUCTION. Do not generate signals without a named setup."
RULE-P6: "Profile shape must support the direction: P-shape supports LONG, 
          b-shape supports SHORT, D-shape supports MEAN_REVERSION only."
RULE-P7: "Opening type context must be respected. In Open Drive, no 
          MEAN_REVERSION. In ORR, no MOMENTUM."
```

Currently the config validator warns at `min_rr_ratio < 1.5` (WARN-4)  but the default `TradeManagerConfig` has `take_profit_pct = 0.015` and `stop_loss_pct = 0.005`, which gives exactly 3:1 ratio on paper — but the LLM is setting actual SL/TP levels based on market structure, not these config values. The LLM needs to be explicitly instructed that R:R < 1.5 is a hard rejection, not just a warning.[^1]

***

### 24. `R:R Validator` Has Wrong Floor — `1.0` vs Fabio's `1.5`

**File**: `backend/app/domain/fabio_ai/services/rr_validator.py`, `config/base.yaml`[^1]

The `Signal` validation in `signal_constructor.py` states: `Signal validation (R:R >= 1.0)`.  But the config validator (WARN-4) explicitly states: *"min_rr_ratio below 1.5 — Fabio's floor."*  This is a direct conflict. The system currently accepts any signal with R:R ≥ 1.0 when Fabio's minimum is 1.5. Every trade generated with R:R between 1.0 and 1.5 is a **below-Fabio-standard trade** slipping through.[^1]

**Fix**: Change the hard validation floor in `rr_validator.py` from 1.0 to 1.5. The current 1.0 floor should become the "emergency fallback" threshold logged as a risk warning, not the production acceptance criterion.

```python
# rr_validator.py
FABIO_MINIMUM_RR = Decimal("1.5")   # Hard block below this
WARN_RR_THRESHOLD = Decimal("2.0")  # Warn but allow between 1.5 and 2.0
OPTIMAL_RR_TARGET = Decimal("3.0")  # Target for full size

def validate(signal: Signal) -> RRValidationResult:
    rr = signal.risk_reward_ratio
    if rr < FABIO_MINIMUM_RR:
        return RRValidationResult(passed=False, reason=f"R:R {rr} below Fabio floor 1.5")
    if rr < WARN_RR_THRESHOLD:
        return RRValidationResult(passed=True, warning="Sub-optimal R:R, reduce size by 50%")
    return RRValidationResult(passed=True)
```


***

### 25. `Overseer` Cooldown Is Too Short — 3-Second Decisions on Live Positions

**File**: `backend/app/application/handlers/llm_overseer_handler.py`[^1]

The LLM Overseer runs every **3 seconds** on open positions.  This means it can reverse a `HOLD` decision to `PARTIAL_EXIT` within 3 seconds if the LLM interprets a single adverse tick. Fabio's position management philosophy is the opposite — he teaches patience: "let the market prove you wrong, don't exit on noise." A 3-second overseer cycle on a 5-minute-candle strategy means the overseer could issue 100 decisions in the lifetime of a single setup candle, each potentially overriding the structural thesis.[^1]

**Fix**:

- Overseer cycle should be aligned to the **candle interval** — run once per candle close, not every 3 seconds
- For a 5-minute chart, overseer fires at candle close ±10 seconds
- Add `HOLD_UNTIL_CANDLE_CLOSE` as a new action type — prevents any exit until the current candle closes
- The only exception: `FULL_EXIT` when `adverse probability > 80%` from the quant engine should remain instant[^1]

***

### 26. `Options Selection Engine` Conflicts with Fabio's Options Preferences

**File**: `backend/app/domain/fabio_ai/services/option_scanner.py`[^1]

The `OptionScanner` scores contracts on a 100-point system where **ATM proximity gets 40 points** and **delta sweet spot (0.40-0.60) gets 10 points**.  This aggressively selects near-ATM options. But in Fabio's AMT methodology for options, the choice between ATM and slightly OTM is **setup-dependent**, not a blanket preference for ATM:[^1]


| Setup Type | Fabio's Option Preference |
| :-- | :-- |
| `AAA` at VAL (high conviction) | ATM or slightly OTM (0.40–0.45 delta) — maximize leverage |
| `FAILED_AUCTION` (reversal) | ATM (0.45–0.55 delta) — fast reaction needed |
| `MEAN_REVERSION` (moderate conviction) | Slightly OTM (0.35–0.45 delta) — cap risk |
| `MOMENTUM` breakout | ATM for initial entry, OTM for scale-in adds |
| Low-conviction setups | OTM (0.25–0.35 delta) — limit premium at risk |

**Fix**: Add `setup_type` and `confidence` as inputs to `OptionScanner.scan()`. The ATM proximity weight should dynamically shift: 40 pts for HIGH conviction, 20 pts for MEDIUM, 10 pts for LOW conviction.

***

### 27. `Walk-Forward Validator` Exists But Is Not Connected to Live Promotion

**File**: `backend/app/domain/services/walk_forward_validator.py`[^1]

The `walk_forward_validator.py` service exists alongside `capital_ladder.py` and `BacktestEngine`. The `/ai/journal/promotion` endpoint assesses paper-trading readiness using configurable thresholds (`minTrades`, `minExpectancy`, `minProfitFactor`, `maxDrawdown`).  But walk-forward validation is fundamentally different from PnL metrics — it tests whether the strategy's edge holds across **different market regimes** and **out-of-sample periods**.[^1]

Currently, a paper run can be promoted to live based on aggregate PnL metrics without ever checking if the strategy degrades on new data. In Fabio's framework, you must demonstrate the system works across at least 3 distinct market regime cycles before live trading.

**Fix**: Wire `WalkForwardValidator` into the promotion assessment pipeline:

- Minimum 2 regime cycles (BALANCED period + IMBALANCED period) in paper history
- Walk-forward out-of-sample ratio ≥ 60% (60% of trades must be in true out-of-sample windows)
- Regime-specific win rates: must be ≥ 45% in BALANCED + ≥ 55% in IMBALANCED
- If any walk-forward fold fails, block live promotion regardless of aggregate PnL

***

### 28. `RL Environment` Observation Space Is Too Narrow — 12 Features vs 42 in LightGBM

**File**: `backend/app/domain/fabio_ai/rl/valentini_env.py`[^1]

The `ValentiniAMTEnv` uses a 12-feature observation space for RL training.  The LightGBM `DirectionAgent` uses 42 features across 6 groups.  These 12 RL features are a subset of Group A (Price Microstructure) and Group B (Order Flow) — they completely exclude:[^1]

- **Order Book features** (6): bid_imbalance, depth_imbalance — critical for institutional intent
- **Options-Specific features** (6): PCR, OI change, moneyness — missing the options market context entirely
- **Temporal features** (4): minutes_to_expiry, session_minute — RL agent has no time-awareness

An RL agent trained on 12 features will learn a policy that's suboptimal compared to what's possible with the full 42-feature space. The action space also has no `SCALE_IN` action — it can't learn the 40/30/30 pyramid strategy.

**Fix**:

- Expand observation space to 24 features minimum (add all 6 Order Book + 6 Options-Specific features)
- Add `SCALE_IN` and `SCALE_OUT` actions (expand from 5 to 7 actions) with action masking:
    - `SCALE_IN` masked unless position already open + confirmation conditions met
    - `SCALE_OUT` masked unless position already open + adverse conditions detected
- Add `minutes_to_expiry` normalization to temporal group in observation

***

## 🟡 P2 Continued — Medium Priority Polish


***

### 29. `Session Phase Gate` Doesn't Use IB to Define Phase Boundaries

**File**: `backend/app/domain/fabio_ai/services/session_phase_gate.py` and `trading_session.py`[^1]

The 5 session phases (Phase 1 = open, Phase 5 = forced close at 15:15 IST) appear to be time-based.  But Fabio's phases are **market-structure-based**, not clock-based:[^1]

- **Phase 1** ends when the Initial Balance is **confirmed** (enough volume to define it), not at 10:15 IST
- **Phase 2** begins when price first tests the IB boundary — this can happen at 09:45 or 11:30 depending on the day
- **Phase 3** (IB breakout phase) only activates when price **closes outside IB** with conviction volume
- **Phase 4** (extension phase) is active until a **failed extension** is detected or 14:00 IST

The current time-based phase gating misidentifies market phase during slow mornings (where IB doesn't complete until 11:00) and during volatile mornings (where all phases compress into 90 minutes).

**Fix**: Add `IBCompletionDetector` that fires an `IBConfirmed` event when volume and price range meet the IB completion criteria. Phase transitions should be event-driven, not time-driven.

***

### 30. `Correlation Guard` Only Covers NSE Indices — MCX-NSE Correlation Missing

**File**: `backend/app/application/services/portfolio_coordinator.py`[^1]

RULE-5 `CORRELATION_GUARD` "blocks NIFTY/BANKNIFTY/FINNIFTY same-direction entries."  But it doesn't account for the[^1]

<div align="center">⁂</div>

[^1]: paste.txt

