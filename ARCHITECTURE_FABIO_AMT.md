# Fabio AMT Trading System Architecture

## Executive Summary

The system implements Fabio Valentini's Adaptive Market Trading (AMT) strategy for NSE options. It combines rule-based gates, a fast micro-agent pipeline (ML), and an advisory LLM into a hybrid decision framework.

## Core Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         EVENT FLOW                                │
├─────────────────────────────────────────────────────────────────┤
│ Tick → AMTHandler → Agent Pipeline → Gate Pipeline → EntryCoord  │
│     ↘                                                           │
│      RegimeDetector → LLM (on regime changes only)              │
└─────────────────────────────────────────────────────────────────┘
```

## Component Layers

### 1. Data Ingest Layer

**`AMTHandler.analyze()`** (`backend/app/application/handlers/amt_handler.py`)
- Converts ticks to float-based OHLC (Decimal-free for speed)
- Maintains incremental volume profile (1000-candle lookback)
- Detects session boundary → resets VP state
- Returns: `AMTResult` with full auction market structure

**`AMTAnalyzer.analyze()`** (`backend/app/domain/fabio_ai/services/amt_analyzer.py`)
- Volume profile construction (70% VA, POC at VWAP tie-break)
- LVN/HVN detection (persistence tracked)
- Market state: BALANCED/IMBALANCED/PROBING/DEAD
- Aggression scoring (0-2.0 scale)
- Drive tracking, IB state, breaks

### 2. Decision Layer (4 Agents in <1ms)

**`run_agent_pipeline()`** (`backend/app/domain/probability/agent_pipeline.py`)

| Agent | Type | Latency | Output |
|-------|------|---------|--------|
| RegimeAgent | Rules | ~0.05ms | DEAD/VOLATILE/TRENDING/BALANCED |
| DirectionAgent | LightGBM | ~0.1ms | P(long), P(short), direction |
| TimingAgent | Rules | ~0.1ms | ENTER_NOW/WAIT/SKIP |
| SizingAgent | Kelly | ~0.01ms | position fraction |

**Features (42 total)**:
- Group A: Price microstructure (close_vs_poc, atr_ratio, wick ratios)
- Group B: Order flow (delta_normalized, cvd_slope, aggression)
- Group C: Volume profile (profile_shape, balance_ratio)
- Group D: Order book (book_imbalance_l5, spread_bps)
- Group E: Temporal (minutes_since_open, session_flag)
- Group F: Options-specific (oi_change_pct, moneyness_pct)

### 3. Validation Layer (12 Gates)

**`run_gate_pipeline()`** (`backend/app/domain/fabio_ai/services/entry_gates/gate_runner.py`)

| Gate | Purpose |
|------|---------|
| 0 | Candle count (≥20) |
| 1 | Stale data reject |
| 2 | Risk halted check |
| 3 | No trade state (DEAD market) |
| 4 | Probing state (FIRST DRIVE) |
| 5 | Key level proximity |
| 6 | Price distance to level |
| 7 | Drive classification (1st/2nd/3rd) |
| 8 | Aggression threshold |
| 9 | Cushion width |
| 10 | R:R ratio (≥0.1) |
| 11 | Position sizing |
| Soft Gate 4b | PCR bias alignment |

### 4. Advisory Layer (LLM)

**`GenerativeAIService.analyze_market()`** (`backend/app/domain/fabio_ai/services/generative_ai_service.py`)
- Model: Gemma-MLX fine-tuned
- Contract: JSON only (direction, confidence, rationale)
- Trigger: RegimeDetector on state changes
- Cooldown: 30s minimum
- **NOT execution authority** — advisory only

**`prompt_builder.py`** constructs 4-section narrative:
1. Session context (phase, gap, IB, prior VA)
2. Market state (location, structure, profile shape)
3. Order flow (CVD, delta, aggression, quant signal)
4. Rules hierarchy (Fabio priority rules)

### 5. Execution Layer

**`SessionEventRouter.execute_entry_path()`** (`backend/app/application/services/session_event_router.py`)
- Gate validation → signal building → entry execution
- Circuit breaker (3 consecutive stops → 15min pause)
- Short gates (separate evaluation for SHORT entries)

## Data Flow Example

```python
# 1. Tick arrives
tick = OHLC(time="09:35", open=22500, high=22510, low=22490, close=22505, volume=1500, delta=420)

