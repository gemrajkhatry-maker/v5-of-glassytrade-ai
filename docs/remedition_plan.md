Here is the complete, definitive operational report for GlassyTrade AI — covering how the system must work end-to-end, what is correctly built, and the full gap analysis.

***
# GlassyTrade AI — Full System Operational Report
### Version 2.0 | Generated 2026-03-27 | 1,080 Tests Passing
---
## Section 1 — System Identity & Purpose
GlassyTrade AI is a **fully automated NSE options trading system** built on Fabio Valentini's Auction Market Theory (AMT). It ingests real-time tick data from DhanHQ WebSocket, builds incremental volume profiles, classifies market state, scores order flow aggression, and routes entry signals through a 17-gate risk pipeline before executing on NIFTY CE/PE and BANKNIFTY CE/PE options. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/81630230/30a80313-901d-41d8-8553-e9c2b9ecea49/SYSTEM_DOCUMENTATION.md)

**Live Scanner State (13:40 IST):** 5 symbols being tracked: [localhost](http://localhost:5190/)
- NIFTY 22950 CE — PROBING
- NIFTY 22950 PE — PROBING
- NIFTY 22900 CE — PROBING
- BANKNIFTY 52500 CE — BALANCED
- BANKNIFTY 52500 PE — BALANCED

All 5 symbols are in active states that should be generating entries — but zero trades exist for BANKNIFTY 52500, confirming that blocked gates are preventing execution. [localhost](http://localhost:5190/)

***
## Section 2 — Architecture: How It Must Be Layered
The system runs on strict **Domain-Driven Design with Port/Adapter isolation** — the domain layer must never import from infrastructure. All external dependencies (broker, storage, LLM) are injected via constructor through abstract ports. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/81630230/30a80313-901d-41d8-8553-e9c2b9ecea49/SYSTEM_DOCUMENTATION.md)

```
API Layer           →  FastAPI routers, WebSocket gameloop
Application Layer   →  trading_session, engine, entry/exit coordinators
Domain Layer        →  AMT logic, gates, aggression, volume profile, LVN (pure Python)
Infrastructure      →  DhanHQ adapter, SQLite storage, mlx LightGBM inference
```

**Technology Stack**: [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/81630230/30a80313-901d-41d8-8553-e9c2b9ecea49/SYSTEM_DOCUMENTATION.md)

| Component | Technology | Notes |
|---|---|---|
| Backend | Python 3.14 + FastAPI | uvicorn ASGI server |
| Frontend | React 18 + TypeScript | Vite + Lightweight Charts |
| Database | SQLite WAL mode | Must migrate to DuckDB for parallel symbols |
| ML Model | LightGBM via mlx | mlx = Apple Silicon only — verify deployment target |
| LLM | Grok 4.1 Fast via OpenRouter | Advisory only, never trade gate |
| Broker | DhanHQ WebSocket + REST | Live + Paper via adapter swap |

***
## Section 3 — The Complete Tick-to-Trade Data Flow
Every tick follows this exact sequence — no step may be skipped: [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/81630230/30a80313-901d-41d8-8553-e9c2b9ecea49/SYSTEM_DOCUMENTATION.md)

1. **DhanHQ WebSocket tick** arrives → `engine.process_tick(symbol, tick, order_book)`
2. → `trading_session.process_tick()` dispatches to all sub-engines
3. → **AMTHandler.analyze()** runs the full AMT cycle:
   - Incremental Volume Profile build (CME Two-Row Pairs method)
   - POC, VAH, VAL computation
   - LVN/HVN detection with 3-bar persistence filter
   - Aggressive prints detection
   - Market State classification (NO_TRADE / BALANCED / IMBALANCED / PROBING)
   - Aggression scoring (7 signals, max 4.5 pts)
   - Session VWAP computation
   - Signal generation via 3 playbooks
4. → **IB Engine** updates Initial Balance High/Low/Mid (9:15–10:15 window)
5. → **1-min Bar Engine** aggregates for MTF scalp stack
6. → **Pre-candle Advisory** fires at T-60s (LLM advisory, not gate)
7. → **Agent Pipeline** computes ML probability (LightGBM, threshold P ≥ 0.55)
8. → **check_exits()** evaluates S-EXIT-1 through S-EXIT-6 for open positions
9. → **Gate Pipeline** — all 12 main gates + 5 SHORT gates must pass
10. → `build_entry_signal()` → `EntryCoordinator` → DhanHQ REST order
11. → `latency_tracker.record()` logs end-to-end tick-to-order time

***
## Section 4 — AMT Strategy: How the Engine Must Decide
### 4.1 Volume Profile Construction
The profile uses **200 buckets** across the session's price range with a 1% buffer on each side. Volume is distributed **uniformly** across each candle's `[low, high]` range — this is a known accuracy limitation (see Section 7). Buy/sell ratio inference logic: [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/81630230/30a80313-901d-41d8-8553-e9c2b9ecea49/SYSTEM_DOCUMENTATION.md)

- If `taker_buy_volume > 0` → use actual ratio
- Else if `delta ≠ 0` → `buy_ratio = 0.5 + delta/(2×volume)` clamped to `[0,1]`
- Else → `close > midpoint → 0.6`, `close < midpoint → 0.4`, at midpoint `→ 0.5`
### 4.2 POC and Value Area
POC = bucket with maximum volume; tie-broken to whichever bucket is closest to session VWAP. Value Area uses the **CME official Two-Row Pairs expansion method** — always expanding the side with the larger 2-row pair sum until 70% of total volume is captured. VAH and VAL are the outer edges (±half step) of the final upper and lower VA buckets. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/81630230/30a80313-901d-41d8-8553-e9c2b9ecea49/SYSTEM_DOCUMENTATION.md)
### 4.3 Market State Classification
| State | Condition | Applicable Playbook |
|---|---|---|
| **NO_TRADE** | Price within 2 ticks of POC | None — Gate 3 blocks |
| **BALANCED** | Price inside VAH ↔ VAL | Playbook B: Mean Reversion |
| **IMBALANCED** | Price outside VA entirely | Playbook A: Trend Continuation |
| **PROBING** | Price testing VAH or VAL boundary | Playbook C: Probing Breakout |
### 4.4 Aggression Scoring — The Trade Trigger
All 7 signals are additive. The system requires **≥ 2.0 points for 3 consecutive 5-minute bars** before any trade is confirmed — a minimum 15-minute sustained aggression window. Pyramid sizing upgrade requires ≥ 3.0 for 3 bars. Tier-A premium setup requires ≥ 3.5. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/81630230/30a80313-901d-41d8-8553-e9c2b9ecea49/SYSTEM_DOCUMENTATION.md)

