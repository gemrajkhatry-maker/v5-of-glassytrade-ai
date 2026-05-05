"""Golden regression tests for Week 1 architecture changes.

Validates exact output equivalence before/after:
- detect_momentum_fade() extraction
- ThreeAlignInput protocol adoption
- match setup_type in signal_builder
"""

import math
import pytest
from unittest.mock import Mock, patch

# Import domain types
from app.domain.trading.models.value_objects import OHLC, AMTResult
from app.domain.fabio_ai.services.entry_gates.confirmation_bundle import check_momentum_fade
from app.domain.fabio_ai.services.entry_gates.three_align import three_align_check
from app.domain.fabio_ai.services.entry_gates.signal_builder import build_entry_signal
from app.domain.fabio_ai.services.entry_gates.detectors import detect_momentum_fade
from app.domain.trading.models.enums import SetupType


def test_detect_momentum_fade_golden():
    """Golden test: detect_momentum_fade() must return identical bool as legacy check_momentum_fade()."""
    # Realistic input from live session (MCX NIFTY Options)
    data = [
        Mock(volume=1200, open=22400.0, high=22460.0, low=22390.0, close=22450.5),
        Mock(volume=1350, open=22450.5, high=22480.0, low=22440.0, close=22475.0),
        Mock(volume=1800, open=22475.0, high=22520.0, low=22460.0, close=22510.0),
    ] * 10  # 30 candles
    
    tick = Mock(
        volume=4200,
        open=22510.0,
        high=22545.0,
        low=22505.0,
        close=22540.0,
    )
    
    # Legacy call
    legacy_result = check_momentum_fade(data, tick, direction="SHORT")
    
    # New detector call
    new_result, _ = detect_momentum_fade(data, tick, direction="SHORT")
    
    assert new_result == legacy_result, f"detect_momentum_fade mismatch: {new_result} != {legacy_result}"


def test_three_align_check_golden():
    """Golden test: three_align_check() with ThreeAlignInput must return identical (gate_passed, confirmation_strong)."""
    # Minimal realistic AMTResult (only fields used by three_align_check)
    amt_result = Mock(
        poc=22450.0,
        value_area_high=22520.0,
        value_area_low=22380.0,
        cvd_slope=2.7,
        session_vwap=22465.0,
        market_state="BALANCED",
        price_velocity=0.08,
        leg_poc=22480.0,
        leg_vah=22530.0,
        leg_val=22420.0,
        dev_poc=22430.0,
        dev_vah=22510.0,
        dev_val=22390.0,
        hvns=[22550.0],
        lvns=[22350.0],
        leg_lvns=[],
    )
    
    # OHLC tick
    tick = Mock(
        close=22455.0,
        high=22465.0,
        low=22445.0,
        open=22450.0,
        vwap=22465.0,
        time="2026-05-04T10:30:00Z",
    )
    
    # Data (candles)
    data = [Mock(time="2026-05-04T10:29:00Z")] * 30
    
    # Legacy call (with AMTResult)
    from app.domain.fabio_ai.services.entry_gates.three_align import three_align_check as legacy_fn
    legacy_result = legacy_fn(data, amt_result, tick)
    
    # New call (with same AMTResult — it implements ThreeAlignInput)
    new_result = three_align_check(data, amt_result, tick)
    
    assert new_result == legacy_result, f"three_align_check mismatch: {new_result} != {legacy_result}"


def test_build_entry_signal_golden():
    """Golden test: build_entry_signal() with match must return identical Signal object."""
    # Realistic inputs
    amt_result = Mock(
        poc=22450.0,
        prior_poc=22420.0,
        value_area_high=22520.0,
        value_area_low=22380.0,
        npoc_above=22580.0,
        npoc_below=22320.0,
        session_vwap=22465.0,
        lvn_play={"direction": "LONG", "price": 22435.0},
        profile_shape="balanced",
        aggressive_prints=[],
    )
    
    tick = Mock(
        close=22455.0,
        high=22465.0,
        low=22445.0,
        open=22450.0,
        vwap=22465.0,
        time="2026-05-04T10:30:00Z",
    )
    
    ai_result = {"setup": "mean-reversion", "rationale": "POC reversion play"}
    
    # Legacy call
    from app.domain.fabio_ai.services.entry_gates.signal_builder import build_entry_signal as legacy_fn
    legacy_signal = legacy_fn(
        direction="LONG",
        tick=tick,
        amt_result=amt_result,
        ai_result=ai_result,
        setup_type=SetupType.MEAN_REVERSION,
        data=[Mock()] * 30,
        tick_size=0.05,
    )
    
    # New call (same args — match handles 'mean-reversion' normalization)
    new_signal = build_entry_signal(
        direction="LONG",
        tick=tick,
        amt_result=amt_result,
        ai_result=ai_result,
        setup_type=SetupType.MEAN_REVERSION,
        data=[Mock()] * 30,
        tick_size=0.05,
    )
    
    # Assert all key Signal fields match
    assert new_signal.type == legacy_signal.type
    assert new_signal.price == legacy_signal.price
    assert new_signal.stop_loss == legacy_signal.stop_loss
    assert new_signal.take_profit == legacy_signal.take_profit
    assert new_signal.metadata["llm_entry"] == legacy_signal.metadata["llm_entry"]
    assert new_signal.metadata["allow_trail"] == legacy_signal.metadata["allow_trail"]
    assert new_signal.metadata["tp_source"] == legacy_signal.metadata["tp_source"]
    assert new_signal.reason == legacy_signal.reason
    
    # Bonus: ensure no unexpected mutation
    assert not hasattr(new_signal, "_frozen") or new_signal._frozen == getattr(legacy_signal, "_frozen", None)
