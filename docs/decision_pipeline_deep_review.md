# GlassyTrade AI — Decision Pipeline Deep Review
## Graphify Knowledge Graph Audit · `quant/decision/`

> Generated: 2026-09-10 | Graph: **219 nodes · 360 edges · 12 communities**
> Scope: `quant/decision/` (22 files) + caller analysis across `quant/`

---

## Full Architecture (Graph-Traced, Ground-Truth)

```
AMT DTO (dict from runtime._decide())
          │
          ▼
 DecisionContextBuilder.build()                [betweenness: 0.098]
          │
          ▼
 DecisionContext  ◄─── GOD NODE  degree=39, betweenness=0.682
          │                         │
          ▼                         ▼
[PATH 1]  TimesFMEngine.analyze()   [PATH 2]  DecisionService.evaluate()
          │ routes on position_open             │
          ├─ ScanningAgent (pos=False)          └─ GatePipeline (Gate 1-4)
          │   └─ shadow g1-g4 (simplified)           └─ SignalBuilder / VA-Fade
          │   └─ can recommend option SHORT           └─ QuantDecision (REAL signal)
          │
          └─ PositionAgent (pos=True)
              └─ ADVISORY EXIT ONLY (UI only!)

[REAL EXITS]  ExitEngine.evaluate()  ← called by runtime._manage_exit()
                │ timesfm_forecast = strategy.get_latest_forecast()
                └─ TimesFMRiskAuthority.evaluate_exit()  ← REAL OMS EXIT
                    └─ monotonic quantile trailing stop + velocity decay
```

> **Key structural finding (graph-confirmed)**: There are **TWO separate exit systems**.
> - `TimesFMPositionAgent` produces ADVISORY exits shown on the dashboard UI.
> - `TimesFMRiskAuthority` (via `ExitEngine`) produces REAL trade exits sent to the OMS.
> These two systems compute exits from the same `TimesFMForecast` but apply **different logic and thresholds**. They can and do disagree silently.

---

## GOD NODES (Betweenness Centrality)

| Node | Degree | Betweenness | Role |
|---|---|---|---|
| `DecisionContext` | 39 | **0.682** | Single bridge for all data flow |
| `TimesFMForecast` | 21 | **0.306** | Shared between 4 communities: scanner, engine, risk, sizing |
| `TimesFMEngine` | 16 | 0.132 | Routes scan/position advisory |
| `DecisionContextBuilder` | — | 0.098 | Only gate to context |
| `TimesFMRiskAuthority` | — | 0.078 | Higher betweenness than DecisionService.evaluate (0.052)! |

`TimesFMForecast` bridges:
- Community 1 (Scanning Agent)
- Community 3 (Engine + Position Agent)
- Community 5 (Risk Authority + Exit)
- Community 0 (Decision Service + Context)

It is the shared data contract that keeps all four systems loosely coupled —
**a change to its fields (`p10_path`, `p50_path`, `q_spread`) silently affects all four systems.**

---

## CONFIRMED BUGS (Code + Graph Evidence)

