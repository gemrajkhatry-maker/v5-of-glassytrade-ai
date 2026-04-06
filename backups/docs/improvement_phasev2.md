<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# do not write code give me dtails , flows, conditions, formulats, sequence etc, llm code agent will implement it

Understood. Pure specification mode — architecture decisions, flows, conditions, formulas, sequences. No code. An LLM agent will implement from this.

***

# GlassyTrade AI — Complete Incremental Build Specification

## Expert System Design | Phase -1 → Phase 5


***

## Guiding Principles (Non-Negotiable)

Before phases, these rules govern every decision:

1. **Every phase ends with a deployable, fully-tested system** — not a half-built one
2. **Config drives behaviour** — no operational decision requires a code change
3. **Each component has one job** — if you cannot state it in one sentence, split it
4. **Observability is not optional** — if you can't measure it, you can't improve it
5. **Fail fast at startup** — bad config discovered at boot, not at 09:20 IST
6. **Feature flags gate all new capability** — turn off without redeploy
7. **Test count never goes down** — every phase adds tests, never removes

***

## Full System Evolution Map

```
Phase -1: NERVOUS SYSTEM
  Config as Architecture + Observability Foundation
  → The skeleton everything else hangs on

Phase 0: DOMAIN INTEGRITY
  God object decomposition + Data truth (real delta, real costs)
  → Trust what the system reports

Phase 1: PARALLEL ENGINE
  True multi-symbol concurrent execution backbone
  → All 7 symbols fire independently

Phase 2: BILATERAL TRADING + DYNAMIC RISK
  SHORT/PE signals + Risk Tier A/B/C + Initial Balance
  → Full market coverage, right sizing

Phase 3: INTELLIGENCE UPGRADE
  Walk-forward ML + IV/VIX/PCR features + LLM restructure
  → Validated edge, regime-aware intelligence

Phase 4: SCALPING LAYER
  1-min/15-sec MTF stack + print-level triggers + IB scalps
  → 10-25 trades/day frequency

Phase 5: PRODUCTION HARDENING
  Live broker activation + capital scaling + self-healing
  → ₹50L/month target
```


***

***

# PHASE -1 — "Nervous System"

## Config as Architecture + Observability Foundation

### Duration: 10 Days | Prerequisite: Nothing | Blocks: Everything


***

### Why This is Phase -1 Not Phase 0

Every problem you have traces back to one root cause: **there is no single authoritative typed configuration model**. The `.env` exchange-mode toggle you mentioned is one symptom. Others:[^1]

- `constants.py` holds NSE+MCX thresholds in a flat global file — change one, risk breaking the other
- `option_scanner.py` has `MIN_OI` and `STRIKE_INTERVALS` hardcoded as dicts inside the file
- `vp_contract_selector.py` has bucket sizes hardcoded inside the file
- `trading_session.py` and `amt_analyzer.py` read from `constants.py` directly — not injected
- No way to run NSE + MCX simultaneously because exchange mode is a single `.env` toggle
- No way to distinguish paper vs live config — risk params are the same in both

**The target state after Phase -1**: Flip `GLASSYTRADE_ENV=paper` → all 7 symbols active, paper broker, realistic costs. Flip `GLASSYTRADE_ENV=live` → live broker, tighter risk, production logging. **Zero code change ever for operational switches.**

***

### P(-1) Component 1: Config File Hierarchy

#### Structure

```
config/
├── base.yaml                        ← All symbols, all exchanges, all defaults
├── environments/
│   ├── development.yaml             ← 1 symbol (NIFTY), paper broker, DEBUG logs
│   ├── paper.yaml                   ← All symbols, paper broker, INFO logs, realistic costs
│   └── live.yaml                    ← All symbols, live broker, WARNING logs, tight risk
├── strategies/
│   ├── amt_thresholds.yaml          ← Every AMT constant per symbol (migration from constants.py)
│   ├── risk.yaml                    ← Every risk param per environment
│   └── ml_models.yaml               ← Model file paths + thresholds per playbook per symbol
└── feature_flags.yaml               ← Every capability toggle
```


#### Merge Sequence (strictly enforced, no exceptions)

```
STEP 1: Load base.yaml                   → establishes ALL defaults
STEP 2: Load environments/{ENV}.yaml     → deep-merge overrides base
STEP 3: Load strategies/*.yaml           → deep-merge overrides result
STEP 4: Read ENV vars for SECRETS ONLY   → API keys, tokens (never config)
STEP 5: Build typed SystemConfig object  → immutable, frozen, validated
STEP 6: Run ConfigValidator              → fail fast if invalid
STEP 7: Log startup summary              → human-readable config snapshot at boot
```


#### Environment Variable Rule

Only these 3 ENV vars are ever read at runtime:

- `GLASSYTRADE_ENV` → selects environment file (default: `development`)
- `DHAN_API_KEY` → secret, never in yaml
- `DHAN_CLIENT_ID` → secret, never in yaml

Everything else lives in YAML. Period.

***

### P(-1) Component 2: base.yaml Full Structure

Every field below must exist. Comments explain the rationale.

#### System Section

```
system:
  name: GlassyTrade AI
  version: 2.0.0
  candle_timeframe_minutes: 5       ← primary signal timeframe
  tick_history_depth: 500           ← bars retained per symbol in memory
```


#### Per-Symbol Fields (repeated for all 7 symbols)

Every symbol carries ALL of the following — no constants.py lookup ever:

**Identity fields**: `enabled`, `exchange`, `segment`, `instrument_type`, `lot_size`, `tick_size`

**Volume Profile fields**:

- `vp_bucket_size` — price width per histogram bucket
- `vp_num_buckets` — total buckets (200 default)
- `value_area_pct` — 0.70 for all (CME standard)
- `lvn_threshold` — bucket volume < X% of mean = LVN candidate (0.15)
- `hvn_threshold` — bucket volume > X× mean = HVN (2.00)
- `lvn_persistence_bars` — must persist N bars before emitting (3)
- `lvn_removal_threshold` — volume rises to X% of mean → remove LVN (0.30)

**AMT fields**:

- `imbalance_threshold` — price distance from VA to classify IMBALANCED (per-symbol points)
- `displacement_multiplier` — bar range must be X× ATR(5) to count as displacement (NSE: 1.5, MCX: 1.2)
- `displacement_min_bars` — consecutive directional bars required (3)
- `balance_ratio_threshold` — fraction of time inside VA to classify BALANCED (NSE: 0.70, MCX: 0.55)
- `no_trade_ticks_from_poc` — dead zone around POC (2 ticks)
- `aggression_sigma` — standard deviations above mean volume = aggressive print (NSE: 2.5, MCX: 2.0)

