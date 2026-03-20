# Master Requirements Specification
## GlassyTrade AI — AMT Order Flow Strategy Engine

**Document Version:** 1.0
**Date:** 2026-03-17
**Status:** Draft
**Source Documents:** srs.md, fulldoc.md, startergy.md

---

## 1. Executive Summary

This document consolidates all functional and non-functional requirements for the GlassyTrade AI trading engine, implementing Fabio Valentini's Auction Market Theory (AMT) methodology for NSE/MCX Indian derivatives markets.

---

## 2. Business Objectives

| ID | Objective | Priority | Status |
|---|---|---|---|
| BO-01 | Detect high-probability trade setups using pure deterministic order flow logic | Critical | Active |
| BO-02 | Eliminate discretionary decisions — every signal must be rule-based | Critical | Active |
| BO-03 | Enforce Fabio Valentini's AMT methodology with zero deviation | Critical | Active |
| BO-04 | Protect capital via session-level and per-trade risk controls | Critical | Active |
| BO-05 | Support multi-symbol scanning across NSE/MCX options simultaneously | High | Active |
| BO-06 | Provide AI Commander rationale output for every scan decision | High | Active |
| BO-07 | Support pyramiding as a structured add — not averaging down | High | Active |
| BO-08 | Manage open trades through partition exit and trailing | High | Active |
| BO-09 | Operate with zero LLM/ML dependency in core signal engine | Critical | Active |

---

## 3. Functional Requirements

### 3.1 Data Ingestion (FR-01)

| ID | Requirement | Data Source | Type | Priority |
|---|---|---|---|---|
| FR-01-01 | Ingest per-tick `price`, `buy_qty`, `sell_qty`, `trade_size`, `timestamp` | DhanHQ WebSocket | Tick stream | Critical |
| FR-01-02 | Ingest per-candle OHLCV (1min, 5min) for ATR and absorption calculations | DhanHQ REST / WS | Aggregated | Critical |
| FR-01-03 | Ingest market depth (L2) — top 5 bid/ask levels, quantity, and order count | DhanHQ `get_market_depth()` | Polled 500ms | High |
| FR-01-04 | Detect session boundary at 09:00 IST (MCX) and 09:15 IST (NSE) — reset all session-scoped state | System clock | Internal | Critical |
| FR-01-05 | Load previous session's POC, VAH, VAL from persistent store at session open | Local DuckDB | Persistent | High |
| FR-01-06 | Handle tick data gaps — if gap > 30 seconds, flag profile as `STALE`, suppress signals | Quality monitor | Internal | High |
| FR-01-07 | Support EIA Natural Gas Storage release detection — suppress signals 15 min around release | Economic calendar | External API | Medium |

### 3.2 Volume Profile Engine (FR-02)

| ID | Requirement | Formula / Rule | Priority |
|---|---|---|---|
| FR-02-01 | Build Session Volume Profile from session open to current tick | `bucket[round(price/tick)] += volume` | Critical |
| FR-02-02 | Calculate POC as the price bucket with maximum cumulative volume | `max(profile, key=volume)` | Critical |
| FR-02-03 | Calculate VAH/VAL via 70% Value Area expansion from POC | Standard 70% rule | Critical |
| FR-02-04 | Persist completed session profile to DuckDB at session close | End-of-day write | High |
| FR-02-05 | Build Leg Profile (FRVP) anchored from leg start timestamp to current tick extreme | Filtered tick subset | High |
| FR-02-06 | Auto-detect leg start: price breaks VAH/VAL + displacement candle + volume > avg×1.5 | `auto_detect_leg_anchor()` | High |
| FR-02-07 | Auto-reset leg anchor when price re-enters value area | `should_reset_leg()` | High |
| FR-02-08 | Detect LVNs: profile rows with volume < 15% of mean row volume | `vol < mean × 0.15` | High |
| FR-02-09 | Detect HVNs: profile rows with volume > 200% of mean row volume | `vol > mean × 2.0` | High |
| FR-02-10 | Score each LVN by quality: thinness (60% weight) + proximity to leg midpoint (40% weight) | `lvn_score()` | Medium |
| FR-02-11 | Build Combined Profile: find levels where LVN on leg profile coincides within 3 ticks of session VAH/VAL/POC | Confluence detection | Medium |
| FR-02-12 | Combined confluence level receives +0.5 aggression score bonus | Scoring modifier | Medium |