# 2. AMT Analysis
amt_result = amt_handler.analyze(data, tick)
# AMTResult: market_state="BALANCED", poc=22450, vah=22510, val=22420, aggression=1.2

# 3. Agent Pipeline
agent_decision = run_agent_pipeline(data, amt_result, tick, prob_engine, features)
# AgentDecision: direction="LONG", probability=0.58, regime="BALANCED", timing="ENTER_NOW"

# 4. Gate Pipeline (12 gates + PCR soft gate)
gate_passed, reason, detail = run_gate_pipeline(data, amt_result, tick, ...)
# gate_passed=True

# 5. Entry
signal = build_entry_signal("LONG", tick, amt_result, ...)
entry_coordinator.execute_signal(symbol, signal, session)
```

## Key Files

| Component | File |
|-----------|------|
| AMT Analysis | `backend/app/domain/fabio_ai/services/amt_analyzer.py` |
| Setup Detector | `backend/app/domain/fabio_ai/strategy/setup_detector.py` |
| OI Wall Engine | `backend/app/domain/services/oi_wall_engine.py` |
| Option Selection | `backend/app/domain/services/option_selection_engine.py` |
| Risk Sizing | `backend/app/domain/services/risk_sizing_engine.py` |
| Volume Profile | `backend/app/domain/services/volume_profile.py` |
| Regime Detector | `backend/app/domain/fabio_ai/services/regime_detector.py` |
| Agent Pipeline | `backend/app/domain/probability/agent_pipeline.py` |
| Feature Extract | `backend/app/domain/probability/features.py` |
| Gate Pipeline | `backend/app/domain/fabio_ai/services/gate_pipeline.py` |
| Gate Runner | `backend/app/domain/fabio_ai/services/entry_gates/gate_runner.py` |
| Session Router | `backend/app/application/services/session_event_router.py` |
| LLM Service | `backend/app/domain/fabio_ai/services/generative_ai_service.py` |
| Prompt Builder | `backend/app/domain/fabio_ai/services/prompt_builder.py` |

## Session Phase Timing (Fabio 6-Phase)

**NSE Primary Session**:
- **Phase 0 (09:15-09:30)**: Opening Noise — DO NOT TRADE
- **Phase 1 (09:30-10:15)**: IB Formation — DO NOT TRADE (wait for completion)
- **Phase 2 (10:15-11:30)**: BEST for AAA setups (Primary Setup Window)
- **Phase 3 (11:30-14:00)**: Mean reversion only (Midday Consolidation)
- **Phase 4 (14:00-15:15)**: SECOND BEST for AAA setups (Power Hour)
- **Phase 5 (15:15-15:30)**: Exit only (Close Protection)

Session gate blocks entries in Phase 3 (midday consolidation) for trend models.

## PCR Integration Flow

```
AMTResult.pcr (default 1.0)
    ↓
session_event_router.run_gate_pipeline(pcr=...)
    ↓
GateContext: pcr, pcr_aligned, pcr_bullish_max=0.85, pcr_bearish_min=1.15
    ↓
_check_pcr_alignment() → logs warning if misaligned
    ↓
Soft gate (doesn't block, informational)
```

PCR Interpretation:
- < 0.85: Bearish bias (favor SHORT)
- 0.85-1.15: Neutral (both allowed)
- > 1.15: Bullish bias (favor LONG)

## Failure Handling

| Condition | Response |
|-----------|----------|
| LLM timeout (>15s) | Fallback to quant signal |
| Model not ready | Skip LLM, continue with agent |
| DEAD market | Skip all, wait for expansion |
| Circuit breaker (3 stops) | Pause 15 minutes |
| Failed auction | Block re-entry at same level |
| Gate rejection | Log, don't execute |

## Test Coverage

- **Total**: 1762 passed, 235 skipped
- **Core AMT tests**: `test_strategy.py` (11), `test_gate_pipeline.py` (25), `test_squeeze_detector.py` (8)
- **PCR tests**: `test_gate_pipeline_soft_gates.py` (10)