**CVD fields**:

- `cvd_slope_warning` — slope magnitude that triggers warning (30.0)
- `cvd_slope_hard_block` — slope magnitude that blocks entry (50.0)
- `cvd_slope_extreme` — slope magnitude that forces exit (100.0)
- `cvd_strong_slope` — minimum slope to confirm direction (2.0)
- `cvd_rolling_bars` — lookback bars for slope computation (20)

**Contract Selection fields**:

- `min_oi` — minimum open interest to consider a contract liquid
- `strike_interval` — spacing between strikes
- `strikes_around_atm` — how many strikes above/below ATM to scan (2)
- `slippage_bps` — basis points slippage for paper broker cost model (ATM default)
- `max_notional_pct` — max portfolio notional this symbol can consume (0.20)
- `min_rr_ratio` — minimum R:R to allow entry (1.5)

**ML Threshold fields** (per playbook):

```
ml_thresholds:
  imbalance_continuation:  { long: 0.55, short: 0.58 }
  return_to_value:         { long: 0.51, short: 0.51 }
  probing_breakout:        { long: 0.58, short: 0.58 }
```

**Why different long/short thresholds**: India markets have structural long bias — short setups require higher conviction to overcome this bias.

***

### P(-1) Component 3: feature_flags.yaml Full Structure

```
features:
  # ── Phase 0 flags ──
  true_delta_lee_ready: false          → true activates Lee-Ready, false = Gaussian proxy
  realistic_cost_model: false          → true activates full NSE cost model in PaperBroker

  # ── Phase 2 flags ──
  short_signals_enabled: false         → enables PE / SHORT gate logic
  risk_tier_engine: false              → enables A/B/C dynamic risk tiers
  initial_balance_engine: false        → enables IB High/Low/Mid tracking
  correlation_guard: false             → blocks NIFTY+BANKNIFTY same-direction

  # ── Phase 3 flags ──
  iv_vix_features: false               → adds VIX, IV Rank, PCR to feature vector
  walk_forward_validation: false       → requires WF-validated models before entry
  shap_feature_pruning: false          → prunes features with |SHAP| < 0.001

  # ── LLM role flags (individual per role) ──
  llm_entry_gate: false                → HARDCODED FALSE — never enabled in any env
  llm_pre_candle_advisory: true        → non-blocking, fires T-60s before bar close
  llm_overseer: true                   → position monitoring (keep as-is)
  llm_post_trade: true                 → post-trade analysis (keep as-is)

  # ── Phase 4 flags ──
  scalp_engine_enabled: false          → enables 1-min/15-sec MTF stack
  ib_breakout_scalp: false             → enables Initial Balance breakout setups
  print_level_trigger: false           → enables 15-sec tick-level aggression trigger

  # ── Infrastructure flags ──
  duckdb_storage: false                → switches from SQLite to DuckDB
  parallel_symbol_sessions: false      → switches from single to per-symbol workers
```

**Feature flag rule**: Every new capability starts `false`. Enabled one at a time, tested, then promoted. You never enable two new flags simultaneously in the same test session.

***

### P(-1) Component 4: Typed Config Model Specification

The `SystemConfig` object is the **only** object passed through `ServiceGraph`. No other config source exists at runtime.

#### Object Graph

```
SystemConfig (frozen, immutable at startup)
├── exchanges: dict[str, ExchangeConfig]
│   └── ExchangeConfig
│       ├── name, enabled, segment
│       ├── session_open (time), session_close (time)
│       ├── warmup_minutes, timezone
│       ├── eia_suppression_minutes (MCX only)
│       └── symbols: dict[str, SymbolConfig]
│           └── SymbolConfig (all fields from base.yaml above)
│               ├── ml_thresholds: dict[str, MLThresholds]
│               └── cost_profile: CostProfile
├── risk: RiskConfig
│   ├── risk_per_trade_pct, max_daily_loss_pct
│   ├── max_consecutive_losses, max_drawdown_pct
│   ├── max_concurrent_positions, portfolio_notional_cap
│   ├── kelly_fraction, kelly_win_prob, kelly_win_loss_ratio
│   └── bootstrap_trade_count
├── flags: FeatureFlags     ← all feature_flags.yaml fields
├── environment: str         ← "development" | "paper" | "live"
├── broker_mode: str         ← "paper" | "live"
├── capital: float           ← starting capital in INR
├── db_path: str
└── log_level: str

Convenience methods on SystemConfig:
  .symbol_config(symbol: str) → SymbolConfig   (finds across exchanges)
  .active_symbols() → list[SymbolConfig]        (enabled only)
  .active_exchanges() → list[ExchangeConfig]    (enabled only)
  .is_live() → bool
  .is_paper() → bool
```


***

### P(-1) Component 5: Config Validation Rules

All rules run at startup. Hard errors block boot. Warnings log but allow boot.

#### Hard Errors (boot blocked)

```
RULE-1:  At least 1 active symbol exists
RULE-2:  In live mode: broker_mode must be "live"
RULE-3:  In live mode: llm_entry_gate must be false
RULE-4:  In live mode: capital ≥ ₹10,00,000
RULE-5:  risk_per_trade_pct ≤ 0.02 (2% hard ceiling)
RULE-6:  portfolio_notional_cap ≤ 0.80
RULE-7:  value_area_pct between 0.60 and 0.85 for all symbols
RULE-8:  min_rr_ratio ≥ 1.0 for all symbols
RULE-9:  sum of all symbol max_notional_pct ≤ 1.50 (sanity check)
RULE-10: cvd_slope_warning < cvd_slope_hard_block < cvd_slope_extreme (ordering)
RULE-11: lvn_threshold < lvn_removal_threshold (removal > detection)
RULE-12: ML model files exist for all active symbols (or shared generic model flagged)
```


#### Warnings (boot allowed, logged)

```
WARN-1:  In paper mode, capital > ₹5,00,00,000 (unusually high for paper)
WARN-2:  short_signals_enabled but walk_forward_validation is false
WARN-3:  risk_tier_engine enabled but bootstrap_trade_count < 30
WARN-4:  Any symbol with min_rr_ratio < 1.5 (below Fabio's recommended floor)
WARN-5:  llm_pre_candle_advisory enabled but LLM model file not found
WARN-6:  MCX enabled but CRUDEOIL/GOLD/SILVER have no option chain (log MCX futures-only note)
```


***

### P(-1) Component 6: Observability System Specification

Four measurement systems, all independent, all zero-cost when disabled.

