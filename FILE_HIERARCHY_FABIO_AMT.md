# Fabio Valentini AMT Implementation - File Hierarchy Document

## Overview

This document details the complete file hierarchy for the Fabio Valentini Adaptive Market Trading (AMT) implementation, organized from root to leaf files with descriptions of their purpose and responsibilities.

---

## Directory Structure

```
backend/
├── app/
│   ├── application/
│   │   ├── handlers/
│   │   ├── services/
│   │   └── di/
│   ├── domain/
│   │   ├── trading/
│   │   ├── services/
│   │   └── fabio_ai/
│   ├── infrastructure/
│   └── shared/
```

### `/backend/app/domain/fabio_ai/`

#### Core Services

| File | Purpose |
|------|---------|
| `services/amt_analyzer.py` | **Core AMT Analysis** - Main analyzer that computes volume profile, market state, aggression scores, drives, IB levels, POC migrations, LVN/HVN detection. Populates `AMTResult` with all analysis fields. |
| `services/session_context.py` | **Session Timing** - Defines NSE 6-phase session structure (Opening Noise, IB Formation, Primary Setup, Midday, Power Hour, Close). Provides `get_session_info()` for session-aware filtering. |
| `services/gate_pipeline.py` | **12-Gate Validation** - Hybrid gate system with HARD gates (fail-fast) and SOFT gates (quorum model). Includes Gate 13 for session strategy filtering. |
| `services/entry_gates/gate_runner.py` | **Gate Pipeline Runner** - Entry point for running the 12-gate pipeline. Creates `GateContext` and evaluates through `GatePipeline`. |
| `services/entry_gates/signal_builder.py` | **Signal Construction** - Builds entry signals from validated gates. Handles direction, confidence, setup type, and risk parameters. |
| `services/setup_detector.py` | **Setup Detection** - Detects AAA setups (Active Auction, Momentum, Mean Reversion, Failed Auction). Implements `_detect_aaa_setup()` and `_detect_failed_auction()`. |
| `strategy/squeeze_detector.py` | **Squeeze Detection** - Detects momentum squeezes via volume compression. Provides `squeeze_state` in `AMTResult`. |

#### Risk & Position Management

| File | Purpose |
|------|---------|
| `services/risk_sizing_engine.py` | **Risk-Based Position Sizing** - Calculates position size based on theta decay, holding cost ratio, and theta-adjusted lots for options. |
| `services/session_risk_manager.py` | **Session Risk Management** - Tracks risk tiers (Conservative/Normal/Defensive/Momentum), stop-loss percentages, session PnL, and forced exits. |
| `services/position_sizer.py` | **Position Calculation** - Kelly-based position sizing with velocity scaling for dynamic adjustments. |
| `services/scale_manager.py` | **Scale Management** - Handles scale-in conditions for positions, tracks scale count, entry gaps, and risk limits. |

#### Order Flow & Profile

| File | Purpose |
|------|---------|
| `services/cvd_tracker.py` | **CVD Tracking** - Cumulative Volume Delta tracking with slope calculation, divergence detection, and storage. |
| `services/aggression_scorer.py` | **Aggression Scoring** - Computes aggression score (0-2.0 scale) based on volume spikes and directional conviction. |
| `services/profile_classifier.py` | **Profile Shape Classification** - Classifies volume profile shapes (D, P, b, B) and tracks POC migration direction. |
| `services/volume_profile.py` | **Volume Profile Engine** - Constructs volume profile with POC, value area high/low, LVNs, HVNs. |
| `services/drive_tracker.py` | **Drive Tracking** - Tracks test drives (D1, D2, D3+) with invalidation on break and retest patterns. |

#### Session & Market State

| File | Purpose |
|------|---------|
| `services/market_state_engine.py` | **Market State Detection** - Determines market state (BALANCED, IMBALANCED, PROBING, DEAD, NO_TRADE). |
| `services/regime_detector.py` | **Regime Detection** - Detects market regime (DEAD, VOLATILE, TRENDING, BALANCED) for ML agent. |
| `services/eia_calendar.py` | **EIA Release Calendar** - Tracks EIA release windows to suppress trading during high volatility events. |
| `services/nse_event_calendar.py` | **NSE Event Calendar** - Tracks NSE-specific events, expiry days, and special market sessions. |

#### Gates & Validation

| File | Purpose |
|------|---------|
| `services/gates/base.py` | **Base Gate Class** - Abstract base for all gate implementations. |
| `services/gates/cvd_gate.py` | **CVD Gate** - Validates CVD divergence and momentum for entries. |
| `services/gates/profile_shape_gate.py` | **Profile Shape Gate** - Validates profile shape alignment for strategy type. |
| `services/gates/momentum_fade_gate.py` | **Momentum Fade Gate** - Detects momentum exhaustion for fade setups. |
| `services/gates/contested_zone_gate.py` | **Contested Zone Gate** - Validates contested zone entry conditions. |
| `services/entry_gates/grading.py` | **Signal Grading** - Grades signal quality based on multiple factors. |
| `services/entry_gates/three_align.py` | **Three Alignment Check** - Pre-gate check for three alignment conditions. |
| `services/entry_gates/confirmation_bundle.py` | **Confirmation Bundle** - Bundles multiple confirmations for entry validation. |

