"""Domain constants — extracted magic numbers."""

# Volume Profile
AGGRESSIVE_PRINT_SIGMA = 2.5  # sigma threshold for volume bubble detection

# CVD
CVD_WINDOW = 20  # lookback window for CVD slope calculation

# Time stops (seconds)
TIME_STOP_BALANCED_SECS = 120
TIME_STOP_IMBALANCED_SECS = 300

# Data limits
MAX_CANDLES = 1000

# Tick batching
TICK_BATCH_SIZE = 50
TICK_FLUSH_INTERVAL_SECS = 5.0
