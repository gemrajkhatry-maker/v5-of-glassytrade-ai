# GlassyTrade AI — Hardcoded Constants Extraction

## Executive Summary

This document extracts all hardcoded constants from the GlassyTrade AI codebase, organized by architectural domain. The codebase uses a YAML-based configuration hierarchy (base.yaml → environments/{env}.yaml → strategies/*.yaml) for most trading parameters, but several categories still contain hardcoded values that should be reviewed for configurability.

---

## 1. Trading System Constants (YAML-based, well-configurized)

### 1.1 Base Configuration (`backend/config/base.yaml`)
These are the primary trading constants defined in YAML and loaded via the config hierarchy.

**Volume Profile:**
- `lvn_threshold: 0.15` — Low Volume Node threshold (15% of mean)
- `hvn_threshold: 2.00` — High Volume Node threshold (200% of mean)
- `value_area_pct: 0.70` — 70% value area
- `lvn_smoothing: 3`
- `lvn_min_persistence_bars: 3`
- `lvn_removal_threshold: 0.30`
- `delta_bucket_size_default: 0.05`
- `delta_profile_buckets: 200`

**Order Flow / CVD:**
- `cvd_slope_window: 20`
- `cvd_strong_slope: 2.0`
- `cvd_slope_hard_block: 50.0`
- `cvd_slope_warning: 30.0`
- `cvd_slope_extreme: 100.0`
- `cvd_slope_persistence_bars: 3`
- `cvd_slope_extended_window: 40`
- `cvd_block_threshold_nse: 5000`
- `cvd_block_threshold_mcx: 50`
- `footprint_imbalance_ratio: 3.0`
- `footprint_imbalance_pct: 0.40`
- `absorption_range_atr: 0.30`
- `absorption_vol_mult: 2.0`
- `big_trade_multiplier: 5.0`
- `big_trade_cluster_count: 3`
- `big_trade_cluster_ticks: 2`
- `volume_bubble_sigma: 2.0`
- `ofi_window: 10`
- `delta_zone_sigma_mult: 2.5`

**Market State:**
- `poc_no_trade_ticks: 20`
- `balance_ratio_threshold: 0.55`
- `drive_rejection_wick_ratio: 0.5`
- `displacement_multiplier: 1.5`

**Aggression Scoring:**
- `aggression_footprint: 1.0`
- `aggression_cvd: 1.0`
- `aggression_big_trade: 1.0`
- `aggression_absorption: 0.5`
- `aggression_ofi: 0.5`
- `aggression_confluence: 0.5`
- `aggression_bubble: 0.5`
- `min_aggression_score: 2.0`
- `pyramid_aggression_score: 3.0`
- `aggression_persistence_bars: 3`
- `aggressive_print_sigma: 2.5`

**Structure:**
- `structure_dwell_ticks: 3`
- `structure_cooldown_ticks: 3`
- `structure_confidence_gate: 60`
- `structure_bypass_confidence: 70`

**Trade Setup:**
- `min_rr_ratio: 1.5`
- `max_cushion_ticks: 10`
- `signal_ttl_seconds: 600`
- `vwap_extreme_multiplier: 1.01`
- `decision_history_limit: 1000`

**Risk:**
- `risk_per_trade_pct: 0.005` (0.5%)
- `max_daily_loss_pct: 0.020` (2%)
- `max_consecutive_losses: 3`
- `max_drawdown_pct: 0.030` (3%)
- `absolute_ceiling_pct: 0.010` (1%)

**Volume Thresholds:**
- `volume_impulse_multiplier: 1.5`
- `volume_aggression_multiplier: 2.5`

**Time:**
- `warm_up_minutes_mcx: 15`
- `warm_up_minutes_nse: 15`
- `ib_candles: 2`

**LLM Throttling:**
- `llm_cooldown_seconds: 10`
- `staleness_timeout_seconds: 30`

**Grade:**
- `grade_extreme_threshold: -5`

**Data Limits:**
- `max_candles: 1000`
- `tick_batch_size: 50`
- `tick_flush_interval_secs: 5.0`

---

### 1.2 Symbol-Specific Configurations (base.yaml)
Each symbol has per-symbol overrides. Key symbol defaults:

**NIFTY:**
- lot_size: 65, tick_size: 0.05, vp_bucket_size: 10.0
- imbalance_threshold: 50.0, balance_ratio_threshold: 0.70
- slippage_bps: 15, min_oi: 500000, strike_interval: 50

**BANKNIFTY:**
- lot_size: 30, tick_size: 0.05, vp_bucket_size: 25.0
- imbalance_threshold: 100.0, balance_ratio_threshold: 0.70
- slippage_bps: 20, min_oi: 300000, strike_interval: 100

**FINNIFTY:**
- lot_size: 60, tick_size: 0.05, vp_bucket_size: 10.0
- imbalance_threshold: 50.0, balance_ratio_threshold: 0.70
- slippage_bps: 30, min_oi: 50000, strike_interval: 50

**MCX Symbols (CRUDEOIL, NATURALGAS, GOLD, SILVER):**
- Varying lot_sizes (100-1250), tick_sizes (0.1-1.0)
- imbalance_thresholds (5.0-100.0), balance_ratio_threshold: 0.55
- displacement_multiplier: 1.2 (vs 1.5 for NSE)

---

### 1.3 Risk Configuration (`backend/app/config_models/__init__.py` + YAML)
The `RiskConfig` dataclass defines:

- `risk_per_trade_pct: 0.005` — 0.5% per trade
- `max_daily_loss_pct: 0.02` — 2% daily loss limit
- `max_consecutive_losses: 3`
- `max_drawdown_pct: 0.03` — 3% max drawdown
- `absolute_ceiling_pct: 0.01` — 1% absolute ceiling
- `max_concurrent_positions: 5`
- `portfolio_notional_cap: 0.60` — 60% of capital
- `per_symbol_notional_cap: 0.20` — 20% per symbol
- `kelly_fraction: 0.25`
- `kelly_win_prob: 0.55`
- `kelly_win_loss_ratio: 2.0`
- `bootstrap_trade_count: 30`

---

### 1.4 ML Thresholds (`backend/app/config_models/__init__.py`)
- `imbalance_continuation_long: 0.55`
- `imbalance_continuation_short: 0.58`
- `return_to_value_long: 0.51`
- `return_to_value_short: 0.51`
- `probing_breakout_long: 0.58`
- `probing_breakout_short: 0.58`

---

### 1.5 Cost Profile (`backend/app/config_models/__init__.py`)
- `slippage_bps: 15.0`
- `stt_pct: 0.000625` (0.0625%)
- `exchange_fee_pct: 0.000495` (0.0495%)
- `brokerage_per_order: 20.0`
- `gst_on_brokerage_pct: 0.18` (18%)
- `sebi_charges_pct: 0.000001` (0.0001%)

---

### 1.6 Feature Flags (`backend/app/config_models/__init__.py`)
- `true_delta_lee_ready: False`
- `realistic_cost_model: False`
- `parallel_symbol_sessions: False`
- `short_signals_enabled: False`
- `risk_tier_engine: False`
- `walk_forward_validation: False`
- `scalp_engine_enabled: False`
- `ib_breakout_scalp: False`
- `print_level_trigger: False`

---

## 2. Dhan Broker Constants (`brokers/broker/dhan/domain/constants.py`)

### 2.1 API Configuration
- `API_BASE_URL: "https://api.dhan.co"`
- `API_VERSION: "v2"`
- `WS_URL: "wss://api-feed.dhan.co"`

### 2.2 WebSocket Endpoints
- `WS_URL_DEPTH_20: "wss://depth-api-feed.dhan.co/twentydepth"`
- `WS_URL_DEPTH_200: "wss://full-depth-api.dhan.co/twohundreddepth"`

### 2.3 Exchange Segment IDs (Dhan-specific)
- `NSE_CASH: 1`
- `NSE_FNO: 2`
- `NSE_CURRENCY: 3`
- `BSE_CASH: 4`
- `MCX: 5`
- `BSE_FNO: 12`
- `IDX_I: 6`

### 2.4 Instrument Types
- `EQUITY: 1`
- `FUTURES: 2`
- `OPTIONS: 3`
- `CURRENCY: 4`
- `COMMODITY: 5`

### 2.5 Order Status Codes
- `ORDER_STATUS_PENDING: "PENDING"`
- `ORDER_STATUS_OPEN: "TRANSIT"` (Dhan-specific)
- `ORDER_STATUS_PARTIALLY_FILLED: "PARTIALLY_FILLED"`
- `ORDER_STATUS_FILLED: "TRADED"` (Dhan-specific)
- `ORDER_STATUS_CANCELLED: "CANCELLED"`
- `ORDER_STATUS_REJECTED: "REJECTED"`

### 2.6 Product Types
- `PRODUCT_TYPE_INTRADAY: "I"`
- `PRODUCT_TYPE_MARGIN: "M"`
- `PRODUCT_TYPE_CNC: "C"`
- `PRODUCT_TYPE_CO: "CO"`
- `PRODUCT_TYPE_BO: "BO"`

### 2.7 Order Types
- `ORDER_TYPE_MARKET: "MARKET"`
- `ORDER_TYPE_LIMIT: "LIMIT"`
- `ORDER_TYPE_STOP_LOSS: "SL"`
- `ORDER_TYPE_STOP_LOSS_MARKET: "SL-M"`

### 2.8 Validity Types
- `VALIDITY_DAY: "DAY"`
- `VALIDITY_IMMEDIATE: "IOC"`
- `VALIDITY_GOOD_TILL_CANCELLED: "GTC"`

### 2.9 WebSocket Feed Types
- `FEED_TYPE_TICKER: 15` (LTP only)
- `FEED_TYPE_QUOTE: 17` (LTP + OHLC + Volume)
- `FEED_TYPE_FULL: 21` (Quote + 5-level depth)
- `FEED_TYPE_FULL_DEPTH: 20` (20-level depth)
- `DEPTH_REQUEST_CODE: 23`
- `DEPTH_UNSUBSCRIBE_CODE: 12`
- `DEPTH_RC_BID: 41`
- `DEPTH_RC_ASK: 51`
- `DEPTH_RC_DISCONNECT: 50`

### 2.10 Lot Sizes
Hardcoded lot sizes for major indices and stocks:
- NIFTY: 65, BANKNIFTY: 30, FINNIFTY: 60, MIDCPNIFTY: 120
- SENSEX: 20, BANKEX: 30
- Various stocks: RELIANCE(250), TCS(150), INFY(600), HDFCBANK(550), etc.

### 2.11 Strike Step Sizes
- NIFTY: 50.0, BANKNIFTY: 100.0, FINNIFTY: 50.0
- MIDCPNIFTY: 25.0, SENSEX: 100.0, BANKEX: 100.0
- DEFAULT: 5.0

### 2.12 Rate Limits
- `RATE_LIMIT_MARKET_DATA: 10`
- `RATE_LIMIT_HISTORICAL: 10`
- `RATE_LIMIT_ORDERS: 5`
- `RATE_LIMIT_DEFAULT: 10`
- `RATE_LIMIT_OPTION_CHAIN: 0.33` (1 per 3 seconds)
- Burst limits: 20/10/10/20/1

### 2.13 Historical Data Limits
- `HISTORICAL_MAX_DAYS: 90`

### 2.14 Timeouts and Retries
- `DEFAULT_TIMEOUT_SECONDS: 10.0`
- `DEFAULT_MAX_RETRIES: 3`
- `DEFAULT_RETRY_BACKOFF_FACTOR: 0.5`
- `DEFAULT_RETRY_MAX_DELAY_SECONDS: 30.0`
- `TOTP_TIME_WINDOW_SECONDS: 30`

### 2.15 WebSocket Configuration
- `WS_PING_INTERVAL_SECONDS: 30.0`
- `WS_RECONNECT_DELAY_SECONDS: 5.0`
- `WS_MAX_RECONNECT_ATTEMPTS: 30`

### 2.16 Cache Configuration
- `INSTRUMENT_CACHE_TTL_SECONDS: 86400` (24 hours)

### 2.17 Error Codes (Dhan API)
- `DH-1001`: Invalid token
- `DH-1002`: Token expired
- `DH-1003`: Invalid access
- `DH-2001`: Symbol not found
- `DH-2002`: Invalid exchange
- `DH-3001`: Rate limit
- `DH-3002`: Timeout
- `DH-3003`: Connection error
- `DH-4001`: Invalid data
- `DH-4002`: Missing data
- `DH-5001`: Order rejected
- `DH-5002`: Insufficient margin
- `DH-5003`: Invalid order

### 2.18 Known Index Underlyings
- `INDEX_UNDERLYINGS`: frozenset({NIFTY, BANKNIFTY, FINNIFTY, MIDCPNIFTY, SENSEX, BANKEX, NIFTY 50, NIFTY BANK})

---

## 3. Frontend Constants (`frontend/constants.ts`)

### 3.1 Time Constants
- `IST_OFFSET_SECONDS: 19800` (UTC+5:30)

### 3.2 Chart Configuration Defaults
- `interval: '5m'`
- `dataSource: 'DHAN'`
- `bullColor: '#00c896'` (Institutional green)
- `bearColor: '#ff4757'` (Institutional red)
- `glassOpacity: 1.0`
- `roughness: 0.1`
- `transmission: 0.95`
- `showGrid: true`
- `autoRotate: false`
- `showPredictions: true`
- `showVolumeProfile: true`
- `vpMode: 'combined'`
- `trend: 'volatile'`

---

## 4. Hardcoded Values in Frontend Components (Local Magic Numbers)

### 4.1 ChartScene.tsx
- Line widths: `1.5`, `1`
- Alpha values: `0.85`, `0.65`, `0.18`, `0.45`, `0.30`, `0.6`
- Shadow blur: `8`, `6`, `0`
- Volume formatting: `1000000` (M), `1000` (K) thresholds

### 4.2 DiagnosticsPanel.tsx
- `vwapCrossThreshold: 0.3` (0.3% from VWAP) — HARDCODED
- `distThreshold: 0.25` — HARDCODED
- Sigma thresholds: `3.0` (extreme extension), `1.65`, `0.8`
- Structure confidence: `70`, `80`
- Configuration: `3` total rules

### 4.3 EquityPanel.tsx
- `target: 20000` — Daily P&L target (HARDCODED)

### 4.4 ThreeA scoring (`utils/threeA.ts`)
- `AGGRESSION_MIN: 2.0` — HARDCODED
- `CVD_SLOPE_MIN: 2.0` — HARDCODED

### 4.5 ProfileInfo.tsx
- `diffPct <= 0.001` → CONFLUENCE (0.1%)
- `diffPct >= 0.005` → DIVERGENCE (0.5%)

### 4.6 OrderFlowCard.tsx
- Format thresholds: `1_000_000` (M), `1_000` (K)
- Spread thresholds: `<= 5` (green), `<= 15` (yellow)
- CVD ratio: `>= 50 && <= 70`

### 4.7 AbsorptionCard.tsx
- `Math.abs(swingDelta) >= 100` — HARDCODED threshold

### 4.8 AgentProbabilityCard.tsx
- Color thresholds: `>= 0.6` (green), `> 0.45` (yellow)
- Confidence thresholds: `>= 0.6`, `> 0.45`

### 4.9 VaFreezeCard.tsx
- `snaps.length >= 2` — Requires 2+ snapshots

### 4.10 InitialBalanceCard.tsx
- `threshold = ibRange * 0.1` — 10% of IB range (local calc, but magic 0.1)

### 4.11 hooks/useServerTradingSystem.ts
- `MAX_RAF_QUEUE_SIZE: 10`
- `configTimeoutMs: 180_000` (3 minutes)
- `parseErrorCount.current >= 3` — Error threshold

### 4.12 VwapContextCard.tsx
- `vwap <= 0` — Zero check

---

## 5. Backend Hardcoded Values (Beyond YAML)

### 5.1 SettingsAdapter Fallbacks (`backend/app/config_models/settings_adapter.py`)
- Default env var values (when YAML not available):
  - `SCANNER_MODE: "mcx_options"`
  - `DEFAULT_EXCHANGE: "MCX"`
  - `DHAN_SYMBOLS: "CRUDEOIL,NATURALGAS"`
  - `SCANNER_UNDERLYINGS: "CRUDEOIL,NATURALGAS,GOLDM,SILVERM"`
  - `SCANNER_TOP_N: 4`
  - `SCANNER_TOP_PER_UNDERLYING: 2`
  - `STRIKES_AROUND_ATM: 2`
  - `SCANNER_EXPIRY_INDEX: 0`
  - `LLM_TIMEOUT_SECONDS: 60`
  - `CAPITAL: 5000000`
  - `TICK_POLL_SECONDS: 5.0`
  - `SIGNAL_STALE_SECONDS: 60`
  - Gap fill: `300`, `60`, `600`, `120` seconds
  - CORS origins: `localhost:3000, localhost:5190`

### 5.2 Alerts (`backend/app/core/alerts.py`)
- `alert_drawdown`: default `threshold: 0.02` (2%)
- `alert_loss_streak`: default `threshold: 3`

### 5.3 Circuit Breakers (`brokers/broker/dhan/infrastructure/resilience.py`)
- `failure_threshold: 5`
- `recovery_timeout: 30.0`
- `success_threshold: 3`

### 5.4 Dhan Auth (`brokers/broker/dhan/infrastructure/auth_provider.py`)
- `NEAR_EXPIRY_SECONDS` — referenced but defined elsewhere

---

## 6. Configuration File Structure

### 6.1 YAML Hierarchy
```
backend/config/
├── base.yaml              # All defaults
├── feature_flags.yaml     # Feature toggles
├── mode_config.py         # Loader logic
├── config_models/         # Typed dataclasses
│   ├── __init__.py        # SystemConfig, SymbolConfig, etc.
│   ├── loader.py          # YAML → SystemConfig
│   ├── validator.py       # Validation rules
│   └── settings_adapter.py # Backward compat
├── environments/
│   ├── paper.yaml         # Paper trading
│   ├── development.yaml   # Development
│   └── live.yaml          # (would be live)
└── strategies/
    ├── mcx_options.yaml   # MCX strategy
    ├── nse_options.yaml   # NSE strategy
    └── ...
```

### 6.2 Environment Variables
Key env vars that override config:
- `GLASSYTRADE_ENV` — environment (paper/development/live)
- `GLASSYTRADE_STRATEGY` — strategy (mcx_options/nse_options)
- `DHAN_CLIENT_ID`, `DHAN_ACCESS_TOKEN`, `DHAN_API_KEY`, `DHAN_API_SECRET` — secrets
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` — notifications
- `CORS_ORIGINS` — allowed origins
- `QUANT_EXECUTION_MODE` — off/shadow/paper/live
- `LLM_EXECUTION_ENABLED` — boolean
- `LLM_TIMEOUT_SECONDS` — LLM timeout
- `CAPITAL` — trading capital
- `SIGNAL_STALE_SECONDS` — signal TTL
- Various `GAP_FILL_*` settings

---

## 7. Findings: Hardcoded vs Configurable

### 7.1 Well-Configurized (YAML-driven)
✅ Trading thresholds (LVN/HVN, CVD, aggression, etc.)
✅ Symbol configs (lot sizes, tick sizes, per-symbol params)
✅ Risk parameters (per-trade, daily loss, drawdown)
✅ Feature flags
✅ ML thresholds
✅ Cost profiles
✅ Environment-specific overrides

### 7.2 Broker-Defined Constants (Acceptable Hardcoding)
✅ Dhan API URLs, endpoints
✅ Exchange segment IDs (Dhan-specific)
✅ Order status codes (Dhan-specific strings)
✅ Product/order types (Dhan-specific strings)
✅ WebSocket feed types (Dhan-specific codes)
✅ Rate limits (Dhan API documented limits)
✅ Error codes (Dhan-specific)
✅ Historical max days (90 — Dhan API limit)

These are essentially API contracts from Dhan and should remain as-is.

### 7.3 Nearly-Configurable but Hardcoded (Review Candidates)

**Local magic numbers in frontend components:**
| Location | Value | Description | Recommendation |
|----------|-------|-------------|----------------|
| DiagnosticsPanel.tsx | 0.3 | VWAP cross threshold | Move to config |
| DiagnosticsPanel.tsx | 0.25 | Distance threshold | Move to config |
| DiagnosticsPanel.tsx | 3.0 | Sigma extreme threshold | Already in YAML |
| DiagnosticsPanel.tsx | 70, 80 | Confidence gates | Already in YAML |
| EquityPanel.tsx | 20000 | Daily P&L target | Move to config |
| threeA.ts | 2.0, 2.0 | Aggression/CVD min | Already in YAML |
| profileInfo.ts | 0.001, 0.005 | Confluence/divergence | Move to config |
| OrderFlowCard.tsx | 5, 15 | Spread thresholds | Move to config |
| AbsorptionCard.tsx | 100 | Swing delta threshold | Move to config |
| VaFreezeCard.tsx | 2 | Min snapshots | Move to config |
| useServerTradingSystem.ts | 10 | RAF queue size | Move to config |
| useServerTradingSystem.ts | 180000 | Config timeout | Move to config |

### 7.4 Hardcoded Time Values That Could Be Configurable
| Location | Value | Description |
|----------|-------|-------------|
| frontend/constants.ts | 19800 | IST offset (fixed by timezone) |
| Dhan constants.py | 86400 | Instrument cache TTL (24h) |
| Dhan constants.py | 30 | TOTP time window |
| Dhan constants.py | 30 | WS ping interval |
| Dhan constants.py | 5 | WS reconnect delay |
| Dhan constants.py | 30 | WS max reconnect attempts |
| SettingsAdapter | 300 | Gap fill interval |
| SettingsAdapter | 60 | Gap fill min gap |
| SettingsAdapter | 600 | Gap fill max lookback |
| SettingsAdapter | 120 | Gap fill max fill age |

### 7.5 Frontend Chart Config
The `ChartConfig` type and `DEFAULT_CONFIG` in `frontend/constants.ts` are well-structured, but could benefit from:
- Theming (colors, opacity, roughness)
- Default data source
- Default interval

These are currently hardcoded but could be overridden per-user or per-environment.

---

## 8. Recommendations

### 8.1 Immediate Actions (Low Risk)
1. **Frontend local thresholds**: Move magic numbers from component files to a `frontend/config.ts` or similar:
   - VWAP cross threshold (0.3%)
   - Distance threshold (0.25)
   - Spread thresholds (5, 15)
   - Daily P&L target (20000)
   - Confluence/divergence thresholds (0.001, 0.005)
   - Min snapshots for VA freeze (2)

2. **Timeout values**: Move `configTimeoutMs: 180000` and `MAX_RAF_QUEUE_SIZE: 10` to config

### 8.2 Medium-Term (Architectural)
1. **Frontend config file**: Create `frontend/config.ts` mirroring the backend approach with defaults + env override
2. **User preferences**: Store chart appearance (colors, opacity) in localStorage/user settings
3. **Dhan constants review**: Verify ratelimit values match current Dhan API docs (they may change)

### 8.3 Already Well-Done
The YAML-based configuration hierarchy is excellent. All core trading logic parameters are properly externalized. The Dhan broker constants are appropriately hardcoded as they represent API contracts. The `SystemConfig` dataclasses provide strong typing and immutability.

---

## Appendix: Config Loading Flow

```
ENV vars (GLASSYTRADE_ENV, GLASSYTRADE_STRATEGY)
    ↓
ModeConfigLoader.load_from_env()
    ↓
    ├── Load base.yaml (all defaults)
    ├── Load environments/{env}.yaml (environment overrides)
    ├── Load strategies/{strategy}.yaml (strategy overrides)
    └── Load feature_flags.yaml (feature toggles)
    ↓
SystemConfig (frozen dataclass)
    ↓
SettingsAdapter (backward compat for existing code)
    ↓
ServiceGraph / dependency injection
```
