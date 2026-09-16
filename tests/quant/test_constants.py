"""Verify magic numbers are centralized in constants module."""

from pathlib import Path


def test_constants_module_exists():
    """Ensure the constants module exists."""
    constants_file = Path("quant/config/constants.py")
    assert constants_file.exists(), "quant/config/constants.py does not exist"


def test_constants_are_importable():
    """Ensure all constants can be imported."""
    from quant.config.constants import (
        WARMUP_BARS,
        DETERMINISTIC_CONVICTION,
        JSONL_FLUSH_BATCH,
        DEFAULT_RING_SIZE,
        MIN_RR_RATIO,
        MAX_STOP_DISTANCE_TICKS,
        TICK_SIZE_NSE_OPTIONS,
        CVD_KILL_THRESHOLD,
        DEFAULT_TIME_STOP_BARS,
        ABSORPTION_MAX_AGE_BARS,
        OBI_AGGRESSION_THRESHOLD,
        SEED_CACHE_TTL_SECONDS,
    )
    
    # Verify types
    assert isinstance(WARMUP_BARS, int)
    assert isinstance(DETERMINISTIC_CONVICTION, float)
    assert isinstance(JSONL_FLUSH_BATCH, int)
    assert isinstance(DEFAULT_RING_SIZE, int)
    assert isinstance(MIN_RR_RATIO, float)
    assert isinstance(MAX_STOP_DISTANCE_TICKS, float)
    assert isinstance(TICK_SIZE_NSE_OPTIONS, float)
    assert isinstance(CVD_KILL_THRESHOLD, float)
    assert isinstance(DEFAULT_TIME_STOP_BARS, int)
    assert isinstance(ABSORPTION_MAX_AGE_BARS, int)
    assert isinstance(OBI_AGGRESSION_THRESHOLD, float)
    assert isinstance(SEED_CACHE_TTL_SECONDS, int)


def test_constants_have_expected_values():
    """Verify constants have the expected values."""
    from quant.config.constants import (
        WARMUP_BARS,
        MIN_RR_RATIO,
        CVD_KILL_THRESHOLD,
    )
    
    assert WARMUP_BARS == 15
    assert MIN_RR_RATIO == 1.5
    assert CVD_KILL_THRESHOLD == 2.0