***
## Section 5 — Gate Pipeline: The 17-Gate Risk Filter
Every single one of the following gates must pass sequentially. The **first failure stops evaluation** and returns the corresponding output state: [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/81630230/30a80313-901d-41d8-8553-e9c2b9ecea49/SYSTEM_DOCUMENTATION.md)

| Gate | Name | Pass Condition | Fail Output |
|---|---|---|---|
| **G0** | Session Time | `candle_count × 5 ≥ warm_up_minutes` | BLOCKED |
| **G1** | Data Quality | `tick_age_seconds ≤ 30` | STALE |
| **G2** | Session Risk | `is_risk_halted = False` | SESSION_STOPPED |
| **G3** | NO_TRADE | `market_state ≠ NO_TRADE` | FLAT |
| **G4** | PROBING | `state ≠ PROBING` OR `aggr ≥ threshold` | FLAT |
| **G5** | Key Level | `nearest_level > 0` | WAIT |
| **G6** | Entry Zone | `distance_to_level ≤ max_distance_ticks` | ALERT |
| **G7** | Drive Check | `drive == 2` OR `(drive ≥ 3 AND valid)` | FLAT |
| **G8** | Aggression | `aggression_score ≥ min_aggression` | WAIT |
| **G9** | Cushion | `cushion_ticks ≤ max_cushion` | INVALID |
| **G10** | R:R Ratio | `r:r ≥ min_rr_ratio` | SKIP |
| **G11** | Position Size | `position_size_ok = True` | BLOCKED |
| **G12** | EIA Window | `eia_window_active = False` | SUPPRESSED |
| **S1** | SHORT Allow | `short_signals_enabled = True` | ❌ BLOCKED (flag off) |
| **S2** | SHORT State | IMBALANCED-DOWN or BALANCED-fail | ❌ blocked by S1 |
| **S3** | SHORT ML | `P ≥ 0.58` | ❌ blocked by S1 |
| **S4** | SHORT Aggression | `ask > bid`, `cvd < 0`, `delta < 0` | ❌ blocked by S1 |
| **S5** | Contract | PE selected | ❌ blocked by S1 |

**G7 Drive Check** is Fabio's core rule: never trade the first impulse drive, only the second (or confirmed third). [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/81630230/30a80313-901d-41d8-8553-e9c2b9ecea49/SYSTEM_DOCUMENTATION.md)

***
## Section 6 — Entry Signal Construction
### 6.1 SL/TP Per Playbook
**Playbook B — Mean Reversion (BALANCED):**
- TP = POC
- SL = aggressive print level OR VAL − buffer (for LONG)
- Max SL = `min(va_width × 0.5, price × 0.02)`
- No trailing stop [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/81630230/30a80313-901d-41d8-8553-e9c2b9ecea49/SYSTEM_DOCUMENTATION.md)

