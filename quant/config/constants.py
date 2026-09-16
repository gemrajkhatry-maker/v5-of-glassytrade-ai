"""Centralized constants for the quant engine.

All magic numbers and configuration values that were previously scattered
across multiple files are now defined here for maintainability.
"""

# ============================================================================
# Engine Configuration
# ============================================================================

# Number of warmup bars before the engine starts trading
WARMUP_BARS = 15

# Conviction threshold for deterministic signals
DETERMINISTIC_CONVICTION = 0.7

# Number of events to batch before flushing to disk
JSONL_FLUSH_BATCH = 128

# Default candle ring size for AMT engine
DEFAULT_RING_SIZE = 8_192

# ============================================================================
# Risk Configuration
# ============================================================================

# Minimum risk-to-reward ratio for entry
MIN_RR_RATIO = 1.5

# Maximum stop distance in ticks
MAX_STOP_DISTANCE_TICKS = 200.0

# Tick size for NSE options (in currency units)
TICK_SIZE_NSE_OPTIONS = 0.05

# ============================================================================
# Session Configuration
# ============================================================================

# Session phases (1-5)
SESSION_PHASE_PRE_MARKET = 1
SESSION_PHASE_OPENING = 2
SESSION_PHASE_MID_SESSION = 3
SESSION_PHASE_CLOSING = 4
SESSION_PHASE_POST_MARKET = 5

# Allowed session phases for entry (Phase 2-4)
ALLOWED_ENTRY_PHASES = (2, 3, 4)

# ============================================================================
# Exit Configuration
# ============================================================================

# CVD kill threshold
CVD_KILL_THRESHOLD = 2.0

# Time stop in bars (default 60 minutes for 1-min bars)
DEFAULT_TIME_STOP_BARS = 60

# ============================================================================
# Position Management
# ============================================================================

# Maximum pyramid add-ons
MAX_PYRAMID_ADDONS = 2

# Pyramid sizing (fraction of base)
PYRAMID_SIZING = [0.50, 0.25]  # First add-on: 50%, second: 25%

# ============================================================================
# Absorption and Aggression
# ============================================================================

# Maximum age of absorption signal (in bars)
ABSORPTION_MAX_AGE_BARS = 5

# OBI aggression threshold
OBI_AGGRESSION_THRESHOLD = 0.20

# ============================================================================
# Seed Cache
# ============================================================================

# Seed cache TTL (seconds)
SEED_CACHE_TTL_SECONDS = 300