### 3.3 Order Flow Metrics (FR-03)

| ID | Requirement | Formula / Rule | Priority |
|---|---|---|---|
| FR-03-01 | Calculate CVD as cumulative sum of `(ask_vol - bid_vol)` per tick from session open | `cumsum(delta)` | Critical |
| FR-03-02 | Calculate CVD slope over rolling 20-candle window | `(cvd[-1] - cvd[-20]) / 20` | Critical |
| FR-03-03 | Detect CVD bullish divergence: price makes new low but CVD does not | `price < prev_low AND cvd > prev_cvd_at_low` | High |
| FR-03-04 | Detect CVD bearish divergence: price makes new high but CVD does not | `price > prev_high AND cvd < prev_cvd_at_high` | High |
| FR-03-05 | Build footprint per candle: aggregate `ask_vol` and `bid_vol` per price level per candle | Per-tick grouping | Critical |
| FR-03-06 | Detect footprint imbalance: cells where ratio ≥ 3.0 (300%) — count as % of total cells | `imbalanced_cells / total_cells ≥ 0.40` | Critical |
| FR-03-07 | Detect Volume Bubble: per-level total volume ≥ mean + 2σ across last 21 bars | 2σ threshold | High |
| FR-03-08 | Classify bubble direction: BUY (ask>>bid×2), SELL (bid>>ask×2), NEUTRAL (absorption) | Direction labeling | High |
| FR-03-09 | Detect absorption: `(high-low) < ATR×0.30` AND `volume > avg_vol×2.0` simultaneously | Dual condition | High |
| FR-03-10 | Classify absorption type: SELL_ABSORBED → LONG signal; BUY_ABSORBED → SHORT signal | Direction assignment | High |
| FR-03-11 | Detect big trade cluster: `trade_size ≥ avg_trade_size × 5.0`, minimum 3 prints within 2 ticks | Cluster threshold | High |
| FR-03-12 | Calculate OFI: `(ask_vol - bid_vol) / total_vol` averaged over last 10 candles | Rolling OFI | Medium |
| FR-03-13 | Calculate VWAP with ±1σ and ±2σ bands from session open | Typical price × volume | Medium |
| FR-03-14 | Calculate Initial Balance from first 2 candles of session | First 2 candles | Medium |
| FR-03-15 | Detect IB break: close outside IB range + volume > avg×1.5 | IB break detection | Medium |
| FR-03-16 | Poll L2 DOM every 500ms — detect liquidity walls | L2 wall detection | Medium |
| FR-03-17 | Detect iceberg: order refreshing at same price level after partial fills | Order persistence check | Low |

### 3.4 Market State Engine (FR-04)

| ID | Requirement | Rule | Priority |
|---|---|---|---|
| FR-04-01 | Classify as NO_TRADE if price within ±2 ticks of session POC | Dead zone rule | Critical |
| FR-04-02 | Classify as BALANCED if price inside VAH–VAL range | 70% value area | Critical |
| FR-04-03 | Within BALANCED: sub-classify as NEAR_VAH, NEAR_VAL, or NEAR_POC | Zone classification | Critical |
| FR-04-04 | Classify as IMBALANCED if price outside VA + displacement candle + high volume | Trend mode trigger | Critical |
| FR-04-05 | Classify as PROBING if price outside VA but no displacement | Unconfirmed break | High |
| FR-04-06 | State PROBING must not generate any trade signal | Hard suppression | Critical |
| FR-04-07 | State transitions must be logged with timestamp and trigger values | Audit trail | Medium |

### 3.5 Drive Detection Engine (FR-05)

