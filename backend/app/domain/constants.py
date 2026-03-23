"""Domain constants — single source of truth for all thresholds (per Fabio AMT spec)."""

# ============================================================================
# Volume Profile (FR-02)
# ============================================================================
LVN_THRESHOLD = 0.15  # FR-02-08: < 15% of mean volume
HVN_THRESHOLD = 2.00  # FR-02-09: > 200% of mean volume
VALUE_AREA_PCT = 0.70  # FR-02-03: 70% value area
LVN_SMOOTHING = 3  # Smoothing window for LVN/HVN detection

# ============================================================================
# Order Flow Metrics (FR-03)
# ============================================================================
CVD_SLOPE_WINDOW = 20  # FR-03-02: rolling 20-candle window
CVD_STRONG_SLOPE = 2.0  # FR-08-04: CVD slope for P3 trail
CVD_WARNING_THRESHOLD = 50.0  # CVD warning level
CVD_BLOCK_THRESHOLD = 100.0  # CVD block level at gate
CVD_EXTREME_THRESHOLD = 500.0  # CVD extreme (safety block)

FOOTPRINT_IMBALANCE_RATIO = 3.0  # FR-03-06: 300% (3:1 ratio)
FOOTPRINT_IMBALANCE_PCT = 0.40  # FR-03-06: ≥ 40% cells confirmed

ABSORPTION_RANGE_ATR = 0.30  # FR-03-09: (high-low) < ATR × 0.30
ABSORPTION_VOL_MULT = 2.0  # FR-03-09: volume > avg × 2.0

BIG_TRADE_MULTIPLIER = 5.0  # FR-03-11: trade_size ≥ avg × 5.0
BIG_TRADE_CLUSTER_COUNT = 3  # FR-03-11: min 3 prints
BIG_TRADE_CLUSTER_TICKS = 2  # FR-03-11: within 2 ticks

VOLUME_BUBBLE_SIGMA = 2.0  # FR-03-07: mean + 2σ across 21 bars

OFI_WINDOW = 10  # FR-03-12: 10-candle rolling average

# ============================================================================
# Market State (FR-04)
# ============================================================================
POC_NO_TRADE_TICKS = 2  # FR-04-01: ±2 ticks of POC = NO_TRADE
BALANCE_RATIO_THRESHOLD = 0.55  # FR-04-02: fraction of candles inside VA

# ============================================================================
# Drive Detection (FR-05)
# ============================================================================
DRIVE_REJECTION_WICK_RATIO = 0.5  # Wick must be > 50% of candle range

# ============================================================================
# Aggression Scoring (FR-06)
# ============================================================================
AGGRESSION_FOOTPRINT = 1.0  # FR-06-01: footprint confirmed
AGGRESSION_CVD = 1.0  # FR-06-02: CVD confirms
AGGRESSION_BIG_TRADE = 1.0  # FR-06-03: big trade cluster
AGGRESSION_ABSORPTION = 0.5  # FR-06-04: absorption detected
AGGRESSION_OFI = 0.5  # FR-06-05: OFI aligned
AGGRESSION_CONFLUENCE = 0.5  # FR-06-06: combined profile confluence
AGGRESSION_BUBBLE = 0.5  # FR-06-07: volume bubble near entry

MIN_AGGRESSION_SCORE = 2.0  # FR-06-08: minimum for trade signal
PYRAMID_AGGRESSION_SCORE = 3.0  # FR-06-09: minimum for pyramid add

# Aggression persistence filter — prevent signal flicker
AGGRESSION_PERSISTENCE_BARS = 3  # Score must be >= threshold for N consecutive bars
CVD_SLOPE_PERSISTENCE_BARS = 3  # Slope sign must persist for N consecutive bars
CVD_SLOPE_EXTENDED_WINDOW = 40  # Extended lookback for session-leg slope

# LVN stability
LVN_MIN_PERSISTENCE_BARS = 3  # LVN must survive N bars before emitted
LVN_REMOVAL_THRESHOLD = 0.30  # LVN removed only if volume rises above 30% of mean