#### Gate Rejection Tracker

**Purpose**: Know exactly which gate is killing signals. Without this, you tune blindly.

**Tracked per gate, per symbol, per session**:

- Total ticks evaluated
- Total gate rejections (and which gate)
- Total signals reaching execution
- Rejection rate per gate (rejections / total evaluated)
- Top-5 gate killers per symbol (sorted by rejection rate)

**Exposed on**: `/api/metrics` endpoint + React dashboard Gate Performance panel

**Key insight**: If Gate 7 (Drive enforcement) rejects 80% of candidates on BANKNIFTY but only 30% on NIFTY, you know BANKNIFTY has more first-drive noise and the threshold may need tuning.

#### Tick-to-Signal Latency Tracker

**Purpose**: Know if the system is fast enough for live trading.

**Tracked per symbol**:

- p50, p95, p99 latency from tick receipt to signal emit or rejection
- Maximum latency spike (detects event loop stalls)
- Rolling 1000-sample window (no memory growth)

**Alert threshold**: p99 > 50ms = warning, p99 > 200ms = critical

#### Delta Accuracy Comparator

**Purpose**: During Phase 0 transition, measure how wrong the Gaussian proxy was.

**When `true_delta_lee_ready` flag is false**:

- Run both Gaussian proxy AND Lee-Ready side-by-side
- Record both values per tick
- Compute: Mean Absolute Error, Pearson correlation, divergence frequency
- Log: "Gaussian proxy was X% wrong on average across Y ticks"

**When `true_delta_lee_ready` flag is true**:

- Tracker deactivated (cost savings)


#### Session Health Reporter

**Purpose**: Every session-end report with key stats.

**Reported at session close (15:15 NSE, 23:15 MCX)**:

- Total ticks processed per symbol
- Total signals fired / rejected ratio
- Gate kill distribution (which gates fired most)
- Latency p95 per symbol
- PnL (paper) in R and INR
- Delta accuracy metrics (if comparator active)
- LLM advisory response rate (% of candles with advisory response)

***

### P(-1) Component 7: Startup Sequence (Exact Order)

```
STARTUP SEQUENCE (main.py):

1. Read GLASSYTRADE_ENV from environment (default: development)
2. Load ConfigLoader → produces SystemConfig (immutable)
3. Run ConfigValidator → fail fast if hard errors
4. Log startup summary → human-readable config snapshot
5. Configure structured logging (log level from config)
6. Initialize MetricsRegistry (in-memory, zero cost)
7. Initialize storage (SQLite or DuckDB based on feature flag)
8. Run DB schema migration (idempotent — safe to run every boot)
9. Initialize ServiceGraph (inject SystemConfig into all components)
10. Start FastAPI (health endpoint returns /ready only after step 9)
11. Start Engine (engine.py) — starts symbol sessions
12. Log "System Ready" with active symbols list
```

**The `/health/ready` endpoint returns 200 only after step 9. `/health/live` returns 200 from step 5 onward.** Load balancers and monitoring tools use `ready` before routing traffic.

***

### P(-1) Exit Criteria (all must be true)

```
[ ] GLASSYTRADE_ENV=development starts with NIFTY only, zero .env edits required
[ ] GLASSYTRADE_ENV=paper starts all 7 symbols, zero .env edits required
[ ] constants.py has ZERO imports anywhere in codebase
[ ] option_scanner.py has ZERO hardcoded dicts for MIN_OI or STRIKE_INTERVALS
[ ] vp_contract_selector.py has ZERO hardcoded bucket sizes or thresholds
[ ] ConfigValidator passes all RULE-1 through RULE-12 checks
[ ] /api/metrics endpoint returns gate rejection data for each active symbol
[ ] Structured logs include symbol + gate name on every rejection
[ ] Startup summary logged to console at every boot
[ ] All 855 existing tests pass (fixtures updated to use SymbolConfig not constants)
[ ] New tests added: ConfigLoader (merge sequence), ConfigValidator (all 12 rules), FeatureFlags (toggle behaviour)
[ ] Target test count: 950+
```


***
***

# PHASE 0 — "Domain Integrity"

## Decompose God Objects + Data Truth

### Duration: 10 Days | Requires: Phase -1 complete


***

### The Central Problem

Three files do too much:[^1]


| File | Lines | Problem |
| :-- | :-- | :-- |
| `amt_analyzer.py` | 2063 | VP + LVN + CVD + State + Aggression + Footprint + Entry detection — all in one |
| `trading_session.py` | 1119 | Tick routing + state + risk + events + LLM — all in one |
| `llm_entry_handler.py` | 983 | Entry gate + overseer + advisory + post-trade — all in one |

**Why this matters beyond cleanliness**: When AMT logic is in a 2063-line file, you cannot test `CVDTracker` alone, cannot inject different configs per symbol, cannot swap `VolumeProfileComputer` for a different implementation without touching everything else.

***

### P0 Component 1: AMTAnalyzer Decomposition

#### Target Component Map

```
AMTAnalyzer (orchestrator, ~150 lines)
    │
    ├── VolumeProfileComputer
    │     Single job: maintain histogram, compute POC/VAH/VAL
    │     Inputs: price, volume per tick; SymbolConfig
    │     Outputs: VolumeProfileSnapshot (POC, VAH, VAL, histogram)
    │
    ├── LVNDetector
    │     Single job: detect and maintain LVN/HVN list
    │     Inputs: VolumeProfileSnapshot; SymbolConfig
    │     Outputs: list[LVNLevel], list[HVNLevel]
    │
    ├── MarketStateEngine (already exists — clean interface)
    │     Single job: classify 4-state model
    │     Inputs: close price, POC, VAH, VAL, OHLC; SymbolConfig
    │     Outputs: MarketState enum + displacement info
    │
    ├── TickDeltaClassifier (NEW — replaces Gaussian proxy)
    │     Single job: classify each trade tick as buy or sell aggression
    │     Inputs: trade price, volume, bid, ask
    │     Outputs: signed delta (float)
    │
    ├── CVDTracker (NEW — extracted from amt_analyzer)
    │     Single job: accumulate delta, compute slope, detect divergence
    │     Inputs: tick delta stream; SymbolConfig
    │     Outputs: CVDSnapshot (cvd, slope, kill_signal, direction)
    │
    ├── AggressionScorer (already exists — inject SymbolConfig)
    │     Single job: score aggression from 6 components
    │     Inputs: tick data stream; SymbolConfig
    │     Outputs: AggressionScore (total, components, tier)
    │
    └── FootprintAnalyzer (already exists — use real delta from TickDeltaClassifier)
          Single job: bid/ask footprint analysis
          Inputs: tick delta (from TickDeltaClassifier); SymbolConfig
          Outputs: FootprintResult (imbalance, absorption, big prints)
```