| ID | Requirement | Rule | Priority |
|---|---|---|---|
| FR-05-01 | Track every touch of each key level (VAH, VAL, LVN) with timestamp and rejection status | DriveTracker class | Critical |
| FR-05-02 | First Drive at any level: record touch, set return alert, suppress all entry signals | Drive 1 = no trade | Critical |
| FR-05-03 | Detect rejection on First Drive: wick through level but close on opposite side | Wick rejection check | Critical |
| FR-05-04 | Second Drive at a level where First Drive was rejected: mark as valid entry zone | Drive 2 = entry eligible | Critical |
| FR-05-05 | Second Drive where First Drive was NOT rejected: suppress signal | No rejection = no entry | Critical |
| FR-05-06 | Third or more drive at same level: suppress signal | Drive 3+ = avoid | Critical |
| FR-05-07 | Second Drive must show fading momentum vs First Drive | Momentum fade check | High |
| FR-05-08 | DriveTracker resets for all levels at session open | Session reset | High |

### 3.6 Aggression Scoring Engine (FR-06)

| ID | Requirement | Weight | Priority |
|---|---|---|---|
| FR-06-01 | Footprint imbalance confirmed at entry level (≥40% cells, ≥3:1 ratio) | +1.0 | Critical |
| FR-06-02 | CVD slope confirms direction OR CVD divergence detected | +1.0 | Critical |
| FR-06-03 | Big trade cluster confirmed at entry level (3+ institutional prints within 2 ticks) | +1.0 | High |
| FR-06-04 | Absorption detected in same direction at entry candle | +0.5 | High |
| FR-06-05 | OFI aligned with direction (> +0.10 for LONG, < -0.10 for SHORT) | +0.5 | Medium |
| FR-06-06 | Combined Profile confluence bonus (LVN + session level overlap) | +0.5 | Medium |
| FR-06-07 | Volume Bubble (directional, not neutral) within 3 ticks of entry zone | +0.5 | Medium |
| FR-06-08 | Minimum aggression score to generate TRADE signal: 2.0 | Hard threshold | Critical |
| FR-06-09 | Minimum aggression score for pyramid add: 3.0 | Pyramid threshold | High |
| FR-06-10 | Confidence labels: ≥3.0 = High, ≥2.0 = Medium, <2.0 = Low (no trade) | Labeling rule | High |

### 3.7 Trade Setup Construction (FR-07)

| ID | Requirement | Rule | Priority |
|---|---|---|---|
| FR-07-01 | Entry zone: exact LVN price or VAH/VAL level — never arbitrary | Level-based only | Critical |
| FR-07-02 | Entry execution: never blind limit at LVN — wait for aggression | Execution rule | Critical |
| FR-07-03 | Stop loss primary: just beyond aggressive print + 2-tick buffer | SL rule 1 | Critical |
| FR-07-04 | Stop loss fallback: entry candle's swing extreme + 2-tick buffer | SL rule 2 | High |
| FR-07-05 | Cushion quality: ≤3 ticks = excellent, ≤6 = acceptable, ≤10 = reduce size 50%, >10 = invalid | Cushion gate | Critical |
| FR-07-06 | Target primary: previous session POC for all trend trades | Trend target | High |
| FR-07-07 | Target for mean reversion: current session POC | MR target | High |
| FR-07-08 | R:R must be minimum 1:1.5 to generate signal | R:R filter | Critical |
| FR-07-09 | Invalidation level: if price closes beyond this level, trade structure is void | Hard invalidation | High |

### 3.8 Partition Exit Engine (FR-08)

| ID | Requirement | Rule | Priority |
|---|---|---|---|
| FR-08-01 | Partition 1 (30%): exit at entry + R×0.33 IF momentum is weak | Seed recovery | High |
| FR-08-02 | If momentum is strong: skip Partition 1, let position run | Strong trend override | High |
| FR-08-03 | Partition 2 (50%): always exit at target (session POC) | Target exit mandatory | Critical |
| FR-08-04 | Partition 3 (20%): trail only if CVD slope > 2.0 at time of P2 exit | Remainder logic | Medium |
| FR-08-05 | After P2 exit, move SL for P3 to P2 exit price | P3 SL rule | High |
| FR-08-06 | Counter-aggression exit (2+ counter signals): exit ALL partitions immediately | Hard exit override | Critical |
| FR-08-07 | Break-even trigger: move SL to entry when price reaches 35% of R toward target | BE rule | High |
| FR-08-08 | Trail logic for P3: SL = current_price - (remaining_to_target × 0.40) | Trail formula | Medium |

### 3.9 Pyramid Engine (FR-09)

