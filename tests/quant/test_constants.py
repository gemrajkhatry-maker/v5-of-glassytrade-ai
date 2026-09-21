"""Verify engine-level magic numbers stay centralized in ONE constants module.

v7 prune N6 folded quant/config/constants.py into quant/contracts/constants.py
(the canonical domain-constants home). This suite now pins the consolidated
values there and guards against the two-modules drift that hid the old
constant-true conviction gate (three spellings of one threshold across two
files).
"""

from pathlib import Path


def test_constants_module_exists():
    """The canonical constants module exists; the old quant/config one is gone."""
    constants_file = Path("quant/contracts/constants.py")
    assert constants_file.exists(), "quant/contracts/constants.py does not exist"
    legacy = Path("quant/config/constants.py")
    assert not legacy.exists(), (
        "quant/config/constants.py must stay deleted — one constants module "
        "(quant/contracts/constants.py) is the single authority"
    )


def test_constants_are_importable():
    """Ensure all engine constants can be imported from the canonical module."""
    from quant.contracts.constants import (
        WARMUP_BARS,
        CVD_KILL_THRESHOLD,
        JSONL_FLUSH_BATCH,
        DEFAULT_RING_SIZE,
        MIN_RR_RATIO,
        MAX_STOP_DISTANCE_TICKS,
        TICK_SIZE_NSE_OPTIONS,
        DEFAULT_TIME_STOP_BARS,
        ABSORPTION_MAX_AGE_BARS,
        OBI_AGGRESSION_THRESHOLD,
        SEED_CACHE_TTL_SECONDS,
    )

    # Verify types
    assert isinstance(WARMUP_BARS, int)
    assert isinstance(CVD_KILL_THRESHOLD, float)
    assert isinstance(JSONL_FLUSH_BATCH, int)
    assert isinstance(DEFAULT_RING_SIZE, int)
    assert isinstance(MIN_RR_RATIO, float)
    assert isinstance(MAX_STOP_DISTANCE_TICKS, float)
    assert isinstance(TICK_SIZE_NSE_OPTIONS, float)
    assert isinstance(DEFAULT_TIME_STOP_BARS, int)
    assert isinstance(ABSORPTION_MAX_AGE_BARS, int)
    assert isinstance(OBI_AGGRESSION_THRESHOLD, float)
    assert isinstance(SEED_CACHE_TTL_SECONDS, int)


def test_constants_have_expected_values():
    """Verify constants have the expected values."""
    from quant.contracts.constants import (
        WARMUP_BARS,
        MIN_RR_RATIO,
        CVD_KILL_THRESHOLD,
    )

    assert WARMUP_BARS == 15
    assert MIN_RR_RATIO == 1.5
    assert CVD_KILL_THRESHOLD == 2.0


def test_no_conviction_threshold_drift():
    """The retired dual-gate trio must not return.

    History: DETERMINISTIC_CONVICTION (0.7) + a local copy in context_builder +
    CONFIDENCE_HIGH_THRESHOLD (0.65) produced a constant-true provenance gate.
    Since N3 no decision branch compares conviction against a data-quality
    threshold; guard the source tree against the comparison returning.
    """
    import re

    banned = re.compile(
        r"agent_probability\s*>=|CONFIDENCE_HIGH_THRESHOLD\s*\)", re.MULTILINE
    )
    for path in Path("quant/decision").rglob("*.py"):
        assert not banned.search(path.read_text(encoding="utf-8")), (
            f"{path}: conviction-vs-threshold comparison returned — the dual "
            "data-quality gate regression guard (N3/N6) fired"
        )