#### VolumeProfileComputer — Full Specification

**State maintained**:

- Histogram: array of `vp_num_buckets` float values (volume per price bucket)
- `price_min`, `price_max` — set on first tick of session
- `total_volume` — running sum
- Reset at session open → session-scoped profile (current day only)

**Bucket index formula**:

$$
\text{bucket\_idx} = \left\lfloor \frac{\text{price} - \text{price\_min}}{\text{bucket\_size}} \right\rfloor
$$

**POC computation**:

```
POC = price at bucket with maximum volume
If tie (two buckets equal max): select bucket closer to session VWAP
VWAP = running sum(price × volume) / running sum(volume)
```

**VAH/VAL computation — CME Two-Row Pairs Method (exact)**:

```
START: upper_idx = POC_bucket, lower_idx = POC_bucket
       va_volume = histogram[POC_bucket]
       target = total_volume × value_area_pct (0.70)

LOOP while va_volume < target:
  top_add = histogram[upper_idx+1] + histogram[upper_idx+2]  (2 rows above)
  bot_add = histogram[lower_idx-1] + histogram[lower_idx-2]  (2 rows below)
  
  IF top_add >= bot_add:
    upper_idx += 2
    va_volume += top_add
  ELSE:
    lower_idx -= 2
    va_volume += bot_add
  
  GUARD: if upper_idx = max OR lower_idx = 0 → break

VAH = price at upper_idx (upper edge of bucket)
VAL = price at lower_idx (lower edge of bucket)
```


#### LVNDetector — Full Specification

**Smoothing step** (prevents false detection on single noisy buckets):

$$
H_{\text{smooth}}[i] = \frac{H[i-1] + H[i] + H[i+1]}{3}
$$

**LVN candidate detection**:

```
Candidate = bucket i where ALL:
  H_smooth[i] < lvn_threshold × mean(H_smooth)
  H_smooth[i] < H_smooth[i-1]    (local minimum — lower than neighbor above)
  H_smooth[i] < H_smooth[i+1]    (local minimum — lower than neighbor below)
```

**LVN persistence rule** (anti-flicker):

```
Candidate must appear in N consecutive bar updates (lvn_persistence_bars = 3)
before being emitted as a confirmed LVN
```

**LVN removal rule**:

```
Remove confirmed LVN when:
  H_smooth[i] > lvn_removal_threshold × mean(H_smooth)   (0.30)
  → Volume filled in the gap — LVN no longer valid
```

**LVN strength score formula**:

$$
\text{LVN\_strength} = 1 - \frac{H_{\text{smooth}}[i]}{\text{mean}(H_{\text{smooth}})}
$$

Range: 0 (weakest — barely qualifies) → 1 (perfect — zero volume in bucket)

**HVN detection** (support/resistance zones):

```
HVN = bucket i where H_smooth[i] > hvn_threshold × mean(H_smooth)   (2.0×)
HVN strength = H_smooth[i] / mean(H_smooth)   (normalized)
```


#### TickDeltaClassifier — Full Specification (Replaces Gaussian Proxy)

**Algorithm: Lee-Ready (standard market microstructure)**

```
INPUT per trade tick: price, volume, bid, ask, prev_price

STEP 1 — Quote Rule (use when bid/ask available):
  IF price >= ask:  delta = +volume   (aggressive buyer lifted the ask)
  IF price <= bid:  delta = -volume   (aggressive seller hit the bid)
  IF bid < price < ask: go to STEP 2  (mid-price trade — ambiguous)

STEP 2 — Tick Rule (for mid-price trades or missing quote):
  IF price > prev_price:  delta = +volume  (uptick = buyer-initiated)
  IF price < prev_price:  delta = -volume  (downtick = seller-initiated)
  IF price = prev_price:  delta = 0        (zero-tick — no classification)

STEP 3 — Update state:
  prev_price = price (for next tick)
```

**CVD accumulation**:

$$
\text{CVD}_t = \text{CVD}_{t-1} + \delta_t
$$

Where $\delta_t$ = Lee-Ready signed delta at tick t.

#### CVDTracker — Full Specification

**Per-bar delta accumulation**:

- Each bar: accumulate all tick deltas → `bar_delta`
- At bar close: append `bar_delta` to rolling history (20 bars)
- Reset `bar_delta = 0` for next bar

**CVD slope computation (linear regression over 20 bars)**:

$$
\text{slope} = \frac{\sum_{i=1}^{n}(x_i - \bar{x})(y_i - \bar{y})}{\sum_{i=1}^{n}(x_i - \bar{x})^2}
$$

Where $y_i$ = bar delta values, $x_i$ = bar index, $n$ = cvd_rolling_bars (20).

**CVD states**:

```
|slope| < cvd_strong_slope (2.0)   → NEUTRAL
|slope| < cvd_slope_warning (30)   → NORMAL
|slope| < cvd_slope_hard_block (50)→ WARNING (gate will log)
|slope| < cvd_slope_extreme (100)  → HARD_BLOCK (entry blocked)
|slope| ≥ cvd_slope_extreme (100)  → EXTREME (existing position: CVD Kill)
```

**CVD divergence detection**:

```
BULLISH DIVERGENCE:
  price makes lower low (bar_low < prev_bar_low)
  BUT cumulative_delta makes higher low (current_cvd > prev_bar_cvd)
  → Smart money buying into price weakness → bullish signal

BEARISH DIVERGENCE:
  price makes higher high (bar_high > prev_bar_high)
  BUT cumulative_delta makes lower high (current_cvd < prev_bar_cvd)
  → Smart money selling into price strength → bearish signal
```


***

### P0 Component 2: TradingSession Decomposition

**Target**: `trading_session.py` becomes a pure tick router — ~150 lines. Everything it currently owns that belongs elsewhere moves to the correct owner.

#### Responsibility Allocation Map

| Responsibility | Current Owner | Correct Owner |
| :-- | :-- | :-- |
| Tick routing to AMT | `trading_session.py` | stays (router job) |
| Session start/stop lifecycle | `trading_session.py` | `session_state_manager.py` (already exists) |
| Risk halt check | `trading_session.py` | `session_risk_coordinator.py` (already exists) |
| Event publishing | `trading_session.py` | `session_event_logger.py` (already exists) |
| Gate evaluation | `trading_session.py` | `entry_gate_coordinator.py` (already exists) |
| LLM entry invocation | `trading_session.py` + `llm_entry_handler.py` | Removed from sync path entirely |
| Position exit check | `trading_session.py` | `exit_coordinator.py` (already exists) |
| Metric recording | not done | `MetricsRegistry` (Phase -1) |

