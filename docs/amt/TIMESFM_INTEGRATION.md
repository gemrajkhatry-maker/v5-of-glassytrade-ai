# TimesFM 3.0 Integration

## Overview

The TimesFM 3.0 integration is an **advisory-only** layer that provides AI-powered market analysis and narrative reasoning. It never blocks ticks and never changes the deterministic 4-gate AMT decision.

## Architecture

```
DecisionContext → TimesFMAdvisor (async worker thread)
    → TimesFMEngine (native) OR TimesFMClient (microservice)
    → TimesFMScanningAgent / TimesFMPositionAgent
    → AgentDecisionProduced event → UI/Journal
```

## Components

### TimesFMEngine (`quant/decision/timesfm_engine.py`)

- **Native mode**: Loads Google TimesFM 3.0 PyTorch model directly from HuggingFace cache
- **Microservice mode**: Connects to TimesFM Prediction Service via HTTP
- **Fallback**: If model fails to load, falls back to rule-based narrative
- **Session gate**: Uses `session_allow_entry()` to block decisions during pre-market/close
- **Health check**: `is_healthy()` and `health_check()` methods for monitoring
- **Warmup**: `warmup()` method loads model on startup (not on first prediction)

### TimesFMAdvisor (`quant/decision/timesfm_advisor.py`)

- Async worker thread (1s poll loop)
- Single-slot queue (drops stale bars)
- Instant baseline emission (rule-based, 0ms)
- Queued TimesFM analysis (~200ms)
- Emits `AgentDecisionProduced` events

### TimesFMScanningAgent (`quant/decision/timesfm_agents.py`)

- Evaluates: Triple-A (VAL/VAH absorption), VA-Fade, Breakout setups
- Uses: price, POC, VAH, VAL, CVD slope, absorption, stacked imbalance
- Returns: ENTER_LONG / ENTER_SHORT / FLAT with confidence

### TimesFMPositionAgent (`quant/decision/timesfm_agents.py`)

- Evaluates: HOLD, TIGHTEN_SL, TAKE_PROFIT, EXIT, TIME_STOP
- Uses: entry price, current PnL, bars held, TimesFM quantile paths
- Returns: action + dynamic trailing stop

## Configuration

| Env Var | Default | Description |
|---|---|---|
| `TIMESFM_ADVISOR_ENABLED` | `false` | Enable TimesFM advisor |
| `TIMESFM_NATIVE` | `true` | Use native in-process mode |
| `TIMESFM_SERVICE_URL` | `http://localhost:8091` | Microservice URL |

## UI Distinction

The frontend clearly distinguishes advisory from deterministic signals:

- **DETERMINISTIC** (green badge): Real AMT signal that triggers orders
- **ADVISORY** (amber badge): TimesFM analysis for reference only

Tooltip: "Advisory signals are for reference only. Real orders are placed by the deterministic AMT engine."

## Data Limitations

### What TimesFM Provides
- 32-step future price trajectory prediction
- Quantile spread (p90 - p10) for uncertainty
- Mean forecast (p50 terminal value)

### What TimesFM Does NOT Provide
- Trade-level aggression flags (uses candle delta as proxy)
- True order-flow imbalance (uses 5-level depth snapshot)
- Tick-level footprint data (uses OHLCV candles)

### Known Constraints
- Model loading: ~30-60s on first load (mitigated by warmup)
- Memory footprint: ~2-4GB for the model
- Inference latency: ~200ms per prediction
- Context window: 32 bars (padded if insufficient history)

## Graceful Fallback

If TimesFM model fails to load:
1. Error is logged
2. Advisor falls back to rule-based narrative
3. UI shows "ADVISORY" badge with rule-based analysis
4. Deterministic AMT strategy continues unaffected

## Session Gating

TimesFM decisions are blocked during:
- Phase 1: Opening Noise (09:15-09:30 IST)
- Phase 5: Close Protection (15:15-15:30 IST)
- Pre-market and post-market

This prevents advisory signals during low-liquidity periods.

## Tests

- `tests/quant/decision/test_timesfm_engine.py` — 14 tests
- `tests/quant/decision/test_timesfm_agents.py` — Unit tests
- `tests/quant/decision/test_timesfm_client.py` — Client tests
- `tests/quant/decision/test_strategy_behavior.py` — 10 behavioral tests
