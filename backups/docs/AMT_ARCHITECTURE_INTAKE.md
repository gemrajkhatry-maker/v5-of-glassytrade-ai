# AMT TRADING SYSTEM — ARCHITECTURE & PERFORMANCE INTAKE

**Based on Fabio Valentini's AMT / Volume Profile / Order Flow**

---

## 1. PROJECT OVERVIEW

- **Project Name**: GlassyTrade AI
- **Project Stage**: [ ] POC [x] Development [x] Live Paper
- **Target Market(s)**: NSE Index Options (NIFTY, BANKNIFTY, FINNIFTY), MCX Commodities (CRUDEOIL, NATURALGAS, GOLD, SILVER)
- **Target Session(s)**: NSE: 09:15–15:15 IST | MCX: 09:00–23:15 IST
- **Primary Goal**: Hybrid — signal generation + auto-execution (paper broker), overseer manages open positions via LLM
- **Team Size & Roles**: 1 (full-stack AI trader — Ishanvi Technologies)

---

## 2. FABIO VALENTINI AMT CONCEPTS IMPLEMENTED

**[x] Market State Classification (Balance vs Imbalance)**
→ 4-state model: NO_TRADE (±2 ticks of POC), BALANCED (inside VA), IMBALANCED (outside VA + displacement + acceptance), PROBING (outside VA, no displacement). Rule-based in `market_state_engine.py:45-128`. Displacement = 3+ consecutive directional candles with 1.5× range expansion.

**[x] Volume Profile Levels — POC, VAH, VAL**
→ 200-bucket uniform histogram, incremental updates per tick. POC = max-volume bucket (VWAP tie-break). VAH/VAL = CME two-row pairs method expanding 70% of total volume from POC. `amt_analyzer.py:115-182, 1277-1333`.

**[x] Low-Volume Nodes (LVNs) Detection**
→ Smooth histogram (window=3), find local minima where volume ≤ 15% of mean. Must persist 3 consecutive bars before emitted. Removed when volume rises above 30% of mean. `constants.py:6,65,66`.

**[x] Order Flow — Delta / CVD Analysis**
→ CVD tracked as cumulative delta with 20-candle rolling slope. Hard block at |slope| ≥ 50.0, warning at 30.0, extreme at 100.0. Delta approximated from taker_buy_volume or candle close-vs-midpoint proxy. `constants.py:14-18`.

**[x] DeepTrades / Large Order Detection**
→ Aggressive prints detected when trade size ≥ 3× or 5× average volume. Clustering: ≥3 prints within 2 ticks of each other over ≤3-bar window. Aggression scorer: max 4.5 points (footprint +1.0, CVD +1.0, big trade +1.0, absorption +0.5, OFI +0.5, confluence +0.5). `aggression_scorer.py:1-242`.

**[x] Trend Model (Out-of-Balance Continuation)**
→ IMBALANCED market: entry at LVN with aggression confirmation, target = VAH + (VAH - POC) for LONG. SL at aggressive print cluster. 1.25× position size multiplier. `entry_gate.py:479-714`.

**[x] Mean Reversion Model (Failed Breakout → Back to Balance)**
→ BALANCED market: failed breakout with opposing aggression → reclaim inside VA → entry with target = POC. `amt_analyzer.py:1940-1978`.

**[x] Triple-A Setup (Location + Timing + Absorption)**
→ Three-align gate: Market State + Location (LVN/VA boundary) + Aggression — ALL THREE must align. Absorption quantified as: range < ATR×0.3 AND volume > avg×2. `entry_gate.py:156-333`, `constants.py:23-24`.

**[x] 70% Value Rule**
→ CME two-row pairs method: start at POC, expand 2 rows at a time above/below, stop when 70% of total volume captured. `amt_analyzer.py:1288-1333`.

**Other custom extensions**:
- LVN Play: highest conviction setup requiring 2/3 of velocity spike, rejection candle, delta flip
- VWAP trail at 1.5R with 2σ tighten
- 3-partition exit (P1@33%R, P2@TP, P3 trail)
- CVD kill signal → immediate breakeven or scratch

---

## 3. DATA ARCHITECTURE

### 3a. Data Sources