# Structure label hysteresis
STRUCTURE_DWELL_TICKS = 3  # New state must persist N consecutive ticks
STRUCTURE_COOLDOWN_TICKS = 3  # Hold after state change before allowing another
STRUCTURE_CONFIDENCE_GATE = 60  # Minimum confidence to accept new state
STRUCTURE_BYPASS_CONFIDENCE = 70  # Skip TRANSITION buffer if confidence exceeds this

# Decision history
DECISION_HISTORY_LIMIT = 1000  # Max decisions to return from API

# ============================================================================
# Trade Setup (FR-07)
# ============================================================================
MIN_RR_RATIO = 1.5  # FR-07-08: minimum 1:1.5 R:R
MAX_CUSHION_TICKS = 10  # FR-07-05: > 10 ticks = invalid
DISPLACEMENT_MULTIPLIER = 1.5  # FR-04-04: displacement = range ≥ ATR × 1.5

# ============================================================================
# Risk Management (FR-10)
# ============================================================================
RISK_PER_TRADE_PCT = 0.005  # FR-10-01: 0.5% per trade
MAX_DAILY_LOSS_PCT = 0.020  # FR-10-02: 2% daily limit
MAX_CONSECUTIVE_LOSSES = 3  # FR-10-03: 3 consecutive = pause
MAX_DRAWDOWN_PCT = 0.030  # FR-10-04: 3% from peak
ABSOLUTE_CEILING_PCT = 0.010  # FR-10-05: 1% absolute max per trade

# ============================================================================
# Volume Thresholds
# ============================================================================
VOLUME_IMPULSE_MULTIPLIER = 1.5  # EMA(20) × 1.5 for impulse
VOLUME_AGGRESSION_MULTIPLIER = 2.5  # EMA(20) × 2.5 for aggression
AGGRESSIVE_PRINT_SIGMA = 2.5  # sigma threshold for volume bubble

# ============================================================================
# Time (FR-10)
# ============================================================================
WARM_UP_MINUTES_MCX = 15  # FR-10-09: avoid first 15 min of MCX
WARM_UP_MINUTES_NSE = 15  # NSE warm-up
IB_CANDLES = 2  # FR-03-14: first 2 candles for IB

# ============================================================================
# Delta Volume Profile (FR-02 — Gap #1)
# ============================================================================
DELTA_ZONE_SIGMA_MULT = 2.5  # High delta = abs(net) > mean × 2.5
DELTA_PROFILE_BUCKETS = 200  # Number of histogram buckets
DELTA_BUCKET_SIZE_DEFAULT = 0.05  # Default bucket size (computed from tick_size)

# ============================================================================
# Signal Validation (FR-07 — Audit Fix)
# ============================================================================
SIGNAL_TTL_SECONDS = 600  # Max age for signals before they're considered stale
VWAP_EXTREME_MULTIPLIER = 1.01  # Beyond +2σ by 1% = institutional anomaly

# ============================================================================
# LLM Throttling (Audit Fix)
# ============================================================================
LLM_COOLDOWN_SECONDS = 10  # Minimum seconds between LLM calls per symbol
STALENESS_TIMEOUT_SECONDS = 30  # Max seconds a request can sit in queue

# ============================================================================
# Grade Thresholds (Audit Fix)
# ============================================================================
GRADE_EXTREME_THRESHOLD = -5  # Below this = disaster prevention block

# ============================================================================
# CVD Market-Specific Thresholds (Audit Fix)
# ============================================================================
CVD_BLOCK_THRESHOLD_NSE = 5000  # NSE: higher volume, wider threshold
CVD_BLOCK_THRESHOLD_MCX = 50  # MCX: thinner books, tighter threshold

# ============================================================================
# Data Limits
# ============================================================================
MAX_CANDLES = 1000
TICK_BATCH_SIZE = 50
TICK_FLUSH_INTERVAL_SECS = 5.0