| ID | Requirement | Rule | Priority |
|---|---|---|---|
| FR-09-01 | Pyramid only when first entry is in profit | Profit gate | Critical |
| FR-09-02 | Maximum 2 pyramid adds (3 total entries per trade) | Add limit | Critical |
| FR-09-03 | Total risk across all adds must not exceed 1.5× single trade risk | Risk ceiling | Critical |
| FR-09-04 | Pyramid entry must be at a different LVN from first entry | New level required | High |
| FR-09-05 | Pyramid lot sizing: Add 1 = 100%, Add 2 = 50%, Add 3 = 25% of base lots | Decreasing size | High |
| FR-09-06 | After each pyramid add, move ALL open stops to SL of latest entry | Unified stop rule | High |
| FR-09-07 | Pyramid requires aggression score ≥ 3.0 | Score gate | High |
| FR-09-08 | Set pre-alert for pyramid level | Alert-based | Medium |

### 3.10 Risk Management Engine (FR-10)

| ID | Requirement | Value | Priority |
|---|---|---|---|
| FR-10-01 | Risk per trade: 0.5% of account equity | Per-trade limit | Critical |
| FR-10-02 | Maximum daily loss: 2% of session-start equity | Daily limit | Critical |
| FR-10-03 | Maximum consecutive losses: 3 — pause trading | Consecutive limit | Critical |
| FR-10-04 | Maximum drawdown from equity peak: 3% | Drawdown limit | Critical |
| FR-10-05 | Absolute ceiling per trade: 1.0% | Hard ceiling | Critical |
| FR-10-06 | Session risk state must be checked at every signal generation | Continuous check | Critical |
| FR-10-07 | All trades, PnL, and risk events logged per session to DuckDB | Audit log | High |
| FR-10-08 | Instrument-specific big trade thresholds configurable per symbol | Per-symbol config | Medium |
| FR-10-09 | Avoid first 15 min of MCX session (09:00–09:15 IST) | Time filter | High |
| FR-10-10 | Best trading windows: 09:30–11:30 IST and 14:00–15:30 IST | Preferred windows | Medium |
| FR-10-11 | Dead zone: 12:00–13:30 IST — reduced confidence | Dead zone label | Medium |

### 3.11 Output Schema (FR-11)

Every signal output must include all fields defined in the OutputSchema (see srs.md Section 2 FR-11 for complete JSON structure).

---

## 4. Non-Functional Requirements

| ID | Requirement | Target | Category | Priority |
|---|---|---|---|---|
| NFR-01 | Signal latency from tick arrival to output | < 500ms | Performance | Critical |
| NFR-02 | Profile rebuild on each new tick — incremental update | O(1) per tick | Efficiency | Critical |
| NFR-03 | System must handle minimum 10 concurrent symbols | No degradation | Scalability | High |
| NFR-04 | All state persisted in DuckDB — survives restart | Full persistence | Durability | High |
| NFR-05 | WebSocket reconnection with state recovery | No signal loss | Reliability | Critical |
| NFR-06 | All signals and decisions logged with full input snapshot | Reproducible audit | Observability | High |
| NFR-07 | Profile calculations use incremental bucket update | O(1) per tick | Time complexity | Critical |
| NFR-08 | Zero dependency on external ML inference | No ML/LLM | Independence | Critical |

---

## 5. Configuration Requirements

### 5.1 Global Configuration Constants

| Parameter | Value | Description |
|---|---|---|
| `tick_size` | 0.10 (NG) / 0.05 (NIFTY) | Minimum price increment |
| `profile_bucket_size` | 0.10 (NG) / 5.0 (NIFTY) | Volume profile row resolution |
| `value_area_pct` | 0.70 | Standard 70% value area rule |
| `lvn_threshold` | 0.15 | LVN = row volume < 15% of mean |
| `hvn_threshold` | 2.00 | HVN = row volume > 200% of mean |
| `footprint_imbalance` | 3.00 | 300% = 3:1 ratio threshold |
| `big_trade_multiplier` | 5.0 | Big trade = 5x avg trade size |
| `absorption_range_atr` | 0.30 | Absorption range threshold |
| `absorption_vol_mult` | 2.00 | Absorption volume threshold |
| `displacement_atr_mult` | 1.50 | Displacement candle threshold |
| `poc_no_trade_ticks` | 2 | Dead zone = ±2 ticks around POC |
| `min_aggression_score` | 2.0 | Minimum to trigger any trade |
| `risk_pct` | 0.005 | 0.5% account risk per trade |
| `ib_period_candles` | 2 | Initial Balance window |
| `cvd_slope_window` | 20 | Candles for CVD slope |
| `ofi_window` | 10 | Candles for OFI calc |
| `atr_period` | 14 | ATR calculation period |
| `avg_vol_period` | 20 | Average volume period |