- **Tick / L2 Order Book Feed**: DhanHQ WebSocket (full packet), REST polling fallback for MCX OPTFUT. ~50-100ms latency.
- **OHLCV Candle Data**: DhanHQ REST API, 5-minute candles, 500-bar lookback per symbol.
- **Volume Profile Data**: Computed in real-time via incremental volume profile (200 buckets). Rolling window: current session candles only.
- **Order Flow / Footprint Data**: Gaussian volume distribution across candle range using VWAP as mean. Bid/ask imbalance detection (3:1 ratio threshold).

### 3b. Data Pipeline

- **Ingestion**: Dhan WebSocket (MCX_COMM/NSE_OPT segments) → asyncio event loop → `DhanMarketDataAdapter`
- **Storage**: SQLite (open_positions, position_events, trades, session_profiles, kv_store)
- **Processing**: In-memory, single-threaded tick processor with RLock for portfolio mutations
- **Real-time vs Batch**: All real-time. No batch processing.

---

## 4. FEATURE ENGINEERING

### 4a. Volume Profile Features (6)
`profile_shape_encoded`, `balance_ratio`, `va_width_pct`, `market_state_encoded`, `hvn_count`, `nearest_lvn_distance_pct`

### 4b. Order Flow Features (8)
`delta_normalized`, `cvd_slope`, `cvd_divergence_flag`, `aggression`, `volume_vs_ema20`, `delta_acceleration`, `cumulative_delta_3bar`, `aggressive_print_imbalance`

### 4c. Price Action Features (12)
`close_vs_poc`, `close_vs_vah`, `close_vs_val`, `close_vs_vwap_pct`, `atr_5`, `atr_20`, `atr_ratio`, `bar_range_pct`, `body_pct`, `upper_wick_ratio`, `lower_wick_ratio`, `close_position_in_range`

### 4d. Market State Features (6)
See 4a + `market_state_encoded`

### 4e. Time / Session Features (4)
`minutes_since_open`, `session_flag`, `day_of_week`, `bars_since_last_displacement`

### 4f. Order Book Features (6)
`bid_ask_spread_bps`, `book_imbalance_l1`, `book_imbalance_l5`, `bid_depth_total`, `ask_depth_total`, `book_pressure_ratio`

### 4g. Options-Specific Features (6)
`oi_change_pct`, `option_type_flag`, `underlying_return_5bar`, `moneyness_pct`, `dte_normalized`, `oi_volume_ratio`

### 4h. Total Feature Count: 42
### 4i. Feature Selection: Domain-driven (Fabio AMT manual), no automated feature selection

---

## 5. ML MODEL ARCHITECTURE

### 5a. Model(s) Used
- **Model Type**: LightGBM (Gradient Boosted Decision Trees)
- **Framework**: LightGBM via `lgbm_probability_adapter.py`
- **Input**: 42-feature vector
- **Output**: P(target hit before stop) for LONG/SHORT, predicted median MFE for dynamic TP

### 5b. Training Setup
- **Models loaded**: `fp_long.txt`, `fp_short.txt`, `mfe_long_q50.txt`, `mfe_short_q50.txt` + optional Platt scaling calibrators
- **Validation**: Walk-forward (recommended)
- **Calibration**: Platt scaling on validation set

### 5c. Inference
- **Latency**: <1ms per prediction
- **Runs**: Real-time on each new candle (5-minute bars)
- **Confidence threshold**: P ≥ 0.55 for entry (varies by playbook)

---

## 6. LLM FINE-TUNING DETAILS

- **Base Model**: Qwen-based fine-tuned model (`glassytrade-qwen-mlx-fused`) via MLX backend
- **Reasoning Model**: `Qwen3.5-4B-Claude-4.6-Opus-Reasoning-Distilled`
- **Fine-tuning Method**: LoRA adapters, prompt engineering
- **Temperature**: Entry=0.4, Overseer=0.3, Max tokens=120, Timeout=15s

- **LLM Role in the System**:
  - [x] Market state reasoning (balance/imbalance classification)
  - [x] Trade setup verbalization / explanation
  - [x] Signal confirmation layer
  - [x] Risk narrative generation
  - [x] Post-trade analysis (overseer)

- **LLM Prompt Template**: 9-section structured prompt with session context, market state, price location, order flow, VWAP, warnings, order book, quant engine probability, and Fabio's 6 canonical rules. See `prompt_builder.py:46-380`.

- **LLM Output Format**: JSON with `direction`, `rationale`, `confidence`, `market_state`
- **LLM Latency**: 15s timeout, runs on new candle boundaries (~5-15 min frequency)

---

## 7. SIGNAL GENERATION LOGIC