#### TradingSession Tick Processing Sequence (exact order)

```
ON EVERY TICK:
  1. Record tick receipt timestamp (for latency metric)
  2. AMTHandler.on_tick(tick) → produces AMTResult
  3. ExitCoordinator.check_all_positions(tick, amt_result) → may close positions
  4. IF SessionRiskCoordinator.is_halted() → STOP, return
  5. IF NOT tick.is_bar_close → STOP, return (entry only on bar close)
  6. EntryGateCoordinator.evaluate(amt_result, tick) → Signal | None
  7. IF Signal: put onto signal_bus (async, non-blocking)
  8. IF flag.llm_pre_candle_advisory: fire advisory task (fire-and-forget, async)
  9. Record latency = now - step 1 timestamp → MetricsRegistry
```


***

### P0 Component 3: LLM Role Separation

**Current problem**: `llm_entry_handler.py` (983 lines) mixes four distinct concerns.[^1]

#### Three Distinct LLM Services (replace one god handler)

```
LLMAdvisoryService (replaces llm_entry_handler.py)
  ├── PreCandleAdvisor
  │     Trigger: T-60s before 5-min bar close (bar minute 4:00)
  │     Output: scenario_narrative, expected_setup, key_levels
  │     Consumer: React dashboard ONLY — not any gate
  │     Timeout: 12s (non-blocking — missed = no advisory, not an error)
  │     Temperature: 0.3
  │     Max tokens: 80
  │
  ├── PositionOverseer (currently llm_overseer_handler.py — keep as-is)
  │     Trigger: PositionOpened event → every ~3s while position open
  │     Output: HOLD | TIGHTEN_SL | PARTIAL_EXIT | FULL_EXIT | ADD
  │     Timeout: 15s (non-blocking — missed = HOLD by default)
  │     Temperature: 0.3
  │     Max tokens: 120
  │
  └── PostTradeAnalyst
        Trigger: PositionClosed event
        Output: trade_quality_score, mistake_identified, improvement_note
        Timeout: 30s (non-blocking — trade already closed, no rush)
        Temperature: 0.25
        Max tokens: 150
```

**The rule**: `llm_entry_gate` feature flag is hardcoded `false` in all environments. Not configurable. Not overridable. The 15-second latency is permanently incompatible with entry gating.[^1]

***

### P0 Component 4: PaperBroker Cost Model

**Current**: 0.05% slippage, zero commission — produces optimistically false PnL.[^1]

#### Realistic Cost Model per Instrument Type

**Cost components per round trip (entry + exit)**:


| Component | Formula | Notes |
| :-- | :-- | :-- |
| Slippage | `notional × slippage_bps / 10000` | Directional: added on buy, subtracted on sell |
| STT | `notional × 0.000625` | On SELL side only for options |
| Exchange fee | `notional × 0.000495 × 2` | Both sides |
| Brokerage | `₹20 × 2` | ₹20 per order × 2 orders |
| GST on brokerage | `brokerage × 0.18` | 18% on brokerage only |
| SEBI charges | `notional × 0.000001 × 2` | Both sides |

#### Slippage Basis Points by Contract Type (from paper.yaml cost_model)

| Contract Type | Slippage BPS | Rationale |
| :-- | :-- | :-- |
| NIFTY ATM CE/PE | 15 bps | Deep liquid — tight spread |
| NIFTY OTM-1 | 25 bps | Slightly wider spread |
| NIFTY OTM-2 | 40 bps | Thinner book |
| BANKNIFTY ATM | 20 bps | High volume but volatile spread |
| BANKNIFTY OTM-1 | 35 bps |  |
| FINNIFTY ATM | 30 bps | Lower liquidity index |
| MCX CRUDEOIL | 10 bps | Futures — tight spread |
| MCX GOLD | 8 bps | Most liquid MCX commodity |
| MCX NATURALGAS | 12 bps |  |

**ATM vs OTM classification**: Based on `moneyness_pct` from SymbolConfig.

- ATM: `|strike - spot| / spot ≤ 0.5%`
- OTM-1: `0.5% < |strike - spot| / spot ≤ 1.0%`
- OTM-2: `|strike - spot| / spot > 1.0%`

***

### P0 Exit Criteria

```
[ ] amt_analyzer.py ≤ 200 lines (pure orchestrator)
[ ] VolumeProfileComputer independent, fully unit-tested (POC, VAH, VAL accuracy)
[ ] LVNDetector independent, fully unit-tested (persistence, removal, strength score)
[ ] CVDTracker independent, fully unit-tested (slope formula, divergence detection)
[ ] TickDeltaClassifier independent, fully unit-tested (quote rule, tick rule, edge cases)
[ ] trading_session.py ≤ 200 lines (pure tick router)
[ ] llm_entry_handler.py DELETED — replaced by 3 focused advisory services
[ ] PaperBroker reports full cost model — paper PnL drops to realistic level
[ ] MetricsRegistry records delta accuracy — logs mean MAE on Gaussian vs Lee-Ready
[ ] Zero references to constants.py anywhere (completed in Phase -1, verified here)
[ ] All 950+ tests pass + new tests for decomposed components
[ ] Target test count: 1100+
[ ] Forward paper test PnL shows realistic (lower) numbers — verified and accepted
```


***
***

# PHASE 1 — "Parallel Engine"

## True Multi-Symbol Concurrent Execution

### Duration: 8 Days | Requires: Phase 0 complete


***

### The Core Problem

The current `engine.py` runs one `TradingSession` which processes all symbols sequentially behind a single `threading.RLock`. During 09:15–09:45 NSE open, all 7 symbols generate ticks simultaneously — they queue behind each other. BANKNIFTY waits for NIFTY to finish, FINNIFTY waits for BANKNIFTY.[^1]

**Target**: 7 symbols fire independently. NIFTY's 300ms AMT computation does not delay BANKNIFTY's tick from being processed.

***

### P1 Component 1: Session Architecture

#### Ownership Model