### BUG-1 · `absorptionSide` Format Mismatch AND Inverted Direction in ScanningAgent
**File**: [`timesfm_agents.py` L125–143 (scanner), L492–517 (position agent)](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/decision/timesfm_agents.py#L125)

The AMT DTO sends `"BUY_ABSORBED"` / `"SELL_ABSORBED"` but the scanner checks bare
`"BUY"` / `"SELL"` (dead arms). Worse, the arms are **directionally inverted** against
canonical semantics — producer (`detectors.py:268,336-341`), Triple-A engine
(`triple_a.py:85-95`), and `_resolve_direction` all agree **`SELL_ABSORBED` = bullish
= LONG**, but scanner Setup A (LONG) keys on BUY and Setup B (SHORT) on SELL:

| Component | LONG keys on | SHORT keys on | Correct? |
|---|---|---|---|
| `PositionAgent` thesis-flip | SELL absorption (exits LONG) | BUY absorption (exits SHORT) | ❌ inverted — exits winners, holds into bearish absorption |
| `_resolve_direction` | `SELL_ABSORBED` | `BUY_ABSORBED` | ✅ |
| `TripleAEngine` | `SELL_ABSORBED` | `BUY_ABSORBED` | ✅ |
| **`ScanningAgent`** | `absorption == "BUY"` | `absorption == "SELL"` | ❌ dead AND inverted |

**Impact**: With a naive substring fix, the scanner would trade backwards on absorption
(enter LONG on bearish absorption). PositionAgent exits LONGs on bullish absorption.

```python
# Fix — scanner L125: "SELL" in absorption (LONG); L143: "BUY" in absorption (SHORT)
# Fix — position agent L492-493, L508-510: LONG exits on ("BUY", "BUY_ABSORBED"),
# SHORT exits on ("SELL", "SELL_ABSORBED"). Stacked-imbalance arms (L495-496) already correct.
```

---

### BUG-2 · DEAD Market State Is a Plain String, Not Enum
**File**: [`context_builder.py` L385](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/decision/context_builder.py#L385)

```python
# WRONG
if raw_ms == "DEAD":
    amt_market_state = "DEAD"   # plain string

# decision_service.py
if ctx.market_state == MarketState.DEAD:  # "DEAD" != enum → always False
```

**Impact**: VA-fade fires in dead/volume-collapsed markets. `gates_edge.py` handles it correctly via `ms_val in ("DEAD", ...)` but `DecisionService` does not.

```python
# Fix — context_builder.py L385
amt_market_state = MarketState.DEAD
```

---

### BUG-3 · Hardcoded Equity in ScanningAgent Sizer
**File**: [`timesfm_agents.py` L315](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/decision/timesfm_agents.py#L315)

```python
equity=100000.0,   # hardcoded — ignores ctx.equity
# Fix:
equity=ctx.equity,
```

---

### BUG-4 · Phantom `allow_entry` Attribute
**File**: [`timesfm_agents.py` L102](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/decision/timesfm_agents.py#L102)

`DecisionContext` has no `allow_entry` field. `getattr(ctx, "allow_entry", True)` always returns `True`. Dead code.

---

## GRAPH-DISCOVERED STRUCTURAL ISSUES

### STRUCT-1 · `TradeIntent` / `RiskSizer` Is Dead Scaffolding (No Production Callers)
**Graph initial finding**: `TradeIntent` appeared orphaned within the `decision/` module.
**Follow-up search across full codebase**: `TradeIntent` is constructed **only in tests**
(`tests/quant/execution/test_risk_sizer.py`, `tests/quant/decision/test_intent.py`);
`FixedRiskSizer.size()` has **zero production callers**. `RiskSizer` itself is a `Protocol`
in `quant/execution/risk_sizer.py` with no live implementation wired in.

**Revised finding (2026-09-10 verification)**: There is no live `Signal → TradeIntent`
conversion point to audit — the abstraction is un-wired scaffolding. Either wire it
(single sizing seam) or delete it; a half-present abstraction invites a second,
divergent sizing path later. Downgraded to P4.

---

### STRUCT-2 · DUAL EXIT SYSTEM — PositionAgent Advisory vs. ExitEngine Real
**Graph finding**: `TimesFMForecast` bridges Communities 1, 3, AND 5 (Risk Authority).

**Confirmed by code trace**:

```
UI Advisory Exit:
  TimesFMEngine.analyze()
    → TimesFMPositionAgent.evaluate()
    → returns action="EXIT", reason="THESIS_FLIP" (displayed on dashboard)
    → NOT sent to OMS

Real Trade Exit:
  runtime._manage_exit()
    → ExitEngine.evaluate(timesfm_forecast=strategy.get_latest_forecast())
    → TimesFMRiskAuthority.evaluate_exit()
    → returns ExitDecision(should_exit=True, reason="VAR_STOP")
    → SENT TO OMS
```

**Impact**: The dashboard can show `EXIT (THESIS_FLIP)` while the actual position stays open
because `ExitEngine` hasn't triggered yet (different logic/thresholds). Operator acts on UI
advisory but the OMS hasn't executed. Conversely, the OMS can exit via `VAR_STOP` without
the UI ever showing an EXIT advisory.

**Threshold comparison** (same forecast, different exit logic):

| Exit System | Thesis Flip | VaR Stop | Velocity Decay |
|---|---|---|---|
| `PositionAgent` (advisory) | CVD slope ≥ 2.5 OR trajectory breaches 0.5R | — | 5 bars stagnant |
| `RiskAuthority` (real) | — | p10/p90 quantile breached | 20+ bars, tau* passed, pct_change < 0.02% |

The advisory exits earlier (CVD 2.5), the real exit exits later (quantile breach). During the gap, the operator sees EXIT on the dashboard but the position is still live.

---

### STRUCT-3 · DATA_QUALITY_BLOCKED Gate Is Permanently Dead
**File**: [`context_builder.py` L414](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/decision/context_builder.py#L414) and [`decision_service.py` L73](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/decision/decision_service.py#L73)

```python
# context_builder.py
_DETERMINISTIC_CONVICTION = 0.7
agent_probability = _DETERMINISTIC_CONVICTION   # always 0.7

# decision_service.py
if ctx.agent_probability >= 0.9:               # 0.7 >= 0.9 → ALWAYS FALSE
    if not conviction_allowed(ctx.data_quality):
        return DATA_QUALITY_BLOCKED
```

**Impact**: Data quality issues never block any trade. The `DataQuality` field is populated but
never acts as a gate. Trades proceed on inferred/unavailable data always.

```python
# Fix (preferred) — lower threshold in DecisionService so the gate is reachable
# without redefining what the 0.7 deterministic conviction means:
if ctx.agent_probability >= 0.65 and not conviction_allowed(ctx.data_quality):
```
Note: Gate 4 (`gates_rr.py`) is stop-width only — no probability check survives
there, so the "0.7 above 0.55 threshold" comments in `context_builder.py:22-25`
and `runtime.py:109-112` are stale and should be updated with whichever fix lands.

---

### STRUCT-4 · ScanningAgent Internal Gates (g1-g4) Are Shadow Duplicates, Missing 5 Guards

ScanningAgent computes simplified internal gates for UI display:
```python
g1 = bool(ctx.session_open and ctx.warmup_complete and not is_opening ...)
g2 = bool(not ctx.risk_halted and ctx.cooldown_remaining_sec == 0)
g3 = bool(direction != "FLAT")
g4 = bool(abs(forecast.mean_forecast - curr_price) >= ...)
```

Canonical `GatePipeline` additionally enforces:
- Stacked imbalance veto (opposing volume bubble)
- Drive count exhaustion (`drive_number >= 3`)
- Anti-climax filter (LONG rejected at +2σ extension)
- CVD direction block (±0.5 NSE)
- OBI aggression threshold (0.20)
- Contested bubble zone veto

**Impact**: Dashboard shows 4 green gate lights while actual trade is blocked by canonical gates.
`TimesFMTradingStrategy.should_enter()` uses ScanningAgent's shadow gates for its approval
decision — it does NOT call `DecisionService.evaluate()` or `GatePipeline`. This means
the trading strategy and the decision service operate on different gate logic simultaneously.

---

### STRUCT-5 · TimesFMTradingStrategy Bypasses DecisionService Entirely

**Confirmed by code**:
```python
# timesfm_strategy.py — should_enter()
scan_res = self.scanning_agent.evaluate(ctx, forecast)   # only ScanningAgent
# ...does NOT call DecisionService.evaluate() or GatePipeline
```

**Two entry decision systems**:
| System | What decides entry? | Used by |
|---|---|---|
| `TimesFMTradingStrategy.should_enter()` | ScanningAgent shadow gates | `TIMESFM_END_TO_END` mode |
| `DecisionService.evaluate()` | Full canonical GatePipeline | All other runtime modes |

In `TIMESFM_END_TO_END` mode, the Fabio AMT guard rails (stacked imbalance, drive exhaustion, anti-climax) are BYPASSED for entry decisions.

---

### STRUCT-6 · ScanningAgent Can Recommend SHORT on Option Instruments
Context builder sets `agent_direction = None` for option SHORTs — but only affects `DecisionService`.
ScanningAgent has no `is_option_contract()` check, emits `ENTER_SHORT` for options in advisory.
UI shows SHORT advisory; actual trade is blocked silently downstream.

---

### STRUCT-7 · Forecast Calibration Loop Is Unwired (Dead Code)
**File**: [`timesfm_risk.py` L214–244](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/decision/timesfm_risk.py#L214)

`record_forecast_outcome()` and `get_session_budget_multiplier()` have **zero callers**
anywhere in the codebase (verified 2026-09-10). The "continuous forecast error tracking
(Brier/RMSE) to throttle risk when the market becomes unmodelable" from the module
docstring never runs: no outcomes are recorded, the budget multiplier is never read.

**Impact**: The RiskAuthority adapts exits to the forecast but never adapts to being
*wrong*. A degrading model keeps full risk budget indefinitely.

---

### STRUCT-8 · Failed Inference Poisons the Exit Cache With a Synthetic Flat Forecast
**File**: [`timesfm_strategy.py` L333–347](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/strategies/timesfm_strategy.py#L333)

On inference exception, `_compute_forecast()` returns a **synthetic flat forecast**
(`pct_change=0.0`, all steps `"FLAT"`, `lat_ms=0.5`) instead of `None`. Consequences:

1. `should_enter` caches it in `_latest_forecasts[symbol]` (line 133 runs before the
   `MODEL_UNAVAILABLE` check can fire — the check only triggers on `None`).
2. `ExitEngine` reads the same cache via `get_latest_forecast()` (`runtime.py:1427`)
   and feeds it to `TimesFMRiskAuthority.evaluate_exit()` **as if it were a real model
   output** — a flat line that suppresses VAR_STOP ratchets and velocity-decay exits.
3. Nothing marks the payload synthetic (`source` field says nothing; `lat_ms=0.5`
   is the only tell).

**Impact**: A model outage silently converts to "hold forever" exit behavior. The
exception path should return `None` (→ `MODEL_UNAVAILABLE`, no cache write) or tag
the payload so `ExitEngine` can fall back to deterministic rules.

---

## TimesFMForecast — The True Architecture Spine

The graph shows `TimesFMForecast` (betweenness 0.306) connects four communities:

```
TimesFMForecast
  ├─ [Community 1] ScanningAgent.evaluate(ctx, forecast)
  │                 → produces advisory ENTER signal
  │
  ├─ [Community 3] TimesFMEngine routes to:
  │   ├─ PositionAgent.evaluate(ctx, forecast)
  │   │   → produces advisory EXIT signal (UI only)
  │   └─ TimesFMEngine._rule_based_fallback (if model unavailable)
  │
  ├─ [Community 5] RiskAuthority.evaluate_exit(forecast=forecast)
  │                 → produces REAL EXIT decision sent to OMS
  │                 → also: update_trailing_stop(forecast=forecast)
  │
  └─ [Community 0] DecisionContext uses forecast.curr_price as reference price
                   (via TimesFMEngine.add_context → ctx.bar.close)
```

**The forecast is the shared ground truth** — but it is computed at different points in time
for different paths:
- ScanningAgent / PositionAgent get it fresh from `TimesFMEngine.analyze()`
- `ExitEngine` gets it from `strategy.get_latest_forecast(symbol)` — a **cached** value

**If a bar closes with a new forecast but the strategy hasn't updated the cache yet, ExitEngine
uses a stale forecast for its RiskAuthority exit decision.**

---

## CVD Threshold Map (all constants verified in code 2026-09-10)

| Component | NSE Threshold | Purpose | Source |
|---|---|---|---|
| `_resolve_direction` | ±0.5 (±0.3 MCX) | Sets `agent_direction` | `context_builder.py:111,127-144` |
| `gates_edge` CVD block | ±0.5 (±0.3 MCX) | Blocks conflicting entries | `gates_edge.py:46-51` |
| `ScanningAgent` Triple-A | **±1.0** | Setup detection | `timesfm_agents.py:126,144` |
| `ScanningAgent` Setup E | ±0.5 | Momentum concordance | `timesfm_agents.py` |
| `PositionAgent` thesis flip | **±2.5** (+0.5R trajectory breach) | Advisory exit | `timesfm_agents.py:498-502` |
| `PositionAgent` time-stop | — | Advisory exit: `bars_held >= 5`, `|rr| < 0.25`, `|pct_change| < 0.0003` | `timesfm_agents.py:555` |
| `RiskAuthority` VAR_STOP | n/a (p10/p90 quantile breach) | Real exit | `timesfm_risk.py:116-133` |
| `RiskAuthority` velocity decay | — | Real exit: `bars_held >= max(tau*+5, 20)`, `rr < 0.2`, `|pct_change| < 0.0002` | `timesfm_risk.py:179` |

---

## Community Structure (12 Communities)

| # | Label | Key Nodes | Health |
|---|---|---|---|
| 0 | Decision Service & Context | `DecisionContext`, `DecisionService`, `QuantDecision` | Core — well connected |
| 1 | TimesFM Scanning Agent | `TimesFMScanningAgent`, `TimesFMForecast` | Uses shadow gates |
| 2 | TimesFM Advisor (HTTP) | `TimesFMAdvisor`, `TimesFMClient`, `TimesFMSnapshotBuffer` | Dual-path risk |
| 3 | TimesFM Engine & Position Agent | `TimesFMEngine`, `TimesFMPositionAgent` | Advisory exits only |
| 4 | Context Builder (AMT → DC) | `DecisionContextBuilder` | God node factory |
| 5 | Risk Authority & Exit | `TimesFMRiskAuthority`, `ModelExitEvaluation` | Real exits — caller is ExitEngine |
| 6 | Signal Builder & Output | `SignalBuilder`, `Signal` | Not used by TimesFMStrategy! |
| 7 | Data Quality & Enums | `DataQuality`, `conviction_allowed` | Gate permanently dead |
| 8 | Trade Intent | `TradeIntent` | Dead scaffolding — tests only, no production callers |
| 9 | Stop Loss Utilities | `structural_anchor`, `tick` | Helpers, fine |
| 10 | VA-Fade Detection | `detect_va_fade`, `VAFadeSignal` | Fine |
| 11 | Package Init | `__init__` | Fine |

---

## Prioritized Fix Table

| Priority | ID | File | Fix | Risk if Unfixed |
|---|---|---|---|---|
| 🔴 P1 | BUG-2 | `context_builder.py:385` | `MarketState.DEAD` enum | VA-fade in dead market |
| 🔴 P1 | BUG-1 | `timesfm_agents.py:125,143` | `"BUY" in absorption` | Absorption arm dead in scanner |
| 🔴 P1 | STRUCT-3 | `context_builder.py:414` | Raise `_DETERMINISTIC_CONVICTION=0.95` | Data quality never gates trades |
| 🔴 P1 | STRUCT-2 | Architecture | Document advisory-vs-real exit gap in operator runbook | Operator acts on stale UI signal |
| 🟠 P2 | STRUCT-5 | `timesfm_strategy.py` | Add `GatePipeline` call in `should_enter` or document intentional bypass | Fabio guard rails skipped in E2E mode |
| 🟠 P2 | STRUCT-4 | `timesfm_agents.py` | Use real `GatePipeline` gate results in scanning agent output | UI gate lights mislead operator |
| 🟠 P2 | STRUCT-8 | `timesfm_strategy.py:333` | Return `None` (or tag synthetic) on inference failure | Model outage → "hold forever" exits |
| 🟡 P3 | STRUCT-7 | `timesfm_risk.py:214` | Wire `record_forecast_outcome` + budget multiplier, or delete | Degrading model keeps full risk |
| 🟡 P3 | BUG-3 | `timesfm_agents.py:315` | `equity=ctx.equity` | Wrong sizing display |
| 🟡 P3 | STRUCT-6 | `timesfm_agents.py` | Add `is_option_contract` check for SHORT setups | Option SHORT in advisory |
| 🟢 P4 | STRUCT-1 | `intent.py` / `risk_sizer.py` | Wire single sizing seam or delete dead scaffolding | Divergent sizing path later |
| 🟢 P4 | BUG-4 | `timesfm_agents.py:102` | Remove phantom `allow_entry` | Code clarity |
| 🟢 P4 | Forecast cache | `runtime.py` / `timesfm_strategy.py` | Verify forecast cache is fresh before ExitEngine evaluates | Stale forecast → wrong exit timing |

---

## Pre-Session Integrity Checklist (12-Point)

```
[ ] 1.  HEALTH:          GET /health → status "ok", TimesFM model loaded, contracts monitored
[ ] 2.  AMT DTO KEYS:    Log first amt_dto — poc/vah/val non-zero after bar 15
[ ] 3.  CVD SLOPE:       ctx.cvd_slope is non-zero (AMT computing it)
[ ] 4.  ABSORPTION FMT:  ctx.absorption_side is "BUY_ABSORBED" or "SELL_ABSORBED" (not bare "BUY"/"SELL")
[ ] 5.  MARKET STATE:    type(ctx.market_state) is MarketState enum (not plain string "DEAD")
[ ] 6.  EQUITY:          ctx.equity matches actual account capital (not 0.0 or 100000.0)
[ ] 7.  SESSION GATE:    session_allow_entry returns True after 09:15 IST for NSE
[ ] 8.  SL PROPAGATION:  After TIGHTEN_SL fires, verify ExitEngine trail stop updated (not just advisory)
[ ] 9.  WARMUP:          ctx.warmup_complete=True AND strategy._latest_forecasts has fresh entry
[ ] 10. EXIT SYSTEM:     Log exit source on every close — confirm "VAR_STOP"/"VELOCITY_DECAY"
        comes from ExitEngine, not confusing it with advisory PositionAgent EXIT signal
[ ] 11. DUAL PATH:       Log advisory source field — confirm "TIMESFM_3.0_NATIVE" not "TIMESFM_FALLBACK"
        to verify model is loaded and not in rule-based fallback mode
[ ] 12. DATA QUALITY:    Confirm DataQuality field arrives in amt_dto and that conviction threshold
        is reachable (currently 0.9, agent_probability is hardcoded 0.7 — always unreachable)
```

---

## Graph Outputs

- **Interactive graph**: [`quant/graphify-out/graph.html`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/graphify-out/graph.html) — open in browser
- **Graph report**: [`quant/graphify-out/GRAPH_REPORT.md`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/graphify-out/GRAPH_REPORT.md)
- **Raw graph JSON**: [`quant/graphify-out/graph.json`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/graphify-out/graph.json)