- **Signal Types**: LONG only (SHORT disabled — BUY-only mode)
- **Setup Classification**: TREND_MODEL, MEAN_REVERSION, PROBING_ACCEPTANCE, PROBING_REJECTION

### Signal Flow
1. Tick received → AMT analysis (VP, aggression, CVD)
2. Agent pipeline: RegimeAgent → DirectionAgent (LightGBM) → TimingAgent → SizingAgent (Kelly)
3. Entry gate pipeline: 12-gate validation
4. Three-align check: Market State + Location + Aggression must all align
5. Confirmation bundle: Volume Impulse (mandatory) + Delta Pressure + Spread Tightness (need 2/3)
6. Second drive enforcement: D1 rejected for trend setups
7. Build signal: SL/TP from aggressive print cluster, VWAP, ATR floor
8. Execute via broker

### Minimum confluence
Three-align + confirmation bundle + P ≥ 0.55

### Confidence scoring
Aggression scorer (max 4.5 points) + gate pipeline (12 gates)

---

## 8. TRADE EXECUTION

- **Execution Mode**: Fully automated (paper broker), signal-only (live broker not yet activated)
- **Broker**: DhanHQ API (MCX_COMM, NSE_OPT segments)
- **Order Types**: MARKET entry, STOP_LOSS_MARKET SL
- **Slippage**: 0.05% assumed
- **Order routing**: Async via DhanHQ REST API

---

## 9. RISK MANAGEMENT

- **Position Sizing**: Half-Kelly criterion, conservative cap 0.25% until 30+ trades
- **Max risk per trade**: 0.5%
- **Max daily drawdown**: 2% from peak equity
- **Stop Loss**: Beyond aggressive print cluster + ATR floor (min 1.5% of price or ATR(14))
- **Take Profit**: POC (mean-reversion) or VAH + (VAH - POC) (trend)
- **Circuit breaker**: 3 consecutive losses = session halt
- **Max concurrent positions**: 5
- **Portfolio notional cap**: 60% of equity

---

## 10. BACKTESTING & PERFORMANCE METRICS

- **Backtesting Framework**: Custom (live paper trading)
- **Backtested Date Range**: N/A (forward test only)
- **Commission & slippage**: 0.05% slippage assumed, no commission

### Key Metrics (forward testing in progress)

| Metric | Value |
|--------|-------|
| Total Trades | TBD (forward testing) |
| Win Rate (%) | TBD |
| Average Win / Loss | TBD |
| Profit Factor | TBD |
| Sharpe Ratio | TBD |
| Max Drawdown (%) | 2% (circuit breaker) |
| Avg R:R Ratio | 1.5–2.2 (playbook-dependent) |
| Best Month | TBD |
| Worst Month | TBD |
| ML Signal Accuracy (%) | TBD |
| LLM Confirmation Acc(%) | TBD |

---

## 11. SYSTEM ARCHITECTURE DIAGRAM

```
┌─────────────┐    WebSocket     ┌──────────────┐
│  Dhan API   │ ───────────────→ │ Tick Handler │
│  (MCX/NSE)  │                  └──────┬───────┘
└─────────────┘                         │
                                        ▼
                              ┌──────────────────┐
                              │   AMT Analyzer   │
                              │  VP · LVN · CVD  │
                              │  Aggression · OF │
                              └────────┬─────────┘
                                       │
                    ┌──────────────────┼──────────────────┐
                    ▼                  ▼                  ▼
           ┌────────────────┐ ┌───────────────┐ ┌────────────────┐
           │ Agent Pipeline │ │ LLM Entry     │ │ VP Selector    │
           │ Regime→Dir→    │ │ (advisory)    │ │ (contract      │
           │ Timing→Sizing  │ │ Qwen MLX      │ │  selection)    │
           └───────┬────────┘ └───────┬───────┘ └────────────────┘
                   │                  │
                   ▼                  ▼
           ┌──────────────────────────────┐
           │      Gate Pipeline (12)      │
           │  Three-Align · Confirm ·     │
           │  CVD Block · Drive · R:R     │
           └──────────────┬───────────────┘
                          │
                          ▼
           ┌──────────────────────────────┐
           │     Entry Coordinator        │
           │  Signal → Broker → Position  │
           └──────────────┬───────────────┘
                          │
                ┌─────────┼─────────┐
                ▼                   ▼
       ┌──────────────┐    ┌──────────────┐
       │ Trade Manager │    │ Overseer     │
       │ SL/TP/Trail   │    │ LLM monitor  │
       │ Partition Exit│    │ TIGHTEN/     │
       │ VWAP Trail    │    │ PARTIAL/EXIT │
       └──────────────┘    └──────────────┘
```

