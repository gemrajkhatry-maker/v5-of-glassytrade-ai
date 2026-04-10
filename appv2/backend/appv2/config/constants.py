"""AMT Constants — Fabio Valentini specification defaults.

These are the canonical thresholds for Auction Market Theory computation.
Override via environment variables in Settings when needed.
"""

from __future__ import annotations

# ── Volume Profile ────────────────────────────────────────────────
LVN_THRESHOLD: float = 0.15  # < 15% of mean profile volume
HVN_THRESHOLD: float = 2.0  # > 200% of mean profile volume
LVN_MIN_PERSISTENCE_BARS: int = 3  # LVN must persist 3+ bars
HVN_MIN_PERSISTENCE_BARS: int = 3  # HVN must persist 3+ bars
LVN_SMOOTHING_WINDOW: int = 3  # Histogram smoothing window
VALUE_AREA_PCT: float = 0.70  # 70% of total volume
POC_NO_TRADE_TICKS: int = 5  # ±5 ticks around POC = dead zone

# ── VWAP ─────────────────────────────────────────────────────────
VWAP_SIGMA_BANDS: list[float] = [1.0, 2.0]  # ±1σ, ±2σ

# ── Displacement ──────────────────────────────────────────────────
DISPLACEMENT_MULTIPLIER: float = 1.5  # Range > 1.5× ATR
DISPLACEMENT_VOLUME_MULT: float = 1.5  # Volume > 1.5× average
DISPLACEMENT_LOOKBACK: int = 20  # Candles to look back for leg detection

# ── Aggression Scoring ────────────────────────────────────────────
AGGRESSION_SIGMA_THRESHOLD: float = 2.5  # Composite score threshold
AGGRESSION_PERSISTENCE_BARS: int = 2  # Must persist 2+ bars
AGGRESSION_EXPIRY_CANDLES: int = 30  # Signal expires after 30 candles

# ── CVD ──────────────────────────────────────────────────────────
CVD_SLOPE_WINDOW: int = 40  # Slope calculation window (bars)
CVD_SLOPE_EXTREME: float = 5.0  # Extreme slope threshold (sigma)
CVD_SLOPE_HARD_BLOCK: float = 2.0  # Hard block threshold
CVD_DIVERGENCE_WINDOW: int = 20  # Window for divergence detection

# ── Initial Balance ───────────────────────────────────────────────
IB_MINUTES_NSE: int = 60  # NSE IB = 09:15–10:15
IB_MINUTES_MCX_MORNING: int = 60  # MCX Morning IB = 09:00–10:00
IB_MINUTES_MCX_US: int = 60  # MCX US Session IB = 19:30–20:30

# ── Session Phases (NSE) ─────────────────────────────────────────
# Phase 1: 09:15–09:30 Opening Noise — NO TRADE
# Phase 2: 09:30–11:30 Primary Window — ALL MODELS
# Phase 3: 11:30–14:00 Midday Consolidation — REVERSION ONLY
# Phase 4: 14:00–15:15 Power Hour — ALL MODELS
# Phase 5: 15:15–15:30 Close Protection — EXIT ONLY

# ── Session Phases (MCX) ─────────────────────────────────────────
# Phase 1: 09:00–09:15 Pre-open — NO TRADE
# Phase 2: 09:15–14:00 Morning — ALL MODELS
# Phase 3: 14:00–18:00 Afternoon — ALL MODELS
# Phase 4: 18:00–23:00 Evening — Reduced liquidity
# Phase 5: 23:00–23:30 Close — EXIT ONLY

# ── Gate Pipeline ─────────────────────────────────────────────────
GATE_SOFT_QUORUM: int = 3  # Need 3 of 4 soft gates to pass
GATE_SOFT_MIN_AGGRESSION: float = 2.0  # Min aggression score
GATE_SOFT_MAX_CUSHION_TICKS: int = 10  # Max cushion to opposing level
GATE_SOFT_MIN_RR: float = 1.5  # Minimum risk:reward
GATE_ENTRY_ZONE_TICKS: int = 3  # Price must be within 3 ticks of entry zone

# ── Options ───────────────────────────────────────────────────────
OPTION_MIN_OI_NIFTY: int = 50_000
OPTION_MIN_OI_BANKNIFTY: int = 10_000
OPTION_MIN_OI_CRUDEOIL: int = 5_000
OPTION_MIN_VOLUME_5MIN: int = 1_000
OPTION_MAX_SPREAD_BPS: int = 50  # 0.5% of premium
THETA_COST_MAX_PCT: float = 20.0  # Theta cost < 20% of expected profit
GAMMA_TRAP_HOUR: int = 14  # No entries after 14:30 on expiry day
GAMMA_TRAP_MINUTE: int = 30
ITM_DELTA_MIN: float = 0.60  # ITM delta range
ITM_DELTA_MAX: float = 0.75
ATM_DELTA_MIN: float = 0.40  # ATM delta sweet spot
ATM_DELTA_MAX: float = 0.60

# ── Risk ──────────────────────────────────────────────────────────
MAX_RISK_PER_TRADE_PCT: float = 2.0  # Max 2% capital per trade
MAX_DAILY_LOSS_PCT: float = 3.0  # Max 3% daily loss
ATR_VOLATILITY_WINDOW: int = 14  # ATR calculation window

# ── Signal ────────────────────────────────────────────────────────
SIGNAL_TTL_SECONDS: int = 600  # Signal expires after 10 min
SIGNAL_MAX_AGE_SECONDS: int = 600  # Discard signals older than 10 min

# ── Execution ─────────────────────────────────────────────────────
ORDER_RETRY_MAX_ATTEMPTS: int = 3
ORDER_RETRY_BACKOFF_BASE_MS: int = 500
POSITION_RECONCILIATION_INTERVAL_SEC: int = 30

# ── Tick Size (default; overridden per-symbol from broker) ────────
DEFAULT_TICK_SIZE_NSE: float = 0.05
DEFAULT_TICK_SIZE_MCX: float = 1.0

# ── Candle ────────────────────────────────────────────────────────
CANDLE_INTERVAL_SECONDS: int = 60  # 1-minute default
MAX_CANDLES_PER_SYMBOL: int = 2000  # Memory cap

# ── Volume Profile Buckets ────────────────────────────────────────
VP_BUCKET_MULTIPLIER: int = 4  # Bucket size = tick_size × 4