```
GlassyTradeEngine (1 instance)
  │
  ├── Per-symbol Sessions (7 instances — fully independent)
  │   ├── NiftySession        → own AMTAnalyzer, own GatePipeline, own AgentPipeline
  │   ├── BankNiftySession    → own AMTAnalyzer, own GatePipeline, own AgentPipeline
  │   ├── FinNiftySession     → own instances
  │   ├── CrudeOilSession     → own instances
  │   ├── NaturalGasSession   → own instances
  │   ├── GoldSession         → own instances
  │   └── SilverSession       → own instances
  │
  ├── Signal Bus (shared asyncio.Queue, maxsize=50)
  │   Signals from all sessions flow here
  │
  ├── PortfolioCoordinator (1 instance — ONLY cross-symbol logic)
  │   Reads from Signal Bus
  │   Makes portfolio-level decisions
  │   Routes approved signals to Broker
  │
  ├── Portfolio Aggregate (shared read — sessions read but never write)
  │
  └── Broker Adapter (shared — one connection, used by PortfolioCoordinator only)
```


#### The Critical Rule

**Sessions never write to Portfolio.** They produce `Signal` objects and put them on the signal bus. Only `PortfolioCoordinator` writes to Portfolio. This eliminates all race conditions without any locks.

***

### P1 Component 2: Concurrency Model

**Technology choice**: `asyncio` (not threading, not multiprocessing)

**Rationale**:

- All I/O (WebSocket ticks, REST API calls, DB writes) is already async via `websockets` library[^1]
- `asyncio.Lock` is non-blocking within one event loop (vs `threading.RLock` which blocks)
- Each session is a coroutine — lightweight, no OS thread per symbol
- `asyncio.Queue` for signal bus — thread-safe by design, no locks needed

**Concurrency topology**:

```
asyncio event loop (single thread, cooperative multitasking)
│
├── session_NIFTY coroutine          → runs on each tick, yields between ticks
├── session_BANKNIFTY coroutine      → independent, no shared mutable state
├── session_FINNIFTY coroutine
├── session_CRUDEOIL coroutine
├── session_NATURALGAS coroutine
├── session_GOLD coroutine
├── session_SILVER coroutine
├── portfolio_coordinator coroutine  → awaits signal_bus.get()
├── watchdog coroutine               → monitors for crashed sessions
└── api_server coroutine             → FastAPI (uvicorn, already async)
```

**Why this works**: asyncio switches between coroutines only at `await` points. When a session is doing CPU-bound AMT computation (non-blocking), it runs to completion before yielding. This is correct — AMT computation is <5ms, so the starvation risk is minimal.

***

### P1 Component 3: PortfolioCoordinator Signal Rules (exact sequence)

```
FOR EACH signal received from signal_bus:

  RULE-1: MAX_POSITIONS check
    IF portfolio.open_count() >= 5 → REJECT, log "MAX_POSITIONS"
  
  RULE-2: PORTFOLIO_NOTIONAL check
    IF portfolio.total_notional() / capital > 0.60 → REJECT, log "NOTIONAL_CAP"
  
  RULE-3: SYMBOL_NOTIONAL check
    IF portfolio.symbol_notional(signal.underlying) / capital > 0.20 → REJECT
  
  RULE-4: DAILY_LOSS check
    IF risk_engine.daily_loss_pct() >= max_daily_loss_pct → REJECT, log "DAILY_HALT"
  
  RULE-5: CORRELATION_GUARD (enabled via feature flag)
    IF short_signals_enabled AND correlation_guard:
      NIFTY / BANKNIFTY / FINNIFTY are correlated (NSE index family)
      RULE: Never hold NIFTY + BANKNIFTY in SAME direction simultaneously
      RULE: Never hold NIFTY + FINNIFTY in SAME direction simultaneously
      IF correlated open position exists in same direction → REJECT
  
  IF all rules pass → route to BrokerAdapter.execute(signal)
```


***

### P1 Component 4: Session-to-Session Independence Contract

These are the rules that **guarantee** no cross-symbol interference:

```
PERMITTED (per-session, private):
  ✅ Own AMTAnalyzer instance
  ✅ Own VolumeProfileComputer
  ✅ Own CVDTracker, TickDeltaClassifier
  ✅ Own AgentPipeline (own LightGBM model loaded per symbol)
  ✅ Own GatePipeline instance
  ✅ Own session-level metrics
  ✅ Own asyncio.Lock (internal, never shared)

READ-ONLY shared (safe, no mutation):
  ✅ SystemConfig (frozen dataclass — immutable)
  ✅ Portfolio.open_positions (read-only view)
  ✅ MetricsRegistry (append-only, thread-safe)

WRITE shared (ONLY PortfolioCoordinator may write):
  🔒 Portfolio aggregate
  🔒 BrokerAdapter (single connection)
  🔒 Database writes (session writes to own partition only)
```


***

### P1 Component 5: Storage Upgrade — SQLite → DuckDB

**Trigger**: feature flag `duckdb_storage: true`

**Why DuckDB**:

- SQLite write-lock: only one writer at a time. With 7 concurrent sessions all writing ticks, sessions wait for the lock → defeats parallelism
- DuckDB: columnar engine, append-only write model, no write locks for concurrent appenders
- DuckDB 10-100× faster for VP analytics queries (session summaries, SHAP computations)
- DuckDB supports Parquet export natively → future backtesting data store

**Schema design principles**:

- **Partitioned by date**: `ticks` table partitioned by day → yesterday's data never touched during live session
- **Append-only for ticks**: never update tick records — immutable audit trail
- **Position events as event stream**: every state change persisted → full replay capability
- **Per-symbol isolation**: queries always include `WHERE symbol = ?` — no cross-symbol table scans

**Migration strategy**:

```
STEP 1: Run DuckDB alongside existing SQLite (feature flag false = SQLite)
STEP 2: On next paper session start with flag true: create DuckDB, run schema
STEP 3: No data migration needed — paper data is ephemeral, starts fresh
STEP 4: SQLite adapter kept in codebase but unused (fallback for development env)
```


***

### P1 Component 6: Watchdog Specification

A crashed session must not silently fail — trades may be open.[^1]

**Watchdog checks every 30 seconds**:

```
FOR each session task:
  IF task.done() AND NOT task.cancelled():
    error = task.exception()
    IF error is not None:
      LOG CRITICAL: session_crashed, symbol, error, timestamp
      ALERT via /api/alerts endpoint (React dashboard shows red banner)
      IF open positions exist for that symbol:
        EMERGENCY: route all open positions for that symbol through ExitCoordinator
        Exit at market — do not leave orphaned positions
      SCHEDULE restart: wait 5s, restart session (max 3 restarts per session per day)
      IF restart count > 3: do not restart, require manual intervention
```


***

### P1 Exit Criteria