---

## 12. TECH STACK SUMMARY

- **Language(s)**: Python 3.14, TypeScript (React frontend)
- **Key Libraries**: FastAPI, Pydantic, LightGBM, NumPy, WebSocket (websockets), SQLite
- **MLX**: Apple MLX for local LLM inference
- **Infrastructure**: Local macOS (M-series), no cloud
- **Monitoring**: Custom React dashboard (http://localhost:5190/), structured JSON logging
- **Version Control**: Git

---

## 13. CURRENT BOTTLENECKS & PAIN POINTS

1. **LLM latency (15s timeout)**: Too slow for real-time decisions. Runs only on candle boundaries (5-min frequency) as compensation.
2. **No live broker activation**: Paper broker only. Dhan broker adapter exists but requires 10+ day forward test.
3. **Single-threaded tick processing**: All AMT + ML + gates run on one thread. Limits throughput to ~1 tick/second per symbol.
4. **MCX data availability**: Dhan doesn't have option chain data for CRUDEOIL, GOLD, SILVER (only NATURALGAS).
5. **No backtesting framework**: Forward-test only. Need proper walk-forward validation for ML model.

---

## 14. IMPROVEMENT GOALS

- [ ] Signal accuracy — reduce false entries, improve confluence quality
- [ ] Latency / speed — parallel tick processing for multi-symbol
- [x] LLM reasoning quality — fine-tuned Qwen with Fabio transcripts
- [ ] Feature engineering — add DTE decay, OI flow, PCR features
- [x] Risk-adjusted returns — Kelly sizing, dynamic SL%, partition exits
- [ ] Overfitting reduction — walk-forward validation, feature importance pruning
- [x] Live execution reliability — race condition fixes, reconciliation guards

---

**System status**: 855 tests passing, 0 failures. Both services running. Exchange: NSE.

---

## 15. CONTRACT SELECTION LOGIC

### 15a. Scanner Option Selection (momentum-based)

`option_scanner.py` — selects ATM options with score-based ranking:

```
Input: Underlyings from .env (e.g., "NIFTY,BANKNIFTY")
  ↓
For each underlying:
  1. Get option chain via Dhan API
  2. Find ATM strike (closest to spot)
  3. Scan strikes_around_atm=2 (ATM±2, i.e., 5 strikes total)
  4. For each CE/PE at each strike:
     a. Get LTP, OI, Volume from chain
     b. Filter: LTP > 0 AND OI ≥ MIN_OI
     c. Score = base_score + liquidity + momentum + spread_penalty
     d. Bullish-only filter: CE only (or PE with strike ≥ ATM)
  5. Group by underlying → take top 5 per underlying
  6. Global sort by score → take top 10 overall
  ↓
Output: List[ScanResult] — symbols to monitor
```

**Scoring formula** (`option_scanner.py:173-250`):

| Component | Calculation | Max Points |
|-----------|------------|-----------|
| Base | Always | 100.0 |
| ATM proximity | `-abs(strike-atm)/step*5` | -50.0 |
| Volume liquidity | `min(15, vol/1000)` | +15.0 |
| OI liquidity | `min(30, oi/min_oi*10)` | +30.0 |
| OI buildup | `if oi > avg*1.5` | +10.0 |
| Bullish bias (CE) | Always | +25.0 |
| Spread penalty | `if spread > 0.5%` | -20.0 |

**MIN_OI thresholds** (`option_scanner.py:48-55`):

| Underlying | MIN_OI |
|-----------|--------|
| NIFTY | 500,000 |
| BANKNIFTY | 300,000 |
| FINNIFTY | 50,000 |
| CRUDEOIL | 10 |
| NATURALGAS | 500 |
| GOLD | 1 |
| SILVER | 1 |

**STRIKE_INTERVALS** (`option_scanner.py:41-47`):

| Underlying | Step |
|-----------|------|
| NIFTY | 50 |
| BANKNIFTY | 100 |
| FINNIFTY | 50 |
| CRUDEOIL | 50 |
| NATURALGAS | 5 |
| GOLD | 100 |
| SILVER | 500 |

### 15b. VP Contract Selector (structure-based)

`vp_contract_selector.py` — selects contracts based on Volume Profile levels:

```
Input: Yesterday's OHLCV data (200 candles, 5-min)
  ↓
Step 1: Compute Volume Profile
  - 200-bucket histogram by close price
  - POC = max-volume bucket
  - VAH/VAL = 70% of total volume around POC (CME two-row pairs)
  - LVNs = buckets with volume < 15% of mean (gap zones)
  - HVNs = buckets with volume > 150% of mean (support/resistance)

Step 2: Classify Market State
  - BULLISH: price > VAH + threshold (50 pts for NIFTY)
  - BEARISH: price < VAL - threshold
  - BALANCE: price within VA ± threshold

Step 3: Select Contracts by State
  BULLISH:  LVN below price → CE, target=VAH, stop=HVN below LVN
  BEARISH:  LVN above price → PE, target=VAL, stop=HVN above LVN
  BALANCE:  Run both CE and PE selection

Step 4: R:R Filter
  R:R = (Target - Entry) / (Entry - Stop)
  Keep if R:R ≥ 2.5, discard otherwise

Step 5: Multi-Index
  Run for each index: NIFTY, BANKNIFTY, FINNIFTY
  Take top 2 per index by R:R
```

**VP Bucket Sizes** (`vp_contract_selector.py:100-108`):

| Index | Bucket Size |
|-------|------------|
| NIFTY | 10.0 |
| BANKNIFTY | 25.0 |
| FINNIFTY | 10.0 |
| CRUDEOIL | 10.0 |
| NATURALGAS | 1.0 |
| GOLD | 10.0 |
| SILVER | 25.0 |

**Imbalance Thresholds** (`vp_contract_selector.py:110-118`):

| Index | Threshold |
|-------|----------|
| NIFTY | 50.0 |
| BANKNIFTY | 100.0 |
| FINNIFTY | 50.0 |
| CRUDEOIL | 20.0 |
| NATURALGAS | 5.0 |
| GOLD | 50.0 |
| SILVER | 100.0 |


---

## 16. COMPONENT TREE & CLASS HIERARCHY

```
backend/
├── app/
│   ├── main.py                          # FastAPI + uvicorn entry
│   ├── config.py                        # Settings (Pydantic + env)
│   ├── domain/
│   │   ├── constants.py                 # Single source: thresholds
│   │   ├── models/
│   │   │   └── exchange_config.py       # ExchangeConfig (NSE/MCX)
│   │   ├── ports/                       # Hexagonal ports (ABC)
│   │   │   ├── market_data.py           # MarketDataPort
│   │   │   ├── broker.py                # BrokerPort
│   │   │   ├── llm_inference.py         # LLMInferencePort
│   │   │   ├── probability_inference.py # ProbabilityInferencePort
│   │   │   ├── storage.py               # StoragePort
│   │   │   ├── event_bus.py             # EventBusPort
│   │   │   └── exchange_strategy.py     # ExchangeStrategy
│   │   ├── services/
│   │   │   ├── symbol_registry.py       # Exchange↔symbol
│   │   │   └── tick_utils.py            # round_to_tick
│   │   ├── trading/
│   │   │   ├── models/
│   │   │   │   ├── entities.py          # Position, Signal, Trade
│   │   │   │   ├── aggregates.py        # Portfolio
│   │   │   │   ├── value_objects.py     # OHLC, AMTResult
│   │   │   │   └── enums.py             # Side, Source
│   │   │   └── events.py                # 13 domain events
│   │   ├── fabio_ai/
│   │   │   ├── services/
│   │   │   │   ├── amt_analyzer.py      # AMTAnalyzer (2063 lines)
│   │   │   │   ├── entry_gate.py        # Entry gate (12 gates)
│   │   │   │   ├── gate_pipeline.py     # OOP GateContext
│   │   │   │   ├── signal_coordinator.py # Signal evaluation
│   │   │   │   ├── option_scanner.py    # Momentum scanner
│   │   │   │   ├── vp_contract_selector.py # VP selector
│   │   │   │   ├── trade_manager.py     # Position lifecycle
│   │   │   │   ├── partition_exit_manager.py # P1/P2/P3 exits
│   │   │   │   ├── generative_ai_service.py # LLM wrapper
│   │   │   │   ├── prompt_builder.py    # Prompt construction
│   │   │   │   ├── footprint_analyzer.py # Order flow
│   │   │   │   └── aggression_scorer.py # Aggression scoring
│   │   │   └── strategy/
│   │   │       ├── setup_detector.py    # Setup detection
│   │   │       └── market_state_engine.py # 4-state model
│   │   └── probability/
│   │       ├── agent_pipeline.py        # 4-agent cascade
│   │       └── features.py              # 42 features
│   ├── application/
│   │   ├── engine.py                    # Tick loop orchestrator
│   │   ├── services/
│   │   │   ├── trading_session.py       # Orchestrator (1119 lines)
│   │   │   ├── entry_coordinator.py     # Signal execution
│   │   │   ├── exit_coordinator.py      # Exit callbacks
│   │   │   ├── session_state_manager.py # Session CRUD
│   │   │   ├── session_risk_coordinator.py # Risk
│   │   │   └── session_event_logger.py  # Logging
│   │   └── handlers/
│   │       ├── amt_handler.py           # AMT handler
│   │       ├── llm_entry_handler.py     # LLM entry (983 lines)
│   │       ├── llm_overseer_handler.py  # LLM monitoring
│   │       ├── trade_lifecycle_handler.py # Lifecycle
│   │       └── entry_gate_coordinator.py # Gates
│   ├── infrastructure/
│   │   ├── adapters/
│   │   │   ├── dhan_adapter.py          # DhanMarketData
│   │   │   ├── dhan_broker_adapter.py   # DhanBroker
│   │   │   ├── paper_broker.py          # PaperBroker
│   │   │   ├── mlx_inference_adapter.py # MLX LLM
│   │   │   └── lgbm_probability_adapter.py # LGBM
│   │   ├── strategies/
│   │   │   ├── nse_strategy.py          # NSE
│   │   │   └── mcx_strategy.py          # MCX
│   │   ├── storage/
│   │   │   └── database.py              # SQLite
│   │   └── event_bus.py                 # InMemoryEventBus
│   ├── api/
│   │   ├── dependencies.py              # ServiceGraph (IoC)
│   │   └── routers/
│   │       ├── health.py                # Config + health
│   │       ├── trading.py               # Trading state
│   │       └── market.py                # Market data
│   └── pipeline/processors/gate.py      # Pipeline gates
├── config/consolidated.py               # YAML bridge
└── tests/unit/domain/                   # 855 tests
```


---

## 17. DETAILED FLOW DIAGRAMS

### 17a. Full Tick → Signal → Execution Flow

```
TICK (Dhan WS) → _on_tick()
  ├─ Phase 5 check → force exit all
  ├─ AMT Analysis → VP, aggression, CVD
  ├─ Agent Pipeline (4-agent cascade)
  │   ├─ RegimeAgent: TRENDING/BALANCED/VOLATILE/DEAD
  │   ├─ DirectionAgent: LGBM P(long) P(short)
  │   ├─ TimingAgent: ENTER_NOW/WAIT/SKIP
  │   └─ SizingAgent: Kelly formula
  ├─ Entry Check: P ≥ 0.55 + direction + can_trade
  ├─ Gate Pipeline (12 gates)
  │   ├─ Gate 0: Session time / warm-up (15 min)
  │   ├─ Gate 1: Data quality / tick age (>30s)
  │   ├─ Gate 2: Session risk halted
  │   ├─ Gate 3: NO_TRADE state (POC ±2 ticks)
  │   ├─ Gate 4: PROBING without aggression (<3.0)
  │   ├─ Gate 5: Key level identified
  │   ├─ Gate 6: Price at entry zone (≤N ticks)
  │   ├─ Gate 7: Drive number (D1 rejected)
  │   ├─ Gate 8: Aggression score (≥2.0)
  │   ├─ Gate 9: Cushion ticks (≤10)
  │   ├─ Gate 10: R:R ratio (≥1.5)
  │   ├─ Gate 11: Position sizing
  │   └─ Gate 12: EIA window (MCX)
  ├─ Three-Align: State + Location + Aggression = ALL align
  ├─ Confirmation Bundle: Volume Impulse (MUST) + Delta + Spread (2/3)
  ├─ Signal Generation: SL/TP from agg_print/vwap/atr
  └─ EntryCoordinator.execute_signal()
      ├─ Validate thesis
      ├─ Risk check
      ├─ Option selection
      ├─ Broker execution
      ├─ Register position
      ├─ Publish PositionOpened
      └─ Persist to DB
```

### 17b. Overseer Flow (after position opens)

```
Position Open → Overseer Timer (~3s)
  ├─ Gather: entry, SL, TP, PnL%, time_held
  ├─ Probability Engine: estimate_exit_prob()
  ├─ Build Prompt (9 sections)
  ├─ LLM Call (Qwen MLX, temp=0.3, max=120, timeout=15s)
  ├─ Parse: action + reason + new_SL
  └─ Execute:
      ├─ HOLD: no-op
      ├─ TIGHTEN_SL: adjust_stop_loss()
      ├─ PARTIAL_EXIT: 50% close + SL→breakeven
      ├─ FULL_EXIT: 100% close + unregister
      └─ ADD: rate-limited pyramid (max 2)
```

### 17c. Exit Flow

```
TradeManager.check_position() (every tick)
  ├─ SL Hit → full exit
  ├─ TP Hit → partition exit
  │   ├─ P1 @ 33%R → 30% size (weak CVD)
  │   ├─ P2 @ TP → 50% size (strong)
  │   └─ P3 Trail → 20% size (VWAP 1.5R, 2σ tighten)
  ├─ Time Stop → session-aware
  ├─ CVD Kill → breakeven or scratch
  └─ Spread Blowout → immediate exit
```

---

## 18. EXACT THRESHOLD VALUES

### AMT Thresholds

| Parameter | NSE | MCX | Source |
|-----------|-----|-----|--------|
| aggression_sigma | 2.5 | 2.0 | `constants.py` |
| displacement_multiplier | 1.5 | 1.2 | `constants.py` |
| balance_ratio_threshold | 0.70 | 0.55 | `constants.py` |
| LVN_THRESHOLD | 0.15 | 0.15 | `constants.py` |
| HVN_THRESHOLD | 2.00 | 2.00 | `constants.py` |
| VALUE_AREA_PCT | 0.70 | 0.70 | `constants.py` |
| LVN_PERSISTENCE | 3 bars | 3 bars | `constants.py` |
| LVN_REMOVAL | 0.30 | 0.30 | `constants.py` |

### CVD Thresholds

| Parameter | Value | Source |
|-----------|-------|--------|
| CVD_SLOPE_HARD_BLOCK | 50.0 | `constants.py` |
| CVD_SLOPE_WARNING | 30.0 | `constants.py` |
| CVD_SLOPE_EXTREME | 100.0 | `constants.py` |
| CVD_STRONG_SLOPE | 2.0 | `constants.py` |

### Aggression Scoring (max 4.5)

| Component | Points |
|-----------|--------|
| Footprint confirmed | +1.0 |
| CVD confirms | +1.0 |
| Big trade cluster | +1.0 |
| Absorption | +0.5 |
| OFI aligned | +0.5 |
| Confluence bonus | +0.5 |

### Risk Constants

| Parameter | Value |
|-----------|-------|
| RISK_PER_TRADE_PCT | 0.5% |
| MAX_DAILY_LOSS_PCT | 2.0% |
| MAX_CONSECUTIVE_LOSSES | 3 |
| MAX_DRAWDOWN_PCT | 3.0% |
| Max concurrent positions | 5 |
| Portfolio notional cap | 60% |
| Per-symbol notional cap | 20% |

### ML Agent Thresholds

| Playbook | LONG P | SHORT P | Margin |
|----------|--------|---------|--------|
| imbalance_continuation | ≥ 0.55 | ≥ 0.53 | 0.04 |
| return_to_value | ≥ 0.51 | ≥ 0.51 | 0.02 |
| probing_breakout | ≥ 0.58 | ≥ 0.58 | 0.06 |

### Kelly Sizing

| Parameter | Value |
|-----------|-------|
| Win probability | 0.55 |
| Win/loss ratio | 2.0 |
| Kelly fraction | 0.25 (conservative) |
| Max fraction | 25% |

### Tick Sizes

| Instrument | Tick Size |
|-----------|-----------|
| NIFTY/BANKNIFTY/FINNIFTY | 0.05 |
| CRUDEOIL | 1.0 |
| NATURALGAS | 0.1 |
| GOLD | 1.0 |
| SILVER | 1.0 |

### Session Times

| Exchange | Open | Close |
|----------|------|-------|
| NSE | 09:15 IST | 15:15 IST |
| MCX | 09:00 IST | 23:15 IST |
| EIA suppression | ±15 min | |