### 5.2 Instrument-Specific Configuration

| Instrument | Tick Size | Lot Size | Point Value | Profile Bucket | Big Trade Threshold | Session Open | Session Close |
|---|---|---|---|---|---|---|---|
| NATURALGAS | 0.10 | 1250 | 1250 | 0.10 | 50 lots | 09:00 | 23:30 |
| NIFTY | 0.05 | 25 | 25 | 5.0 | 100 | 09:15 | 15:30 |
| BANKNIFTY | 0.05 | 15 | 15 | 5.0 | 50 | 09:15 | 15:30 |

---

## 6. Decision Gate Sequence

Every tick runs through ALL gates in order. First FAIL = output immediately.

| Gate | Check | Fail Output |
|---|---|---|
| GATE 0 | Session time filter (warm-up, dead zone) | BLOCKED |
| GATE 1 | Data quality check (STALE flag, gap > 30s) | STALE |
| GATE 2 | Session risk manager (daily loss, drawdown, consec) | SESSION_STOPPED |
| GATE 3 | Market state = NO_TRADE (POC dead zone ±2 ticks) | FLAT |
| GATE 4 | Market state = PROBING (unconfirmed break) | FLAT |
| GATE 5 | Profile selected and key level identified | WAIT |
| GATE 6 | Price AT entry zone (within 3 ticks) | ALERT |
| GATE 7 | Drive number = 2 (first drive rejected) | FLAT / ALERT |
| GATE 8 | Aggression score ≥ 2.0 | WAIT |
| GATE 9 | Cushion ≤ 10 ticks | INVALID |
| GATE 10 | R:R ≥ 1.5 | SKIP |
| GATE 11 | Position sizing passes risk manager | BLOCKED |
| GATE 12 | EIA release window (if applicable) | SUPPRESSED |

ALL GATES PASSED → TRADE SIGNAL

---

## 7. Open Items / Gaps

| ID | Item | Resolution Needed | Owner | Status |
|---|---|---|---|---|
| OI-01 | DhanHQ WebSocket field names verification | Test with live connection | TBD | Open |
| OI-02 | MCX NATURALGAS big trade threshold calibration | 1-week tick data analysis | TBD | Open |
| OI-03 | MCX evening session boundary handling | Design decision | TBD | Open |
| OI-04 | Thread-per-symbol vs async event loop | Performance test | TBD | Open |
| OI-05 | L2 DOM polling rate limits | API docs check | TBD | Open |
| OI-06 | EIA release calendar API integration | External data source | TBD | Open |
| OI-07 | Profile bucket size for options vs underlying | Design decision | TBD | Open |
| OI-08 | Frontend push mechanism selection | Architecture choice | TBD | Open |

---

## 8. Traceability Index

| Requirement Category | Source Document | Section |
|---|---|---|
| Business Objectives | srs.md | Section 1 |
| Functional Requirements | srs.md | Section 2 |
| Non-Functional Requirements | srs.md | Section 3 |
| Technical Design | fulldoc.md | TDD-01 to TDD-05 |
| API Contracts | fulldoc.md | API-01 to API-03 |
| Test Plan | fulldoc.md | TP-01 |
| Strategy Algorithm | startergy.md | PHASE 0-10 |
| Risk Management | startergy.md | PHASE 10 |
| Drive Detection | startergy.md | PHASE 2B |
| Pyramid Logic | startergy.md | Pyramid section |

---

**Document Control:**
- Created: 2026-03-17
- Last Modified: 2026-03-17
- Next Review: TBD
- Approved By: TBD