```
[ ] feature flag parallel_symbol_sessions: true activates multi-session engine
[ ] 7 symbols process independently — verified by running all 7 and checking tick timestamps
[ ] No tick loss during NSE open window (09:15–09:45) — measured via latency tracker
[ ] PortfolioCoordinator applies all 5 cross-symbol rules correctly (tested)
[ ] Correlation guard tested: NIFTY long blocked when BANKNIFTY long already open
[ ] DuckDB active (duckdb_storage: true) — SQLite no longer written during live session
[ ] Watchdog recovers from simulated session crash (inject artificial error in test)
[ ] All 1100+ tests pass + new concurrency tests
[ ] Target test count: 1250+
[ ] Latency p95 < 20ms per symbol during 7-symbol paper run
```


***
***

# PHASE 2 — "Bilateral + Dynamic Risk"

## SHORT/PE Signals + Risk Tier A/B/C + Initial Balance Engine

### Duration: 10 Days | Requires: Phase 1 complete


***

### P2 Component 1: SHORT Signal Logic

**Current gap**: `fp_short.txt` and `mfe_short_q50.txt` are loaded but the entry gate has a hard LONG-only filter. This blocks ~40% of valid setups.[^1]

#### SHORT Signal Gate Additions (add after existing 12 gates)

```
GATE S1 — SHORT DIRECTION ALLOWED check:
  IF feature_flag.short_signals_enabled = false → REJECT all SHORT signals
  (This flag is the kill switch — flip to enable without code change)

GATE S2 — SHORT MARKET STATE check:
  Valid SHORT states:
    IMBALANCED + displacement_direction = DOWN → Trend SHORT
    BALANCED + failed_breakout = UP (above VAH, reclaimed inside) → MR SHORT
  Any other state → REJECT SHORT

GATE S3 — SHORT ML PROBABILITY check:
  ML threshold for SHORT is higher than LONG (India upward bias):
    imbalance_continuation SHORT: P(short) ≥ 0.58 (vs 0.55 for long)
    return_to_value SHORT:         P(short) ≥ 0.51 (same as long)
    probing_breakout SHORT:        P(short) ≥ 0.58 (same as long)

GATE S4 — SHORT AGGRESSION DIRECTION check:
  aggression must come from SELLERS, not buyers
  footprint: ask_volume > bid_volume (selling pressure)
  CVD slope: negative (sellers in control)
  delta_normalized: negative value

GATE S5 — SHORT CONTRACT TYPE check:
  SHORT signal → must select PE option (not CE)
  VP Contract Selector already supports BEARISH → PE selection
  Remove bullish-only CE bias (+25 points) from option_scanner scoring
  Add equivalent PE bias (+25 points) when direction = SHORT
```

**SHORT Target Formula**:

- Trend SHORT: $TP = VAL_{new} - (POC_{new} - VAL_{new})$
- Mean Reversion SHORT: TP = POC of original balance area
- Stop: just above the failed high (for MR) or above LVN retest (for trend)

***

### P2 Component 2: Risk Tier Engine

**Fabio's exact A/B/C model** — currently completely absent from the system:[^1]

#### Tier Definitions

| Tier | Risk Per Trade | Unlock Condition | Lock Condition |
| :-- | :-- | :-- | :-- |
| HALT | 0% | — | 3 consecutive losses |
| C | 0.15% of capital | Session start (always) | Downgrade on 3 losses |
| B | 0.25% of capital | Daily P\&L ≥ +1R | Downgrade if daily < +1R |
| A | 0.45% of capital | Daily P\&L ≥ +3R AND setup quality = premium | Downgrade if daily < +2R |

#### Tier State Machine

```
SESSION START:
  tier = C (always — protect capital at start)
  daily_pnl_r = 0.0
  consecutive_losses = 0

ON TRADE CLOSED with result pnl_r:
  consecutive_losses = consecutive_losses + 1 IF pnl_r < 0 ELSE 0
  daily_pnl_r += pnl_r
  
  IF consecutive_losses >= 3:
    tier = HALT
    publish SessionHaltedEvent (3 consecutive losses)
  ELIF daily_pnl_r >= 3.0:
    tier = A (only if current setup qualifies as premium — see below)
  ELIF daily_pnl_r >= 1.0:
    tier = B
  ELSE:
    tier = C

TIER A PREMIUM SETUP REQUIREMENTS (ALL must be true):
  aggression_score >= 3.5
  lvn_strength >= 0.85
  cvd_divergence = true
  drive = D2 (not first drive)
  india_vix between 15 and 22 (not too calm, not too volatile — Phase 3 feature)
  ml_probability >= 0.65

DAILY RESET:
  Called at session close (15:15 NSE / 23:15 MCX)
  Reset: daily_pnl_r = 0.0, consecutive_losses = 0
  Tier resets to C at next session open
```


#### Integration with SizingAgent

```
CURRENT SizingAgent: uses fixed Kelly formula → uniform risk per trade
TARGET SizingAgent: uses RiskTierEngine → dynamic risk per trade

Risk amount = capital × RiskTierEngine.risk_pct_for_current_tier()

IF tier = HALT: return 0 (no trade)
IF tier = C:    risk_amount = capital × 0.0015
IF tier = B:    risk_amount = capital × 0.0025
IF tier = A:    risk_amount = capital × 0.0045

Lot size formula (unchanged):
lot_size = floor(risk_amount / (stop_distance_ticks × tick_value × symbol_lot_size))
```


***

### P2 Component 3: Initial Balance Engine

**Currently absent** — needed for both structural setups and IB breakout scalps (Phase 4).

#### IB Computation

```
IB Build Window:
  NSE: 09:15–09:45 (first 30 minutes — first 6 candles of 5-min chart)
  MCX: 09:00–09:30

IB_HIGH = highest high of all bars within build window
IB_LOW  = lowest low of all bars within build window
IB_MID  = (IB_HIGH + IB_LOW) / 2
IB_WIDTH = IB_HIGH - IB_LOW

IB complete: true after first bar post-window

IB normal width reference (per symbol):
  NIFTY:     90–120 pts = normal, < 60 = narrow, > 180 = wide
  BANKNIFTY: 200–280 pts = normal, < 120 = narrow, > 400 = wide
  CRUDEOIL:  80–120 pts = normal
```


#### IB Price Location Classification

```
classify_price_vs_ib(current_price):
  IF NOT ib_complete → return IB_BUILDING
  IF current_price > IB_HIGH → return ABOVE_IB
  IF current_price < IB_LOW  → return BELOW_IB
  ELSE                        → return INSIDE_IB
```


#### IB Feature Addition (adds to feature vector in Phase 3)