#### Exit & Trade Management

| File | Purpose |
|------|---------|
| `services/exit_engine.py` | **Exit Engine** - Determines exit conditions based on market state, risk, and PnL. |
| `services/trail_engine.py` | **Trailing Engine** - Manages trailing stops based on profit, volatility, and session phase. |
| `services/partition_exit_manager.py` | **Partition Exit** - Manages partial exits and scale-out decisions. |

---

## Domain Services Layer

### `/backend/app/domain/services/`

| File | Purpose |
|------|---------|
| `oi_wall_engine.py` | **OI Wall Detection** - Detects call/put walls for NSE options based on open interest clusters. Provides resistance/support levels. |
| `option_selection_engine.py` | **Option Selection** - Selects CE/PE options based on direction, delta, OTM/ATM criteria, and liquidity filters. Includes PCR alignment and max pain filtering. |
| `risk_sizing_engine.py` | **Risk Sizing** - Calculates position size accounting for theta decay, holding costs, and options-specific risk. |

---

## Trading Models Layer

### `/backend/app/domain/trading/models/`

| File | Purpose |
|------|---------|
| `value_objects.py` | **AMTResult Dataclass** - Contains all AMT analysis results including: `poc`, `value_area_high/low`, `aggression`, `setup`, `pcr`, `oi_walls`, `squeeze_state`, `session_favor_strategy`, `prior_poc/vah/val`, etc. |
| `enums.py` | **Trading Enums** - Defines `MarketState`, `SetupType`, `Direction`, `ProfileShape`, etc. |

---

## Application Layer

### `/backend/app/application/handlers/`

| File | Purpose |
|------|---------|
| `amt_handler.py` | **AMT Handler** - Main application handler that orchestrates AMT analysis on tick events. |
| `llm_overseer_handler.py` | **LLM Overseer** - Monitors open positions, applies CVD breakeven logic, and provides advisory oversight. |
| `llm_entry_handler.py` | **LLM Entry Handler** - Triggers LLM analysis based on confidence thresholds and session state. |

### `/backend/app/application/services/`

| File | Purpose |
|------|---------|
| `session_event_router.py` | **Event Router** - Routes tick events to appropriate handlers, executes entry path through gate pipeline, builds signals. Passes `favor_strategy` to gate pipeline. |
| `entry_coordinator.py` | **Entry Coordinator** - Coordinates entry execution with risk checks and position sizing. |
| `exit_coordinator.py` | **Exit Coordinator** - Handles exit signals and stop-out callbacks. |
| `session_risk_coordinator.py` | **Risk Coordinator** - Manages session-level risk state and trade recording. |

---

## Infrastructure Layer

### `/backend/app/infrastructure/`

| File | Purpose |
|------|---------|
| `strategies/nse_strategy.py` | **NSE Strategy** - NSE-specific strategy implementation with options-aware logic. |

---

## Test Suite

### `/backend/tests/unit/domain/`

| File | Purpose |
|------|---------|
| `test_gate_13_session_filter.py` | Tests for Gate 13 session strategy filtering. |
| `test_gate_pipeline.py` | Tests for all 12 gates + session filter. |
| `test_gate_pipeline_soft_gates.py` | Tests for soft gate quorum behavior (PCR, OI walls, etc.). |
| `test_oi_wall_engine.py` | Tests for OI wall detection. |
| `test_option_selection.py` | Tests for option selection engine. |
| `test_squeeze_detector.py` | Tests for squeeze detection. |
| `test_strategy.py` | Tests for setup detection (AAA, failed auction). |
| `test_valentini_rl.py` | Tests for session context and RL integration. |

---

## Data Flow Summary

```
Tick → AMTHandler.analyze() → AMTResult
       ↓
AMTResult → run_gate_pipeline() → GateContext(favor_strategy, pcr, oi_walls)
       ↓
GatePipeline.evaluate() → HARD GATES (0-13) + SOFT GATES (4b, 4c, 6-10)
       ↓
If passed → SignalBuilder.build_entry_signal()
       ↓
EntryCoordinator.execute_signal()
       ↓
Position Opened → OverseerHandler monitors → apply_cvd_breakeven()
```

---

## Key Integration Points

1. **Session Filter Flow**: `AMTResult.session_favor_strategy` → `GateContext.favor_strategy` → Gate 13 blocks TREND_MODEL when session favors MEAN_REVERSION

2. **CVD Breakeven Flow**: `OverseerHandler._llm_worker_loop()` → `apply_cvd_breakeven()` → moves SL to breakeven on CVD confirmation

3. **PCR Flow**: `AMTResult.pcr` → `GateContext.pcr` → Soft Gate 4b warns on PCR misalignment

4. **OI Walls Flow**: `AMTResult.oi_walls` → `GateContext.oi_walls` → Soft Gate 4c warns on OI wall proximity

5. **Squeeze State**: `MomentumSqueezeDetector` → `AMTResult.squeeze_state` → Available for breakout entries