**Playbook A — Trend Continuation (IMBALANCED):**
- TP = `VAH + (VAH − POC)` for LONG
- SL = aggressive print level OR `POC − buffer`
- Max SL = `min(va_width × 0.75, price × 0.03)`
- Trailing stop enabled [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/81630230/30a80313-901d-41d8-8553-e9c2b9ecea49/SYSTEM_DOCUMENTATION.md)

**Playbook C — Probing Breakout (PROBING):**
- TP = measured move from level
- SL = level itself
- Requires VWAP alignment confirmation [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/81630230/30a80313-901d-41d8-8553-e9c2b9ecea49/SYSTEM_DOCUMENTATION.md)
### 6.2 Minimum SL Floor
\[ \text{min\_sl\_dist} = \max(\text{price} \times 0.015, \text{ATR}(14)) \]

If ATR(14) is unavailable, falls back to `price × 0.015`. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/81630230/30a80313-901d-41d8-8553-e9c2b9ecea49/SYSTEM_DOCUMENTATION.md)
### 6.3 Size Multiplier
- Confidence: High = 1.0, Medium = 0.75, Low = 0.5
- LVN bonus: ×1.25 if LVN play direction matches trade
- Final size = `confidence_multiplier × lvn_multiplier × base_size` [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/81630230/30a80313-901d-41d8-8553-e9c2b9ecea49/SYSTEM_DOCUMENTATION.md)

***
## Section 7 — Risk Management Architecture
### 7.1 Risk Tier Engine (Currently Disabled)
The A/B/C tier engine dynamically scales position risk based on session performance. With `risk_tier_engine: False`, the system stays at **Tier C (0.15%)** all session regardless of performance. Tier A (0.45%) premium setup requires all five conditions simultaneously: `aggression ≥ 3.5`, `lvn_strength ≥ 0.85`, `cvd_divergence = True`, `is_second_drive = True`, `ml_probability ≥ 0.65`. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/81630230/30a80313-901d-41d8-8553-e9c2b9ecea49/SYSTEM_DOCUMENTATION.md)
### 7.2 Portfolio Coordinator Hard Limits (Always Active)
| Rule | Limit |
|---|---|
| MAX_POSITIONS | 5 simultaneous |
| PORTFOLIO_NOTIONAL | 60% of capital |
| SYMBOL_NOTIONAL | 20% of capital per underlying |
| DAILY_LOSS | 2% of capital → halt |
| CORRELATION_GUARD | NIFTY + BANKNIFTY same-direction blocked ✅ |
### 7.3 Exit Rules: S-EXIT-1 to S-EXIT-6
| Rule | Trigger | Action |
|---|---|---|
| S-EXIT-1 | Price hits hard stop | FULL EXIT |
| S-EXIT-2 | Unrealized ≥ 1.0R | Trail to breakeven |
| S-EXIT-3 | 1-min CVD flips against position | FULL EXIT |
| S-EXIT-4 | Opposing absorption detected | FULL EXIT |
| S-EXIT-5 | Unrealized ≥ 1.5R | PARTIAL EXIT 50%, trail rest |
| S-EXIT-6 | 12 bars = 60 minutes elapsed | FULL EXIT (time stop) |

***
## Section 8 — Scalping Layer (Currently Disabled)
The full scalping stack is built but inactive (`scalp_engine_enabled: False`). When enabled, it requires a **3-condition 15-second trigger** (ALL must fire simultaneously): [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/81630230/30a80313-901d-41d8-8553-e9c2b9ecea49/SYSTEM_DOCUMENTATION.md)
1. `volume ≥ 3× rolling EMA(20)` — large print detected
2. No opposing large print within 3 ticks — no absorption
3. 15-sec CVD crosses zero — micro flip confirmed

The scalp gate pipeline (G1–G6) also requires **MTF alignment**: 5-min bias + 1-min aggression + 15-sec trigger must all align. The IB Breakout Scalp (Setup A: continuation retest, Setup B: failed breakout fade) is a separate sub-strategy also currently disabled. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/81630230/30a80313-901d-41d8-8553-e9c2b9ecea49/SYSTEM_DOCUMENTATION.md)