```
ib_location:       0 = INSIDE, 1 = ABOVE, -1 = BELOW, null = BUILDING
ib_width_pct:      IB_WIDTH / (session ATR(5) × spot) — normalized
ib_position_pct:   (price - IB_LOW) / IB_WIDTH — 0% = at low, 100% = at high
```


***

### P2 Exit Criteria

```
[ ] short_signals_enabled: true activates SHORT/PE entries end-to-end
[ ] SHORT signal tested on all 3 playbooks (imbalance, return_to_value, probing)
[ ] PE contract selected correctly (not CE) when direction = SHORT
[ ] RiskTierEngine state machine correct: C→B→A progression, HALT on 3 losses
[ ] Tier A only activates when ALL premium setup requirements met
[ ] SizingAgent uses RiskTierEngine risk amount (not fixed Kelly)
[ ] InitialBalanceEngine computes IB_HIGH, IB_LOW, IB_MID for all 7 symbols
[ ] IB_WIDTH within normal range logged per symbol per session
[ ] PortfolioCoordinator correlation_guard active for SHORT+LONG mix
[ ] All 1250+ tests pass + bilateral tests, tier engine tests
[ ] Target test count: 1450+
[ ] Paper forward test shows SHORT signals firing correctly on BALANCED failed-breakout setups
```


***
***

# PHASE 3 — "Intelligence Upgrade"

## ML Validation + IV/VIX/PCR + LLM Restructure

### Duration: 12 Days | Requires: Phase 2 complete


***

### P3 Component 1: Walk-Forward ML Validation

**Non-negotiable before live broker activation**. Without this, all ML probability estimates are based on unvalidated models.[^1]

#### Walk-Forward Protocol

```
DATA REQUIREMENTS:
  Minimum 6 months NSE 5-min OHLCV with order flow
  Minimum 3 months MCX 5-min OHLCV with order flow
  Source: DhanHQ Historical API
  Label generation: target = 1 if TP hit before SL, 0 if SL hit first

WALK-FORWARD PARAMETERS:
  Training window:  3 months (66 trading days × 78 bars = 5,148 bars)
  Test window:      1 month  (22 trading days × 78 bars = 1,716 bars)
  Step size:        1 month  (roll forward 1 month per iteration)
  Minimum iterations: 3 (need 6 months data for 3 walk-forward windows)

PER ITERATION — TRAIN:
  Features: 42-feature vector (41 after duplicate removal from Phase 0)
  Target: binary — TP hit before SL
  Imbalance handling: class_weight = {0: 1, 1: ratio_of_negatives_to_positives}
  Calibration: Platt scaling on held-out validation split (20% of train)
  
PER ITERATION — TEST:
  Compute: accuracy, precision, recall, F1 at threshold 0.55/0.58
  Compute: Brier score (calibration quality)
  Compute: profit factor (simulated trades at threshold)
  Compute: top-10 features by SHAP mean absolute value
  
ACCEPTANCE CRITERIA (model considered valid):
  Long model: precision ≥ 0.58 across ALL iterations (not just average)
  Short model: precision ≥ 0.60 across ALL iterations
  Profit factor ≥ 1.4 across ALL iterations
  Brier score < 0.22 (well-calibrated probabilities)
  
REJECTION: If ANY iteration fails → model not live-ready
  Action: collect more data, add features, or adjust thresholds
```


#### SHAP Feature Pruning

```
AFTER walk-forward completes:
  Compute SHAP values on test set for each iteration
  Feature importance = mean(|SHAP_values|) per feature per iteration
  Average importance across all iterations
  
PRUNE features where: mean_importance < 0.001 (noise contributors)
  
EXPECTED PRUNING:
  market_state_encoded (duplicate — appears in 4a AND 4d) → REMOVE from 4a
  Potentially: profile_shape_encoded (if encoding is ordinal — replace with dummies)
  
Target: reduce from 41 features to 35-38 high-signal features
```


***

### P3 Component 2: New Features — IV / VIX / PCR

**Currently absent but critical for options trading**. Without volatility regime features, the ML model is blind to the most important options-specific dimension.[^1]

#### India VIX Feature

**Source**: NSE VIX index (symbol: `INDIA VIX`, available via DhanHQ)

```
india_vix_raw:          raw VIX value (typically 10–35 for NIFTY)
india_vix_normalized:   india_vix / 20.0   (20 = long-run average)

vix_regime (categorical):
  VIX < 12:      regime = 0  (LOW — cheap options, avoid buying premium)
  12 ≤ VIX < 18: regime = 1  (NORMAL — standard conditions)
  18 ≤ VIX < 25: regime = 2  (ELEVATED — good for buying premium)
  VIX ≥ 25:      regime = 3  (SPIKE — reduce size, widen stops 1.5×)
```

**Impact on system**:

- `vix_regime = 0 (LOW)`: tighten ML threshold to 0.60 (harder to pass), reduce size 20%
- `vix_regime = 3 (SPIKE)`: block Tier A entry, force Tier C max, widen SL by 1.5×


#### IV Rank Feature

**Source**: Computed from 20-day IV history per underlying (from DhanHQ option chain)

$$
\text{IV\_Rank} = \frac{\text{IV\_current} - \text{IV\_20d\_min}}{\text{IV\_20d\_max} - \text{IV\_20d\_min}} \times 100
$$

```
iv_rank range: 0-100
  < 25:  low IV → options cheap → prefer buying options
  25-75: normal IV
  > 75:  high IV → options expensive → wider TP targets needed
```


#### IV Percentile Feature

$$
\text{IV\_Percentile} = \frac{\text{count of days where IV}_{d} < \text{IV\_current}}{20} \times 100
$$

Differs from IV Rank: percentile measures distribution, not range position.

#### PCR Feature

**Source**: NSE Option Chain via DhanHQ (PUT OI / CALL OI per underlying)

```
pcr_oi = total_put_oi / total_call_oi   (for NIFTY/BANKNIFTY/FINNIFTY)

pcr_signal_normalized = (pcr_oi - 0.95) / 0.95   (0 = neutral baseline)

Interpretation (contrarian):
  PCR > 1.2:  extreme put buying → contrarian BULLISH (market oversold)
  PCR < 0.7:  extreme call buying → contrarian BEARISH (market overbought)
  PCR 0.8-1.1: neutral zone
```


#### Total Feature Count After Phase 3

```
Phase 0 features:   41 (42 - 1 duplicate removed)
Phase 3 additions:  +6 (india_vix_normalized, vix_regime, iv_


<div align="center">⁂</div>

[^1]: AMT_ARCHITECTURE_INTAKE.md```

