"""Domain constants — single source of truth for all thresholds."""

# Volume Profile
AGGRESSIVE_PRINT_SIGMA = 2.5  # sigma threshold for volume bubble detection

# CVD Thresholds (UNIFIED — single source of truth)
# Fabio: "If CVD is extreme, do not fade institutional pressure"
CVD_WINDOW = 20  # lookback window for CVD slope calculation
CVD_WARNING_THRESHOLD = 50.0     # Add warning to LLM prompt
CVD_BLOCK_THRESHOLD = 100.0      # Block at gate level (entry_gate.py)
CVD_EXTREME_THRESHOLD = 500.0    # True institutional avalanche (safety block)

# Volume thresholds
VOLUME_IMPULSE_MULTIPLIER = 1.5   # EMA(20) × 1.5 for impulse
VOLUME_AGGRESSION_MULTIPLIER = 2.5 # EMA(20) × 2.5 for aggression

# LVN/HVN thresholds (per Fabio spec)
# Spec: LVN < 15% of mean, HVN > 200% of mean
LVN_THRESHOLD = 0.15  # < 15% of mean volume (spec-compliant)
HVN_THRESHOLD = 2.00  # > 200% of mean volume (spec-compliant)

# Time stops (seconds)
TIME_STOP_BALANCED_SECS = 120
TIME_STOP_IMBALANCED_SECS = 300

# Data limits
MAX_CANDLES = 1000

# Tick batching
TICK_BATCH_SIZE = 50
TICK_FLUSH_INTERVAL_SECS = 5.0