***
## Section 9 — Feature Flag State: Critical Gap Analysis
Only **3 of 18 flags are active** — the system is operating at approximately 17% of its designed capability. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/81630230/30a80313-901d-41d8-8553-e9c2b9ecea49/SYSTEM_DOCUMENTATION.md)
### Flags That Must Be Enabled (Prioritised)
| Priority | Flag | Impact of Remaining Off |
|---|---|---|
| **P0 — Now** | `realistic_cost_model` | Paper PnL overstated — STT, brokerage, GST, SEBI costs not deducted |
| **P0 — Now** | `short_signals_enabled` | ALL PE trades blocked at Gate S1 — half the options market invisible |
| **P1** | `initial_balance_engine` | IB levels shown on UI but not wired into Gate 5/6 — dead UI data |
| **P1** | `risk_tier_engine` | No position scaling on winning days — stuck at 0.15% all session |
| **P1** | `iv_vix_features` | Options traded with zero IV/VIX context — theta/vega risk unmodelled |
| **P2** | `true_delta_lee_ready` | Delta computed from Gaussian proxy, not actual taker-side — aggression scores approximate |
| **P2** | `parallel_symbol_sessions` + `duckdb_storage` | Must enable together — SQLite WAL will bottleneck at 5 parallel sessions |
| **P3** | `scalp_engine_enabled` + `ib_breakout_scalp` | Full scalping layer unused — only after IB engine live |
| **P3** | `walk_forward_validation` + `shap_feature_pruning` | ML model robustness not validated — feature importance not pruned |
### Flags That Must Stay Off
| Flag | Reason |
|---|---|
| `llm_entry_gate` | Hardcoded False permanently — LLM must never gate trades, only advise |

***
## Section 10 — Known Accuracy Limitations
### 10.1 Volume Distribution Is Uniform (Not Tick-Level)
The formula `vol_per_bucket = volume / (end_bucket − start_bucket + 1)` spreads a candle's volume evenly across its entire price range. A 20-point wide candle puts the same volume at its extreme low as at its POC area — this **distorts POC, VAH, VAL, and LVN detection**. The fix: since DhanHQ delivers tick-level data, aggregate volume *at actual tick prices* before profile construction, not from OHLCV bars. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/81630230/30a80313-901d-41d8-8553-e9c2b9ecea49/SYSTEM_DOCUMENTATION.md)
### 10.2 Aggression Persistence = 15-Minute Minimum Entry Latency
Three consecutive 5-minute bars at ≥ 2.0 aggression means no entry can trigger in under 15 minutes of sustained signal. On NIFTY expiry days where options move 20–30% in a single 5-minute bar, this filter will systematically produce late entries or miss the entire move. Recommendation: make the persistence bar count configurable — 2 bars for PROBING state (10 min), 3 bars for BALANCED (15 min). [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/81630230/30a80313-901d-41d8-8553-e9c2b9ecea49/SYSTEM_DOCUMENTATION.md)
### 10.3 LightGBM via mlx — Deployment Dependency
`mlx` is Apple Silicon optimised inference. On Linux cloud servers (AWS/GCP/Azure), mlx will either fail or fall back to CPU inefficiently. Before deploying to any non-macOS server, swap the `mlx_inference` adapter for standard `lightgbm` via the port/adapter pattern — this is already supported by the architecture. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/81630230/30a80313-901d-41d8-8553-e9c2b9ecea49/SYSTEM_DOCUMENTATION.md)

***
## Section 11 — What the System Must Look Like When Fully Operational
A correctly operating GlassyTrade AI session must produce the following observable state:

- **Scanner**: ≥ 3 symbols in PROBING or IMBALANCED state with aggression building
- **Closed Trades panel**: Trades appearing — if zero trades after 60+ minutes of PROBING/IMBALANCED symbols, a gate is blocking silently
- **MODEL I/O**: Showing LONG or SHORT signals (not perpetually FLAT) — FLAT after warm-up indicates Gate G3/G4/G8 failure
- **Risk Tier**: Displaying active tier (C/B/A), not static after winning trades
- **IB Levels**: Wired into Key Level gate, not just visual overlay
- **PE signals**: Being generated alongside CE signals on same underlying
- **LLM Advisory**: Pre-candle messages at T-60s populating the AI Commander panel
- **CVD / Delta / OFI**: All three moving directionally — if CVD is flat, tick feed has gaps

***
## Section 12 — Immediate Action Checklist
```
Step 1 → config/feature_flags.yaml:
         realistic_cost_model: true
         short_signals_enabled: true

Step 2 → config/feature_flags.yaml:
         initial_balance_engine: true
         risk_tier_engine: true
         iv_vix_features: true    (requires VIX/IV data source wiring)

Step 3 → Fix volume profile:
         Switch from OHLCV uniform distribution
         to tick-price-aggregated volume buckets

Step 4 → config/feature_flags.yaml (together):
         parallel_symbol_sessions: true
         duckdb_storage: true

Step 5 → Verify mlx adapter:
         On Linux: swap mlx_inference → lightgbm adapter

Step 6 → Enable scalp layer only after Step 1-4 are paper-validated:
         scalp_engine_enabled: true
         ib_breakout_scalp: true
```

The architecture is production-grade and the strategy is correctly modelled. The path to full operation is entirely through enabling the feature flags in the sequence above — no structural code rewrites are required. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/81630230/30a80313-901d-41d8-8553-e9c2b9ecea49/SYSTEM_DOCUMENTATION.md)